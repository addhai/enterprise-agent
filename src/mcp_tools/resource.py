"""云资源查询 MCP 工具集 — 真实云 API（阿里云 OpenAPI，只读）+ 样本回退

设计要点：
    1. 只读：所有工具只查询、不修改任何资源，符合最小权限原则。
    2. 真实数据：检测到 ALIYUN_ACCESS_KEY_ID/SECRET 时，直连阿里云 OpenAPI
       （ECS/RDS/SLB/Redis 查询 + 云监控指标），经 src.mcp_tools.cloud_provider 适配层。
    3. 安全回退：无密钥时自动回退样本数据（src.mcp_tools.cloud_provider.SampleProvider），
       保证本地/CI 可运行、不产生费用、不产生越权。
    4. 多租户隔离：tenant_id 由后端强制注入，真实模式下按资源标签 `tenant=` 过滤，
       样本模式下按内置 tenant_id 过滤；LLM 不可越租户。
    5. 复用 src.agent.tools.PermissionChecker 做身份与越权校验。

权限矩阵：
    query_resources / describe_resource / get_resource_monitor
        → 任何已认证用户（需 user_id 非 anonymous）
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional

from langchain_core.tools import tool

from src.agent.tools import PermissionChecker
from src.mcp_tools.cloud_provider import CloudProvider, get_provider

logger = logging.getLogger(__name__)


def _resource_to_line(r: dict) -> str:
    ip = r.get("public_ip") or r.get("private_ip") or "-"
    ip_label = "公网 IP" if r.get("public_ip") else ("内网 IP" if r.get("private_ip") else "IP")
    return (
        f"  • {r['name']}（{r['resource_id']}）| {r['region']} | {r['status']} | "
        f"{r['spec']} | {ip_label} {ip}"
    )


def _format_metrics(metrics: dict) -> str:
    unit = {"cpu": "%", "memory": "%", "connection": "个", "disk": "%"}
    if not metrics:
        return "    (无监控数据，可能该资源类型不支持云监控指标查询)"
    lines = []
    for k, v in metrics.items():
        lines.append(f"  • {k}: {v}{unit.get(k, '')}")
    return "\n".join(lines)


def _source_note(provider: CloudProvider) -> str:
    return "（数据来源：阿里云实时 API）" if provider.source == "aliyun" else "（演示样本数据）"


def create_resource_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建云资源查询工具列表（只读）

    Args:
        user_id: 调用者 user_id（多租户隔离强制）
        tenant_id: 调用者 tenant_id（多租户隔离强制）
        roles: 调用者角色列表
        plan: 订阅计划
        authority_source: 权威数据源回调（敏感操作前刷新权限）
    """
    checker = PermissionChecker(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles or [],
        access_levels=["public"],
        plan=plan,
        authority_source=authority_source,
    )
    # 按当前租户/用户选择 Provider（真实 API 或样本回退）
    provider = get_provider(tenant_id=tenant_id, user_id=user_id)

    @tool
    def query_resources(
        resource_type: str = "",
        region: str = "",
        keyword: str = "",
    ) -> str:
        """查询当前租户名下的云资源清单（只读，真实云 API）。

        何时使用：用户想了解自己有哪些云资源、查看 ECS/RDS/OSS/SLB/Redis 实例，
        或按类型/地域/名称关键字筛选。比如"我有哪些 ECS 实例"、"列出杭州地域的资源"、
        "查一下名字含 websrv 的资源"。

        Args:
            resource_type: 按类型过滤，可选: ECS/RDS/OSS/SLB/Redis（留空=全部类型）
            region: 按地域过滤，如 cn-hangzhou（留空=全部地域）
            keyword: 名称/ID 关键字模糊匹配（留空=不匹配）
        """
        if not checker.check("query_resources"):
            return "[权限不足] 您没有权限查询资源。"
        if user_id in ("", "anonymous"):
            return "[权限不足] 请先登录后再查询资源。"

        resources = provider.list_resources(tenant_id)
        if resource_type:
            resources = [r for r in resources if r["resource_type"].lower() == resource_type.lower()]
        if region:
            resources = [r for r in resources if r["region"].lower() == region.lower()]
        if keyword:
            kw = keyword.lower()
            resources = [
                r for r in resources
                if kw in r["name"].lower() or kw in r["resource_id"].lower()
            ]

        if not resources:
            scope = tenant_id or "演示租户"
            return f"[查询完成] 租户 {scope} 下没有匹配的资源。"

        lines = [f"[查询完成] 共 {len(resources)} 个资源（租户: {tenant_id or '演示租户'}）{_source_note(provider)}:"]
        for r in resources:
            lines.append(_resource_to_line(r))
        lines.append("\n提示：使用 describe_resource(<资源ID>) 查看详情，get_resource_monitor(<资源ID>) 查看监控。")
        return "\n".join(lines)

    @tool
    def describe_resource(resource_id: str) -> str:
        """查看单个云资源的详细信息（只读，真实云 API）。

        何时使用：用户想看某个具体资源的配置、状态、网络信息、归属等。
        比如"帮我看下 i-bp1a2b3c4d5e6f 这台机器的详情"。

        Args:
            resource_id: 资源 ID，如 i-bp1a2b3c4d5e6f、rm-bp1q2w3e4r5t6y
        """
        if not checker.check("describe_resource"):
            return "[权限不足] 您没有权限查询资源。"
        if user_id in ("", "anonymous"):
            return "[权限不足] 请先登录后再查询资源。"

        r = provider.describe(resource_id.strip(), tenant_id)
        if r is None:
            return f"[未找到] 资源 {resource_id} 不存在或不属于当前租户。"

        lines = [
            f"资源ID: {r['resource_id']}",
            f"名称: {r['name']}",
            f"类型: {r['resource_type']}",
            f"地域: {r['region']}",
            f"状态: {r['status']}",
            f"规格: {r['spec']}",
            f"私网IP: {r.get('private_ip') or '-'}",
            f"公网IP: {r.get('public_ip') or '-'}",
            f"归属人: {r['owner']}",
            f"创建时间: {r['created_at']}",
            f"租户: {r['tenant_id'] or '演示租户'}",
            _source_note(provider),
        ]
        return "\n".join(lines)

    @tool
    def get_resource_monitor(resource_id: str, metric: str = "") -> str:
        """查看云资源的监控指标（只读，真实云 API：ECS/RDS 走云监控）。

        何时使用：用户想了解资源当前的 CPU/内存等健康度。
        比如"websrv-01 的 CPU 使用率怎么样"。

        Args:
            resource_id: 资源 ID
            metric: 指标名（可选），如 cpu/memory；留空返回该资源支持的监控指标
        """
        if not checker.check("get_resource_monitor"):
            return "[权限不足] 您没有权限查询资源。"
        if user_id in ("", "anonymous"):
            return "[权限不足] 请先登录后再查询资源。"

        r = provider.describe(resource_id.strip(), tenant_id)
        if r is None:
            return f"[未找到] 资源 {resource_id} 不存在或不属于当前租户。"

        metrics = provider.get_metrics(resource_id.strip(), metric, tenant_id)
        name = r["name"]
        rid = r["resource_id"]
        if metric:
            key = metric.lower()
            if key in metrics:
                unit = "%" if key != "connection" else "个"
                return f"[监控] {name} ({rid}) — {key}: {metrics[key]}{unit} {_source_note(provider)}"
            return f"[监控] 不支持的指标: {metric}（ECS/RDS 支持 cpu/memory）"

        lines = [f"[监控] {name} ({rid}) {_source_note(provider)}:"]
        lines.append(_format_metrics(metrics))
        return "\n".join(lines)

    return [query_resources, describe_resource, get_resource_monitor]
