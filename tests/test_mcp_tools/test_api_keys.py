"""API Key 管理 MCP 工具测试 — 生成/吊销/列表/查询/轮换"""
import pytest

from src.mcp_tools.api_keys import (
    create_api_key_tools,
    _api_key_store,
    APIKey,
    APIKeyStatus,
)
from src.mcp_tools.common import current_utc_time, generate_id


@pytest.fixture(autouse=True)
def reset_store():
    _api_key_store._store.clear()
    _api_key_store._timestamps.clear()
    yield
    _api_key_store._store.clear()
    _api_key_store._timestamps.clear()


@pytest.fixture
def admin_tools():
    return create_api_key_tools(
        user_id="admin_1",
        tenant_id="tenant_A",
        roles=["admin"],
    )


@pytest.fixture
def user_tools():
    return create_api_key_tools(
        user_id="user_1",
        tenant_id="tenant_A",
        roles=[],
    )


def _find(tools, name):
    return [t for t in tools if t.name == name][0]


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------

def test_api_key_tools_registered(admin_tools):
    names = {t.name for t in admin_tools}
    expected = {
        "api_key_generate",
        "api_key_revoke",
        "api_key_list",
        "api_key_get",
        "api_key_rotate",
    }
    assert expected.issubset(names)


# ---------------------------------------------------------------------------
# api_key_generate
# ---------------------------------------------------------------------------

def test_generate_admin_success(admin_tools):
    """admin 可以生成 API Key"""
    result = _find(admin_tools, "api_key_generate").invoke({
        "name": "my-app-key",
    })
    assert "[API Key 已生成]" in result
    assert "sk_" in result
    assert "my-app-key" in result
    assert "永久" in result  # 默认永久有效


def test_generate_user_denied(user_tools):
    """普通用户不能生成 API Key"""
    result = _find(user_tools, "api_key_generate").invoke({"name": "test"})
    assert "[权限不足]" in result


def test_generate_with_expiry(admin_tools):
    """生成带有效期的 Key"""
    result = _find(admin_tools, "api_key_generate").invoke({
        "name": "temp-key",
        "expires_days": 30,
    })
    assert "[API Key 已生成]" in result
    # 不再显示"永久"
    assert "永久" not in result


def test_generate_returns_valid_key_format(admin_tools):
    """生成的 Key 应符合 sk_ 前缀格式"""
    result = _find(admin_tools, "api_key_generate").invoke({"name": "test"})
    # 提取 key 值
    for line in result.split("\n"):
        if "key:" in line and "sk_" in line:
            key_value = line.split("key: ")[1].strip()
            assert key_value.startswith("sk_")
            assert len(key_value) > 20
            return
    pytest.fail("未找到有效的 key 值")


# ---------------------------------------------------------------------------
# api_key_revoke
# ---------------------------------------------------------------------------

def test_revoke_admin_success(admin_tools):
    """admin 可以吊销 Key"""
    created = _find(admin_tools, "api_key_generate").invoke({"name": "to-revoke"})
    key_id = created.split("key_id: ")[1].split("\n")[0]

    result = _find(admin_tools, "api_key_revoke").invoke({"key_id": key_id, "reason": "泄露"})
    assert "[API Key 已吊销]" in result

    key = _api_key_store.get("tenant_A", key_id)
    assert key.status == APIKeyStatus.REVOKED


def test_revoke_user_denied(user_tools):
    """普通用户不能吊销"""
    result = _find(user_tools, "api_key_revoke").invoke({"key_id": "AK-X"})
    assert "[权限不足]" in result


def test_revoke_nonexistent(admin_tools):
    """吊销不存在的 Key"""
    result = _find(admin_tools, "api_key_revoke").invoke({"key_id": "AK-GHOST"})
    assert "[未找到]" in result


def test_revoke_already_revoked(admin_tools):
    """重复吊销返回已吊销"""
    created = _find(admin_tools, "api_key_generate").invoke({"name": "test"})
    key_id = created.split("key_id: ")[1].split("\n")[0]

    _find(admin_tools, "api_key_revoke").invoke({"key_id": key_id})
    result = _find(admin_tools, "api_key_revoke").invoke({"key_id": key_id})
    assert "[已吊销]" in result


# ---------------------------------------------------------------------------
# api_key_list
# ---------------------------------------------------------------------------

def test_list_empty(admin_tools):
    """无 Key 时返回空"""
    result = _find(admin_tools, "api_key_list").invoke({"limit": 10})
    assert "暂无 API Key" in result


def test_list_after_generate(admin_tools):
    """生成后应能在列表中看到"""
    _find(admin_tools, "api_key_generate").invoke({"name": "key1"})
    _find(admin_tools, "api_key_generate").invoke({"name": "key2"})

    result = _find(admin_tools, "api_key_list").invoke({"limit": 10})
    assert "共 2 个 API Key" in result
    assert "key1" in result
    assert "key2" in result


def test_list_user_denied(user_tools):
    """普通用户不能列出"""
    result = _find(user_tools, "api_key_list").invoke({"limit": 10})
    assert "[权限不足]" in result


def test_list_masks_key_value(admin_tools):
    """列表中 Key 值应被掩码"""
    _find(admin_tools, "api_key_generate").invoke({"name": "secret"})
    result = _find(admin_tools, "api_key_list").invoke({"limit": 10})
    # 不应包含完整的 sk_ 值
    for line in result.split("\n"):
        if "sk_" in line and "..." not in line:
            pytest.fail(f"Key 值未掩码: {line}")


# ---------------------------------------------------------------------------
# api_key_get
# ---------------------------------------------------------------------------

def test_get_key_details(admin_tools):
    """查询 Key 详情"""
    created = _find(admin_tools, "api_key_generate").invoke({"name": "detail-key"})
    key_id = created.split("key_id: ")[1].split("\n")[0]

    result = _find(admin_tools, "api_key_get").invoke({"key_id": key_id})
    assert "[查询成功]" in result
    assert "detail-key" in result
    assert "read,write" in result  # permissions


def test_get_key_nonexistent(admin_tools):
    """查询不存在的 Key"""
    result = _find(admin_tools, "api_key_get").invoke({"key_id": "AK-GHOST"})
    assert "[未找到]" in result


def test_get_key_masks_value(admin_tools):
    """详情中 Key 值应被掩码"""
    created = _find(admin_tools, "api_key_generate").invoke({"name": "mask"})
    key_id = created.split("key_id: ")[1].split("\n")[0]

    result = _find(admin_tools, "api_key_get").invoke({"key_id": key_id})
    # 应包含省略号
    assert "..." in result


# ---------------------------------------------------------------------------
# api_key_rotate
# ---------------------------------------------------------------------------

def test_rotate_success(admin_tools):
    """轮换 Key 应生成新值"""
    created = _find(admin_tools, "api_key_generate").invoke({"name": "rotate-test"})
    key_id = created.split("key_id: ")[1].split("\n")[0]
    old_key = created.split("key: ")[1].split("\n")[0]

    result = _find(admin_tools, "api_key_rotate").invoke({"key_id": key_id})
    assert "[API Key 已轮换]" in result
    new_key = result.split("new_key: ")[1].split("\n")[0]

    # 新旧 Key 不同
    assert new_key != old_key
    assert new_key.startswith("sk_")

    # Key ID 保持不变
    key = _api_key_store.get("tenant_A", key_id)
    assert key.key == new_key


def test_rotate_nonexistent(admin_tools):
    """轮换不存在的 Key"""
    result = _find(admin_tools, "api_key_rotate").invoke({"key_id": "AK-GHOST"})
    assert "[未找到]" in result


def test_rotate_user_denied(user_tools):
    """普通用户不能轮换"""
    result = _find(user_tools, "api_key_rotate").invoke({"key_id": "AK-X"})
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# 多租户隔离
# ---------------------------------------------------------------------------

def test_cross_tenant_isolation(admin_tools):
    """不同租户的 Key 互不可见"""
    created = _find(admin_tools, "api_key_generate").invoke({"name": "tenant-A-key"})
    key_id = created.split("key_id: ")[1].split("\n")[0]

    b_tools = create_api_key_tools(
        user_id="admin_B", tenant_id="tenant_B", roles=["admin"],
    )
    result = _find(b_tools, "api_key_get").invoke({"key_id": key_id})
    assert "[未找到]" in result
