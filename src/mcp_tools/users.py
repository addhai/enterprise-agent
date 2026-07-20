"""用户管理 MCP 工具 — get_user_profile / reset_password / disable_account"""
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
from src.mcp_tools.audit import record_audit_log

logger = logging.getLogger(__name__)


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    SUPPORT_AGENT = "support_agent"
    BILLING_MANAGER = "billing_manager"


class User(BaseModel):
    id: str
    tenant_id: str
    email: str
    name: str
    status: UserStatus
    roles: List[str]
    created_at: str
    last_login: Optional[str] = None
    profile: dict = Field(default_factory=dict)


_user_store = TenantIsolatedStore(max_items_per_tenant=1000, name="users")


def create_user_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建用户管理工具"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    @tool
    def user_get_profile(target_user_id: str = "") -> str:
        """查询用户信息。

        何时使用：用户查看自己的信息，或客服查看其他用户资料（需 admin）。

        Args:
            target_user_id: 目标用户 ID（不传则查自己）
        """
        if not checker.check("user_get_profile"):
            return format_result("权限不足", "您没有权限查询用户信息")

        lookup_id = target_user_id or user_id
        user = _user_store.get(tenant_id, lookup_id)
        if user is None:
            return format_result("未找到", f"用户 {lookup_id} 不存在")

        if lookup_id != user_id and not require_admin(checker, "user_get_profile"):
            return format_result("权限不足", "查看其他用户信息需要 admin 角色")

        return format_result("查询成功", "", {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "status": user.status,
            "roles": ",".join(user.roles),
            "created_at": user.created_at,
        })

    @tool
    def user_reset_password(target_user_id: str, reason: str = "") -> str:
        """重置用户密码（仅 admin 可调用）。

        何时使用：客服帮用户重置密码。

        Args:
            target_user_id: 目标用户 ID
            reason: 重置原因（可选）
        """
        if not checker.check("user_reset_password"):
            return format_result("权限不足", "您没有权限重置密码")
        if not require_admin(checker, "user_reset_password"):
            return format_result("权限不足", "需要 admin 角色")

        user = _user_store.get(tenant_id, target_user_id)
        if user is None:
            return format_result("未找到", f"用户 {target_user_id} 不存在")

        logger.info("Password reset: user=%s by=%s reason=%s", target_user_id, user_id, reason)
        record_audit_log(
            tenant_id=tenant_id,
            user_id=user_id,
            action="update",
            resource=f"user:{target_user_id}:password",
            details={"reason": reason or "未提供", "target_email": user.email},
        )
        return format_result("密码已重置", "", {
            "user_id": target_user_id,
            "email": user.email,
            "method": "系统自动生成临时密码并发送邮件",
        })

    @tool
    def user_disable_account(target_user_id: str, reason: str) -> str:
        """禁用用户账号（仅 admin 可调用）。

        何时使用：客服禁用违规用户或离职员工账号。

        Args:
            target_user_id: 目标用户 ID
            reason: 禁用原因（必填）
        """
        if not checker.check("user_disable_account"):
            return format_result("权限不足", "您没有权限禁用账号")
        if not require_admin(checker, "user_disable_account"):
            return format_result("权限不足", "需要 admin 角色")

        if not reason.strip():
            return format_result("参数错误", "禁用原因不能为空")

        user = _user_store.get(tenant_id, target_user_id)
        if user is None:
            return format_result("未找到", f"用户 {target_user_id} 不存在")

        if user.status == UserStatus.DISABLED:
            return format_result("已禁用", "该用户已被禁用")

        user.status = UserStatus.DISABLED
        _user_store.save(tenant_id, target_user_id, user)

        logger.info("Account disabled: user=%s by=%s reason=%s", target_user_id, user_id, reason)
        record_audit_log(
            tenant_id=tenant_id,
            user_id=user_id,
            action="delete",
            resource=f"user:{target_user_id}:status",
            details={"reason": reason, "target_email": user.email},
        )
        return format_result("账号已禁用", "", {"user_id": target_user_id, "reason": reason})

    @tool
    def user_list(limit: int = 20) -> str:
        """列出租户内用户（仅 admin 可调用）。

        何时使用：客服需要查看租户下所有用户。

        Args:
            limit: 返回条数，默认 20
        """
        if not checker.check("user_list"):
            return format_result("权限不足", "您没有权限列出用户")
        if not require_admin(checker, "user_list"):
            return format_result("权限不足", "需要 admin 角色")

        users = _user_store.list(tenant_id, min(100, max(1, limit)))
        if not users:
            return format_result("查询完成", "暂无用户")

        lines = [f"[查询完成] 共 {len(users)} 位用户:"]
        for u in users:
            lines.append(f"  • {u.id} | {u.email} | {u.name} | {u.status}")
        return "\n".join(lines)

    @tool
    def user_update_profile(target_user_id: str, name: str = "", email: str = "") -> str:
        """更新用户资料（仅 admin 可调用）。

        何时使用：客服帮用户修改姓名或邮箱。

        Args:
            target_user_id: 目标用户 ID
            name: 新姓名（可选）
            email: 新邮箱（可选）
        """
        if not checker.check("user_update_profile"):
            return format_result("权限不足", "您没有权限更新用户资料")
        if not require_admin(checker, "user_update_profile"):
            return format_result("权限不足", "需要 admin 角色")

        user = _user_store.get(tenant_id, target_user_id)
        if user is None:
            return format_result("未找到", f"用户 {target_user_id} 不存在")

        changes = []
        if name:
            user.name = name
            changes.append(f"name={name}")
        if email:
            user.email = email
            changes.append(f"email={email}")

        if not changes:
            return format_result("无变更", "未提供任何更新字段")

        _user_store.save(tenant_id, target_user_id, user)
        logger.info("Profile updated: user=%s changes=[%s]", target_user_id, ",".join(changes))
        return format_result("资料已更新", "", {
            "user_id": target_user_id,
            "changes": ",".join(changes),
        })

    return [
        user_get_profile,
        user_reset_password,
        user_disable_account,
        user_list,
        user_update_profile,
    ]
