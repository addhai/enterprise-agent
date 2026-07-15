"""工单 MCP 工具测试 — 覆盖权限、CRUD、多租户隔离、幂等"""
import pytest

from src.ticket.tools import create_ticket_tools
from src.ticket.store import InMemoryTicketStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_store():
    """每个测试独立的内存存储，避免互相污染"""
    return InMemoryTicketStore()


@pytest.fixture
def admin_tools(fresh_store):
    """admin 角色 — 拥有全部权限"""
    return create_ticket_tools(
        user_id="admin_1",
        tenant_id="tenant_A",
        roles=["admin"],
        store=fresh_store,
    )


@pytest.fixture
def user_tools(fresh_store):
    """普通用户 — 只能查/改自己的工单"""
    return create_ticket_tools(
        user_id="user_1",
        tenant_id="tenant_A",
        roles=[],
        store=fresh_store,
    )


def _find_tool(tools, name: str):
    return [t for t in tools if t.name == name][0]


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------

def test_all_six_tools_registered(admin_tools):
    """应注册 6 个工单工具"""
    names = [t.name for t in admin_tools]
    expected = {
        "ticket_create", "ticket_query", "ticket_list",
        "ticket_update", "ticket_close", "ticket_add_comment",
    }
    assert expected.issubset(set(names)), f"缺少工具: {expected - set(names)}"


def test_tools_have_descriptions(admin_tools):
    """每个工具都应有非空描述（MCP 暴露给 Agent 的元数据）"""
    for t in admin_tools:
        assert t.description, f"{t.name} description is empty"
        assert len(t.description) > 20, f"{t.name} description too short"


# ---------------------------------------------------------------------------
# ticket_create
# ---------------------------------------------------------------------------

def test_ticket_create_success(admin_tools):
    """admin 创建工单应成功"""
    create_tool = _find_tool(admin_tools, "ticket_create")
    result = create_tool.invoke({
        "title": "无法登录",
        "description": "点击登录无响应",
        "category": "account",
        "priority": "high",
        "tags": "登录,紧急",
    })

    assert "[工单已创建]" in result
    assert "Title: 无法登录" in result
    assert "Status: open" in result
    assert "Priority: high" in result


def test_ticket_create_invalid_category(admin_tools):
    """无效 category 应被拒绝"""
    create_tool = _find_tool(admin_tools, "ticket_create")
    result = create_tool.invoke({
        "title": "测试",
        "description": "",
        "category": "invalid_cat",
    })
    assert "[参数错误]" in result


def test_ticket_create_idempotent(fresh_store):
    """相同 idempotency_key 应返回同一张工单"""
    tools = create_ticket_tools(
        user_id="u", tenant_id="t", roles=["admin"], store=fresh_store,
    )
    create_tool = _find_tool(tools, "ticket_create")

    r1 = create_tool.invoke({
        "title": "工单1", "description": "d",
        "idempotency_key": "req-001",
    })
    r2 = create_tool.invoke({
        "title": "工单1", "description": "d",
        "idempotency_key": "req-001",
    })

    # 两次返回的 ID 应相同
    id1 = r1.split("ID: ")[1].split("\n")[0]
    id2 = r2.split("ID: ")[1].split("\n")[0]
    assert id1 == id2


# ---------------------------------------------------------------------------
# ticket_query
# ---------------------------------------------------------------------------

def test_ticket_query_success(admin_tools):
    """创建后应能查到"""
    create_tool = _find_tool(admin_tools, "ticket_create")
    query_tool = _find_tool(admin_tools, "ticket_query")

    created = create_tool.invoke({"title": "查询测试", "description": "d"})
    ticket_id = created.split("ID: ")[1].split("\n")[0]

    result = query_tool.invoke({"ticket_id": ticket_id})
    assert "Title: 查询测试" in result


def test_ticket_query_not_found(admin_tools):
    """查不到的工单应返回未找到"""
    query_tool = _find_tool(admin_tools, "ticket_query")
    result = query_tool.invoke({"ticket_id": "TKT-NOTEXIST"})
    assert "[未找到]" in result


def test_ticket_query_cross_user_denied(fresh_store):
    """普通用户查别人工单应被拒绝"""
    # user_1 创建工单
    admin_tools = create_ticket_tools(
        user_id="admin_1", tenant_id="t", roles=["admin"], store=fresh_store,
    )
    create_tool = _find_tool(admin_tools, "ticket_create")
    created = create_tool.invoke({"title": "admin创建的", "description": "d"})
    ticket_id = created.split("ID: ")[1].split("\n")[0]

    # user_2 尝试查询
    other_tools = create_ticket_tools(
        user_id="user_2", tenant_id="t", roles=[], store=fresh_store,
    )
    query_tool = _find_tool(other_tools, "ticket_query")
    result = query_tool.invoke({"ticket_id": ticket_id})

    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# ticket_list
# ---------------------------------------------------------------------------

def test_ticket_list_user_sees_only_own(fresh_store):
    """普通用户 list 只能看到自己的工单"""
    # user_1 创建 2 个
    u1_tools = create_ticket_tools(
        user_id="user_1", tenant_id="t", roles=[], store=fresh_store,
    )
    _find_tool(u1_tools, "ticket_create").invoke({"title": "u1-1", "description": "d"})
    _find_tool(u1_tools, "ticket_create").invoke({"title": "u1-2", "description": "d"})

    # user_2 创建 1 个
    u2_tools = create_ticket_tools(
        user_id="user_2", tenant_id="t", roles=[], store=fresh_store,
    )
    _find_tool(u2_tools, "ticket_create").invoke({"title": "u2-1", "description": "d"})

    # user_1 列表应只有 2 个
    list_tool = _find_tool(u1_tools, "ticket_list")
    result = list_tool.invoke({"limit": 10})
    assert "共 2 条工单" in result


def test_ticket_list_admin_sees_all(fresh_store):
    """admin list 应看到租户内全部工单"""
    u1_tools = create_ticket_tools(
        user_id="user_1", tenant_id="t", roles=[], store=fresh_store,
    )
    _find_tool(u1_tools, "ticket_create").invoke({"title": "u1-1", "description": "d"})

    u2_tools = create_ticket_tools(
        user_id="user_2", tenant_id="t", roles=[], store=fresh_store,
    )
    _find_tool(u2_tools, "ticket_create").invoke({"title": "u2-1", "description": "d"})

    admin_tools = create_ticket_tools(
        user_id="admin", tenant_id="t", roles=["admin"], store=fresh_store,
    )
    list_tool = _find_tool(admin_tools, "ticket_list")
    result = list_tool.invoke({"limit": 10})

    assert "共 2 条工单" in result


def test_ticket_list_filter_by_status(fresh_store):
    """按 status 过滤"""
    admin_tools = create_ticket_tools(
        user_id="admin", tenant_id="t", roles=["admin"], store=fresh_store,
    )
    create_tool = _find_tool(admin_tools, "ticket_create")
    update_tool = _find_tool(admin_tools, "ticket_update")

    t1 = create_tool.invoke({"title": "open-1", "description": "d"})
    t2 = create_tool.invoke({"title": "progress-1", "description": "d"})
    t2_id = t2.split("ID: ")[1].split("\n")[0]
    update_tool.invoke({"ticket_id": t2_id, "status": "in_progress"})

    list_tool = _find_tool(admin_tools, "ticket_list")
    result = list_tool.invoke({"status": "in_progress", "limit": 10})
    assert "共 1 条工单" in result


# ---------------------------------------------------------------------------
# ticket_update
# ---------------------------------------------------------------------------

def test_ticket_update_admin_success(fresh_store):
    """admin 可更新工单"""
    admin_tools = create_ticket_tools(
        user_id="admin", tenant_id="t", roles=["admin"], store=fresh_store,
    )
    create_tool = _find_tool(admin_tools, "ticket_create")
    update_tool = _find_tool(admin_tools, "ticket_update")

    created = create_tool.invoke({"title": "原标题", "description": "d"})
    ticket_id = created.split("ID: ")[1].split("\n")[0]

    result = update_tool.invoke({
        "ticket_id": ticket_id,
        "status": "in_progress",
        "assignee": "agent_007",
    })
    assert "[工单已更新]" in result
    assert "Status: in_progress" in result
    assert "Assignee: agent_007" in result


def test_ticket_update_normal_user_denied(fresh_store):
    """普通用户没有写权限"""
    user_tools = create_ticket_tools(
        user_id="user", tenant_id="t", roles=[], store=fresh_store,
    )
    create_tool = _find_tool(user_tools, "ticket_create")
    update_tool = _find_tool(user_tools, "ticket_update")

    created = create_tool.invoke({"title": "原标题", "description": "d"})
    ticket_id = created.split("ID: ")[1].split("\n")[0]

    result = update_tool.invoke({
        "ticket_id": ticket_id,
        "status": "in_progress",
    })
    assert "[权限不足]" in result
    assert "admin" in result or "support_agent" in result


# ---------------------------------------------------------------------------
# ticket_close
# ---------------------------------------------------------------------------

def test_ticket_close_adds_resolution_comment(fresh_store):
    """关闭工单应追加 resolution 评论"""
    admin_tools = create_ticket_tools(
        user_id="admin", tenant_id="t", roles=["admin"], store=fresh_store,
    )
    create_tool = _find_tool(admin_tools, "ticket_create")
    close_tool = _find_tool(admin_tools, "ticket_close")

    created = create_tool.invoke({"title": "待关闭", "description": "d"})
    ticket_id = created.split("ID: ")[1].split("\n")[0]

    result = close_tool.invoke({
        "ticket_id": ticket_id,
        "resolution": "已通过重置密码解决",
    })

    assert "[工单已关闭]" in result
    assert "Status: closed" in result
    assert "Comments: 1 条" in result


def test_ticket_close_empty_resolution_rejected(fresh_store):
    """resolution 为空应被拒绝"""
    admin_tools = create_ticket_tools(
        user_id="admin", tenant_id="t", roles=["admin"], store=fresh_store,
    )
    create_tool = _find_tool(admin_tools, "ticket_create")
    close_tool = _find_tool(admin_tools, "ticket_close")

    created = create_tool.invoke({"title": "待关闭", "description": "d"})
    ticket_id = created.split("ID: ")[1].split("\n")[0]

    result = close_tool.invoke({
        "ticket_id": ticket_id,
        "resolution": "  ",
    })
    assert "[参数错误]" in result


# ---------------------------------------------------------------------------
# ticket_add_comment
# ---------------------------------------------------------------------------

def test_add_comment_to_own_ticket(user_tools):
    """用户应能给自己工单加评论"""
    create_tool = _find_tool(user_tools, "ticket_create")
    comment_tool = _find_tool(user_tools, "ticket_add_comment")

    created = create_tool.invoke({"title": "我的工单", "description": "d"})
    ticket_id = created.split("ID: ")[1].split("\n")[0]

    result = comment_tool.invoke({
        "ticket_id": ticket_id,
        "content": "补充信息：错误码 403",
    })
    assert "[评论已添加" in result
    assert "1 条评论" in result


def test_add_comment_to_other_user_denied(fresh_store):
    """普通用户不能给别人的工单加评论"""
    admin_tools = create_ticket_tools(
        user_id="admin", tenant_id="t", roles=["admin"], store=fresh_store,
    )
    create_tool = _find_tool(admin_tools, "ticket_create")
    created = create_tool.invoke({"title": "admin的", "description": "d"})
    ticket_id = created.split("ID: ")[1].split("\n")[0]

    user_tools = create_ticket_tools(
        user_id="user", tenant_id="t", roles=[], store=fresh_store,
    )
    comment_tool = _find_tool(user_tools, "ticket_add_comment")
    result = comment_tool.invoke({
        "ticket_id": ticket_id,
        "content": "插嘴",
    })
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# 多租户隔离
# ---------------------------------------------------------------------------

def test_cross_tenant_completely_isolated(fresh_store):
    """不同租户的工单完全互不可见"""
    # tenant_A 创建工单
    a_tools = create_ticket_tools(
        user_id="admin_A", tenant_id="tenant_A",
        roles=["admin"], store=fresh_store,
    )
    created = _find_tool(a_tools, "ticket_create").invoke({
        "title": "租户A工单", "description": "d",
    })
    ticket_id = created.split("ID: ")[1].split("\n")[0]

    # tenant_B admin 查询
    b_tools = create_ticket_tools(
        user_id="admin_B", tenant_id="tenant_B",
        roles=["admin"], store=fresh_store,
    )
    result = _find_tool(b_tools, "ticket_query").invoke({"ticket_id": ticket_id})
    assert "[未找到]" in result

    # tenant_B admin 尝试关闭
    close_result = _find_tool(b_tools, "ticket_close").invoke({
        "ticket_id": ticket_id,
        "resolution": "强行关闭",
    })
    assert "[关闭失败]" in close_result


# ---------------------------------------------------------------------------
# tenant_id 强制注入（防 LLM 越权）
# ---------------------------------------------------------------------------

def test_tenant_id_cannot_be_spoofed(fresh_store):
    """即使 LLM 构造请求，tenant_id 也由后端强制注入"""
    a_tools = create_ticket_tools(
        user_id="admin_A", tenant_id="tenant_A",
        roles=["admin"], store=fresh_store,
    )
    create_tool = _find_tool(a_tools, "ticket_create")

    # 工具签名里根本没有 tenant_id 参数，LLM 无法传入
    import inspect
    sig = inspect.signature(create_tool.func)
    assert "tenant_id" not in sig.parameters
    assert "user_id" not in sig.parameters

    # 创建的工单 tenant_id 必然是 tenant_A
    created = create_tool.invoke({"title": "测试", "description": "d"})
    assert "Tenant: tenant_A" in created
