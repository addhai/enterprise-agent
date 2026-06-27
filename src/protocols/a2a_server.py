"""
A2A (Agent-to-Agent) Server + Client — 客服 Agent 与其他 Agent 协作

使用 a2a-sdk 1.1.0 实现标准化 Agent 间通信。
客服 Agent 发布 Agent Card，其他 Agent 可自动发现并委托任务。

启动方式:
  Server: python -m src.protocols.a2a_server
  测试:   python -m src.protocols.demo_protocols

架构:
  客服 Agent (本服务) ──A2A──→ 性能专家 Agent (远程)
  客服 Agent 遇到自己搞不定的复杂性能问题时，
  通过 A2A 委托给远程性能专家 Agent 处理。
"""

import asyncio
import logging
from typing import Optional

from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    Message,
    Part,
    Role,
    TaskState,
)
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.routes import add_a2a_routes_to_fastapi
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.routes.rest_routes import create_rest_routes
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory

from fastapi import FastAPI
import httpx
import uvicorn
import warnings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: create agent text messages without deprecated a2a.utils API
# ---------------------------------------------------------------------------

def _make_text_message(text: str, context_id: str, task_id: str):
    """Create a Message with a text Part (a2a-sdk 1.1.0 compatible)"""
    from a2a.types import Message, Part, Role
    from uuid import uuid4
    return Message(
        message_id=str(uuid4()),
        role=Role.ROLE_AGENT,
        context_id=context_id,
        task_id=task_id,
        parts=[Part(text=text)],
    )

# ---------------------------------------------------------------------------
# 客服 Agent 的执行逻辑（A2A Server 端）
# ---------------------------------------------------------------------------


class CustomerServiceExecutor(AgentExecutor):
    """把现有的客服 Agent 包装为 A2A 可执行单元"""

    def __init__(self, workflow=None):
        self.workflow = workflow

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """接收远程 A2A 请求，调用 LangGraph 工作流处理"""
        query = context.get_user_input()

        if not query:
            await event_queue.enqueue_event(
                _make_text_message(
                    "No input provided. Please send a support question.",
                    context.context_id,
                    context.task_id,
                )
            )
            return

        if self.workflow is None:
            from src.graph.workflow import create_workflow
            self.workflow = create_workflow()

        from src.graph.state import AgentState
        from langchain_core.messages import HumanMessage

        state = AgentState(
            messages=[HumanMessage(content=query)],
            intent=None,
            retrieved_docs=[],
            needs_human=False,
            turn_count=0,
            final_response="",
            user_id=context.context_id or "a2a_user",
            faq_match=None,
            effective_max_turns=5,
            has_reflected=False,
        )

        result = self.workflow.invoke(
            state,
            config={"configurable": {"thread_id": context.task_id}},
        )

        reply = result.get("final_response", "Unable to process your request.")
        await event_queue.enqueue_event(
            _make_text_message(reply, context.context_id, context.task_id)
        )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        pass


# ---------------------------------------------------------------------------
# Agent Card（服务发现元数据）
# ---------------------------------------------------------------------------

SERVICE_AGENT_CARD = AgentCard(
    name="CloudSync Customer Service Agent",
    description=(
        "CloudSync SaaS 平台智能客服 Agent。"
        "处理产品咨询、技术排查、SSO 配置、API 使用、错误排查。"
        "超出知识库范围自动转人工。"
    ),
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True),
    default_input_modes=["text", "text/plain"],
    default_output_modes=["text", "text/plain"],
    skills=[
        AgentSkill(
            id="faq_support",
            name="FAQ Support",
            description="Handle common questions: password reset, pricing, SSO setup, API keys",
            tags=["faq", "support", "general"],
            examples=["How do I reset my password?", "What are your pricing plans?"],
        ),
        AgentSkill(
            id="technical_troubleshooting",
            name="Technical Troubleshooting",
            description="Diagnose SDK/API errors (403,401,429), sync issues, CORS config",
            tags=["technical", "debugging", "sdk", "api"],
            examples=[
                "I keep getting a 403 error when calling the API",
                "Sync is stuck at processing for 30 minutes",
            ],
        ),
        AgentSkill(
            id="human_escalation",
            name="Human Escalation",
            description="Transfer complex billing, account, or complaint issues to human agent",
            tags=["escalation", "billing", "account"],
            examples=[
                "I want to talk to a real person about a refund",
                "I need help with a billing dispute",
            ],
        ),
    ],
)


def build_a2a_server(workflow=None) -> FastAPI:
    """构建 A2A Server（基于 FastAPI + a2a-sdk routes）"""

    app = FastAPI(
        title="CloudSync Customer Service A2A Agent",
        description="A2A-compatible agent providing CloudSync customer support",
        version="1.0.0",
    )

    handler = DefaultRequestHandler(
        agent_executor=CustomerServiceExecutor(workflow=workflow),
        task_store=InMemoryTaskStore(),
        agent_card=SERVICE_AGENT_CARD,
    )

    # 注册 A2A 路由：Agent Card + JSON-RPC + REST
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(
            agent_card=SERVICE_AGENT_CARD,
            card_url="/.well-known/agent.json",
        ),
        jsonrpc_routes=create_jsonrpc_routes(
            request_handler=handler,
            rpc_url="/",
        ),
        rest_routes=create_rest_routes(
            request_handler=handler,
            path_prefix="/v1",
        ),
    )

    return app


# ---------------------------------------------------------------------------
# A2A Client —— 委托任务给远程 Agent
# ---------------------------------------------------------------------------


async def delegate_to_expert(
    query: str,
    expert_agent_url: str = "http://localhost:9002",
    timeout: int = 30,
) -> Optional[str]:
    """
    将复杂问题委托给远程专家 Agent（A2A Client）。

    客服 Agent 遇到复杂性能问题 → 委托给性能专家 Agent。
    专家 Agent 返回排查结论后，客服 Agent 翻译为用户友好回复。

    Args:
        query: 需要委托的问题
        expert_agent_url: 专家 Agent 的 A2A 地址
        timeout: 超时秒数

    Returns:
        专家 Agent 的回复，或 None（失败时）
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            # 1. 发现远程 Agent（拉取 Agent Card）
            card_resolver = A2ACardResolver(http_client, expert_agent_url)
            agent_card = await card_resolver.get_agent_card()
            logger.info(
                "Discovered expert agent: %s - %s",
                agent_card.name,
                agent_card.description,
            )

            # 2. 创建 client 连接
            config = ClientConfig(httpx_client=http_client)
            factory = ClientFactory(config=config)
            agent_client = factory.create(agent_card)

            # 3. 发送委托消息
            message = Message(
                role=Role.ROLE_USER,
                parts=[Part(text=query)],
            )

            # 4. 收集响应
            response_parts = []
            async for event in agent_client.send_message(message):
                if hasattr(event, "parts"):
                    for part in event.parts:
                        if part.text:
                            response_parts.append(part.text)

            return "\n".join(response_parts) if response_parts else None

    except Exception as e:
        logger.error("Failed to delegate to expert agent: %s", e)
        return None


# ---------------------------------------------------------------------------
# A2A Server 启动入口
# ---------------------------------------------------------------------------


async def main():
    """启动 A2A Server: python -m src.protocols.a2a_server"""
    from src.graph.workflow import create_workflow

    logger.info("Initializing LangGraph workflow for A2A agent...")
    workflow = create_workflow()

    app = build_a2a_server(workflow=workflow)

    logger.info("A2A Customer Service Agent starting on http://localhost:9001")
    logger.info("Agent Card: http://localhost:9001/.well-known/agent.json")

    config = uvicorn.Config(app, host="0.0.0.0", port=9001, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


if __name__ == "__main__":
    asyncio.run(main())
