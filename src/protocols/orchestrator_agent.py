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


class Orchestrator:
    """Orchestrator 核心逻辑 — 智能路由和协调"""

    def __init__(self):
        from src.protocols.agent_registry import registry
        self.registry = registry

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

        # 性能相关关键词（排除安全相关的 api）
        perf_keywords = [
            "slow", "lag", "延迟", "卡顿", "stuck", "卡住", "timeout", "超时",
            "performance", "性能", "sync", "同步", "响应慢", "429", "503",
            "transfer", "传输", "database", "数据库", "lock", "锁", "deadlock", "死锁"
        ]

        # 客服相关关键词（兜底）
        cs_keywords = [
            "help", "帮助", "faq", "问题", "issue", "bug", "错误", "error",
            "how", "如何", "what", "什么", "why", "为什么", "support", "支持",
            "guide", "指南", "文档", "document", "setup", "配置", "install", "安装"
        ]

        matched_agents = []

        # 匹配安全专家（优先）
        is_security_query = any(kw in query_lower for kw in security_keywords)
        if is_security_query:
            sec_entry = self.registry.get("security_expert")
            if sec_entry and sec_entry.status == "online":
                matched_agents.append(("security_expert", "high", sec_entry))

        # 匹配性能专家（当安全查询中包含 api key 时，不重复匹配 api）
        is_perf_query = any(kw in query_lower for kw in perf_keywords)
        if is_perf_query:
            perf_entry = self.registry.get("performance_expert")
            if perf_entry and perf_entry.status == "online":
                matched_agents.append(("performance_expert", "high", perf_entry))

        # 匹配客服（兜底或客服特定查询）
        cs_entry = self.registry.get("customer_service")
        if cs_entry and cs_entry.status == "online":
            if not matched_agents or any(kw in query_lower for kw in cs_keywords):
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

        if entry.status != "online":
            logger.error("Agent offline: %s", agent_id)
            return None

        try:
            if _A2A_AVAILABLE:
                return await self._delegate_via_a2a(entry.url, query)
            else:
                return await self._delegate_local(agent_id, query)
        except Exception as e:
            logger.error("Failed to delegate to %s: %s", agent_id, e)
            return None

    async def _delegate_via_a2a(self, url: str, query: str) -> Optional[str]:
        """通过 A2A 协议委托"""
        from src.protocols.a2a_server import _make_text_message
        from uuid import uuid4

        client = a2a.Client(url)
        context_id = str(uuid4())
        task_id = str(uuid4())

        message = _make_text_message(query, context_id, task_id)
        response = await client.send_message(message)

        if response and response.parts:
            return "\n".join(p.text for p in response.parts if p.text)
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

    from a2a.types import AgentCard, AgentCapabilities, AgentSkill

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
    )


# ---------------------------------------------------------------------------
# Orchestrator A2A Server
# ---------------------------------------------------------------------------


class OrchestratorExecutor:
    """A2A AgentExecutor — 处理 A2A 委托请求"""

    def __init__(self):
        self.orchestrator = Orchestrator()

    async def execute(self, message):
        """执行 A2A 请求"""
        from a2a.types import Message, Part, Role
        from uuid import uuid4

        try:
            query = "\n".join(p.text for p in message.parts if p.text)
            logger.info("Orchestrator received query: %s", query[:100])

            result = await self.orchestrator.orchestrate(query)
            final_response = result.get("final_response", "No response")

            return Message(
                message_id=str(uuid4()),
                role=Role.ROLE_AGENT,
                context_id=message.context_id,
                task_id=message.task_id,
                parts=[Part(text=final_response)],
            )
        except Exception as e:
            logger.error("Orchestrator execution error: %s", e)
            return Message(
                message_id=str(uuid4()),
                role=Role.ROLE_AGENT,
                context_id=message.context_id,
                task_id=message.task_id,
                parts=[Part(text=f"Orchestrator error: {str(e)}")],
            )


def build_orchestrator_server(port: int = 9000) -> Optional["a2a.Server"]:
    """构建 Orchestrator A2A Server（延迟加载 a2a-sdk）"""
    if not _A2A_AVAILABLE:
        logger.warning("a2a-sdk not available, skipping orchestrator server build")
        return None

    _build_orchestrator_agent_card()

    server = a2a.Server(port=port, agent_card=ORCHESTRATOR_AGENT_CARD)
    server.register_executor(OrchestratorExecutor())

    return server


# ---------------------------------------------------------------------------
# CLI 启动入口
# ---------------------------------------------------------------------------


def main():
    """启动 Orchestrator Agent"""
    import argparse

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

    server = build_orchestrator_server(args.port)
    if server:
        logger.info("Orchestrator Agent starting on port %d", args.port)
        server.run()
    else:
        logger.error("Failed to build orchestrator server")


if __name__ == "__main__":
    main()
