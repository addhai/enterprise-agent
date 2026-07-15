"""
安全审计专家 Agent — 独立 A2A Agent

从客服 Agent 中拆分出的安全审计专家，专注处理：
  1. 可疑登录/异常操作检测
  2. 权限越权排查
  3. API Key 泄露风险评估
  4. 合规审计报告生成

启动方式:
  python -m src.protocols.security_agent            # 端口 9003
  python -m src.protocols.security_agent --port 9103

A2A 协作流:
  客服 Agent ──delegate_to_expert()──→ 安全审计专家 Agent (本服务)
  客服 Agent 翻译专家结论为用户友好回复
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 安全审计知识库（无外部依赖，可独立测试）
# ---------------------------------------------------------------------------

_SECURITY_KNOWLEDGE = {
    "suspicious_login": (
        "【可疑登录检测】\n"
        "检测指标:\n"
        "1. 异地登录 — 短时间内跨城市/国家登录\n"
        "2. 暴力破解 — 同一账号 5 分钟内 ≥10 次失败登录\n"
        "3. 非工作时间 — 凌晨 2:00-5:00 的管理员操作\n"
        "4. 设备指纹变更 — 新设备/新浏览器首次登录\n"
        "建议:\n"
        "→ 立即强制该用户重新认证（触发 2FA）\n"
        "→ 检查该登录后的操作记录是否有异常\n"
        "→ 如确认被盗，吊销所有活跃会话和 API Key\n"
        "→ 开启登录告警通知（邮件/短信）"
    ),
    "permission_escalation": (
        "【权限越权排查】\n"
        "检查项:\n"
        "1. 角色变更 — 查看角色变更审计日志，确认是否为合法操作\n"
        "2. 资源访问 — 对比用户 access_levels 与被访问资源的 required_level\n"
        "3. 权限缓存 — 检查 PermissionCache 是否在权限变更后正确失效\n"
        "4. 多租户隔离 — 确认 tenant_id 是否被伪造（跨租户越权）\n"
        "建议:\n"
        "→ 调用 audit_search_by_user 查看该用户最近操作\n"
        "→ 检查 PermissionChecker 的 _audit_log 中的 ROLE_DENIED 记录\n"
        "→ 如确认越权，立即降级用户角色并通知管理员\n"
        "→ 审查权限变更流程是否需要双人审批"
    ),
    "api_key_leak": (
        "【API Key 泄露评估】\n"
        "风险评估:\n"
        "1. 暴露范围 — 是否已公开（GitHub/日志/聊天工具）\n"
        "2. 权限级别 — 泄露的 Key 有哪些权限（read/write/admin）\n"
        "3. 使用记录 — 检查泄露后的 API 调用是否有异常\n"
        "4. 时间窗口 — 从泄露到发现的时间差\n"
        "建议:\n"
        "→ 立即吊销泄露的 Key（api_key_revoke）\n"
        "→ 生成新的 Key 并更新所有合法调用方\n"
        "→ 审查泄露时间窗口内的 API 调用日志\n"
        "→ 如有数据泄露风险，通知受影响的用户\n"
        "→ 实施 IP 白名单限制 Key 使用范围"
    ),
    "compliance_audit": (
        "【合规审计报告】\n"
        "报告内容:\n"
        "1. 操作记录 — CREATE/UPDATE/DELETE 等敏感操作统计\n"
        "2. 权限变更 — 角色提升/降级/吊销的完整历史\n"
        "3. 数据访问 — 知识库/用户数据/API 调用的访问日志\n"
        "4. 安全事件 — PERMISSION_DENIED/PROMPT_INJECTION 等安全告警\n"
        "建议:\n"
        "→ 调用 audit_export_report 导出指定时间范围的日志\n"
        "→ 重点关注 PERMISSION_DENIED 事件的频率和来源\n"
        "→ 检查是否有用户频繁触发安全规则（可能的探测行为）\n"
        "→ 定期（月度/季度）生成报告满足合规要求"
    ),
}


def _security_analyze(query: str) -> str:
    """基于关键词匹配的安全审计分析（无外部依赖）"""
    q = query.lower()

    if any(kw in q for kw in ["login", "unknown ip", "different country", "异地", "异常登录", "被盗"]):
        return _SECURITY_KNOWLEDGE["suspicious_login"]
    if any(kw in q for kw in ["permission", "escalation", "unauthorized", "越权", "权限", "角色提升"]):
        return _SECURITY_KNOWLEDGE["permission_escalation"]
    if any(kw in q for kw in ["api key", "leak", "stolen", "breach", "泄露", "被盗", "github"]):
        return _SECURITY_KNOWLEDGE["api_key_leak"]
    if any(kw in q for kw in ["compliance", "audit report", "soc2", "合规", "审计报告"]):
        return _SECURITY_KNOWLEDGE["compliance_audit"]

    return (
        "【安全审计】未匹配到特定场景，通用建议:\n"
        "1. 检查最近 24 小时的 PERMISSION_DENIED 审计日志\n"
        "2. 确认是否有异常的 API 调用频率突增\n"
        "3. 检查用户角色变更记录是否合法\n"
        "4. 如需进一步分析请提供具体的安全事件描述"
    )


# ---------------------------------------------------------------------------
# Agent Card 定义（延迟加载 a2a-sdk）
# ---------------------------------------------------------------------------

SECURITY_AGENT_CARD = None
SECURITY_AGENT_SKILLS = [
    {
        "id": "suspicious_login_detection",
        "name": "Suspicious Login Detection",
        "description": "检测异常登录行为：异地登录、暴力破解、非工作时间登录",
        "tags": ["security", "login", "anomaly", "brute-force"],
        "examples": [
            "I see a login from an unknown IP address",
            "My account was accessed from a different country",
        ],
    },
    {
        "id": "permission_escalation_check",
        "name": "Permission Escalation Check",
        "description": "排查权限越权：角色提升、未授权资源访问、权限缓存失效",
        "tags": ["security", "permission", "escalation", "unauthorized"],
        "examples": [
            "A user accessed resources they should not have access to",
            "Someone changed their own role to admin",
        ],
    },
    {
        "id": "api_key_leak_assessment",
        "name": "API Key Leak Assessment",
        "description": "评估 API Key 泄露风险：暴露范围、潜在影响、补救措施",
        "tags": ["security", "api-key", "leak", "breach"],
        "examples": [
            "My API key was accidentally committed to GitHub",
            "I think my API key was stolen",
        ],
    },
    {
        "id": "compliance_audit_report",
        "name": "Compliance Audit Report",
        "description": "生成合规审计报告：操作记录、权限变更历史、数据访问日志",
        "tags": ["security", "compliance", "audit", "report"],
        "examples": [
            "Generate a compliance audit report for last month",
            "I need an audit trail for SOC2 compliance",
        ],
    },
]


def _build_security_agent_card():
    """延迟构建 a2a AgentCard 对象"""
    global SECURITY_AGENT_CARD
    if SECURITY_AGENT_CARD is not None:
        return SECURITY_AGENT_CARD

    from a2a.types import AgentCard, AgentCapabilities, AgentSkill

    SECURITY_AGENT_CARD = AgentCard(
        name="Security Audit Expert Agent",
        description=(
            "CloudSync 安全审计专家 Agent。"
            "专精可疑登录检测、权限越权排查、API Key 泄露评估、合规审计报告。"
            "接收来自客服 Agent 的 A2A 委托请求。"
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
            for s in SECURITY_AGENT_SKILLS
        ],
    )
    return SECURITY_AGENT_CARD


# ---------------------------------------------------------------------------
# A2A Server（延迟加载 a2a-sdk）
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


class SecurityExpertExecutor:
    """安全审计专家 Agent 的 A2A 执行器"""

    async def execute(
        self, context, event_queue
    ) -> None:
        """接收 A2A 委托请求，执行安全审计分析"""
        query = context.get_user_input()

        if not query:
            await event_queue.enqueue_event(
                _make_text_message(
                    "请提供需要分析的安全问题描述。",
                    context.context_id,
                    context.task_id,
                )
            )
            return

        logger.info("Security expert received query: %s", query[:200])
        analysis = _security_analyze(query)

        await event_queue.enqueue_event(
            _make_text_message(analysis, context.context_id, context.task_id)
        )

    async def cancel(
        self, context, event_queue
    ) -> None:
        pass


def build_security_agent_server():
    """构建安全审计专家 Agent 的 A2A Server"""
    from fastapi import FastAPI
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.server.routes import add_a2a_routes_to_fastapi
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.routes.rest_routes import create_rest_routes

    card = _build_security_agent_card()

    app = FastAPI(
        title="CloudSync Security Audit Expert A2A Agent",
        description="A2A-compatible security audit expert agent",
        version="1.0.0",
    )

    handler = DefaultRequestHandler(
        agent_executor=SecurityExpertExecutor(),
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
# 启动入口
# ---------------------------------------------------------------------------


async def main():
    """启动安全审计专家 Agent: python -m src.protocols.security_agent"""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Security Audit Expert A2A Agent")
    parser.add_argument("--port", type=int, default=9003)
    args = parser.parse_args()

    app = build_security_agent_server()

    logger.info("Security Expert Agent starting on http://localhost:%s", args.port)
    logger.info("Agent Card: http://localhost:%s/.well-known/agent.json", args.port)

    config = uvicorn.Config(app, host="0.0.0.0", port=args.port, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


if __name__ == "__main__":
    asyncio.run(main())
