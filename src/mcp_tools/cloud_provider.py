"""云资源 Provider 抽象层

设计目标：
    - 对上层工具（resource.py）屏蔽数据来源差异：真实阿里云 API 与本地样本数据
      提供完全一致的接口（list / describe / metrics）。
    - 真实模式：检测到 ALIYUN_ACCESS_KEY_ID/SECRET 时直连阿里云 OpenAPI（只读）。
    - 安全回退：无密钥时自动使用 SampleProvider，保证本地/CI 仍可运行、不产生费用。
    - 多租户：真实模式下按资源标签 `tenant=<tenant_id>` 过滤；样本模式按内置 tenant_id 过滤。

统一资源结构（dict）：
    resource_id, name, resource_type, region, status, spec,
    private_ip, public_ip, tenant_id, owner, created_at
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from dotenv import load_dotenv
from src.mcp_tools.aliyun_client import AliyunClient, get_credentials

logger = logging.getLogger(__name__)
load_dotenv(override=False)  # 确保 .env 中的 ALIYUN_* 开关可见（无 .env 时静默）


# ===========================================================================
# 演示用样本数据（真实接入时由 AliyunProvider 替代；无密钥时回退到此）
# ===========================================================================
_SAMPLE_RESOURCES: List[dict] = [
    {
        "resource_id": "i-bp1a2b3c4d5e6f", "name": "websrv-01", "resource_type": "ECS",
        "region": "cn-hangzhou", "status": "Running", "spec": "ecs.g7.large (2vCPU 8GiB)",
        "private_ip": "172.16.0.10", "public_ip": "47.98.12.34", "tenant_id": "", "owner": "user_1",
        "created_at": "2026-03-12",
    },
    {
        "resource_id": "i-bp9z8y7x6w5v4u", "name": "websrv-02", "resource_type": "ECS",
        "region": "cn-hangzhou", "status": "Stopped", "spec": "ecs.g7.large (2vCPU 8GiB)",
        "private_ip": "172.16.0.11", "public_ip": "", "tenant_id": "", "owner": "user_1",
        "created_at": "2026-04-01",
    },
    {
        "resource_id": "rm-bp1q2w3e4r5t6y", "name": "mydb-main", "resource_type": "RDS",
        "region": "cn-hangzhou", "status": "Running", "spec": "MySQL 8.0 高可用版 (4核8G)",
        "private_ip": "rm-bp1q2w3e4r5t6y.mysql.rds.aliyuncs.com", "public_ip": "",
        "tenant_id": "", "owner": "user_1", "created_at": "2026-02-20",
    },
    {
        "resource_id": "oss-bucket-cloudsync-assets", "name": "cloudsync-assets", "resource_type": "OSS",
        "region": "cn-hangzhou", "status": "Available", "spec": "标准存储 / 1.2 TB 已用",
        "private_ip": "", "public_ip": "https://cloudsync-assets.oss-cn-hangzhou.aliyuncs.com",
        "tenant_id": "", "owner": "user_1", "created_at": "2026-01-15",
    },
    {
        "resource_id": "lb-bp1m2n3b4v5c6x", "name": "internet-slb", "resource_type": "SLB",
        "region": "cn-hangzhou", "status": "Active", "spec": "公网 SLB / 按流量计费",
        "private_ip": "", "public_ip": "120.55.88.10", "tenant_id": "", "owner": "user_1",
        "created_at": "2026-03-30",
    },
    {
        "resource_id": "r-bp1k8l9m0n1b2v", "name": "cache-session", "resource_type": "Redis",
        "region": "cn-hangzhou", "status": "Normal", "spec": "Redis 7.0 社区版 (主从版 2G)",
        "private_ip": "r-bp1k8l9m0n1b2v.redis.rds.aliyuncs.com", "public_ip": "",
        "tenant_id": "", "owner": "user_1", "created_at": "2026-03-05",
    },
    # 仅当传入对应 tenant_id 时可见，用于演示多租户隔离
    {
        "resource_id": "i-bpA000000000001", "name": "tenantA-only-ecs", "resource_type": "ECS",
        "region": "cn-beijing", "status": "Running", "spec": "ecs.c7.large (2vCPU 4GiB)",
        "private_ip": "10.0.0.21", "public_ip": "", "tenant_id": "tenant_A", "owner": "admin_1",
        "created_at": "2026-05-10",
    },
    {
        "resource_id": "rm-bpB000000000002", "name": "tenantB-only-rds", "resource_type": "RDS",
        "region": "cn-shanghai", "status": "Running", "spec": "PostgreSQL 15 (2核4G)",
        "private_ip": "rm-bpB000000000002.pg.rds.aliyuncs.com", "public_ip": "",
        "tenant_id": "tenant_B", "owner": "user_9", "created_at": "2026-05-22",
    },
]


def _deterministic_metric(resource_id: str, metric: str) -> float:
    """基于 resource_id 生成稳定的演示指标（0-100 区间）"""
    seed = sum(ord(c) for c in resource_id) + sum(ord(c) for c in metric)
    return round((seed % 70) + 15.0, 1)  # 15.0 ~ 84.9


# ===========================================================================
# Provider 抽象
# ===========================================================================
class CloudProvider(ABC):
    """统一云资源访问接口（真实 API 与样本数据都实现它）"""

    @abstractmethod
    def list_resources(self, tenant_id: str = "") -> List[dict]:
        ...

    @abstractmethod
    def describe(self, resource_id: str, tenant_id: str = "") -> Optional[dict]:
        ...

    @abstractmethod
    def get_metrics(self, resource_id: str, metric: str = "", tenant_id: str = "") -> Dict[str, float]:
        ...

    @property
    def source(self) -> str:
        return "abstract"


class SampleProvider(CloudProvider):
    """本地样本数据 Provider（无密钥时回退）"""

    @property
    def source(self) -> str:
        return "sample"

    def _for_tenant(self, tenant_id: str) -> List[dict]:
        if not tenant_id:
            return [r for r in _SAMPLE_RESOURCES if r["tenant_id"] == ""]
        return [r for r in _SAMPLE_RESOURCES if r["tenant_id"] == tenant_id]

    def list_resources(self, tenant_id: str = "") -> List[dict]:
        return [dict(r) for r in self._for_tenant(tenant_id)]

    def describe(self, resource_id: str, tenant_id: str = "") -> Optional[dict]:
        for r in self._for_tenant(tenant_id):
            if r["resource_id"] == resource_id:
                return dict(r)
        return None

    def get_metrics(self, resource_id: str, metric: str = "", tenant_id: str = "") -> Dict[str, float]:
        r = self.describe(resource_id, tenant_id)
        if r is None:
            return {}
        metrics = {
            "cpu": _deterministic_metric(resource_id, "cpu"),
            "memory": _deterministic_metric(resource_id, "memory"),
            "connection": round(_deterministic_metric(resource_id, "connection") * 10, 0),
            "disk": _deterministic_metric(resource_id, "disk"),
        }
        return metrics


class AliyunProvider(CloudProvider):
    """真实阿里云 API Provider（只读）"""

    def __init__(self, region_id: Optional[str] = None, credentials: Optional[dict] = None):
        self.client = AliyunClient(region_id=region_id, credentials=credentials)
        self._cache: Optional[List[dict]] = None

    @property
    def source(self) -> str:
        return "aliyun"

    # ---- 归一化：把各产品 RPC 结果转成统一结构 ----
    @staticmethod
    def _norm_tags(tag_list) -> Dict[str, str]:
        out = {}
        if not isinstance(tag_list, list):
            return out
        for t in tag_list:
            if isinstance(t, dict) and "TagKey" in t and "TagValue" in t:
                out[t["TagKey"]] = t["TagValue"]
        return out

    def _fetch_all(self) -> List[dict]:
        if self._cache is not None:
            return self._cache
        resources: List[dict] = []

        # ECS
        for inst in self.client.list_ecs():
            pub = inst.get("PublicIpAddress", {})
            pub = pub.get("IpAddress", []) if isinstance(pub, dict) else []
            priv = inst.get("VpcAttributes", {})
            priv = priv.get("PrivateIpAddress", {}).get("IpAddress", []) if isinstance(priv, dict) else []
            tags = self._norm_tags(inst.get("Tags", {}).get("Tag", []) if isinstance(inst.get("Tags"), dict) else inst.get("Tags"))
            resources.append({
                "resource_id": inst.get("InstanceId", ""),
                "name": inst.get("InstanceName") or inst.get("InstanceId", ""),
                "resource_type": "ECS",
                "region": inst.get("RegionId", self.client.region_id),
                "status": inst.get("Status", ""),
                "spec": inst.get("InstanceType", ""),
                "private_ip": (priv[0] if priv else ""),
                "public_ip": (pub[0] if pub else ""),
                "tenant_id": tags.get("tenant", ""),
                "owner": tags.get("owner", inst.get("InstanceId", "")),
                "created_at": (inst.get("CreationTime") or "")[:10],
                "tags": tags,
            })

        # RDS
        for db in self.client.list_rds():
            tags = self._norm_tags(db.get("Tags", {}).get("Tag", []) if isinstance(db.get("Tags"), dict) else db.get("Tags"))
            resources.append({
                "resource_id": db.get("DBInstanceId", ""),
                "name": db.get("DBInstanceDescription") or db.get("DBInstanceId", ""),
                "resource_type": "RDS",
                "region": db.get("RegionId", self.client.region_id),
                "status": db.get("DBInstanceStatus", ""),
                "spec": f"{db.get('Engine','')} {db.get('EngineVersion','')} {db.get('DBInstanceClass','')}".strip(),
                "private_ip": db.get("ConnectionString", ""),
                "public_ip": "",
                "tenant_id": tags.get("tenant", ""),
                "owner": tags.get("owner", db.get("DBInstanceId", "")),
                "created_at": (db.get("CreateTime") or "")[:10],
                "tags": tags,
            })

        # SLB
        for lb in self.client.list_slb():
            tags = self._norm_tags(lb.get("Tags", {}).get("Tag", []) if isinstance(lb.get("Tags"), dict) else lb.get("Tags"))
            resources.append({
                "resource_id": lb.get("LoadBalancerId", ""),
                "name": lb.get("LoadBalancerName") or lb.get("LoadBalancerId", ""),
                "resource_type": "SLB",
                "region": lb.get("RegionId", self.client.region_id),
                "status": lb.get("LoadBalancerStatus", ""),
                "spec": f"{lb.get('AddressType','')} SLB",
                "private_ip": "",
                "public_ip": lb.get("Address", ""),
                "tenant_id": tags.get("tenant", ""),
                "owner": tags.get("owner", lb.get("LoadBalancerId", "")),
                "created_at": (lb.get("CreateTimeStamp") or "")[:10] if lb.get("CreateTimeStamp") else "",
                "tags": tags,
            })

        # Redis (KVStore)
        for rd in self.client.list_redis():
            tags = self._norm_tags(rd.get("Tags", {}).get("Tag", []) if isinstance(rd.get("Tags"), dict) else rd.get("Tags"))
            resources.append({
                "resource_id": rd.get("InstanceId", ""),
                "name": rd.get("InstanceName") or rd.get("InstanceId", ""),
                "resource_type": "Redis",
                "region": rd.get("RegionId", self.client.region_id),
                "status": rd.get("InstanceStatus", ""),
                "spec": f"Redis {rd.get('InstanceClass','')} {rd.get('Capacity','')}MB",
                "private_ip": rd.get("ConnectionDomain", ""),
                "public_ip": "",
                "tenant_id": tags.get("tenant", ""),
                "owner": tags.get("owner", rd.get("InstanceId", "")),
                "created_at": (rd.get("CreateTime") or "")[:10],
                "tags": tags,
            })

        self._cache = resources
        return resources

    def list_resources(self, tenant_id: str = "") -> List[dict]:
        all_res = self._fetch_all()
        if not tenant_id:
            return all_res
        matched = [r for r in all_res if (r.get("tags") or {}).get("tenant") == tenant_id]
        if not matched:
            # 真实账号通常未打 tenant 标签：MVP 阶段降级返回全部，并在日志提示
            logger.warning("未找到 tenant=%s 的资源标签，降级返回账号全部资源（生产应强制按标签隔离）", tenant_id)
            return all_res
        return matched

    def describe(self, resource_id: str, tenant_id: str = "") -> Optional[dict]:
        for r in self.list_resources(tenant_id):
            if r["resource_id"] == resource_id:
                return r
        return None

    def get_metrics(self, resource_id: str, metric: str = "", tenant_id: str = "") -> Dict[str, float]:
        r = self.describe(resource_id, tenant_id)
        if r is None:
            return {}
        rtype = r["resource_type"]
        # 不同资源类型的云监控命名空间与指标名
        ns_metric = {
            "ECS": ("acs_ecs_dashboard", {"cpu": "CPUUtilization", "memory": "memory_usage"}),
            "RDS": ("acs_rds_dashboard", {"cpu": "CPUUtilization", "memory": "MemoryUsage"}),
        }
        if rtype not in ns_metric:
            return {}
        namespace, mapping = ns_metric[rtype]
        result: Dict[str, float] = {}
        targets = {metric.lower(): mapping[metric.lower()]} if metric and metric.lower() in mapping else mapping
        for key, ali_metric in targets.items():
            val = self.client.get_metric(resource_id, ali_metric, namespace)
            if val is not None:
                result[key] = round(val, 1)
        return result


# ===========================================================================
# 混合 Provider：真实优先 + 无资源时样本兜底
# ===========================================================================
class FallbackProvider(CloudProvider):
    """真实优先、无资源时回退样本的混合 Provider。

    适用场景：已接入真实阿里云 AK/SK，但账号暂无资源（如试用/学生账号），
    希望对话演示不空。真实查询有结果时只用真实数据；真实为空时回退样本。
    source 标记 'aliyun+sample' 便于审计/日志区分真实与演示数据。
    """

    def __init__(self, real: CloudProvider, sample: CloudProvider, enabled: bool = True):
        self.real = real
        self.sample = sample
        self.enabled = enabled

    @property
    def source(self) -> str:
        return "aliyun+sample"

    def list_resources(self, tenant_id: str = "") -> List[dict]:
        real = self.real.list_resources(tenant_id)
        if self.enabled and not real:
            logger.info("真实资源为空，回退样本数据（tenant=%r）", tenant_id)
            return self.sample.list_resources(tenant_id)
        return real

    def describe(self, resource_id: str, tenant_id: str = "") -> Optional[dict]:
        r = self.real.describe(resource_id, tenant_id)
        if self.enabled and r is None:
            return self.sample.describe(resource_id, tenant_id)
        return r

    def get_metrics(self, resource_id: str, metric: str = "", tenant_id: str = "") -> Dict[str, float]:
        real_metrics = self.real.get_metrics(resource_id, metric, tenant_id)
        if real_metrics:
            return real_metrics
        if self.enabled:
            sample_res = self.sample.describe(resource_id, tenant_id)
            if sample_res:
                return self.sample.get_metrics(resource_id, metric, tenant_id)
        return {}


# ===========================================================================
# 工厂：根据密钥 + 兜底开关返回合适的 Provider
# ===========================================================================
def get_provider(tenant_id: str = "", user_id: str = "") -> CloudProvider:
    """返回合适的 Provider 实例。

    有 AK/SK：
        - ALIYUN_DEMO_FALLBACK=true  → FallbackProvider（真实优先，无资源回退样本）
        - 否则                        → AliyunProvider（纯真实云 API，只读）
    无 AK/SK → SampleProvider（样本数据回退，保证本地/CI 可运行、不产生费用）
    """
    creds = get_credentials()
    if creds:
        real = AliyunProvider(region_id=creds["region_id"], credentials=creds)
        fallback = os.environ.get("ALIYUN_DEMO_FALLBACK", "false").lower() in ("1", "true", "yes", "on")
        if fallback:
            logger.info("使用 FallbackProvider：真实优先 + 无资源回退样本（region=%s）", creds["region_id"])
            return FallbackProvider(real=real, sample=SampleProvider(), enabled=True)
        logger.info("使用真实阿里云 API Provider（region=%s）", creds["region_id"])
        return real
    logger.info("未检测到阿里云 AK/SK，回退样本数据 Provider")
    return SampleProvider()
