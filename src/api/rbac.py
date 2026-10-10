"""RBAC 权限控制 — 5 级角色与资源权限校验

角色定义：
    - super_admin: 超级管理员，可操作所有功能、管理用户角色
    - admin: 管理员，可查看全部数据、分配工单、管理知识库
    - agent: 客服，处理分配给自己的会话/工单
    - viewer: 只读，仅查看仪表盘和数据
    - supervisor: 主管，可查看仪表盘和只读数据
"""

import logging
import os
from enum import Enum
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

# 鉴权入口统一委托 src.api.auth.get_current_user：token 验签、停用账号 403、
# 默认密码强制改密拦截全部在该函数收口。历史上 rbac 内维护过一份精简副本，
# 只验 token 不查 status/默认密码，管理端链路会绕过 P0-1/P0-6 校验，已删除。
from src.api.auth import get_current_user  # noqa: E402
from src.models.common import UserRole

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rbac"])


# ====================================================================
# 权限定义
# ====================================================================


class Permission(str, Enum):
    """系统权限点"""

    DASHBOARD_VIEW = "dashboard:view"
    CUSTOMER_VIEW = "customer:view"
    CUSTOMER_MANAGE = "customer:manage"
    TICKET_VIEW = "ticket:view"
    TICKET_MANAGE = "ticket:manage"
    TICKET_ASSIGN = "ticket:assign"
    AGENT_WORKSPACE = "agent:workspace"
    SATISFACTION_VIEW = "satisfaction:view"
    KNOWLEDGE_VIEW = "knowledge:view"
    KNOWLEDGE_MANAGE = "knowledge:manage"
    CHANNEL_VIEW = "channel:view"
    CHANNEL_MANAGE = "channel:manage"
    USER_VIEW = "user:view"
    USER_MANAGE = "user:manage"
    NOTIFICATION_VIEW = "notification:view"
    MONITOR_VIEW = "monitor:view"  # 监控大屏：查看业务/质量/风险/系统指标
    # P3-P6 新增模块权限
    CONFIG_VIEW = "config:view"  # 配置中心：查看
    CONFIG_MANAGE = "config:manage"  # 配置中心：修改/重置
    EVALUATION_VIEW = "evaluation:view"  # 评估：查看数据集与报告
    EVALUATION_MANAGE = "evaluation:manage"  # 评估：创建/触发/删除
    WORKFLOW_VIEW = "workflow:view"  # 工作流：查看
    WORKFLOW_MANAGE = "workflow:manage"  # 工作流：编辑/发布


# 角色 -> 权限映射
ROLE_PERMISSIONS: dict[UserRole, list[Permission]] = {
    UserRole.SUPER_ADMIN: list(Permission),
    UserRole.ADMIN: [
        Permission.DASHBOARD_VIEW,
        Permission.CUSTOMER_VIEW,
        Permission.CUSTOMER_MANAGE,
        Permission.TICKET_VIEW,
        Permission.TICKET_MANAGE,
        Permission.TICKET_ASSIGN,
        Permission.AGENT_WORKSPACE,
        Permission.SATISFACTION_VIEW,
        Permission.KNOWLEDGE_VIEW,
        Permission.KNOWLEDGE_MANAGE,
        Permission.CHANNEL_VIEW,
        Permission.CHANNEL_MANAGE,
        Permission.USER_VIEW,
        Permission.NOTIFICATION_VIEW,
        Permission.MONITOR_VIEW,
        Permission.CONFIG_VIEW,
        Permission.CONFIG_MANAGE,
        Permission.EVALUATION_VIEW,
        Permission.EVALUATION_MANAGE,
        Permission.WORKFLOW_VIEW,
        Permission.WORKFLOW_MANAGE,
    ],
    UserRole.AGENT: [
        Permission.DASHBOARD_VIEW,
        Permission.CUSTOMER_VIEW,
        Permission.TICKET_VIEW,
        Permission.TICKET_MANAGE,
        Permission.AGENT_WORKSPACE,
        Permission.SATISFACTION_VIEW,
        Permission.NOTIFICATION_VIEW,
        Permission.MONITOR_VIEW,
        Permission.CONFIG_VIEW,
        Permission.EVALUATION_VIEW,
        Permission.WORKFLOW_VIEW,
    ],
    UserRole.VIEWER: [
        Permission.DASHBOARD_VIEW,
        Permission.CUSTOMER_VIEW,
        Permission.TICKET_VIEW,
        Permission.SATISFACTION_VIEW,
        Permission.KNOWLEDGE_VIEW,
        Permission.CHANNEL_VIEW,
        Permission.USER_VIEW,
        Permission.NOTIFICATION_VIEW,
        Permission.MONITOR_VIEW,
        Permission.CONFIG_VIEW,
        Permission.EVALUATION_VIEW,
        Permission.WORKFLOW_VIEW,
    ],
    UserRole.SUPERVISOR: [
        # 主管：团队视角，查看为主 + 工单处置/分配（团队管理职责）
        Permission.DASHBOARD_VIEW,
        Permission.CUSTOMER_VIEW,
        Permission.TICKET_VIEW,
        Permission.TICKET_MANAGE,
        Permission.TICKET_ASSIGN,
        Permission.AGENT_WORKSPACE,
        Permission.SATISFACTION_VIEW,
        Permission.KNOWLEDGE_VIEW,
        Permission.CHANNEL_VIEW,
        Permission.USER_VIEW,
        Permission.NOTIFICATION_VIEW,
        Permission.MONITOR_VIEW,
        Permission.CONFIG_VIEW,
        Permission.EVALUATION_VIEW,
        Permission.WORKFLOW_VIEW,
    ],
}


# ====================================================================
# 角色 -> 文档密级映射（2026-10 P0-1/P0-6 安全收口）
# ====================================================================
# 文档密级 4 级：public < internal < confidential < restricted，
# 检索层按「用户最高密级 >= 文档密级」放行（src/rag/retriever.py
# _filter_by_permission）。本映射是全系统授予密级的唯一真相，禁止调用方
# 再从请求体读取 user_access_levels（曾导致 /chat 匿名自报四级全开）。
#
# 现状说明（辩证）：生产 652 块的密级由关键词启发式自动打标
# （src/rag/processors/metadata_enrich.py），客服必读的售后政策整文被标
# confidential、校准指南被标 restricted，标签本身偏粗。在文档密级人工
# 校准完成前，agent/supervisor 暂保持四级可见，避免把正确答案藏起来；
# viewer 为只读账号，先收紧到 public/internal。密级进一步收紧必须以
# 文档密级校准为前置，并重新跑金标 50 题验证。
_ACCESS_LEVEL_PUBLIC_AND_INTERNAL = ["public", "internal"]
_ACCESS_LEVEL_ALL = ["public", "internal", "confidential", "restricted"]

ROLE_ACCESS_LEVELS: dict[UserRole, list[str]] = {
    UserRole.SUPER_ADMIN: _ACCESS_LEVEL_ALL,
    UserRole.ADMIN: _ACCESS_LEVEL_ALL,
    UserRole.SUPERVISOR: _ACCESS_LEVEL_ALL,  # 待文档密级校准后评估收紧
    UserRole.AGENT: _ACCESS_LEVEL_ALL,  # 客服业务依赖售后/校准文档，同上
    UserRole.VIEWER: _ACCESS_LEVEL_PUBLIC_AND_INTERNAL,
}


def role_to_access_levels(role: str | None) -> list[str]:
    """把服务端角色解析为可检索密级列表。

    未知角色 fail-closed 到最小权限 public，不得默认放开。
    """
    try:
        parsed = UserRole(role) if role else None
    except ValueError:
        return ["public"]
    return list(ROLE_ACCESS_LEVELS.get(parsed, ["public"]))


# ====================================================================
# Pydantic 模型
# ====================================================================


class RoleInfo(BaseModel):
    """角色信息"""

    role: str
    label: str
    description: str
    permissions: list[str]


class UpdateRoleRequest(BaseModel):
    """更新用户角色请求"""

    role: UserRole = Field(..., description="目标角色")


class UserWithRole(BaseModel):
    """带角色的用户信息"""

    user_id: str
    username: str
    avatar: str
    role: str
    status: str
    tenant_id: str = "default"
    created_at: float


# ====================================================================
# 依赖注入
# ====================================================================


def require_permissions(*permissions: Permission):
    """权限校验依赖工厂"""

    async def checker(current_user: dict[str, Any] = Depends(get_current_user)):
        role_str = current_user.get("role", "viewer")
        try:
            role = UserRole(role_str)
        except ValueError:
            raise HTTPException(status_code=403, detail="无效的用户角色") from None
        user_perms = ROLE_PERMISSIONS.get(role, [])
        missing = [p.value for p in permissions if p not in user_perms]
        if missing:
            raise HTTPException(
                status_code=403, detail=f"权限不足，缺少: {', '.join(missing)}"
            )
        return current_user

    return checker


def require_role(*roles: UserRole):
    """角色校验依赖工厂"""

    async def checker(current_user: dict[str, Any] = Depends(get_current_user)):
        role_str = current_user.get("role", "viewer")
        try:
            role = UserRole(role_str)
        except ValueError:
            raise HTTPException(status_code=403, detail="无效的用户角色") from None
        if role not in roles:
            raise HTTPException(status_code=403, detail="当前角色无权限执行此操作")
        return current_user

    return checker


# ====================================================================
# 简化角色控制（Role 为 UserRole 别名，单一真相，用于关键 API 端点角色校验）
# ====================================================================

# 角色口径单一真相：UserRole（见 src/models/common.py）。
# 此处仅保留别名以兼容既有 require_roles 调用，不再定义第二套枚举。
Role = UserRole


def require_roles(*roles: Role):
    """角色依赖检查装饰器

    校验当前用户角色是否在允许的角色列表中。
    super_admin 视为最高权限，自动通过所有角色校验（向后兼容）。
    """

    def role_checker(current_user: dict[str, Any] = Depends(get_current_user)):
        user_role = current_user.get("role")
        # super_admin 为系统最高权限，直接通过所有角色校验
        if user_role == UserRole.SUPER_ADMIN.value:
            return current_user
        allowed = [r.value for r in roles]
        if user_role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要以下角色之一: {allowed}",
            )
        return current_user

    return role_checker


# 常用权限依赖
require_admin = require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)
require_user_manage = require_role(UserRole.SUPER_ADMIN)


# ====================================================================
# API 路由
# ====================================================================


@router.get("/rbac/roles")
async def list_roles():
    """获取所有角色定义"""
    return {
        "roles": [
            RoleInfo(
                role=r.value,
                label=_role_label(r),
                description=_role_desc(r),
                permissions=[p.value for p in ROLE_PERMISSIONS.get(r, [])],
            )
            for r in UserRole
        ]
    }


@router.get("/rbac/permissions")
async def list_permissions():
    """获取所有权限点"""
    return {
        "permissions": [
            {"permission": p.value, "label": _perm_label(p)} for p in Permission
        ]
    }


@router.get("/rbac/users")
async def list_users_with_roles(
    current_user: dict[str, Any] = Depends(require_permissions(Permission.USER_VIEW)),
):
    """获取用户列表及其角色（仅本租户，R4 租户维度）"""
    from src.db.repositories import DEFAULT_TENANT, list_users

    tenant_id = current_user.get("tenant_id") or DEFAULT_TENANT
    users = [
        UserWithRole(
            user_id=u["user_id"],
            username=u["username"],
            avatar=u.get("avatar", u["username"][0].upper() if u["username"] else "?"),
            role=u.get("role", "viewer"),
            status=u.get("status", "active"),
            tenant_id=u.get("tenant_id", "default"),
            created_at=u.get("created_at", 0),
        )
        for u in list_users(tenant_id=tenant_id)
    ]
    users.sort(key=lambda x: x.created_at, reverse=True)
    return {"total": len(users), "users": users}


@router.put("/rbac/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    request: UpdateRoleRequest,
    current_user: dict[str, Any] = Depends(require_user_manage),
):
    """更新用户角色（仅超级管理员）"""
    from src.db.repositories import user_get_by_id, user_update

    target = user_get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 租户维度 R4：禁止跨租户管理用户
    if target.get("tenant_id") != current_user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="无权管理其他租户的用户")
    # 不能修改自己的角色，避免把自己锁死
    if target["user_id"] == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
    old_role = target.get("role", "viewer")
    user_update(user_id, {"role": request.role.value})
    logger.info(
        "User role updated: %s %s -> %s by %s",
        user_id,
        old_role,
        request.role.value,
        current_user["user_id"],
    )
    return {
        "success": True,
        "user_id": user_id,
        "role": request.role.value,
    }


@router.put("/rbac/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    status: str = Body(..., embed=True),
    current_user: dict[str, Any] = Depends(require_permissions(Permission.USER_MANAGE)),
):
    """启用/禁用用户"""
    from src.db.repositories import user_get_by_id, user_update

    target = user_get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 租户维度 R4：禁止跨租户管理用户
    if target.get("tenant_id") != current_user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="无权管理其他租户的用户")
    if target["user_id"] == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    if status not in ("active", "inactive", "suspended"):
        raise HTTPException(status_code=400, detail="无效的状态")
    user_update(user_id, {"status": status})
    return {"success": True, "user_id": user_id, "status": status}


@router.get("/rbac/me/permissions")
async def get_my_permissions(current_user: dict[str, Any] = Depends(get_current_user)):
    """获取当前用户权限"""
    role_str = current_user.get("role", "viewer")
    try:
        role = UserRole(role_str)
    except ValueError:
        role = UserRole.VIEWER
    return {
        "role": role.value,
        "role_label": _role_label(role),
        "permissions": [p.value for p in ROLE_PERMISSIONS.get(role, [])],
    }


# ====================================================================
# 辅助函数
# ====================================================================


def _role_label(role: UserRole) -> str:
    return {
        UserRole.SUPER_ADMIN: "超级管理员",
        UserRole.ADMIN: "管理员",
        UserRole.AGENT: "客服",
        UserRole.VIEWER: "只读用户",
        UserRole.SUPERVISOR: "主管",
    }.get(role, role.value)


def _role_desc(role: UserRole) -> str:
    return {
        UserRole.SUPER_ADMIN: "系统最高权限，可管理所有用户和配置",
        UserRole.ADMIN: "可查看全部数据、分配工单、管理知识库",
        UserRole.AGENT: "处理分配给自己的会话与工单",
        UserRole.VIEWER: "仅可查看数据，不能执行操作",
        UserRole.SUPERVISOR: "团队主管视角，查看为主、可处置与分配工单",
    }.get(role, "")


def _perm_label(perm: Permission) -> str:
    return {
        Permission.DASHBOARD_VIEW: "查看仪表盘",
        Permission.CUSTOMER_VIEW: "查看客户",
        Permission.CUSTOMER_MANAGE: "管理客户",
        Permission.TICKET_VIEW: "查看工单",
        Permission.TICKET_MANAGE: "处理工单",
        Permission.TICKET_ASSIGN: "分配工单",
        Permission.AGENT_WORKSPACE: "客服工作台",
        Permission.SATISFACTION_VIEW: "查看满意度",
        Permission.KNOWLEDGE_VIEW: "查看知识库",
        Permission.KNOWLEDGE_MANAGE: "管理知识库",
        Permission.CHANNEL_VIEW: "查看渠道",
        Permission.CHANNEL_MANAGE: "管理渠道",
        Permission.USER_VIEW: "查看用户",
        Permission.USER_MANAGE: "管理用户",
        Permission.NOTIFICATION_VIEW: "查看通知",
        Permission.CONFIG_VIEW: "查看配置",
        Permission.CONFIG_MANAGE: "修改配置",
        Permission.EVALUATION_VIEW: "查看评估",
        Permission.EVALUATION_MANAGE: "管理评估",
        Permission.WORKFLOW_VIEW: "查看工作流",
        Permission.WORKFLOW_MANAGE: "管理工作流",
        Permission.MONITOR_VIEW: "查看监控大屏",
    }.get(perm, perm.value)
