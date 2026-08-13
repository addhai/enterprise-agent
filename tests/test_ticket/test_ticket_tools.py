"""tests for src.ticket.tools

覆盖 6 个工单 MCP 工具的全部分支：权限校验、参数校验、资源级权限、
写角色限制、正常读写、各类未找到/失败分支。
"""
import pytest

from src.agent.tools import PermissionChecker
from src.ticket.store import InMemoryTicketStore
from src.ticket.tools import create_ticket_tools


def _make_tools(user_id="u1", tenant_id="t1", roles=None, store=None):
    if store is None:
        store = InMemoryTicketStore()
    return create_ticket_tools(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles or ["support_agent"],
        store=store,
    )


def _create_one(tools, store, title="测试工单", description="desc", user_id="u1",
                tenant_id="t1", **kw):
    tools[0].invoke(
        {
            "title": title,
            "description": description,
            "category": kw.get("category", "technical"),
            "priority": kw.get("priority", "medium"),
            "tags": kw.get("tags", "退款,企业版"),
        }
    )
    # 从 store 取最新工单 id
    flt = __import__("src.ticket.models", fromlist=["TicketListFilter"]).TicketListFilter(
        tenant_id=tenant_id, user_id=user_id
    )
    tickets = store.list(flt)
    return tickets[0]


# ---------------------------------------------------------------------------
# _ticket_to_summary
# ---------------------------------------------------------------------------
def test_ticket_to_summary_all_branches():
    from src.ticket.models import Ticket, TicketCategory, TicketPriority, TicketStatus
    from datetime import datetime, timezone

    t = Ticket(
        id="TKT-12345678",
        tenant_id="t1",
        user_id="u1",
        title="标题",
        description="x" * 300,  # 触发截断分支
        category=TicketCategory.TECHNICAL,
        priority=TicketPriority.HIGH,
        status=TicketStatus.OPEN,
        assignee="agent9",
        tags=["a", "b"],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    t.comments = [object(), object()]  # 触发 Comments 分支
    s = __import__("src.ticket.tools", fromlist=["_ticket_to_summary"])._ticket_to_summary(t)
    assert "TKT-12345678" in s
    assert "Assignee: agent9" in s
    assert "Tags: a, b" in s
    assert "Comments: 2 条" in s
    assert "..." in s  # 长描述被截断


# ---------------------------------------------------------------------------
# ticket_create
# ---------------------------------------------------------------------------
def test_create_ticket_ok():
    store = InMemoryTicketStore()
    tools = _make_tools(store=store)
    out = tools[0].invoke(
        {"title": "登录失败", "description": "无法登录", "category": "account", "priority": "high"}
    )
    assert "[工单已创建]" in out
    assert "登录失败" in out
    assert "TKT-" in out


def test_create_ticket_permission_denied(monkeypatch):
    store = InMemoryTicketStore()
    monkeypatch.setattr(PermissionChecker, "check", lambda self, n, scope=None: False)
    tools = _make_tools(store=store)
    out = tools[0].invoke({"title": "x", "description": "y"})
    assert "[权限不足] 您没有权限创建工单。" in out


def test_create_ticket_invalid_category():
    store = InMemoryTicketStore()
    tools = _make_tools(store=store)
    out = tools[0].invoke({"title": "x", "description": "y", "category": "bogus"})
    assert "[参数错误] 无效的 category" in out


def test_create_ticket_invalid_priority():
    store = InMemoryTicketStore()
    tools = _make_tools(store=store)
    out = tools[0].invoke({"title": "x", "description": "y", "priority": "bogus"})
    assert "[参数错误] 无效的 priority" in out


def test_create_ticket_idempotency():
    store = InMemoryTicketStore()
    tools = _make_tools(store=store)
    kw = {"title": "idem", "description": "d", "idempotency_key": "KEY-1"}
    out1 = tools[0].invoke(kw)
    out2 = tools[0].invoke(kw)
    # 幂等键相同 -> 不会创建第二个工单
    flt = __import__("src.ticket.models", fromlist=["TicketListFilter"]).TicketListFilter(
        tenant_id="t1", user_id="u1"
    )
    assert len(store.list(flt)) == 1
    assert out1 == out2


# ---------------------------------------------------------------------------
# ticket_query
# ---------------------------------------------------------------------------
def test_query_ticket_ok():
    store = InMemoryTicketStore()
    tools = _make_tools(store=store)
    t = _create_one(tools, store)
    out = tools[1].invoke({"ticket_id": t.id})
    assert "TKT-" in out
    assert "登录失败" not in out  # 标题是默认 "测试工单"
    assert t.title in out


def test_query_ticket_not_found():
    store = InMemoryTicketStore()
    tools = _make_tools(store=store)
    out = tools[1].invoke({"ticket_id": "TKT-NOPE"})
    assert "[未找到]" in out


def test_query_ticket_resource_denied():
    store = InMemoryTicketStore()
    tools_a = _make_tools(user_id="A", tenant_id="t1", roles=["customer"], store=store)
    t = _create_one(tools_a, store, user_id="A", tenant_id="t1")
    # 用 B（无 admin）查询 A 的工单 -> 资源级拒绝
    tools_b = _make_tools(user_id="B", tenant_id="t1", roles=["customer"], store=store)
    out = tools_b[1].invoke({"ticket_id": t.id})
    assert "[权限不足] 您只能查看自己提交的工单。" in out


def test_query_ticket_permission_denied(monkeypatch):
    store = InMemoryTicketStore()
    monkeypatch.setattr(PermissionChecker, "check", lambda self, n, scope=None: False)
    tools = _make_tools(store=store)
    out = tools[1].invoke({"ticket_id": "TKT-X"})
    assert "[权限不足] 您没有权限查询工单。" in out


# ---------------------------------------------------------------------------
# ticket_list
# ---------------------------------------------------------------------------
def test_list_tickets_as_admin():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["admin"], store=store)
    _create_one(tools, store)
    _create_one(tools, store, title="第二个")
    out = tools[2].invoke({})
    assert "共 2 条工单" in out


def test_list_tickets_empty():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["admin"], store=store)
    out = tools[2].invoke({})
    assert "[查询完成] 当前没有匹配的工单。" in out


def test_list_tickets_filter_status():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["admin"], store=store)
    _create_one(tools, store)
    out = tools[2].invoke({"status": "open"})
    assert "共 1 条工单" in out
    out2 = tools[2].invoke({"status": "resolved"})
    assert "当前没有匹配的工单" in out2


def test_list_tickets_invalid_status():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["admin"], store=store)
    out = tools[2].invoke({"status": "bogus"})
    assert "[参数错误]" in out


def test_list_tickets_permission_denied(monkeypatch):
    store = InMemoryTicketStore()
    monkeypatch.setattr(PermissionChecker, "check", lambda self, n, scope=None: False)
    tools = _make_tools(store=store)
    out = tools[2].invoke({})
    assert "[权限不足] 您没有权限列出工单。" in out


# ---------------------------------------------------------------------------
# ticket_update
# ---------------------------------------------------------------------------
def test_update_ticket_ok():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["support_agent"], store=store)
    t = _create_one(tools, store)
    out = tools[3].invoke({"ticket_id": t.id, "status": "in_progress", "priority": "urgent"})
    assert "[工单已更新]" in out
    assert "urgent" in out


def test_update_ticket_write_denied():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["viewer"], store=store)
    t = _create_one(tools, store)
    out = tools[3].invoke({"ticket_id": t.id, "status": "in_progress"})
    assert "[权限不足] 更新工单需要 admin 或 support_agent 角色。" in out


def test_update_ticket_permission_denied(monkeypatch):
    store = InMemoryTicketStore()
    monkeypatch.setattr(PermissionChecker, "check", lambda self, n, scope=None: False)
    tools = _make_tools(store=store)
    out = tools[3].invoke({"ticket_id": "TKT-X"})
    assert "[权限不足] 您没有权限更新工单。" in out


def test_update_ticket_invalid_param():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["support_agent"], store=store)
    t = _create_one(tools, store)
    out = tools[3].invoke({"ticket_id": t.id, "status": "bogus"})
    assert "[参数错误]" in out


def test_update_ticket_not_found():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["support_agent"], store=store)
    out = tools[3].invoke({"ticket_id": "TKT-NOPE", "status": "open"})
    assert "[更新失败]" in out


# ---------------------------------------------------------------------------
# ticket_close
# ---------------------------------------------------------------------------
def test_close_ticket_ok():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["admin"], store=store)
    t = _create_one(tools, store)
    out = tools[4].invoke({"ticket_id": t.id, "resolution": "已修复"})
    assert "[工单已关闭]" in out
    # 关闭后状态应为 closed
    flt = __import__("src.ticket.models", fromlist=["TicketListFilter"]).TicketListFilter(
        tenant_id="t1", user_id="u1"
    )
    closed = store.list(flt)[0]
    assert closed.status.value == "closed"


def test_close_ticket_write_denied():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["viewer"], store=store)
    t = _create_one(tools, store)
    out = tools[4].invoke({"ticket_id": t.id, "resolution": "x"})
    assert "[权限不足] 关闭工单需要 admin 或 support_agent 角色。" in out


def test_close_ticket_empty_resolution():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["admin"], store=store)
    t = _create_one(tools, store)
    out = tools[4].invoke({"ticket_id": t.id, "resolution": "   "})
    assert "[参数错误] resolution 不能为空。" in out


def test_close_ticket_not_found():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["admin"], store=store)
    out = tools[4].invoke({"ticket_id": "TKT-NOPE", "resolution": "x"})
    assert "[关闭失败]" in out


def test_close_ticket_permission_denied(monkeypatch):
    store = InMemoryTicketStore()
    monkeypatch.setattr(PermissionChecker, "check", lambda self, n, scope=None: False)
    tools = _make_tools(store=store)
    out = tools[4].invoke({"ticket_id": "TKT-X", "resolution": "x"})
    assert "[权限不足] 您没有权限关闭工单。" in out


# ---------------------------------------------------------------------------
# ticket_add_comment
# ---------------------------------------------------------------------------
def test_add_comment_ok():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["support_agent"], store=store)
    t = _create_one(tools, store)
    out = tools[5].invoke({"ticket_id": t.id, "content": "正在处理"})
    assert "评论已添加" in out
    assert "1 条评论" in out


def test_add_comment_empty():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["support_agent"], store=store)
    t = _create_one(tools, store)
    out = tools[5].invoke({"ticket_id": t.id, "content": "   "})
    assert "[参数错误] content 不能为空。" in out


def test_add_comment_not_found():
    store = InMemoryTicketStore()
    tools = _make_tools(roles=["support_agent"], store=store)
    out = tools[5].invoke({"ticket_id": "TKT-NOPE", "content": "x"})
    assert "[未找到]" in out


def test_add_comment_resource_denied():
    store = InMemoryTicketStore()
    tools_a = _make_tools(user_id="A", tenant_id="t1", roles=["customer"], store=store)
    t = _create_one(tools_a, store, user_id="A", tenant_id="t1")
    tools_b = _make_tools(user_id="B", tenant_id="t1", roles=["customer"], store=store)
    out = tools_b[5].invoke({"ticket_id": t.id, "content": "我想评论"})
    assert "[权限不足] 您只能给自己提交的工单评论。" in out


def test_add_comment_permission_denied(monkeypatch):
    store = InMemoryTicketStore()
    monkeypatch.setattr(PermissionChecker, "check", lambda self, n, scope=None: False)
    tools = _make_tools(store=store)
    out = tools[5].invoke({"ticket_id": "TKT-X", "content": "x"})
    assert "[权限不足] 您没有权限添加评论。" in out
