"""用户管理 MCP 工具测试 — 权限、查询、重置密码、禁用账号、更新资料"""
import pytest

from src.mcp_tools.users import (
    create_user_tools,
    _user_store,
    User,
    UserStatus,
    UserRole,
)
from src.mcp_tools.common import current_utc_time, generate_id


@pytest.fixture(autouse=True)
def reset_store():
    _user_store._store.clear()
    _user_store._timestamps.clear()
    yield
    _user_store._store.clear()
    _user_store._timestamps.clear()


@pytest.fixture
def admin_tools():
    return create_user_tools(
        user_id="admin_1",
        tenant_id="tenant_A",
        roles=["admin"],
    )


@pytest.fixture
def user_tools():
    return create_user_tools(
        user_id="user_1",
        tenant_id="tenant_A",
        roles=[],
    )


@pytest.fixture
def seeded_user():
    """预置一个用户用于测试"""
    user = User(
        id="user_42",
        tenant_id="tenant_A",
        email="user42@example.com",
        name="测试用户",
        status=UserStatus.ACTIVE,
        roles=["user"],
        created_at=current_utc_time().isoformat(),
    )
    _user_store.save("tenant_A", "user_42", user)
    return user


def _find(tools, name):
    return [t for t in tools if t.name == name][0]


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------

def test_user_tools_registered(admin_tools):
    names = {t.name for t in admin_tools}
    expected = {
        "user_get_profile",
        "user_reset_password",
        "user_disable_account",
        "user_list",
        "user_update_profile",
    }
    assert expected.issubset(names)


# ---------------------------------------------------------------------------
# user_get_profile
# ---------------------------------------------------------------------------

def test_get_profile_self(user_tools, seeded_user):
    """用户可以查看自己的资料"""
    # user_tools 用 user_id="user_1"，所以另建一个匹配的
    user = User(
        id="user_1",
        tenant_id="tenant_A",
        email="u1@example.com",
        name="自身",
        status=UserStatus.ACTIVE,
        roles=["user"],
        created_at=current_utc_time().isoformat(),
    )
    _user_store.save("tenant_A", "user_1", user)

    result = _find(user_tools, "user_get_profile").invoke({"target_user_id": "user_1"})
    assert "[查询成功]" in result
    assert "user_1" in result
    assert "自身" in result


def test_get_profile_other_as_admin(admin_tools, seeded_user):
    """admin 可以查看其他用户"""
    result = _find(admin_tools, "user_get_profile").invoke({"target_user_id": "user_42"})
    assert "[查询成功]" in result
    assert "user_42" in result


def test_get_profile_other_as_user_denied(user_tools, seeded_user):
    """普通用户不能查看其他用户"""
    result = _find(user_tools, "user_get_profile").invoke({"target_user_id": "user_42"})
    assert "[权限不足]" in result


def test_get_profile_not_found(user_tools):
    """查不存在的用户返回未找到"""
    result = _find(user_tools, "user_get_profile").invoke({"target_user_id": "ghost"})
    assert "[未找到]" in result


# ---------------------------------------------------------------------------
# user_reset_password
# ---------------------------------------------------------------------------

def test_reset_password_admin_success(admin_tools, seeded_user):
    """admin 可以重置密码"""
    result = _find(admin_tools, "user_reset_password").invoke({
        "target_user_id": "user_42",
        "reason": "忘记密码",
    })
    assert "[密码已重置]" in result
    assert "user_42" in result


def test_reset_password_user_denied(user_tools, seeded_user):
    """普通用户不能重置密码"""
    result = _find(user_tools, "user_reset_password").invoke({
        "target_user_id": "user_42",
    })
    assert "[权限不足]" in result


def test_reset_password_nonexistent_user(admin_tools):
    """重置不存在用户的密码"""
    result = _find(admin_tools, "user_reset_password").invoke({
        "target_user_id": "ghost",
    })
    assert "[未找到]" in result


# ---------------------------------------------------------------------------
# user_disable_account
# ---------------------------------------------------------------------------

def test_disable_account_admin_success(admin_tools, seeded_user):
    """admin 可以禁用账号"""
    result = _find(admin_tools, "user_disable_account").invoke({
        "target_user_id": "user_42",
        "reason": "违规操作",
    })
    assert "[账号已禁用]" in result
    assert "违规操作" in result

    # 验证状态已变更
    user = _user_store.get("tenant_A", "user_42")
    assert user.status == UserStatus.DISABLED


def test_disable_account_user_denied(user_tools, seeded_user):
    """普通用户不能禁用账号"""
    result = _find(user_tools, "user_disable_account").invoke({
        "target_user_id": "user_42",
        "reason": "test",
    })
    assert "[权限不足]" in result


def test_disable_account_empty_reason_rejected(admin_tools, seeded_user):
    """禁用原因不能为空"""
    result = _find(admin_tools, "user_disable_account").invoke({
        "target_user_id": "user_42",
        "reason": "  ",
    })
    assert "[参数错误]" in result


def test_disable_already_disabled(admin_tools, seeded_user):
    """重复禁用返回已禁用"""
    _find(admin_tools, "user_disable_account").invoke({
        "target_user_id": "user_42",
        "reason": "第一次",
    })
    result = _find(admin_tools, "user_disable_account").invoke({
        "target_user_id": "user_42",
        "reason": "第二次",
    })
    assert "[已禁用]" in result


# ---------------------------------------------------------------------------
# user_list
# ---------------------------------------------------------------------------

def test_list_users_admin_success(admin_tools, seeded_user):
    """admin 可以列出用户"""
    result = _find(admin_tools, "user_list").invoke({"limit": 10})
    assert "共 1 位用户" in result
    assert "user_42" in result


def test_list_users_user_denied(user_tools):
    """普通用户不能列出用户"""
    result = _find(user_tools, "user_list").invoke({"limit": 10})
    assert "[权限不足]" in result


def test_list_users_empty(admin_tools):
    """无用户时返回空"""
    result = _find(admin_tools, "user_list").invoke({"limit": 10})
    assert "暂无用户" in result


# ---------------------------------------------------------------------------
# user_update_profile
# ---------------------------------------------------------------------------

def test_update_profile_success(admin_tools, seeded_user):
    """admin 可以更新用户资料"""
    result = _find(admin_tools, "user_update_profile").invoke({
        "target_user_id": "user_42",
        "name": "新名字",
        "email": "new@example.com",
    })
    assert "[资料已更新]" in result
    assert "name=新名字" in result

    user = _user_store.get("tenant_A", "user_42")
    assert user.name == "新名字"
    assert user.email == "new@example.com"


def test_update_profile_no_changes(admin_tools, seeded_user):
    """未提供更新字段时返回无变更"""
    result = _find(admin_tools, "user_update_profile").invoke({
        "target_user_id": "user_42",
    })
    assert "[无变更]" in result


def test_update_profile_nonexistent_user(admin_tools):
    """更新不存在用户"""
    result = _find(admin_tools, "user_update_profile").invoke({
        "target_user_id": "ghost",
        "name": "test",
    })
    assert "[未找到]" in result


def test_update_profile_user_denied(user_tools, seeded_user):
    """普通用户不能更新资料"""
    result = _find(user_tools, "user_update_profile").invoke({
        "target_user_id": "user_42",
        "name": "test",
    })
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# 多租户隔离
# ---------------------------------------------------------------------------

def test_cross_tenant_isolation(admin_tools, seeded_user):
    """不同租户用户互不可见"""
    # admin_tools 的 tenant_id="tenant_A"
    # admin_tools 查询 tenant_B 的用户应查不到
    result = _find(admin_tools, "user_get_profile").invoke({"target_user_id": "user_B"})
    assert "[未找到]" in result
