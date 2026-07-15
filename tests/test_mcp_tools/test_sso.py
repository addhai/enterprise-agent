"""SSO 配置 MCP 工具测试 — 配置/列表/测试连接/启用/禁用"""
import pytest

from src.mcp_tools.sso import (
    create_sso_tools,
    _sso_store,
    SSOConfiguration,
    SSOProviderType,
    SSOStatus,
)
from src.mcp_tools.common import current_utc_time, generate_id


@pytest.fixture(autouse=True)
def reset_store():
    _sso_store._store.clear()
    _sso_store._timestamps.clear()
    yield
    _sso_store._store.clear()
    _sso_store._timestamps.clear()


@pytest.fixture
def admin_tools():
    return create_sso_tools(
        user_id="admin_1",
        tenant_id="tenant_A",
        roles=["admin"],
    )


@pytest.fixture
def user_tools():
    return create_sso_tools(
        user_id="user_1",
        tenant_id="tenant_A",
        roles=[],
    )


def _find(tools, name):
    return [t for t in tools if t.name == name][0]


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------

def test_sso_tools_registered(admin_tools):
    names = {t.name for t in admin_tools}
    expected = {
        "sso_configure",
        "sso_list_providers",
        "sso_test_connection",
        "sso_enable",
        "sso_disable",
    }
    assert expected.issubset(names)


# ---------------------------------------------------------------------------
# sso_configure
# ---------------------------------------------------------------------------

def test_configure_admin_success(admin_tools):
    """admin 可以配置 SSO"""
    result = _find(admin_tools, "sso_configure").invoke({
        "provider_type": "saml",
        "name": "企业微信 SSO",
        "config_json": '{"entity_id": "https://example.com/saml", "x509_cert": "MIIB..."}',
    })
    assert "[SSO 配置已保存]" in result
    assert "saml" in result
    assert "企业微信 SSO" in result


def test_configure_user_denied(user_tools):
    """普通用户不能配置 SSO"""
    result = _find(user_tools, "sso_configure").invoke({
        "provider_type": "saml",
        "name": "test",
        "config_json": "{}",
    })
    assert "[权限不足]" in result


def test_configure_invalid_json(admin_tools):
    """无效 JSON 被拒绝"""
    result = _find(admin_tools, "sso_configure").invoke({
        "provider_type": "saml",
        "name": "test",
        "config_json": "not-a-json",
    })
    assert "[参数错误]" in result
    assert "JSON" in result


def test_configure_invalid_provider_type(admin_tools):
    """无效 provider_type 被拒绝"""
    result = _find(admin_tools, "sso_configure").invoke({
        "provider_type": "ldap",
        "name": "test",
        "config_json": "{}",
    })
    assert "[参数错误]" in result


def test_configure_oidc(admin_tools):
    """支持 OIDC 类型"""
    result = _find(admin_tools, "sso_configure").invoke({
        "provider_type": "oidc",
        "name": "Google OIDC",
        "config_json": '{"client_id": "xxx", "client_secret": "yyy"}',
    })
    assert "[SSO 配置已保存]" in result
    assert "oidc" in result


# ---------------------------------------------------------------------------
# sso_list_providers
# ---------------------------------------------------------------------------

def test_list_providers_empty(user_tools):
    """无配置时返回空"""
    result = _find(user_tools, "sso_list_providers").invoke({})
    assert "暂无 SSO 配置" in result


def test_list_providers_after_configure(admin_tools):
    """配置后应能在列表中看到"""
    _find(admin_tools, "sso_configure").invoke({
        "provider_type": "saml",
        "name": "SSO1",
        "config_json": "{}",
    })
    _find(admin_tools, "sso_configure").invoke({
        "provider_type": "oidc",
        "name": "SSO2",
        "config_json": "{}",
    })

    result = _find(admin_tools, "sso_list_providers").invoke({})
    assert "共 2 个 SSO 提供商" in result
    assert "SSO1" in result
    assert "SSO2" in result


# ---------------------------------------------------------------------------
# sso_test_connection
# ---------------------------------------------------------------------------

def test_test_connection_success(admin_tools):
    """测试连接成功"""
    created = _find(admin_tools, "sso_configure").invoke({
        "provider_type": "saml",
        "name": "test-sso",
        "config_json": "{}",
    })
    sso_id = created.split("sso_id: ")[1].split("\n")[0]

    result = _find(admin_tools, "sso_test_connection").invoke({"sso_id": sso_id})
    assert "[连接测试成功]" in result
    assert "active" in result


def test_test_connection_nonexistent(admin_tools):
    """测试不存在的 SSO 配置"""
    result = _find(admin_tools, "sso_test_connection").invoke({"sso_id": "SSO-NOTEXIST"})
    assert "[未找到]" in result


def test_test_connection_user_denied(user_tools):
    """普通用户不能测试连接"""
    result = _find(user_tools, "sso_test_connection").invoke({"sso_id": "SSO-X"})
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# sso_enable / sso_disable
# ---------------------------------------------------------------------------

def test_enable_sso(admin_tools):
    """启用 SSO"""
    created = _find(admin_tools, "sso_configure").invoke({
        "provider_type": "saml",
        "name": "enable-test",
        "config_json": "{}",
    })
    sso_id = created.split("sso_id: ")[1].split("\n")[0]

    result = _find(admin_tools, "sso_enable").invoke({"sso_id": sso_id})
    assert "[SSO 已启用]" in result

    sso = _sso_store.get("tenant_A", sso_id)
    assert sso.status == SSOStatus.ACTIVE


def test_disable_sso(admin_tools):
    """禁用 SSO"""
    created = _find(admin_tools, "sso_configure").invoke({
        "provider_type": "saml",
        "name": "disable-test",
        "config_json": "{}",
    })
    sso_id = created.split("sso_id: ")[1].split("\n")[0]

    # 先启用
    _find(admin_tools, "sso_enable").invoke({"sso_id": sso_id})
    # 再禁用
    result = _find(admin_tools, "sso_disable").invoke({"sso_id": sso_id, "reason": "维护"})
    assert "[SSO 已禁用]" in result

    sso = _sso_store.get("tenant_A", sso_id)
    assert sso.status == SSOStatus.CONFIGURED


def test_enable_nonexistent_sso(admin_tools):
    """启用不存在的 SSO"""
    result = _find(admin_tools, "sso_enable").invoke({"sso_id": "SSO-GHOST"})
    assert "[未找到]" in result


def test_disable_user_denied(user_tools):
    """普通用户不能禁用"""
    result = _find(user_tools, "sso_disable").invoke({"sso_id": "SSO-X"})
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# 多租户隔离
# ---------------------------------------------------------------------------

def test_cross_tenant_isolation(admin_tools):
    """不同租户的 SSO 配置互不可见"""
    # tenant_A 配置
    created = _find(admin_tools, "sso_configure").invoke({
        "provider_type": "saml",
        "name": "A-SSO",
        "config_json": "{}",
    })
    sso_id = created.split("sso_id: ")[1].split("\n")[0]

    # 切换到 tenant_B
    b_tools = create_sso_tools(
        user_id="admin_B", tenant_id="tenant_B", roles=["admin"],
    )
    result = _find(b_tools, "sso_test_connection").invoke({"sso_id": sso_id})
    assert "[未找到]" in result
