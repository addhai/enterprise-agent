"""云资源 Provider 测试 — 真实阿里云 API 路径（mock RPC，无需网络/密钥）

覆盖：
    - Provider 工厂按密钥有无选择 AliyunProvider / SampleProvider
    - AliyunProvider 把 ECS/RDS/SLB/Redis RPC 结果归一化为统一结构
    - 多租户：按资源标签 tenant= 过滤
    - 监控：ECS/RDS 走云监控 DescribeMetricLast
    - 降级：RPC 报错时不抛异常、返回空列表
"""
import pytest
from unittest.mock import patch

from src.mcp_tools.cloud_provider import AliyunProvider, SampleProvider, get_provider, FallbackProvider
from src.mcp_tools import cloud_provider as cp_module
import src.mcp_tools.aliyun_client as aliyun_client_module


@pytest.fixture(autouse=True)
def _no_fallback_env(monkeypatch):
    """默认关闭兜底开关，避免 .env 中的 ALIYUN_DEMO_FALLBACK 干扰纯真实/样本测试"""
    monkeypatch.delenv("ALIYUN_DEMO_FALLBACK", raising=False)


FAKE_CREDS = {
    "access_key_id": "fake-id",
    "access_key_secret": "fake-secret",
    "region_id": "cn-hangzhou",
}


def _fake_rpc(product, action, region_id, params=None, credentials=None, timeout=10):
    """模拟阿里云 RPC 返回（只读接口）"""
    if product == "ecs":
        return {"Instances": {"Instance": [
            {
                "InstanceId": "i-abc123", "InstanceName": "web1", "RegionId": "cn-hangzhou",
                "Status": "Running", "InstanceType": "ecs.g7.large",
                "PublicIpAddress": {"IpAddress": ["1.2.3.4"]},
                "VpcAttributes": {"PrivateIpAddress": {"IpAddress": ["10.0.0.1"]}},
                "CreationTime": "2026-01-01T00:00:00Z",
                "Tags": {"Tag": [{"TagKey": "tenant", "TagValue": "tenant_A"}]},
            }
        ]}}
    if product == "rds":
        return {"Items": {"DBInstance": [
            {
                "DBInstanceId": "rm-xyz", "DBInstanceDescription": "maindb", "RegionId": "cn-hangzhou",
                "DBInstanceStatus": "Running", "Engine": "MySQL", "EngineVersion": "8.0",
                "DBInstanceClass": "mysql.x8", "ConnectionString": "rm-xyz.mysql.rds.aliyuncs.com",
                "CreateTime": "2026-01-02T00:00:00Z", "Tags": {"Tag": []},
            }
        ]}}
    if product == "slb":
        return {"LoadBalancers": {"LoadBalancer": [
            {
                "LoadBalancerId": "lb-1", "LoadBalancerName": "lb1", "RegionId": "cn-hangzhou",
                "LoadBalancerStatus": "Active", "AddressType": "internet", "Address": "5.6.7.8",
                "CreateTimeStamp": "1700000000000",
            }
        ]}}
    if product == "r-kvstore":
        return {"Instances": {"KVStoreInstance": [
            {
                "InstanceId": "r-1", "InstanceName": "cache1", "RegionId": "cn-hangzhou",
                "InstanceStatus": "Normal", "InstanceClass": "redis.master.small", "Capacity": 2048,
                "ConnectionDomain": "r-1.redis.rds.aliyuncs.com", "CreateTime": "2026-01-03T00:00:00Z",
                "Tags": {"Tag": []},
            }
        ]}}
    if product == "cms":
        return {"Datapoints": [{"Average": 12.3}]}
    return {"Error": {"Code": "UnknownProduct", "Message": product}}


@pytest.fixture
def aliyun_provider():
    with patch.object(aliyun_client_module, "rpc_call", _fake_rpc):
        yield AliyunProvider(region_id="cn-hangzhou", credentials=FAKE_CREDS)


def test_factory_returns_sample_without_creds(monkeypatch):
    monkeypatch.setattr(cp_module, "get_credentials", lambda: None)
    assert isinstance(get_provider(), SampleProvider)


def test_factory_returns_aliyun_with_creds(monkeypatch):
    monkeypatch.setattr(cp_module, "get_credentials", lambda: dict(FAKE_CREDS))
    assert isinstance(get_provider(), AliyunProvider)


def test_aliyun_normalizes_all_types(aliyun_provider):
    res = aliyun_provider.list_resources("")
    by_type = {r["resource_type"] for r in res}
    assert by_type == {"ECS", "RDS", "SLB", "Redis"}
    ecs = next(r for r in res if r["resource_type"] == "ECS")
    assert ecs["resource_id"] == "i-abc123"
    assert ecs["public_ip"] == "1.2.3.4"
    assert ecs["private_ip"] == "10.0.0.1"
    assert ecs["status"] == "Running"


def test_aliyun_tenant_tag_filter(aliyun_provider):
    """tenant_A 应只看到打了 tenant=tenant_A 标签的 ECS，其余无标签资源不混入"""
    res = aliyun_provider.list_resources("tenant_A")
    assert len(res) == 1
    assert res[0]["resource_id"] == "i-abc123"


def test_aliyun_describe(aliyun_provider):
    r = aliyun_provider.describe("rm-xyz", "")
    assert r is not None
    assert r["resource_type"] == "RDS"
    assert r["name"] == "maindb"


def test_aliyun_metrics(aliyun_provider):
    m = aliyun_provider.get_metrics("i-abc123", "", "")
    assert "cpu" in m and "memory" in m
    assert m["cpu"] == 12.3
    single = aliyun_provider.get_metrics("i-abc123", "cpu", "")
    assert single == {"cpu": 12.3}


def test_aliyun_rpc_error_degrades(monkeypatch):
    """RPC 返回 Error 时，provider 不抛异常、返回空列表"""
    def boom(*a, **k):
        return {"Error": {"Code": "Throttling", "Message": "busy"}}
    monkeypatch.setattr(aliyun_client_module, "rpc_call", boom)
    p = AliyunProvider(region_id="cn-hangzhou", credentials=FAKE_CREDS)
    assert p.list_resources("") == []
    assert p.describe("anything") is None
    assert p.get_metrics("anything") == {}


def test_tool_real_source_note(monkeypatch):
    """有密钥时，工具输出应标注'阿里云实时 API'"""
    monkeypatch.setattr(cp_module, "get_credentials", lambda: dict(FAKE_CREDS))
    with patch.object(aliyun_client_module, "rpc_call", _fake_rpc):
        tools = {t.name: t for t in
                 __import__("src.mcp_tools.resource", fromlist=["create_resource_tools"])
                 .create_resource_tools(user_id="u", tenant_id="tenant_A", roles=[])}
        out = tools["query_resources"].invoke({})
        assert "阿里云实时 API" in out
        assert "i-abc123" in out


def test_factory_returns_fallback_with_flag(monkeypatch):
    """ALIYUN_DEMO_FALLBACK=true 且有密钥 → 返回 FallbackProvider（真实优先+无资源兜底）"""
    monkeypatch.setattr(cp_module, "get_credentials", lambda: dict(FAKE_CREDS))
    monkeypatch.setenv("ALIYUN_DEMO_FALLBACK", "true")
    p = get_provider()
    assert isinstance(p, FallbackProvider)
    assert p.source == "aliyun+sample"


def test_fallback_prefers_real_when_present(monkeypatch):
    """真实账号有资源时，只用真实数据、不混入样本"""
    monkeypatch.setattr(cp_module, "get_credentials", lambda: dict(FAKE_CREDS))
    monkeypatch.setenv("ALIYUN_DEMO_FALLBACK", "true")
    with patch.object(aliyun_client_module, "rpc_call", _fake_rpc):
        p = get_provider()
        res = p.list_resources("")
        ids = {r["resource_id"] for r in res}
        assert "i-abc123" in ids          # 真实数据
        assert "i-bp1a2b3c4d5e6f" not in ids  # 不应混入样本


def test_fallback_sample_when_real_empty(monkeypatch):
    """真实账号无资源（RPC 报错/空）时，回退样本数据，演示不空"""
    monkeypatch.setattr(cp_module, "get_credentials", lambda: dict(FAKE_CREDS))
    monkeypatch.setenv("ALIYUN_DEMO_FALLBACK", "true")
    with patch.object(aliyun_client_module, "rpc_call",
                      lambda *a, **k: {"Error": {"Code": "NoResource", "Message": "empty"}}):
        p = get_provider()
        res = p.list_resources("")
        assert len(res) > 0                       # 回退样本
        assert any(r["resource_id"] == "i-bp1a2b3c4d5e6f" for r in res)
        d = p.describe("i-bp1a2b3c4d5e6f", "")
        assert d is not None and d["name"] == "websrv-01"
        m = p.get_metrics("i-bp1a2b3c4d5e6f", "cpu", "")
        assert "cpu" in m
