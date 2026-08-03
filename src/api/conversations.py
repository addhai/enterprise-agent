"""会话历史查询 API

暴露已持久化的对话与消息，供前端"历史会话"列表 / 复盘使用。
鉴权：任意已登录用户（get_current_user）；user_id 过滤默认只看自己，
admin / agent 可传 ?user_id= 查看他人会话。

实现委托给 ``src.api.sessions_service`` 共享 service 层（与 admin.py 的
/sessions、/admin/sessions 共用同一套 list/detail/messages/delete 逻辑）。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.rbac import Role, get_current_user, require_roles
from src.api.sessions_service import (
    delete_session,
    get_session_messages,
    list_sessions,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["会话历史 Conversations"])


@router.get("")
async def list_conversations(
    user_id: Optional[str] = Query(None, description="按用户过滤；留空则返回当前用户"),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """列出会话（按最近活跃时间倒序）。

    普通用户只能看自己的会话；admin / agent 可指定 user_id 查看他人。
    """
    conversations = list_sessions(
        current_user, user_id, limit, include_live=False, all_users=False
    )
    return {"conversations": conversations}


@router.get("/{session_id}/messages")
async def get_conversation_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """获取单个会话的全部消息（按时间正序）。

    归属校验：普通用户只能读自己的会话；admin / agent 可读任意会话。
    """
    try:
        data = get_session_messages(session_id, current_user, limit)
    except PermissionError:
        raise HTTPException(status_code=403, detail="无权访问此会话")
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        )
    return data


@router.delete("/{session_id}")
async def delete_conversation(
    session_id: str,
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """删除会话及其全部消息（仅 admin / agent；同时从内存与 DB 删除）。"""
    ok = delete_session(session_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        )
    return {"success": True, "session_id": session_id}
