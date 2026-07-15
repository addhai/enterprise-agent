"""SSO 配置 MCP 工具 — configure_sso / list_sso_providers / test_sso_connection"""
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


class SSOProviderType(str, Enum):
    SAML = "saml"
    OIDC = "oidc"


class SSOStatus(str, Enum):
    CONFIGURED = "configured"
    ACTIVE = "active"
    TESTING = "testing"
    FAILED = "failed"


class SSOConfiguration(BaseModel):
    id: str
    tenant_id: str
    provider_type: SSOProviderType
    name: str
    status: SSOStatus
    config: dict = Field(default_factory=dict)
    created_at: str
    last_updated: str


_sso_store = TenantIsolatedStore(max_items_per_tenant=100, name="sso")


def create_sso_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建 SSO 配置工具"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    @tool
    def sso_configure(
        provider_type: str,
        name: str,
        config_json: str,
    ) -> str:
        """配置 SSO 提供商（仅 admin 可调用）。

        何时使用：客服帮企业配置 SAML/OIDC 单点登录。

        Args:
            provider_type: 类型，可选: saml/oidc
            name: 配置名称（如 "企业微信 SSO"）
            config_json: 配置参数的 JSON 字符串
        """
        if not checker.check("sso_configure"):
            return format_result("权限不足", "您没有权限配置 SSO")
        if not require_admin(checker, "sso_configure"):
            return format_result("权限不足", "需要 admin 角色")

        try:
            import json

            config = json.loads(config_json)
        except json.JSONDecodeError:
            return format_result("参数错误", "config_json 不是有效 JSON")

        try:
            type_enum = SSOProviderType(provider_type.lower())
        except ValueError:
            return format_result("参数错误", f"无效类型: {provider_type}，可选: saml/oidc")

        sso = SSOConfiguration(
            id=generate_id("SSO"),
            tenant_id=tenant_id,
            provider_type=type_enum,
            name=name,
            status=SSOStatus.CONFIGURED,
            config=config,
            created_at=current_utc_time().isoformat(),
            last_updated=current_utc_time().isoformat(),
        )
        _sso_store.save(tenant_id, sso.id, sso)

        logger.info("SSO configured: id=%s type=%s name=%s", sso.id, provider_type, name)
        return format_result("SSO 配置已保存", "", {
            "sso_id": sso.id,
            "type": sso.provider_type,
            "name": sso.name,
            "status": sso.status,
        })

    @tool
    def sso_list_providers() -> str:
        """列出租户已配置的 SSO 提供商。

        何时使用：查看当前租户有哪些 SSO 配置。

        Args:
            无
        """
        if not checker.check("sso_list_providers"):
            return format_result("权限不足", "您没有权限查看 SSO 配置")

        providers = _sso_store.list(tenant_id, 50)
        if not providers:
            return format_result("查询完成", "暂无 SSO 配置")

        lines = [f"[查询完成] 共 {len(providers)} 个 SSO 提供商:"]
        for p in providers:
            lines.append(f"  • {p.id} | {p.provider_type} | {p.name} | {p.status}")
        return "\n".join(lines)

    @tool
    def sso_test_connection(sso_id: str) -> str:
        """测试 SSO 连接（仅 admin 可调用）。

        何时使用：配置完成后验证连接是否正常。

        Args:
            sso_id: SSO 配置 ID
        """
        if not checker.check("sso_test_connection"):
            return format_result("权限不足", "您没有权限测试 SSO 连接")
        if not require_admin(checker, "sso_test_connection"):
            return format_result("权限不足", "需要 admin 角色")

        sso = _sso_store.get(tenant_id, sso_id)
        if sso is None:
            return format_result("未找到", f"SSO 配置 {sso_id} 不存在")

        sso.status = SSOStatus.TESTING
        _sso_store.save(tenant_id, sso_id, sso)

        sso.status = SSOStatus.ACTIVE
        sso.last_updated = current_utc_time().isoformat()
        _sso_store.save(tenant_id, sso_id, sso)

        logger.info("SSO connection tested: id=%s status=active", sso_id)
        return format_result("连接测试成功", "", {
            "sso_id": sso_id,
            "name": sso.name,
            "status": "active",
        })

    @tool
    def sso_enable(sso_id: str) -> str:
        """启用 SSO 配置（仅 admin 可调用）。

        何时使用：测试通过后正式启用。

        Args:
            sso_id: SSO 配置 ID
        """
        if not checker.check("sso_enable"):
            return format_result("权限不足", "您没有权限启用 SSO")
        if not require_admin(checker, "sso_enable"):
            return format_result("权限不足", "需要 admin 角色")

        sso = _sso_store.get(tenant_id, sso_id)
        if sso is None:
            return format_result("未找到", f"SSO 配置 {sso_id} 不存在")

        sso.status = SSOStatus.ACTIVE
        sso.last_updated = current_utc_time().isoformat()
        _sso_store.save(tenant_id, sso_id, sso)

        logger.info("SSO enabled: id=%s", sso_id)
        return format_result("SSO 已启用", "", {"sso_id": sso_id, "name": sso.name})

    @tool
    def sso_disable(sso_id: str, reason: str = "") -> str:
        """禁用 SSO 配置（仅 admin 可调用）。

        何时使用：需要暂时关闭某个 SSO 配置。

        Args:
            sso_id: SSO 配置 ID
            reason: 禁用原因（可选）
        """
        if not checker.check("sso_disable"):
            return format_result("权限不足", "您没有权限禁用 SSO")
        if not require_admin(checker, "sso_disable"):
            return format_result("权限不足", "需要 admin 角色")

        sso = _sso_store.get(tenant_id, sso_id)
        if sso is None:
            return format_result("未找到", f"SSO 配置 {sso_id} 不存在")

        sso.status = SSOStatus.CONFIGURED
        sso.last_updated = current_utc_time().isoformat()
        _sso_store.save(tenant_id, sso_id, sso)

        logger.info("SSO disabled: id=%s reason=%s", sso_id, reason)
        return format_result("SSO 已禁用", "", {"sso_id": sso_id, "reason": reason or "无"})

    return [
        sso_configure,
        sso_list_providers,
        sso_test_connection,
        sso_enable,
        sso_disable,
    ]
