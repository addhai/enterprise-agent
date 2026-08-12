"""阿里云 OpenAPI 客户端（零额外依赖，纯 requests + RPC Signature V1 签名）

为什么不用官方 SDK：
    - 官方 SDK（alibabacloud_ecs* / aliyun-python-sdk-*）体积大、需联网安装，
      在沙箱/面试机环境常常装不上。本模块只用已普遍安装的 requests，
      手写 RPC 签名，代码透明、可审计，也更适合作品集展示"你真的懂云 API 鉴权"。

能力范围（只读，绝不写操作）：
    - ECS      DescribeInstances          查询 ECS 实例
    - RDS      DescribeDBInstances        查询 RDS 实例
    - SLB      DescribeLoadBalancers      查询 SLB 负载均衡
    - KVStore  DescribeInstances          查询 Redis 实例
    - CloudMonitor  DescribeMetricLast     查询实例监控指标（CPU/内存等）

鉴权：从环境变量读取 AK/SK
    ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET / ALIYUN_REGION_ID

参考：阿里云 RPC 签名机制 V1（HMAC-SHA1）
https://help.aliyun.com/zh/sdk/product-overview/rpc-mechanism
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import requests

# 自动从本地项目根目录的 .env 读取密钥（.env 已被 .gitignore 忽略，不进仓库、不上公网）
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # 未安装 python-dotenv 时跳过，不影响其他逻辑
    pass

logger = logging.getLogger(__name__)

# 各产品的接入点模板与 API 版本
# endpoint 模板中的 {region} 由调用方传入的 RegionId 填充
PRODUCT_ENDPOINTS: Dict[str, Dict[str, str]] = {
    "ecs": {
        "endpoint": "ecs.{region}.aliyuncs.com",
        "version": "2014-05-26",
        "scheme": "https",
    },
    "rds": {
        "endpoint": "rds.{region}.aliyuncs.com",
        "version": "2014-08-15",
        "scheme": "https",
    },
    "slb": {
        "endpoint": "slb.{region}.aliyuncs.com",
        "version": "2014-05-15",
        "scheme": "https",
    },
    "r-kvstore": {
        "endpoint": "r-kvstore.{region}.aliyuncs.com",
        "version": "2015-01-01",
        "scheme": "https",
    },
    "cms": {
        # 云监控接入点为 metrics.<region>.aliyuncs.com
        "endpoint": "metrics.{region}.aliyuncs.com",
        "version": "2019-01-01",
        "scheme": "https",
    },
}


def get_credentials() -> Optional[Dict[str, str]]:
    """从环境变量读取阿里云密钥；缺失返回 None（此时上层应回退样本数据）"""
    ak = os.environ.get("ALIYUN_ACCESS_KEY_ID")
    sk = os.environ.get("ALIYUN_ACCESS_KEY_SECRET")
    region = os.environ.get("ALIYUN_REGION_ID") or "cn-hangzhou"
    if not ak or not sk:
        return None
    # 允许值为空字符串（compose 默认 -ALIYUN_ACCESS_KEY_ID=${...:-}）
    if ak.strip() == "" or sk.strip() == "":
        return None
    return {"access_key_id": ak.strip(), "access_key_secret": sk.strip(), "region_id": region.strip()}


def _percent_encode(text: str) -> str:
    """RFC 3986 百分号编码，并适配阿里云要求的特殊字符处理"""
    import urllib.parse

    encoded = urllib.parse.quote(str(text), safe="")
    # 阿里云要求：* 编码为 %2A，空格编码为 %20，~ 保持原样
    encoded = encoded.replace("+", "%20").replace("*", "%2A").replace("%7E", "~")
    return encoded


def _sign(access_key_secret: str, string_to_sign: str) -> str:
    """HMAC-SHA1 签名，返回 Base64 字符串"""
    key = (access_key_secret + "&").encode("utf-8")
    message = string_to_sign.encode("utf-8")
    digest = hmac.new(key, message, hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def rpc_call(
    product: str,
    action: str,
    region_id: str,
    params: Optional[Dict[str, Any]] = None,
    credentials: Optional[Dict[str, str]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """调用一次阿里云 RPC 接口，返回解析后的 JSON 字典。

    Args:
        product: 产品标识，见 PRODUCT_ENDPOINTS（ecs/rds/slb/r-kvstore/cms）
        action: 接口名，如 DescribeInstances
        region_id: 地域，如 cn-hangzhou
        params: 业务参数（不含公共参数）
        credentials: get_credentials() 返回值；为空则抛 ValueError
        timeout: 请求超时（秒）

    Returns:
        成功：接口的 JSON 主体（dict）
        失败：包含 {"Error": {...}} 的字典，不抛异常（便于上层降级）
    """
    if credentials is None:
        credentials = get_credentials()
    if credentials is None:
        return {"Error": {"Code": "NoCredential", "Message": "未配置阿里云 AK/SK"}}

    product_cfg = PRODUCT_ENDPOINTS.get(product)
    if product_cfg is None:
        return {"Error": {"Code": "UnknownProduct", "Message": f"未知产品: {product}"}}

    common: Dict[str, Any] = {
        "Format": "JSON",
        "Version": product_cfg["version"],
        "AccessKeyId": credentials["access_key_id"],
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "Action": action,
        "RegionId": region_id,
    }
    if params:
        common.update(params)

    # 按 ASCII 排序并构造待签名查询串
    sorted_keys = sorted(common.keys())
    canonical = "&".join(
        f"{_percent_encode(k)}={_percent_encode(common[k])}" for k in sorted_keys
    )
    string_to_sign = f"GET&{_percent_encode('/')}&{_percent_encode(canonical)}"
    signature = _sign(credentials["access_key_secret"], string_to_sign)
    common["Signature"] = signature

    endpoint = product_cfg["endpoint"].format(region=region_id)
    url = f"{product_cfg['scheme']}://{endpoint}/"
    query = "&".join(f"{k}={common[k]}" for k in sorted_keys) + f"&Signature={_percent_encode(signature)}"

    try:
        resp = requests.get(url, params=query, timeout=timeout)
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("Aliyun RPC %s.%s 网络错误: %s", product, action, e)
        return {"Error": {"Code": "NetworkError", "Message": str(e)}}
    except json.JSONDecodeError as e:
        logger.warning("Aliyun RPC %s.%s 响应解析失败: %s", product, action, e)
        return {"Error": {"Code": "BadResponse", "Message": str(e)}}

    if "Code" in data and data.get("Code") not in ("", "200", "Success"):
        # 阿里云错误响应：{"Code": "...", "Message": "..."}
        return {"Error": {"Code": data.get("Code"), "Message": data.get("Message", "")},
                "RequestId": data.get("RequestId")}
    return data


class AliyunClient:
    """面向本项目的高层封装：把各产品的 RPC 结果归一化为统一资源结构。"""

    def __init__(self, region_id: Optional[str] = None, credentials: Optional[Dict[str, str]] = None):
        self.creds = credentials or get_credentials()
        self.region_id = (region_id or (self.creds or {}).get("region_id") or "cn-hangzhou")

    def is_configured(self) -> bool:
        return self.creds is not None

    # ---- 资源查询 ----
    def list_ecs(self) -> list:
        data = rpc_call("ecs", "DescribeInstances", self.region_id, {"PageSize": 100}, self.creds)
        if "Error" in data:
            logger.warning("ECS 查询失败: %s", data["Error"])
            return []
        return data.get("Instances", {}).get("Instance", []) if isinstance(data.get("Instances"), dict) else []

    def list_rds(self) -> list:
        data = rpc_call("rds", "DescribeDBInstances", self.region_id, {"PageSize": 100}, self.creds)
        if "Error" in data:
            logger.warning("RDS 查询失败: %s", data["Error"])
            return []
        items = data.get("Items", {})
        return items.get("DBInstance", []) if isinstance(items, dict) else []

    def list_slb(self) -> list:
        data = rpc_call("slb", "DescribeLoadBalancers", self.region_id, {"PageSize": 100}, self.creds)
        if "Error" in data:
            logger.warning("SLB 查询失败: %s", data["Error"])
            return []
        return data.get("LoadBalancers", {}).get("LoadBalancer", []) if isinstance(data.get("LoadBalancers"), dict) else []

    def list_redis(self) -> list:
        data = rpc_call("r-kvstore", "DescribeInstances", self.region_id, {"PageSize": 100}, self.creds)
        if "Error" in data:
            logger.warning("Redis 查询失败: %s", data["Error"])
            return []
        items = data.get("Instances", {})
        return items.get("KVStoreInstance", []) if isinstance(items, dict) else []

    # ---- 监控 ----
    def get_metric(self, instance_id: str, metric_name: str, namespace: str = "acs_ecs_dashboard") -> Optional[float]:
        """查询云监控最近一个数据点（CPU/内存等）

        Args:
            instance_id: 实例 ID
            metric_name: 指标名，如 CPUUtilization / memory_usage
            namespace: 云监控命名空间
        """
        params = {
            "Namespace": namespace,
            "MetricName": metric_name,
            "Period": "60",
            "Length": "1",
            "Dimensions": json.dumps([{"instanceId": instance_id}]),
        }
        data = rpc_call("cms", "DescribeMetricLast", self.region_id, params, self.creds)
        if "Error" in data:
            logger.warning("监控查询失败 %s/%s: %s", instance_id, metric_name, data["Error"])
            return None
        datapoints = data.get("Datapoints")
        if not datapoints:
            return None
        try:
            first = datapoints[0] if isinstance(datapoints, list) else json.loads(datapoints)[0]
            return float(first.get("Average", first.get("Value", 0)))
        except (ValueError, TypeError, json.JSONDecodeError, IndexError):
            return None
