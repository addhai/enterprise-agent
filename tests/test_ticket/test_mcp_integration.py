"""MCP Server 注册工单工具的集成测试

不启动真实 HTTP 服务，仅验证 build 函数正确注册了所有工具。
"""
import pytest

from src.protocols.mcp_server import build_mcp_server, build_ticket_only_server


def test_build_mcp_server_registers_all_tools(monkeypatch):
    """默认 MCP Server 应注册 33 个工具"""
    class FakeServer:
        def __init__(self, **kwargs):
            self.name = kwargs.get("name")
            self.version = kwargs.get("version")
            self.registered = []

        def tool(self, func):
            self.registered.append(func.__name__)
            return func

    monkeypatch.setattr("src.protocols.mcp_server.McpServer", FakeServer)

    server = build_mcp_server(
        user_id="test_user",
        tenant_id="test_tenant",
        roles=["admin"],
    )

    expected = {
        "search_knowledge_base", "search_faq", "escalate_to_human",
        "ticket_create", "ticket_query", "ticket_list",
        "ticket_update", "ticket_close", "ticket_add_comment",
        "billing_query_subscription", "billing_change_plan",
        "billing_refund", "billing_list_transactions", "billing_deduct",
        "user_get_profile", "user_reset_password", "user_disable_account",
        "user_list", "user_update_profile",
        "sso_configure", "sso_list_providers", "sso_test_connection",
        "sso_enable", "sso_disable",
        "api_key_generate", "api_key_revoke", "api_key_list",
        "api_key_get", "api_key_rotate",
        "audit_query_logs", "audit_export_report", "audit_search_by_user",
        "audit_get_log_details",
        "kb_ingest_document", "kb_rebuild_index", "kb_list_items",
        "kb_delete_item", "kb_search",
    }
    assert expected.issubset(set(server.registered)), \
        f"Missing tools: {expected - set(server.registered)}"


def test_build_mcp_server_without_ticket_tools(monkeypatch):
    """include_ticket=False 应不注册工单工具"""
    class FakeServer:
        def __init__(self, **kwargs):
            self.registered = []

        def tool(self, func):
            self.registered.append(func.__name__)
            return func

    monkeypatch.setattr("src.protocols.mcp_server.McpServer", FakeServer)

    server = build_mcp_server(include_ticket=False)
    assert "ticket_create" not in server.registered


def test_build_ticket_only_server(monkeypatch):
    """build_ticket_only_server 应只注册 6 个工单工具"""
    class FakeServer:
        def __init__(self, **kwargs):
            self.registered = []

        def tool(self, func):
            self.registered.append(func.__name__)
            return func

    monkeypatch.setattr("src.protocols.mcp_server.McpServer", FakeServer)

    server = build_ticket_only_server()
    expected = {
        "ticket_create", "ticket_query", "ticket_list",
        "ticket_update", "ticket_close", "ticket_add_comment",
    }
    assert set(server.registered) == expected


def test_build_mcp_server_admin_only_tools(monkeypatch):
    """客服工具不依赖 tenant_id，其他工具都依赖"""
    class FakeServer:
        def __init__(self, **kwargs):
            self.registered = []

        def tool(self, func):
            self.registered.append(func.__name__)
            return func

    monkeypatch.setattr("src.protocols.mcp_server.McpServer", FakeServer)

    server = build_mcp_server(
        include_customer_service=False,
        include_ticket=True,
        include_billing=True,
        include_users=True,
        include_sso=True,
        include_api_keys=True,
        include_audit=True,
        include_kb=True,
    )
    assert len(server.registered) == 35
