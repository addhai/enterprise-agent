"""RBAC 权限控制 — 4 级角色与资源权限校验

角色定义：
    - super_admin: 超级管理员，可操作所有功能、管理用户角色
    - admin: 管理员，可查看全部数据、分配工单、管理知识库
    - agent: 客服，处理分配给自己的会话/工单
    - viewer: 只读，仅查看仪表盘和数据
"""
import os
import logging
from enum import Enum
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Header, Depends, Body
from pydantic import BaseModel, Field

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

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


# 角色 -> 权限映射
ROLE_PERMISSIONS: Dict[UserRole, List[Permission]] = {
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
    ],
    UserRole.AGENT: [
        Permission.DASHBOARD_VIEW,
        Permission.CUSTOMER_VIEW,
        Permission.TICKET_VIEW,
        Permission.TICKET_MANAGE,
        Permission.AGENT_WORKSPACE,
        Permission.SATISFACTION_VIEW,
        Permission.NOTIFICATION_VIEW,
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
    ],
}


# ====================================================================
# Pydantic 模型
# ====================================================================

class RoleInfo(BaseModel):
    """角色信息"""
    role: str
    label: str
    description: str
    permissions: List[str]


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
    created_at: float


# ====================================================================
# 依赖注入
# ====================================================================

async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """获取当前登录用户"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证令牌")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="认证令牌格式错误")
    token = authorization[7:]
    from src.api.auth import _get_user_by_token
    user = _get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="认证令牌无效或已过期")
    return user


def require_permissions(*permissions: Permission):
    """权限校验依赖工厂"""
    async def checker(current_user: Dict[str, Any] = Depends(get_current_user)):
        role_str = current_user.get("role", "viewer")
        try:
            role = UserRole(role_str)
        except ValueError:
            raise HTTPException(status_code=403, detail="无效的用户角色")
        user_perms = ROLE_PERMISSIONS.get(role, [])
        missing = [p.value for p in permissions if p not in user_perms]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"权限不足，缺少: {', '.join(missing)}"
            )
        return current_user
    return checker


def require_role(*roles: UserRole):
    """角色校验依赖工厂"""
    async def checker(current_user: Dict[str, Any] = Depends(get_current_user)):
        role_str = current_user.get("role", "viewer")
        try:
            role = UserRole(role_str)
        except ValueError:
            raise HTTPException(status_code=403, detail="无效的用户角色")
        if role not in roles:
            raise HTTPException(status_code=403, detail="当前角色无权限执行此操作")
        return current_user
    return checker


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
            {"permission": p.value, "label": _perm_label(p)}
            for p in Permission
        ]
    }


@router.get("/rbac/users")
async def list_users_with_roles(
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.USER_VIEW))
):
    """获取用户列表及其角色"""
    from src.api.auth import _users
    users = []
    for u in _users.values():
        users.append(UserWithRole(
            user_id=u["user_id"],
            username=u["username"],
            avatar=u.get("avatar", u["username"][0].upper() if u["username"] else "?"),
            role=u.get("role", "viewer"),
            status=u.get("status", "active"),
            created_at=u.get("created_at", 0),
        ))
    users.sort(key=lambda x: x.created_at, reverse=True)
    return {"total": len(users), "users": users}


@router.put("/rbac/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    request: UpdateRoleRequest,
    current_user: Dict[str, Any] = Depends(require_user_manage),
):
    """更新用户角色（仅超级管理员）"""
    from src.api.auth import _users
    target = _users.get(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 不能修改自己的角色，避免把自己锁死
    if target["user_id"] == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
    old_role = target.get("role", "viewer")
    target["role"] = request.role.value
    logger.info("User role updated: %s %s -> %s by %s", user_id, old_role, request.role.value, current_user["user_id"])
    return {
        "success": True,
        "user_id": user_id,
        "role": request.role.value,
    }


@router.put("/rbac/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    status: str = Body(..., embed=True),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.USER_MANAGE)),
):
    """启用/禁用用户"""
    from src.api.auth import _users
    target = _users.get(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target["user_id"] == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    if status not in ("active", "inactive", "suspended"):
        raise HTTPException(status_code=400, detail="无效的状态")
    target["status"] = status
    return {"success": True, "user_id": user_id, "status": status}


@router.get("/rbac/me/permissions")
async def get_my_permissions(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
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
    }.get(role, role.value)


def _role_desc(role: UserRole) -> str:
    return {
        UserRole.SUPER_ADMIN: "系统最高权限，可管理所有用户和配置",
        UserRole.ADMIN: "可查看全部数据、分配工单、管理知识库",
        UserRole.AGENT: "处理分配给自己的会话与工单",
        UserRole.VIEWER: "仅可查看数据，不能执行操作",
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
    }.get(perm, perm.value)
