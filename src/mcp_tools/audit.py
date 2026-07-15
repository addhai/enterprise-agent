"""审计日志查询 MCP 工具 — query_audit_logs / export_audit_report"""
import logging
from enum import Enum
from typing import Callable, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agent.tools import PermissionChecker
from src.mcp_tools.common import (
    TenantIsolatedStore,
    current_utc_time,
    format_result,
    generate_id,
    require_admin,
)

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    LOGIN = "login"
    LOGOUT = "logout"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    QUERY = "query"
    API_CALL = "api_call"
    PERMISSION_DENIED = "permission_denied"
    TICKET_CREATE = "ticket_create"
    TICKET_CLOSE = "ticket_close"
    REFUND = "refund"
    KEY_GENERATE = "key_generate"
    KEY_REVOKE = "key_revoke"


class AuditLog(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    action: AuditAction
    resource: str
    details: dict = Field(default_factory=dict)
    ip_address: Optional[str] = None
    timestamp: str


_audit_store = TenantIsolatedStore(max_items_per_tenant=10000, ttl_hours=168, name="audit")


def create_audit_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建审计日志查询工具"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    @tool
    def audit_query_logs(
        action: str = "",
        resource: str = "",
        limit: int = 20,
    ) -> str:
        """查询审计日志（仅 admin 可调用）。

        何时使用：合规审计、安全排查、追踪异常操作。

        Args:
            action: 按操作类型过滤（可选）
            resource: 按资源类型过滤（可选）
            limit: 返回条数，默认 20
        """
        if not checker.check("audit_query_logs"):
            return format_result("权限不足", "您没有权限查询审计日志")
        if not require_admin(checker, "audit_query_logs"):
            return format_result("权限不足", "需要 admin 角色")

        logs = _audit_store.list(tenant_id, min(200, max(1, limit)))
        if action:
            logs = [l for l in logs if l.action == action.lower()]
        if resource:
            logs = [l for l in logs if resource.lower() in l.resource.lower()]

        if not logs:
            return format_result("查询完成", "暂无匹配的审计日志")

        lines = [f"[查询完成] 共 {len(logs)} 条日志:"]
        for l in logs:
            lines.append(
                f"  • {l.id} | {l.action} | {l.resource} | "
                f"user={l.user_id} | {l.timestamp[:19]}"
            )
        return "\n".join(lines)

    @tool
    def audit_export_report(
        start_date: str = "",
        end_date: str = "",
        format: str = "json",
    ) -> str:
        """导出审计报告（仅 admin 可调用）。

        何时使用：定期合规报告、安全事件调查。

        Args:
            start_date: 开始日期（YYYY-MM-DD，可选）
            end_date: 结束日期（YYYY-MM-DD，可选）
            format: 导出格式，可选: json/csv，默认 json
        """
        if not checker.check("audit_export_report"):
            return format_result("权限不足", "您没有权限导出审计报告")
        if not require_admin(checker, "audit_export_report"):
            return format_result("权限不足", "需要 admin 角色")

        logs = _audit_store.list(tenant_id, 1000)

        if start_date:
            logs = [l for l in logs if l.timestamp >= start_date]
        if end_date:
            logs = [l for l in logs if l.timestamp <= end_date + "T23:59:59"]

        report_id = generate_id("REP")
        logger.info("Audit report exported: id=%s count=%d", report_id, len(logs))

        return format_result("报告已导出", "", {
            "report_id": report_id,
            "total_records": len(logs),
            "format": format,
            "start_date": start_date or "最早",
            "end_date": end_date or "最新",
            "download_path": f"/reports/audit/{report_id}.{format}",
        })

    @tool
    def audit_search_by_user(target_user_id: str, limit: int = 20) -> str:
        """按用户查询审计日志（仅 admin 可调用）。

        何时使用：追踪某个用户的操作历史。

        Args:
            target_user_id: 目标用户 ID
            limit: 返回条数，默认 20
        """
        if not checker.check("audit_search_by_user"):
            return format_result("权限不足", "您没有权限查询用户审计日志")
        if not require_admin(checker, "audit_search_by_user"):
            return format_result("权限不足", "需要 admin 角色")

        logs = _audit_store.list(tenant_id, min(100, max(1, limit)))
        logs = [l for l in logs if l.user_id == target_user_id]

        if not logs:
            return format_result("查询完成", f"用户 {target_user_id} 暂无审计日志")

        lines = [f"[查询完成] 用户 {target_user_id} 共 {len(logs)} 条操作记录:"]
        for l in logs:
            lines.append(f"  • {l.action} | {l.resource} | {l.timestamp[:19]}")
        return "\n".join(lines)

    @tool
    def audit_get_log_details(log_id: str) -> str:
        """获取审计日志详细信息（仅 admin 可调用）。

        何时使用：查看某条日志的完整上下文。

        Args:
            log_id: 日志 ID
        """
        if not checker.check("audit_get_log_details"):
            return format_result("权限不足", "您没有权限查看日志详情")
        if not require_admin(checker, "audit_get_log_details"):
            return format_result("权限不足", "需要 admin 角色")

        log = _audit_store.get(tenant_id, log_id)
        if log is None:
            return format_result("未找到", f"日志 {log_id} 不存在")

        details_str = ", ".join(f"{k}={v}" for k, v in log.details.items())
        return format_result("查询成功", "", {
            "log_id": log.id,
            "action": log.action,
            "resource": log.resource,
            "user_id": log.user_id,
            "ip_address": log.ip_address or "未知",
            "timestamp": log.timestamp,
            "details": details_str,
        })

    return [
        audit_query_logs,
        audit_export_report,
        audit_search_by_user,
        audit_get_log_details,
    ]


def record_audit_log(
    tenant_id: str,
    user_id: str,
    action: str,
    resource: str,
    details: dict = None,
    ip_address: str = None,
):
    """记录审计日志（内部函数，供其他模块调用）"""
    log = AuditLog(
        id=generate_id("AUD"),
        tenant_id=tenant_id,
        user_id=user_id,
        action=AuditAction(action.lower()),
        resource=resource,
        details=details or {},
        ip_address=ip_address,
        timestamp=current_utc_time().isoformat(),
    )
    _audit_store.save(tenant_id, log.id, log)
