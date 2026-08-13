"""
Orchestrator Agent — 多专家协调器

作为请求入口，智能路由到合适的专家 Agent。支持：
- 技能匹配路由
- 多专家协同
- 结果聚合
- 容错与降级

架构:
  用户请求 ──→ Orchestrator Agent ──→ 路由决策
                                        ↓
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
            客服 Agent            性能专家 Agent        安全专家 Agent
            (常规咨询)            (性能诊断)            (安全审计)

使用方式:
  启动: python -m src.protocols.orchestrator_agent      # 端口 9000

  A2A 委托示例:
    client = a2a.Client(orchestrator_url)
    response = await client.send_message("My sync is stuck")
"""

import asyncio
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# A2A SDK 是否可用（延迟检测）
_A2A_AVAILABLE = False
try:
    import a2a  # noqa: F401
    _A2A_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Orchestrator 路由逻辑
# ---------------------------------------------------------------------------


def _keyword_match(keyword: str, text: str) -> bool:
    """精确关键词匹配（避免子串误命中）

    - 英文关键词：用词边界 \\b 匹配，避免 "sync" 命中 "CloudSync"
    - 中文关键词：中文无词边界概念，直接子串匹配（中文不会出现
      "CloudSync" 含 "sync" 这种跨语言子串误命中问题）
    - 含空格的复合词（如 "api key"）：作为整体按词边界匹配
    - 纯数字关键词（如错误码 "429"）：直接子串匹配
    """
    import re
    # 纯数字（错误码）直接子串匹配
    if keyword.isdigit():
        return keyword in text
    # 含中文字符 → 子串匹配（中文无词边界）
    if re.search(r'[\u4e00-\u9fff]', keyword):
        return keyword in text
    # 纯英文/含空格复合词 → 词边界匹配（忽略大小写已由调用方保证）
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))


class Orchestrator:
    """Orchestrator 核心逻辑 — 智能路由和协调"""

    def __init__(self):
        from src.protocols.agent_registry import registry
        self.registry = registry
        # 延迟获取 HealthChecker 单例（含 CircuitBreaker）
        # 首次调用 route_request / delegate_to_agent 时才解析，避免循环导入
        self._health_checker = None

    @property
    def health_checker(self):
        """延迟获取 HealthChecker 单例"""
        if self._health_checker is None:
            try:
                from src.protocols.health_checker import get_health_checker
                self._health_checker = get_health_checker()
            except Exception as e:
                logger.warning("HealthChecker unavailable, fallback to no-circuit mode: %s", e)
                self._health_checker = None
        return self._health_checker

    def _is_available(self, agent_id: str) -> bool:
        """检查 Agent 是否可调用：在线 + 熔断器未断开"""
        entry = self.registry.get(agent_id)
        if not entry or entry.status != "online":
            return False
        cb = self.health_checker.circuit_breaker if self.health_checker else None
        if cb and not cb.can_call(agent_id):
            logger.info(
                "Agent %s skipped (circuit %s)",
                agent_id, cb.state(agent_id),
            )
            return False
        return True

    async def route_request(self, query: str) -> dict:
        """智能路由请求到合适的 Agent

        Args:
            query: 用户查询文本

        Returns:
            路由结果，包含匹配的 Agent 列表和优先级排序
        """
        query_lower = query.lower()

        # 安全相关关键词（优先检查，因为包含更具体的复合词）
        security_keywords = [
            "security", "安全", "auth", "认证", "login", "登录", "password", "密码",
            "token", "令牌", "api key", "apikey", "泄露", "exploit", "漏洞",
            "permission", "权限", "audit", "审计", "compliance", "合规", "越权",
            "hack", "攻击", "phishing", "钓鱼", "malware", "恶意"
        ]

        # 性能"症状词"：直接命中即判定为性能问题。
        # 注意：sync/同步/transfer/传输/database 等领域词已移除，
        # 因为它们单独出现时可能是客服咨询功能（如"配置同步设置"），
        # 需配合症状词（慢/卡/超时/瓶颈）才构成性能问题。
        perf_symptom_keywords = [
            "slow", "lag", "延迟", "卡顿", "stuck", "卡住", "timeout", "超时",
            "performance", "性能", "响应慢", "429", "503", "瓶颈", "失败",
            "lock", "锁", "deadlock", "死锁", "慢", "error", "错误", "crash", "崩溃"
        ]

        # 客服相关关键词（兜底）
        cs_keywords = [
            "help", "帮助", "faq", "问题", "issue", "bug", "错误", "error",
            "how", "如何", "what", "什么", "why", "为什么", "support", "支持",
            "guide", "指南", "文档", "document", "setup", "配置", "install", "安装"
        ]

        matched_agents = []

        # 匹配安全专家（优先）
        is_security_query = any(_keyword_match(kw, query_lower) for kw in security_keywords)
        if is_security_query:
            sec_entry = self.registry.get("security_expert")
            if sec_entry and self._is_available("security_expert"):
                matched_agents.append(("security_expert", "high", sec_entry))

        # 匹配性能专家：
        # - 症状词直接命中 → 性能问题（如"慢/卡/超时/瓶颈"）
        # - 仅领域词命中（如"同步/传输"）但无症状词 → 可能是客服咨询功能，不算性能问题
        has_perf_symptom = any(_keyword_match(kw, query_lower) for kw in perf_symptom_keywords)
        is_perf_query = has_perf_symptom
        if is_perf_query:
            perf_entry = self.registry.get("performance_expert")
            if perf_entry and self._is_available("performance_expert"):
                matched_agents.append(("performance_expert", "high", perf_entry))

        # 匹配客服（兜底或客服特定查询）
        cs_entry = self.registry.get("customer_service")
        if cs_entry and self._is_available("customer_service"):
            if not matched_agents or any(_keyword_match(kw, query_lower) for kw in cs_keywords):
                matched_agents.append(("customer_service", "medium", cs_entry))

        # 按优先级排序
        priority_order = {"high": 0, "medium": 1, "low": 2}
        matched_agents.sort(key=lambda x: priority_order[x[1]])

        return {
            "query": query,
            "matched_agents": [
                {
                    "agent_id": aid,
                    "priority": pri,
                    "name": entry.name,
                    "url": entry.url,
                    "skills": [s["name"] for s in entry.skills],
                }
                for aid, pri, entry in matched_agents
            ],
            "best_match": matched_agents[0][0] if matched_agents else None,
        }

    async def delegate_to_agent(self, agent_id: str, query: str) -> Optional[str]:
        """委托请求到指定 Agent

        在调用前后更新熔断器：
        - 成功（返回非空字符串）→ record_success
        - 失败（抛异常 / 返回 None / 返回空串）→ record_failure

        Args:
            agent_id: 目标 Agent ID
            query: 用户查询

        Returns:
            Agent 返回的结果，失败返回 None
        """
        entry = self.registry.get(agent_id)
        if not entry:
            logger.error("Agent not found: %s", agent_id)
            return None

        # 二次检查熔断器状态（防止并发期间状态变化）
        if not self._is_available(agent_id):
            logger.warning("Agent %s not available (offline or circuit open)", agent_id)
            return None

        cb = self.health_checker.circuit_breaker if self.health_checker else None

        try:
            if _A2A_AVAILABLE:
                result = await self._delegate_via_a2a(entry.url, query)
            else:
                result = await self._delegate_local(agent_id, query)

            # 空结果也视为失败（专家没响应）
            if not result or not result.strip():
                if cb:
                    cb.record_failure(agent_id, "empty_response")
                logger.warning("Agent %s returned empty response", agent_id)
                return None

            # 成功 → 重置熔断器
            if cb:
                cb.record_success(agent_id)
            return result

        except Exception as e:
            # 失败 → 累计失败次数
            if cb:
                cb.record_failure(agent_id, str(e)[:100])
            logger.error("Failed to delegate to %s: %s", agent_id, e)
            return None

    async def _delegate_via_a2a(self, url: str, query: str) -> Optional[str]:
        """通过 A2A 协议委托

        带显式超时 + 指数退避重试：
        - 超时：a2a_expert_timeout（默认 30s）
        - 重试：最多 3 次，间隔 0.5s → 1s → 2s
        - 重试条件：网络异常 / 超时（业务错误不重试）
        """
        from a2a.client import create_client
        from a2a.types.a2a_pb2 import SendMessageRequest
        from uuid import uuid4
        import asyncio as _asyncio
        import os

        # 确保 localhost 直连不走代理
        os.environ.setdefault("NO_PROXY", "*")
        os.environ.setdefault("no_proxy", "*")

        # 读取超时配置（a2a_server 中已有 a2a_expert_timeout，这里复用）
        try:
            from src.config import settings
            timeout_seconds = getattr(settings, "a2a_expert_timeout", 30)
        except Exception:
            timeout_seconds = 30

        max_retries = 3
        backoff_seconds = 0.5

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                # 创建高超时 httpx client 并通过 ClientConfig 传入，
                # 避免 cs agent 调 LLM 慢响应导致默认超时失败
                # 用 async with 确保重试时旧 client 自动关闭，避免连接泄漏
                import httpx as _httpx
                from a2a.client.client import ClientConfig as _ClientConfig
                async with _httpx.AsyncClient(
                    trust_env=False,
                    timeout=_httpx.Timeout(float(timeout_seconds), connect=30.0),
                ) as _http:
                    _cfg = _ClientConfig(httpx_client=_http)
                    client = await create_client(
                        url,
                        client_config=_cfg,
                        relative_card_path="/.well-known/agent.json",
                        resolver_http_kwargs={"timeout": float(timeout_seconds)},
                    )
                    context_id = str(uuid4())
                    # task_id 留空：a2a-sdk 服务端要求若指定 task_id 则该 task 必须已存在，
                    # 否则抛 TaskNotFoundError；让服务端自动创建新 task。
                    from a2a.types import Role
                    message = _make_text_message(
                        query, context_id, "", role=Role.ROLE_USER
                    )
                    request = SendMessageRequest(message=message)
                    # send_message 返回流式 AsyncIterator[StreamResponse]，
                    # 取第一个响应；外层用 asyncio.wait_for 兜底超时
                    async def _consume_response():
                        async for resp in client.send_message(request):
                            return resp
                        return None

                    response = await _asyncio.wait_for(
                        _consume_response(),
                        timeout=timeout_seconds,
                    )

                    # StreamResponse.payload oneof: message | task | status_update | artifact_update
                    if response and response.message and response.message.parts:
                        return "\n".join(
                            p.text for p in response.message.parts if p.text
                        )
                    return None

            except _asyncio.TimeoutError:
                last_error = f"timeout after {timeout_seconds}s"
                logger.warning(
                    "A2A delegate timeout (attempt %d/%d) url=%s",
                    attempt, max_retries, url,
                )
            except Exception as e:
                last_error = str(e)[:100]
                # 业务错误（如 4xx）不重试，仅网络/超时重试
                err_str = str(e).lower()
                if any(x in err_str for x in ["400", "401", "403", "404", "validation"]):
                    logger.error("A2A delegate business error (no retry): %s", e)
                    return None
                logger.warning(
                    "A2A delegate error (attempt %d/%d) url=%s: %s",
                    attempt, max_retries, url, e,
                )

            # 还有重试机会则等待
            if attempt < max_retries:
                await _asyncio.sleep(backoff_seconds)
                backoff_seconds *= 2  # 指数退避

        logger.error(
            "A2A delegate failed after %d retries (url=%s): %s",
            max_retries, url, last_error,
        )
        return None

    async def _delegate_local(self, agent_id: str, query: str) -> Optional[str]:
        """本地委托（fallback）"""
        if agent_id == "performance_expert":
            from src.protocols.perf_agent import diagnose_performance_issue
            return diagnose_performance_issue(query)
        elif agent_id == "security_expert":
            from src.protocols.security_agent import perform_security_audit
            return perform_security_audit(query)
        elif agent_id == "customer_service":
            from src.agent.tools import search_knowledge_base
            return search_knowledge_base(query)
        return None

    async def orchestrate(self, query: str) -> dict:
        """完整编排流程：路由 + 委托 + 聚合

        Args:
            query: 用户查询

        Returns:
            包含路由结果和各 Agent 响应的字典
        """
        routing = await self.route_request(query)
        responses = {}

        if routing["matched_agents"]:
            best_match = routing["best_match"]
            logger.info("Routing query to %s", best_match)
            response = await self.delegate_to_agent(best_match, query)
            responses[best_match] = response or "No response"

        return {
            "query": query,
            "routing": routing,
            "responses": responses,
            "final_response": list(responses.values())[0] if responses else None,
        }


# ---------------------------------------------------------------------------
# Orchestrator Agent Card 定义（延迟加载 a2a-sdk）
# ---------------------------------------------------------------------------


ORCHESTRATOR_AGENT_CARD = None
ORCHESTRATOR_AGENT_SKILLS = [
    {
        "id": "request_routing",
        "name": "Request Routing",
        "description": "智能路由用户请求到最合适的专家 Agent",
        "tags": ["orchestrator", "routing", "dispatch", "coordination"],
        "examples": [
            "Route this request to the right expert",
            "Find the best agent for this query",
        ],
    },
    {
        "id": "multi_agent_coordination",
        "name": "Multi-Agent Coordination",
        "description": "协调多个专家 Agent 共同解决复杂问题",
        "tags": ["orchestrator", "coordination", "multi-agent", "workflow"],
        "examples": [
            "Need both performance and security analysis",
            "Coordinate multiple experts for a complex issue",
        ],
    },
    {
        "id": "result_aggregation",
        "name": "Result Aggregation",
        "description": "聚合多个专家 Agent 的响应，提供综合解决方案",
        "tags": ["orchestrator", "aggregation", "summary", "integration"],
        "examples": [
            "Summarize responses from multiple agents",
            "Combine expert opinions",
        ],
    },
    {
        "id": "fault_tolerance",
        "name": "Fault Tolerance",
        "description": "自动处理专家 Agent 不可用情况，提供降级方案",
        "tags": ["orchestrator", "fault-tolerance", "fallback", "recovery"],
        "examples": [
            "Handle unavailable agents gracefully",
            "Automatic fallback when expert is offline",
        ],
    },
]


def _build_orchestrator_agent_card():
    """延迟构建 a2a AgentCard 对象"""
    global ORCHESTRATOR_AGENT_CARD
    if ORCHESTRATOR_AGENT_CARD is not None:
        return ORCHESTRATOR_AGENT_CARD

    from a2a.types import AgentCard, AgentCapabilities, AgentSkill, AgentInterface

    ORCHESTRATOR_AGENT_CARD = AgentCard(
        name="Orchestrator Agent",
        description=(
            "CloudSync Orchestrator Agent — 多专家协调器。"
            "作为请求入口，智能路由用户请求到合适的专家 Agent（客服、性能、安全）。"
            "支持技能匹配路由、多专家协同、结果聚合、容错与降级。"
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
            for s in ORCHESTRATOR_AGENT_SKILLS
        ],
        supported_interfaces=[
            AgentInterface(
                url="/",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
    )
    return ORCHESTRATOR_AGENT_CARD


# ---------------------------------------------------------------------------
# Orchestrator A2A Server
# ---------------------------------------------------------------------------


def _make_text_message(text: str, context_id: str, task_id: str, role=None):
    """Create a Message with a text Part (a2a-sdk 1.1.x compatible)"""
    from uuid import uuid4
    from a2a.types import Message, Part, Role
    return Message(
        message_id=str(uuid4()),
        role=role if role is not None else Role.ROLE_AGENT,
        context_id=context_id,
        task_id=task_id,
        parts=[Part(text=text)],
    )


class OrchestratorExecutor:
    """A2A AgentExecutor — 处理 A2A 委托请求"""

    def __init__(self):
        self.orchestrator = Orchestrator()

    async def execute(self, context, event_queue) -> None:
        """执行 A2A 请求（a2a-sdk 1.1.x AgentExecutor 接口）

        从 context 读取用户输入，调 orchestrator 协调路由，
        将最终回复通过 event_queue 发布为 Message 事件。
        """
        query = context.get_user_input()

        if not query:
            await event_queue.enqueue_event(
                _make_text_message(
                    "请提供需要协调处理的问题描述。",
                    context.context_id,
                    context.task_id,
                )
            )
            return

        logger.info("Orchestrator received query: %s", query[:100])

        try:
            result = await self.orchestrator.orchestrate(query)
            final_response = result.get("final_response", "No response")
        except Exception as e:
            logger.error("Orchestrator execution error: %s", e)
            final_response = f"Orchestrator error: {str(e)}"

        await event_queue.enqueue_event(
            _make_text_message(
                final_response, context.context_id, context.task_id
            )
        )

    async def cancel(self, context, event_queue) -> None:
        """取消任务（a2a-sdk 1.1.x AgentExecutor 接口要求）"""
        pass


def build_orchestrator_server(port: int = 9000):
    """构建 Orchestrator A2A Server（FastAPI + a2a-sdk 1.1.x 路由模式）

    注：旧版 a2a.Server(port=..., agent_card=...) 在 a2a-sdk 1.1.x 已移除，
    改用 FastAPI + DefaultRequestHandler + add_a2a_routes_to_fastapi（与
    perf_agent / security_agent / a2a_server 保持一致）。
    """
    if not _A2A_AVAILABLE:
        logger.warning("a2a-sdk not available, skipping orchestrator server build")
        return None

    from fastapi import FastAPI
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.server.routes import add_a2a_routes_to_fastapi
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.routes.rest_routes import create_rest_routes

    card = _build_orchestrator_agent_card()

    # a2a-sdk 1.1.x 客户端直接用 AgentInterface.url 作为请求 URL（不拼接 base url），
    # 故需把相对路径 "/" 补全为绝对 URL，否则客户端报 "Request URL is missing an 'http://' protocol"。
    for _iface in card.supported_interfaces:
        if _iface.url.startswith("/"):
            _iface.url = f"http://127.0.0.1:{port}{_iface.url}"

    app = FastAPI(
        title="CloudSync Orchestrator A2A Agent",
        description="A2A-compatible orchestrator agent — 多专家协调器",
        version="1.0.0",
    )

    handler = DefaultRequestHandler(
        agent_executor=OrchestratorExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

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
# CLI 启动入口
# ---------------------------------------------------------------------------


async def main():
    """启动 Orchestrator Agent: python -m src.protocols.orchestrator_agent"""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Orchestrator Agent")
    parser.add_argument("--port", type=int, default=9000, help="Port to listen on")
    parser.add_argument("--register", action="store_true", help="Register to registry")
    args = parser.parse_args()

    from src.protocols.agent_registry import register_default_agents, register_agent_card

    if args.register:
        register_default_agents()
        register_agent_card(
            agent_id="orchestrator",
            name="Orchestrator Agent",
            description=(
                "CloudSync Orchestrator Agent — 多专家协调器。"
                "智能路由请求到合适的专家 Agent。"
            ),
            url=f"http://localhost:{args.port}",
            skills=ORCHESTRATOR_AGENT_SKILLS,
            capabilities={"streaming": True},
            version="1.0.0",
        )

    app = build_orchestrator_server(args.port)
    if app is None:
        logger.error("Failed to build orchestrator server (a2a-sdk unavailable?)")
        return

    logger.info("Orchestrator Agent starting on http://localhost:%s", args.port)
    logger.info("Agent Card: http://localhost:%s/.well-known/agent.json", args.port)

    config = uvicorn.Config(app, host="0.0.0.0", port=args.port, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


if __name__ == "__main__":
    asyncio.run(main())
