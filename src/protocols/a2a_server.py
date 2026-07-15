"""
A2A (Agent-to-Agent) Server + Client — 客服 Agent 与专家 Agent 协作

使用 a2a-sdk 1.1.0 实现标准化 Agent 间通信。
客服 Agent 发布 Agent Card，其他 Agent 可自动发现并委托任务。

启动方式:
  客服 Agent:    python -m src.protocols.a2a_server          # 端口 9001
  性能专家 Agent: python -m src.protocols.perf_agent           # 端口 9002
  安全专家 Agent: python -m src.protocols.security_agent      # 端口 9003
  测试:          python -m src.protocols.demo_protocols

架构:
  客服 Agent (本服务) ──A2A──→ 性能专家 Agent (perf_agent.py)
  客服 Agent (本服务) ──A2A──→ 安全审计专家 Agent (security_agent.py)
  客服 Agent 遇到复杂的性能/安全问题超出知识库范围时，
  通过 delegate_to_expert() 委托给对应专家 Agent 处理。

注意：
  本模块的逻辑层（委托函数、本地回退）不依赖 a2a-sdk。
  a2a-sdk 仅在 build_a2a_server() / delegate_to_expert() 实际发起 A2A 通信时延迟加载。
  当 a2a-sdk 未安装时，委托函数回退到本地专家诊断逻辑（perf_agent / security_agent）。
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# A2A SDK 是否可用（延迟检测）
_A2A_AVAILABLE = False
try:
    import a2a  # noqa: F401
    _A2A_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Helper: create agent text messages without deprecated a2a.utils API
# ---------------------------------------------------------------------------

def _make_text_message(text: str, context_id: str, task_id: str):
    """Create a Message with a text Part (a2a-sdk 1.1.0 compatible)"""
    from uuid import uuid4
    from a2a.types import Message, Part, Role
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

# 延迟加载 a2a-sdk 基类：当 a2a-sdk 不可用时使用 object 占位
if _A2A_AVAILABLE:
    from a2a.server.agent_execution import AgentExecutor
    _ExecutorBase = AgentExecutor
else:
    _ExecutorBase = object


class CustomerServiceExecutor(_ExecutorBase):
    """把现有的客服 Agent 包装为 A2A 可执行单元"""

    def __init__(self, workflow=None):
        if _ExecutorBase is not object:
            super().__init__()
        self.workflow = workflow

    async def execute(self, context, event_queue) -> None:
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

    async def cancel(self, context, event_queue) -> None:
        pass


# ---------------------------------------------------------------------------
# Agent Card（服务发现元数据）— 延迟构建，避免模块加载时依赖 a2a-sdk
# ---------------------------------------------------------------------------

SERVICE_AGENT_SKILLS = [
    {
        "id": "faq_support",
        "name": "FAQ Support",
        "description": "Handle common questions: password reset, pricing, SSO setup, API keys",
        "tags": ["faq", "support", "general"],
        "examples": ["How do I reset my password?", "What are your pricing plans?"],
    },
    {
        "id": "technical_troubleshooting",
        "name": "Technical Troubleshooting",
        "description": "Diagnose SDK/API errors (403,401,429), sync issues, CORS config",
        "tags": ["technical", "debugging", "sdk", "api"],
        "examples": [
            "I keep getting a 403 error when calling the API",
            "Sync is stuck at processing for 30 minutes",
        ],
    },
    {
        "id": "human_escalation",
        "name": "Human Escalation",
        "description": "Transfer complex billing, account, or complaint issues to human agent",
        "tags": ["escalation", "billing", "account"],
        "examples": [
            "I want to talk to a real person about a refund",
            "I need help with a billing dispute",
        ],
    },
]

SERVICE_AGENT_CARD = None


def _build_service_agent_card():
    """延迟构建 a2a AgentCard 对象（首次调用时构建并缓存）"""
    global SERVICE_AGENT_CARD
    if SERVICE_AGENT_CARD is not None:
        return SERVICE_AGENT_CARD

    from a2a.types import AgentCard, AgentCapabilities, AgentSkill

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
                id=s["id"],
                name=s["name"],
                description=s["description"],
                tags=s["tags"],
                examples=s["examples"],
            )
            for s in SERVICE_AGENT_SKILLS
        ],
    )
    return SERVICE_AGENT_CARD


def build_a2a_server(workflow=None):
    """构建 A2A Server（基于 FastAPI + a2a-sdk routes）

    需要 a2a-sdk 已安装。若未安装会抛出 RuntimeError。
    """
    if not _A2A_AVAILABLE:
        raise RuntimeError(
            "a2a-sdk 未安装，无法构建 A2A Server。"
            "请安装 a2a-sdk 或使用本地回退模式。"
        )

    from fastapi import FastAPI
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.server.routes import add_a2a_routes_to_fastapi
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.routes.rest_routes import create_rest_routes

    card = _build_service_agent_card()

    app = FastAPI(
        title="CloudSync Customer Service A2A Agent",
        description="A2A-compatible agent providing CloudSync customer support",
        version="1.0.0",
    )

    handler = DefaultRequestHandler(
        agent_executor=CustomerServiceExecutor(workflow=workflow),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    # 注册 A2A 路由：Agent Card + JSON-RPC + REST
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(
            agent_card=card,
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
    if not _A2A_AVAILABLE:
        raise RuntimeError(
            "a2a-sdk 未安装，无法发起 A2A 委托。"
            "请使用 delegate_to_perf_expert / delegate_to_security_expert 的本地回退。"
        )

    import httpx
    from a2a.types import Message, Part, Role
    from a2a.client import A2ACardResolver, ClientConfig, ClientFactory

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
# 专家 Agent 委托 — 复用 delegate_to_expert() 的 A2A Client 模式
# ---------------------------------------------------------------------------

# 专家 Agent 默认地址（可被 config.py 覆盖）
from src.config import settings as _settings

PERF_EXPERT_URL = _settings.a2a_perf_expert_url
SECURITY_EXPERT_URL = _settings.a2a_security_expert_url


async def delegate_to_perf_expert(
    query: str,
    expert_agent_url: str = "",
    timeout: int = 30,
) -> Optional[str]:
    """将性能问题委托给性能诊断专家 Agent。

    复用 delegate_to_expert() 的 A2A Client 模式。
    a2a-sdk 不可用时回退到本地诊断逻辑。
    """
    url = expert_agent_url or PERF_EXPERT_URL
    if not _A2A_AVAILABLE:
        # a2a-sdk 未安装时回退到本地诊断逻辑
        from src.protocols.perf_agent import _diagnose
        return _diagnose(query)
    return await delegate_to_expert(query, url, timeout)


async def delegate_to_security_expert(
    query: str,
    expert_agent_url: str = "",
    timeout: int = 30,
) -> Optional[str]:
    """将安全问题委托给安全审计专家 Agent。

    复用 delegate_to_expert() 的 A2A Client 模式。
    a2a-sdk 不可用时回退到本地分析逻辑。
    """
    url = expert_agent_url or SECURITY_EXPERT_URL
    if not _A2A_AVAILABLE:
        # a2a-sdk 未安装时回退到本地分析逻辑
        from src.protocols.security_agent import _security_analyze
        return _security_analyze(query)
    return await delegate_to_expert(query, url, timeout)


# ---------------------------------------------------------------------------
# LangChain 工具封装 — 供客服 Agent 调用
# ---------------------------------------------------------------------------

import asyncio as _asyncio
from langchain_core.tools import tool as langchain_tool


@langchain_tool
def delegate_to_performance_expert(query: str) -> str:
    """将复杂的性能问题委托给性能诊断专家 Agent。

    当以下情况时调用此工具：
    1. 用户报告同步卡住、超时等性能问题，且知识库无法解答
    2. 涉及大文件传输瓶颈、数据库锁冲突等底层问题
    3. API 延迟/限流问题超出常规 FAQ 范围

    Args:
        query: 需要委托给性能专家的问题描述（包含具体的错误码、文件大小、时间等上下文）
    """
    try:
        result = _asyncio.run(delegate_to_perf_expert(query))
        if result:
            return f"[性能专家诊断结果]\n{result}"
        return "[委托失败] 性能专家 Agent 暂时不可用，建议转人工客服处理此性能问题。"
    except RuntimeError:
        return "[委托失败] 无法发起 A2A 委托，可能性能专家 Agent 未启动。建议转人工客服。"
    except Exception as e:
        return f"[委托失败] {str(e)[:100]}"


@langchain_tool
def delegate_to_security_audit_expert(query: str) -> str:
    """将安全问题委托给安全审计专家 Agent。

    当以下情况时调用此工具：
    1. 用户怀疑账号被盗、有异常登录记录
    2. 涉及权限越权、API Key 泄露等安全事件
    3. 需要生成合规审计报告（如 SOC2）
    4. 安全相关问题超出客服知识库范围

    Args:
        query: 需要委托给安全专家的问题描述（包含具体的用户ID、时间、可疑操作等上下文）
    """
    try:
        result = _asyncio.run(delegate_to_security_expert(query))
        if result:
            return f"[安全专家分析结果]\n{result}"
        return "[委托失败] 安全审计专家 Agent 暂时不可用，建议转人工客服处理此安全问题。"
    except RuntimeError:
        return "[委托失败] 无法发起 A2A 委托，可能安全审计专家 Agent 未启动。建议转人工客服。"
    except Exception as e:
        return f"[委托失败] {str(e)[:100]}"


def create_expert_delegation_tools() -> list:
    """创建专家委托工具列表，供客服 Agent 使用。

    Returns:
        [delegate_to_performance_expert, delegate_to_security_audit_expert]
    """
    return [delegate_to_performance_expert, delegate_to_security_audit_expert]


# ---------------------------------------------------------------------------
# A2A Server 启动入口
# ---------------------------------------------------------------------------


async def main():
    """启动 A2A Server: python -m src.protocols.a2a_server"""
    import uvicorn
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
