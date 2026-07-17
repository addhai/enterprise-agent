"""
MCP (Model Context Protocol) Server — 企业级 Agent 能力暴露

使用 zeromcp (McpServer, 1.4.0) 实现 HTTP 模式 MCP Server。
任意 MCP 兼容的 Agent（Claude Desktop、Claude Agent SDK、自定义 Agent 等）
通过 HTTP 连接后可以自动发现并调用工具。

启动方式:
  # 默认启动（所有内部工具，默认禁用外部服务）
  python -m src.protocols.mcp_server

  # 启用所有外部服务
  python -m src.protocols.mcp_server --enable-pg --enable-dingtalk --enable-github --enable-email --enable-calendar --enable-fs

  # 仅启动工单管理 MCP Server（端口 9005）
  python -m src.protocols.mcp_server --ticket-only

  # 仅启动管理后台工具（admin-only，端口 9010）
  python -m src.protocols.mcp_server --admin-only

  # 带身份上下文启动（注入 admin 角色）
  python -m src.protocols.mcp_server --user-id agent_007 --tenant-id tenant_A --roles admin

工具分类:
  [客服]     search_knowledge_base / search_faq / escalate_to_human (3)
  [工单]     ticket_* (6)
  [账单]     billing_* (5)
  [用户]     user_* (5)
  [SSO]      sso_* (5)
  [API]      api_key_* (5)
  [审计]     audit_* (4)
  [知识库]   kb_* (5)
  --- 外部服务集成 ---
  [PostgreSQL] pg_* (5)
  [钉钉]     dingtalk_* (6)
  [GitHub]   github_* (7)
  [Email]    email_* (5)
  [Calendar] calendar_* (6)
  [文件系统] fs_* (7)
  [Slack]    slack_* (7)
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from zeromcp import McpServer
except ImportError:
    McpServer = None

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _get_server_class():
    if McpServer is None:
        raise ImportError("zeromcp not installed. Install with: pip install zeromcp")
    return McpServer


def _register_tools(server, tools):
    """批量注册工具并返回工具名称列表"""
    names = []
    for t in tools:
        server.tool(t.func)
        names.append(t.name)
    return names


def build_mcp_server(
    user_id: str = "mcp_agent",
    tenant_id: str = "default",
    roles: list = None,
    include_customer_service: bool = True,
    include_ticket: bool = True,
    include_billing: bool = True,
    include_users: bool = True,
    include_sso: bool = True,
    include_api_keys: bool = True,
    include_audit: bool = True,
    include_kb: bool = True,
    include_postgres: bool = False,
    include_dingtalk: bool = False,
    include_feishu: bool = False,
    include_github: bool = False,
    include_email: bool = False,
    include_calendar: bool = False,
    include_filesystem: bool = False,
    include_slack: bool = False,
) -> McpServer:
    """构建完整的企业级 MCP Server

    Args:
        user_id: MCP 调用者身份
        tenant_id: 多租户隔离上下文
        roles: 调用者角色列表
        include_*: 是否注册各类工具
    """
    server = _get_server_class()(
        name="enterprise-agent",
        version="2.0.0",
    )

    all_tool_names = []
    context = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "roles": roles or [],
        "plan": "enterprise",
        "authority_source": None,
    }

    if include_customer_service:
        from src.agent.tools import create_tools

        tools = create_tools(retriever=None, user_id=user_id)
        all_tool_names.extend(_register_tools(server, tools))

    if include_ticket:
        from src.ticket.tools import create_ticket_tools

        tools = create_ticket_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_billing:
        from src.mcp_tools.billing import create_billing_tools

        tools = create_billing_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_users:
        from src.mcp_tools.users import create_user_tools

        tools = create_user_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_sso:
        from src.mcp_tools.sso import create_sso_tools

        tools = create_sso_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_api_keys:
        from src.mcp_tools.api_keys import create_api_key_tools

        tools = create_api_key_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_audit:
        from src.mcp_tools.audit import create_audit_tools

        tools = create_audit_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_kb:
        from src.mcp_tools.kb import create_kb_tools

        tools = create_kb_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    # ---- 外部服务集成工具 ----
    if include_postgres:
        from src.mcp_tools.postgres import create_postgres_tools

        tools = create_postgres_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_dingtalk:
        from src.mcp_tools.dingtalk import create_dingtalk_tools

        tools = create_dingtalk_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_feishu:
        from src.mcp_tools.feishu import create_feishu_tools

        tools = create_feishu_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_github:
        from src.mcp_tools.github import create_github_tools

        tools = create_github_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_email:
        from src.mcp_tools.email_tool import create_email_tools

        tools = create_email_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_calendar:
        from src.mcp_tools.calendar import create_calendar_tools

        tools = create_calendar_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_filesystem:
        from src.mcp_tools.filesystem import create_filesystem_tools

        tools = create_filesystem_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    if include_slack:
        from src.mcp_tools.slack import create_slack_tools

        tools = create_slack_tools(**context)
        all_tool_names.extend(_register_tools(server, tools))

    logger.info("Registered %d MCP tools: %s", len(all_tool_names), all_tool_names)
    return server


def build_ticket_only_server(**kwargs) -> McpServer:
    """仅工单管理 MCP Server"""
    server = _get_server_class()(
        name="enterprise-ticket-service",
        version="1.0.0",
    )
    from src.ticket.tools import create_ticket_tools

    tools = create_ticket_tools(**kwargs)
    _register_tools(server, tools)
    logger.info("Ticket-only server: %d tools registered", len(tools))
    return server


def build_admin_only_server(**kwargs) -> McpServer:
    """仅管理后台工具（不含客服基础工具）"""
    server = _get_server_class()(
        name="enterprise-admin-service",
        version="1.0.0",
    )

    from src.ticket.tools import create_ticket_tools
    from src.mcp_tools.billing import create_billing_tools
    from src.mcp_tools.users import create_user_tools
    from src.mcp_tools.sso import create_sso_tools
    from src.mcp_tools.api_keys import create_api_key_tools
    from src.mcp_tools.audit import create_audit_tools
    from src.mcp_tools.kb import create_kb_tools

    all_tools = []
    all_tools.extend(create_ticket_tools(**kwargs))
    all_tools.extend(create_billing_tools(**kwargs))
    all_tools.extend(create_user_tools(**kwargs))
    all_tools.extend(create_sso_tools(**kwargs))
    all_tools.extend(create_api_key_tools(**kwargs))
    all_tools.extend(create_audit_tools(**kwargs))
    all_tools.extend(create_kb_tools(**kwargs))

    _register_tools(server, all_tools)
    logger.info("Admin-only server: %d tools registered", len(all_tools))
    return server


def build_billing_only_server(**kwargs) -> McpServer:
    """仅账单管理 MCP Server"""
    server = _get_server_class()(
        name="enterprise-billing-service",
        version="1.0.0",
    )
    from src.mcp_tools.billing import create_billing_tools

    tools = create_billing_tools(**kwargs)
    _register_tools(server, tools)
    logger.info("Billing-only server: %d tools registered", len(tools))
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enterprise MCP Server")

    parser.add_argument(
        "--ticket-only", action="store_true",
        help="仅启动工单管理 MCP Server（端口 9005）",
    )
    parser.add_argument(
        "--admin-only", action="store_true",
        help="仅启动管理后台工具（端口 9010，不含客服基础工具）",
    )
    parser.add_argument(
        "--billing-only", action="store_true",
        help="仅启动账单管理 MCP Server（端口 9011）",
    )
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    parser.add_argument("--user-id", type=str, default="mcp_agent")
    parser.add_argument("--tenant-id", type=str, default="default")
    parser.add_argument(
        "--roles", type=str, default="",
        help="角色（逗号分隔），如 admin,support_agent,billing_manager",
    )

    group = parser.add_argument_group("工具过滤")
    group.add_argument("--no-cs", action="store_true", help="禁用客服工具")
    group.add_argument("--no-ticket", action="store_true", help="禁用工单工具")
    group.add_argument("--no-billing", action="store_true", help="禁用账单工具")
    group.add_argument("--no-users", action="store_true", help="禁用用户工具")
    group.add_argument("--no-sso", action="store_true", help="禁用 SSO 工具")
    group.add_argument("--no-api-keys", action="store_true", help="禁用 API Key 工具")
    group.add_argument("--no-audit", action="store_true", help="禁用审计工具")
    group.add_argument("--no-kb", action="store_true", help="禁用知识库工具")

    ext_group = parser.add_argument_group("外部服务集成（默认禁用）")
    ext_group.add_argument("--enable-pg", action="store_true", help="启用 PostgreSQL MCP 工具")
    ext_group.add_argument("--enable-dingtalk", action="store_true", help="启用钉钉 MCP 工具")
    ext_group.add_argument("--enable-feishu", action="store_true", help="启用飞书 MCP 工具")
    ext_group.add_argument("--enable-github", action="store_true", help="启用 GitHub MCP 工具")
    ext_group.add_argument("--enable-email", action="store_true", help="启用 Email MCP 工具")
    ext_group.add_argument("--enable-calendar", action="store_true", help="启用 Calendar MCP 工具")
    ext_group.add_argument("--enable-fs", action="store_true", help="启用文件系统 MCP 工具")
    ext_group.add_argument("--enable-slack", action="store_true", help="启用 Slack MCP 工具")

    args = parser.parse_args()

    roles_list = [r.strip() for r in args.roles.split(",") if r.strip()] or None
    context = {
        "user_id": args.user_id,
        "tenant_id": args.tenant_id,
        "roles": roles_list,
    }

    if args.ticket_only:
        server = build_ticket_only_server(**context)
        port = args.port or 9005
        logger.info("Starting Ticket-only MCP Server on http://localhost:%s", port)
    elif args.admin_only:
        server = build_admin_only_server(**context)
        port = args.port or 9010
        logger.info("Starting Admin-only MCP Server on http://localhost:%s", port)
    elif args.billing_only:
        server = build_billing_only_server(**context)
        port = args.port or 9011
        logger.info("Starting Billing-only MCP Server on http://localhost:%s", port)
    else:
        server = build_mcp_server(
            **context,
            include_customer_service=not args.no_cs,
            include_ticket=not args.no_ticket,
            include_billing=not args.no_billing,
            include_users=not args.no_users,
            include_sso=not args.no_sso,
            include_api_keys=not args.no_api_keys,
            include_audit=not args.no_audit,
            include_kb=not args.no_kb,
            include_postgres=args.enable_pg,
            include_dingtalk=args.enable_dingtalk,
            include_feishu=args.enable_feishu,
            include_github=args.enable_github,
            include_email=args.enable_email,
            include_calendar=args.enable_calendar,
            include_filesystem=args.enable_fs,
            include_slack=args.enable_slack,
        )
        port = args.port or 9000
        logger.info("Starting Enterprise MCP Server on http://localhost:%s", port)

    logger.info("  Streamable HTTP: http://localhost:%s/mcp", port)
    logger.info("  SSE:              http://localhost:%s/sse", port)
    logger.info("")
    logger.info("Any MCP-compatible agent can now:")
    logger.info("  1. Connect to http://localhost:%s/mcp", port)
    logger.info("  2. Call initialize → discover tools")
    logger.info("  3. Call tools/call → invoke any registered tool")
    server.serve(host="0.0.0.0", port=port, background=False)
