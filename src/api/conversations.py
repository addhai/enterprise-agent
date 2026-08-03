"""会话历史查询 API

暴露已持久化的对话与消息，供前端"历史会话"列表 / 复盘使用。
鉴权：任意已登录用户（get_current_user）；user_id 过滤默认只看自己，
admin / agent 可传 ?user_id= 查看他人会话。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.api.rbac import get_current_user
from src.db.repositories import DEFAULT_TENANT, conversation_list, message_list

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
    requester_role = current_user.get("role", "viewer")
    requester_id = current_user.get("user_id", "")

    if user_id:
        # 仅 admin / agent 可越权查看
        if requester_role not in ("admin", "super_admin", "agent"):
            return {"conversations": []}
        target = user_id
    else:
        target = requester_id

    conversations = conversation_list(DEFAULT_TENANT, target, limit)
    return {"conversations": conversations}


@router.get("/{session_id}/messages")
async def get_conversation_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """获取单个会话的全部消息（按时间正序）。"""
    messages = message_list(session_id, limit)
    return {"session_id": session_id, "count": len(messages), "messages": messages}
