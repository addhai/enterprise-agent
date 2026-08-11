"""共享枚举与基础模型

用于 RBAC、业务状态、通知等跨模块复用的类型定义。
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """RBAC 角色（单一真相，5 角色口径）

    对齐 delivery/安全设计.md §2.2 / D-02：admin / agent / viewer / user(≈agent|viewer) / supervisor 共 5 角色口径。
    原代码曾存在 `UserRole`（权限映射）与 `Role`（端点校验）两套枚举且 SUPER_ADMIN / SUPERVISOR 不一致，
    现已统一为 `UserRole` 单一枚举，`src/api/rbac.py` 的 `Role` 为其别名。
    """
    SUPER_ADMIN = "super_admin"   # 超级管理员：可管理用户、系统配置
    ADMIN = "admin"               # 管理员：可查看所有数据、分配工单
    AGENT = "agent"               # 客服：处理会话和工单
    VIEWER = "viewer"             # 只读：仅查看数据，不能操作
    SUPERVISOR = "supervisor"     # 主管：督导客服团队，可协助处理工单与会话


class UserStatus(str, Enum):
    """用户状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class NotificationType(str, Enum):
    """通知类型"""
    HANDOFF = "handoff"           # 转接人工
    TICKET = "ticket"             # 新工单/工单更新
    SYSTEM = "system"             # 系统通知
    SATISFACTION = "satisfaction" # 满意度评价


class NotificationLevel(str, Enum):
    """通知级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class ApiResponse(BaseModel):
    """统一 API 响应结构"""
    success: bool = True
    message: str = "ok"
    data: Optional[dict] = None
