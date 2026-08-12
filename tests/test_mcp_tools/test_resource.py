"""云资源查询 MCP 工具测试 — 注册、只读、租户隔离、匿名拒绝（样本回退路径）

通过 monkeypatch 强制 get_credentials 返回 None，确保这些用例始终走 SampleProvider，
不受测试/CI 环境是否设置了阿里云密钥影响。
"""
import pytest

from src.mcp_tools.resource import create_resource_tools

EXPECTED = {"query_resources", "describe_resource", "get_resource_monitor"}


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr("src.mcp_tools.cloud_provider.get_credentials", lambda: None)
    return create_resource_tools(
        user_id="user_1", tenant_id="", roles=[], plan="free",
    )


def _map(tools):
    return {t.name: t for t in tools}


def test_three_tools_registered(tools):
    names = {t.name for t in tools}
    assert EXPECTED.issubset(names)


def test_tools_have_descriptions(tools):
    for t in tools:
        assert t.description, f"{t.name} 缺少描述"


def test_query_resources_demo_tenant(tools):
    """演示租户（tenant=''）应返回内置样本资源"""
    m = _map(tools)
    out = m["query_resources"].invoke({})
    assert "查询完成" in out
    assert "websrv-01" in out
    assert "i-bp1a2b3c4d5e6f" in out


def test_query_resources_type_filter(tools):
    """按类型过滤"""
    m = _map(tools)
    out = m["query_resources"].invoke({"resource_type": "RDS"})
    assert "mydb-main" in out
    assert "websrv-01" not in out


def test_describe_resource_cross_tenant_isolated(tools):
    """空租户不可见 tenant_A 的专属资源"""
    m = _map(tools)
    out = m["describe_resource"].invoke({"resource_id": "i-bpA000000000001"})
    assert "未找到" in out
    assert "不属于当前租户" in out


def test_describe_resource_found(tools):
    m = _map(tools)
    out = m["describe_resource"].invoke({"resource_id": "i-bp1a2b3c4d5e6f"})
    assert "websrv-01" in out
    assert "Running" in out


def test_resource_monitor_all_and_single(tools):
    m = _map(tools)
    out = m["get_resource_monitor"].invoke({"resource_id": "i-bp1a2b3c4d5e6f"})
    assert "cpu" in out.lower()
    assert "memory" in out.lower()
    out2 = m["get_resource_monitor"].invoke({"resource_id": "i-bp1a2b3c4d5e6f", "metric": "cpu"})
    assert "cpu:" in out2


def test_anonymous_denied():
    """匿名用户查询资源应被拒绝"""
    anon = create_resource_tools(user_id="anonymous", tenant_id="", roles=[], plan="free")
    m = _map(anon)
    out = m["query_resources"].invoke({})
    assert "权限不足" in out


def test_tenant_scoped_visibility(monkeypatch):
    """tenant_A 用户应只看到本租户资源（强制走 SampleProvider，隔离环境 .env 干扰）"""
    monkeypatch.setattr("src.mcp_tools.cloud_provider.get_credentials", lambda: None)
    ta = create_resource_tools(user_id="admin_1", tenant_id="tenant_A", roles=["admin"], plan="free")
    m = _map(ta)
    out = m["query_resources"].invoke({})
    assert "tenantA-only-ecs" in out
    assert "websrv-01" not in out  # 演示租户资源对 tenant_A 不可见
