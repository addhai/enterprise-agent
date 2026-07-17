"""通知中心 API — 系统消息、转接提醒、工单提醒统一收口

支持按角色/用户推送通知，未读数统计，一键已读。
"""
import os
import time
import logging
import threading
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.models.common import NotificationType, NotificationLevel
from src.api.rbac import get_current_user, require_permissions, Permission

logger = logging.getLogger(__name__)
router = APIRouter(tags=["notifications"])


# ====================================================================
# 内存数据存储
# ====================================================================

_notifications: List[Dict[str, Any]] = []
_notifications_lock = threading.Lock()
_notification_counter = 0


# ====================================================================
# Pydantic 模型
# ====================================================================

class Notification(BaseModel):
    """通知实体"""
    id: str
    type: str
    level: str
    title: str
    message: str
    target_roles: List[str] = Field(default_factory=list)
    target_users: List[str] = Field(default_factory=list)
    link: Optional[str] = None
    read_by: List[str] = Field(default_factory=list)
    created_at: float


# ====================================================================
# API 路由
# ====================================================================

@router.get("/notifications")
async def list_notifications(
    unread_only: bool = Query(False, description="仅未读"),
    limit: int = Query(50, ge=1, le=200),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.NOTIFICATION_VIEW)),
):
    """获取当前用户的通知列表"""
    user_id = current_user["user_id"]
    user_role = current_user.get("role", "viewer")
    username = current_user.get("username", "")

    with _notifications_lock:
        all_notes = list(_notifications)

    # 筛选对当前用户可见的通知
    visible = []
    for n in all_notes:
        # 如果指定了目标用户
        if n.get("target_users"):
            if username in n["target_users"] or user_id in n["target_users"]:
                visible.append(n)
                continue
        # 如果指定了目标角色
        if n.get("target_roles"):
            if user_role in n["target_roles"]:
                visible.append(n)
                continue
        # 没有指定目标，全员可见
        if not n.get("target_users") and not n.get("target_roles"):
            visible.append(n)

    if unread_only:
        visible = [n for n in visible if user_id not in n.get("read_by", [])]

    visible.sort(key=lambda n: n["created_at"], reverse=True)

    # 标记当前用户是否已读
    result = []
    for n in visible[:limit]:
        item = dict(n)
        item["is_read"] = user_id in n.get("read_by", [])
        result.append(item)

    return {"total": len(visible), "notifications": result}


@router.get("/notifications/unread-count")
async def get_unread_count(
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.NOTIFICATION_VIEW)),
):
    """获取未读通知数"""
    user_id = current_user["user_id"]
    user_role = current_user.get("role", "viewer")
    username = current_user.get("username", "")

    count = 0
    with _notifications_lock:
        for n in _notifications:
            if user_id in n.get("read_by", []):
                continue
            if n.get("target_users") and (username in n["target_users"] or user_id in n["target_users"]):
                count += 1
            elif n.get("target_roles") and user_role in n["target_roles"]:
                count += 1
            elif not n.get("target_users") and not n.get("target_roles"):
                count += 1

    return {"unread_count": count}


@router.post("/notifications/{notification_id}/read")
async def mark_as_read(
    notification_id: str,
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.NOTIFICATION_VIEW)),
):
    """标记单条通知为已读"""
    user_id = current_user["user_id"]
    with _notifications_lock:
        for n in _notifications:
            if n["id"] == notification_id:
                if user_id not in n.get("read_by", []):
                    n.setdefault("read_by", []).append(user_id)
                return {"success": True}
    raise HTTPException(status_code=404, detail="通知不存在")


@router.post("/notifications/read-all")
async def mark_all_as_read(
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.NOTIFICATION_VIEW)),
):
    """标记所有可见通知为已读"""
    user_id = current_user["user_id"]
    user_role = current_user.get("role", "viewer")
    username = current_user.get("username", "")

    with _notifications_lock:
        for n in _notifications:
            visible = False
            if n.get("target_users") and (username in n["target_users"] or user_id in n["target_users"]):
                visible = True
            elif n.get("target_roles") and user_role in n["target_roles"]:
                visible = True
            elif not n.get("target_users") and not n.get("target_roles"):
                visible = True

            if visible and user_id not in n.get("read_by", []):
                n.setdefault("read_by", []).append(user_id)

    return {"success": True}


# ====================================================================
# 公共函数（供其他模块调用）
# ====================================================================

def add_notification(
    type: str,
    level: str,
    title: str,
    message: str,
    target_roles: Optional[List[str]] = None,
    target_users: Optional[List[str]] = None,
    link: Optional[str] = None,
) -> Dict[str, Any]:
    """添加通知"""
    global _notification_counter
    with _notifications_lock:
        _notification_counter += 1
        notification = {
            "id": f"NOT-{_notification_counter}",
            "type": type,
            "level": level,
            "title": title,
            "message": message,
            "target_roles": target_roles or [],
            "target_users": target_users or [],
            "link": link,
            "read_by": [],
            "created_at": time.time(),
        }
        _notifications.append(notification)

    logger.info("Notification added: %s - %s", title, message)
    return notification


def add_handoff_notification(session_id: str, user_id: str, reason: str = ""):
    """转接人工通知"""
    return add_notification(
        type="handoff",
        level="warning",
        title="用户请求转接人工",
        message=f"用户 {user_id[:12]} 请求人工客服" + (f"，原因：{reason}" if reason else ""),
        target_roles=["super_admin", "admin", "agent"],
        link=f"/agent?session={session_id}",
    )
