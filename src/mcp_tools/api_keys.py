"""API Key 管理 MCP 工具 — generate_api_key / revoke_api_key / list_api_keys"""
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


class APIKeyStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class APIKey(BaseModel):
    id: str
    tenant_id: str
    name: str
    key: str
    status: APIKeyStatus
    permissions: List[str] = Field(default_factory=list)
    created_at: str
    expires_at: Optional[str] = None
    last_used: Optional[str] = None


_api_key_store = TenantIsolatedStore(max_items_per_tenant=1000, name="api_keys")


def _generate_api_key_value() -> str:
    """生成实际的 API Key 值（格式：sk_开头 + 43位随机字符）"""
    from uuid import uuid4

    return f"sk_{uuid4().hex[:32]}{uuid4().hex[:11]}"


def create_api_key_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建 API Key 管理工具"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    @tool
    def api_key_generate(name: str, expires_days: int = 0) -> str:
        """生成新的 API Key（仅 admin 可调用）。

        何时使用：用户需要获取 API Key 进行开发集成。

        Args:
            name: Key 名称（用于标识用途）
            expires_days: 有效期天数（0 表示永久有效）
        """
        if not checker.check("api_key_generate"):
            return format_result("权限不足", "您没有权限生成 API Key")
        if not require_admin(checker, "api_key_generate"):
            return format_result("权限不足", "需要 admin 角色")

        key_value = _generate_api_key_value()
        expires_at = None
        if expires_days > 0:
            from datetime import timedelta

            expires_at = (current_utc_time() + timedelta(days=expires_days)).isoformat()

        api_key = APIKey(
            id=generate_id("AK"),
            tenant_id=tenant_id,
            name=name,
            key=key_value,
            status=APIKeyStatus.ACTIVE,
            permissions=["read", "write"],
            created_at=current_utc_time().isoformat(),
            expires_at=expires_at,
        )
        _api_key_store.save(tenant_id, api_key.id, api_key)

        logger.info("API Key generated: id=%s name=%s", api_key.id, name)
        record_audit_log(
            tenant_id=tenant_id,
            user_id=user_id,
            action="key_generate",
            resource=f"api_key:{api_key.id}",
            details={"name": name, "expires_at": expires_at or "永久"},
        )
        return format_result("API Key 已生成", "", {
            "key_id": api_key.id,
            "key": key_value,
            "name": name,
            "expires_at": expires_at or "永久",
            "permissions": ",".join(api_key.permissions),
        })

    @tool
    def api_key_revoke(key_id: str, reason: str = "") -> str:
        """吊销 API Key（仅 admin 可调用）。

        何时使用：Key 泄露或不再需要时吊销。

        Args:
            key_id: Key ID（不是完整的 key 值）
            reason: 吊销原因（可选）
        """
        if not checker.check("api_key_revoke"):
            return format_result("权限不足", "您没有权限吊销 API Key")
        if not require_admin(checker, "api_key_revoke"):
            return format_result("权限不足", "需要 admin 角色")

        api_key = _api_key_store.get(tenant_id, key_id)
        if api_key is None:
            return format_result("未找到", f"API Key {key_id} 不存在")

        if api_key.status == APIKeyStatus.REVOKED:
            return format_result("已吊销", "该 API Key 已被吊销")

        api_key.status = APIKeyStatus.REVOKED
        _api_key_store.save(tenant_id, key_id, api_key)

        logger.info("API Key revoked: id=%s reason=%s", key_id, reason)
        record_audit_log(
            tenant_id=tenant_id,
            user_id=user_id,
            action="key_revoke",
            resource=f"api_key:{key_id}",
            details={"reason": reason or "未提供", "name": api_key.name},
        )
        return format_result("API Key 已吊销", "", {"key_id": key_id, "reason": reason or "无"})

    @tool
    def api_key_list(limit: int = 20) -> str:
        """列出当前租户的所有 API Key（仅 admin 可调用）。

        何时使用：查看租户下有哪些 API Key。

        Args:
            limit: 返回条数，默认 20
        """
        if not checker.check("api_key_list"):
            return format_result("权限不足", "您没有权限列出 API Key")
        if not require_admin(checker, "api_key_list"):
            return format_result("权限不足", "需要 admin 角色")

        keys = _api_key_store.list(tenant_id, min(100, max(1, limit)))
        if not keys:
            return format_result("查询完成", "暂无 API Key")

        lines = [f"[查询完成] 共 {len(keys)} 个 API Key:"]
        for k in keys:
            masked_key = f"{k.key[:8]}..." if k.key else "N/A"
            lines.append(
                f"  • {k.id} | {k.name} | {k.status} | "
                f"{masked_key} | expires={k.expires_at or '永久'}"
            )
        return "\n".join(lines)

    @tool
    def api_key_get(key_id: str) -> str:
        """查询单个 API Key 详情（仅 admin 可调用）。

        何时使用：查看某个 Key 的详细信息。

        Args:
            key_id: Key ID
        """
        if not checker.check("api_key_get"):
            return format_result("权限不足", "您没有权限查询 API Key")
        if not require_admin(checker, "api_key_get"):
            return format_result("权限不足", "需要 admin 角色")

        api_key = _api_key_store.get(tenant_id, key_id)
        if api_key is None:
            return format_result("未找到", f"API Key {key_id} 不存在")

        masked_key = f"{api_key.key[:8]}..." if api_key.key else "N/A"
        return format_result("查询成功", "", {
            "key_id": api_key.id,
            "name": api_key.name,
            "key": masked_key,
            "status": api_key.status,
            "permissions": ",".join(api_key.permissions),
            "created_at": api_key.created_at,
            "expires_at": api_key.expires_at or "永久",
            "last_used": api_key.last_used or "从未使用",
        })

    @tool
    def api_key_rotate(key_id: str) -> str:
        """轮换 API Key（生成新 key 值，保留 ID，仅 admin 可调用）。

        何时使用：Key 可能泄露但不想改变 ID 时轮换。

        Args:
            key_id: Key ID
        """
        if not checker.check("api_key_rotate"):
            return format_result("权限不足", "您没有权限轮换 API Key")
        if not require_admin(checker, "api_key_rotate"):
            return format_result("权限不足", "需要 admin 角色")

        api_key = _api_key_store.get(tenant_id, key_id)
        if api_key is None:
            return format_result("未找到", f"API Key {key_id} 不存在")

        old_key = api_key.key[:8] + "..."
        new_key = _generate_api_key_value()
        api_key.key = new_key
        _api_key_store.save(tenant_id, key_id, api_key)

        logger.info("API Key rotated: id=%s", key_id)
        return format_result("API Key 已轮换", "", {
            "key_id": key_id,
            "old_key": old_key,
            "new_key": new_key,
            "name": api_key.name,
        })

    return [
        api_key_generate,
        api_key_revoke,
        api_key_list,
        api_key_get,
        api_key_rotate,
    ]
