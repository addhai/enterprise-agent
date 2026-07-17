"""
管理后台 API — 会话管理与渠道配置
"""
import os
import time
import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Path, Depends, Header, Body

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.websocket.session_manager import get_session_manager, SessionMode
from src.config import settings
from src.api.rbac import require_permissions, Permission

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])


def _get_last_message_preview(conversation_history: list, max_length: int = 50) -> str:
    """获取最后一条消息的预览"""
    if not conversation_history:
        return ""
    last_msg = conversation_history[-1]
    content = last_msg.get("content", "")
    if len(content) > max_length:
        return content[:max_length] + "..."
    return content


def _session_to_dict(session, include_history: bool = False) -> Dict[str, Any]:
    """将会话状态转换为可序列化的字典"""
    result = {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "mode": session.mode.value,
        "created_at": session.created_at,
        "last_active": session.last_active,
        "turn_count": session.turn_count,
        "last_message_preview": _get_last_message_preview(session.conversation_history),
    }
    if include_history:
        result["conversation_history"] = session.conversation_history
        result["handoff_context"] = session.handoff_context
        result["assigned_agent"] = session.assigned_agent
        result["needs_human"] = session.needs_human
        result["failed_attempts"] = session.failed_attempts
        result["suggest_human"] = session.suggest_human
    return result


def _get_current_user_optional(authorization: Optional[str] = Header(None)) -> Optional[Dict[str, Any]]:
    """可选的用户认证（未登录也能访问，但会过滤会话）"""
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    try:
        from src.api.auth import _get_user_by_token
        return _get_user_by_token(token)
    except Exception:
        return None


# ====================================================================
# 普通用户会话 API（需要登录，只能看到自己的会话）
# ====================================================================

@router.get("/sessions")
async def get_user_sessions(current_user: Optional[Dict[str, Any]] = Depends(_get_current_user_optional)):
    """获取当前用户的会话列表
    
    需要用户登录，返回当前用户的所有会话
    返回：session_id, created_at, last_active, turn_count, 最后一条消息预览
    """
    session_mgr = get_session_manager()
    all_sessions = list(session_mgr._sessions.values())
    
    # 如果有当前用户，只返回该用户的会话
    user_id = current_user.get("user_id") if current_user else None
    if user_id:
        sessions = [s for s in all_sessions if s.user_id == user_id]
    else:
        sessions = all_sessions
    
    return {
        "total": len(sessions),
        "sessions": [_session_to_dict(s) for s in sessions],
    }


@router.get("/sessions/{session_id}")
async def get_user_session_detail(
    session_id: str = Path(..., description="会话 ID"),
    current_user: Optional[Dict[str, Any]] = Depends(_get_current_user_optional),
):
    """获取当前用户的会话详情和历史消息
    
    需要用户登录，只能查看自己的会话
    """
    session_mgr = get_session_manager()
    session = session_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    
    # 如果有当前用户，检查是否是自己的会话
    user_id = current_user.get("user_id") if current_user else None
    if user_id and session.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")
    
    return _session_to_dict(session, include_history=True)


@router.delete("/sessions/{session_id}")
async def delete_user_session(
    session_id: str = Path(..., description="会话 ID"),
    current_user: Optional[Dict[str, Any]] = Depends(_get_current_user_optional),
):
    """删除当前用户的会话
    
    需要用户登录，只能删除自己的会话
    """
    session_mgr = get_session_manager()
    session = session_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    
    # 如果有当前用户，检查是否是自己的会话
    user_id = current_user.get("user_id") if current_user else None
    if user_id and session.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权删除此会话")
    
    success = session_mgr.remove_session(session_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除会话失败")
    
    return {"success": True, "message": "会话已删除"}


# ====================================================================
# 管理员会话 API（需要 admin 权限，可以看到所有会话）
# ====================================================================

@router.get("/admin/sessions")
async def get_admin_sessions(
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.AGENT_WORKSPACE))
):
    """获取所有用户的会话列表（管理员版）
    
    需要 admin/agent 权限
    """
    session_mgr = get_session_manager()
    sessions = session_mgr._sessions.values()
    return {
        "total": len(list(sessions)),
        "sessions": [_session_to_dict(s) for s in sessions],
    }


@router.get("/admin/sessions/{session_id}")
async def get_admin_session_detail(
    session_id: str = Path(..., description="会话 ID"),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.AGENT_WORKSPACE)),
):
    """获取会话详情（管理员版）
    
    包含会话基本信息和完整的历史消息
    需要 admin/agent 权限
    """
    session_mgr = get_session_manager()
    session = session_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    
    return _session_to_dict(session, include_history=True)


@router.get("/admin/channels")
async def get_channels(
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CHANNEL_VIEW))
):
    """获取已启用的渠道列表
    
    web 渠道始终启用，feishu 渠道根据配置决定
    """
    channels = [
        {
            "name": "web",
            "enabled": True,
            "description": "Web 端聊天窗口",
        }
    ]

    if settings.mcp_feishu_enabled:
        channels.append({
            "name": "feishu",
            "enabled": True,
            "description": "飞书渠道",
        })

    return {
        "total": len(channels),
        "channels": channels,
    }


# ====================================================================
# 人工客服坐席 API
# ====================================================================

@router.get("/admin/handoff/queue")
async def get_handoff_queue(
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.AGENT_WORKSPACE))
):
    """获取转接人工客服队列
    
    返回所有等待人工接入的会话，按等待时间排序
    """
    session_mgr = get_session_manager()
    all_sessions = list(session_mgr._sessions.values())
    
    waiting_sessions = [
        s for s in all_sessions 
        if s.mode in (SessionMode.WAITING_HUMAN, SessionMode.HUMAN_CHAT)
    ]
    
    waiting_sessions.sort(key=lambda s: s.last_active)
    
    return {
        "total": len(waiting_sessions),
        "queue": [
            {
                "session_id": s.session_id,
                "user_id": s.user_id,
                "mode": s.mode.value,
                "created_at": s.created_at,
                "last_active": s.last_active,
                "turn_count": s.turn_count,
                "last_message_preview": _get_last_message_preview(s.conversation_history),
                "handoff_context": s.handoff_context,
                "assigned_agent": s.assigned_agent,
                "wait_time": int(time.time() - s.last_active) if s.mode == SessionMode.WAITING_HUMAN else 0,
            }
            for s in waiting_sessions
        ],
    }


@router.post("/admin/handoff/{session_id}/accept")
async def accept_handoff(
    session_id: str = Path(..., description="会话 ID"),
    agent_id: str = Body(default="admin", embed=True),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.AGENT_WORKSPACE)),
):
    """人工坐席接入会话

    坐席点击接入后，会话状态从 waiting_human 变为 human_chat
    """
    session_mgr = get_session_manager()
    session = session_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

    if session.mode not in (SessionMode.WAITING_HUMAN, SessionMode.HUMAN_CHAT):
        raise HTTPException(status_code=400, detail="该会话未请求人工服务")

    session_mgr.assign_agent_to_session(session_id, agent_id)

    # 触发通知
    try:
        from src.api.notifications import add_notification
        add_notification(
            type="handoff",
            level="info",
            title="人工坐席已接入",
            message=f"坐席 {agent_id} 已接入用户 {session.user_id[:12]} 的会话",
            target_roles=["super_admin", "admin"],
        )
    except Exception as e:
        logger.warning("Failed to send handoff accept notification: %s", e)

    return {
        "success": True,
        "message": "已接入会话",
        "session": _session_to_dict(session, include_history=True),
    }


@router.post("/admin/handoff/{session_id}/reply")
async def agent_reply(
    session_id: str = Path(..., description="会话 ID"),
    message: str = Body(..., embed=True),
    agent_id: str = Body(default="admin", embed=True),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.AGENT_WORKSPACE)),
):
    """人工坐席发送回复消息

    将人工客服的回复发送给用户，并记录到对话历史中
    """
    session_mgr = get_session_manager()
    session = session_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

    if session.mode != SessionMode.HUMAN_CHAT:
        raise HTTPException(status_code=400, detail="该会话未处于人工对话状态")
    
    now = time.time()
    
    session.conversation_history.append({
        "role": "assistant",
        "content": message,
        "timestamp": now,
        "is_human_agent": True,
        "agent_id": agent_id,
    })
    
    session.last_active = now
    session.turn_count += 1
    
    if session._websocket_ref and hasattr(session._websocket_ref, 'send_json'):
        try:
            await session._websocket_ref.send_json({
                "type": "human_agent_message",
                "session_id": session_id,
                "agent_id": agent_id,
                "content": message,
                "timestamp": now,
            })
        except Exception as e:
            logger.warning(f"Failed to push agent reply to session {session_id}: {e}")
    
    return {
        "success": True,
        "message": "回复已发送",
    }


@router.post("/admin/handoff/{session_id}/close")
async def close_handoff(
    session_id: str = Path(..., description="会话 ID"),
    agent_id: str = Body(default="admin", embed=True),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.AGENT_WORKSPACE)),
):
    """结束人工服务，将会话转回 AI 或关闭

    人工客服结束服务后，可选择转回 AI 或结束会话
    """
    session_mgr = get_session_manager()
    session = session_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

    session_mgr.update_mode(session_id, SessionMode.AI_CHAT)
    session.assigned_agent = None

    now = time.time()
    session.conversation_history.append({
        "role": "system",
        "content": "人工客服已结束服务，将由 AI 继续为您服务。请问您对本次服务是否满意？",
        "timestamp": now,
    })

    # 触发满意度评价邀请通知
    try:
        from src.api.satisfaction import create_satisfaction_invite
        invite = create_satisfaction_invite(session_id, session.user_id, agent_id)
    except Exception as e:
        logger.warning("Failed to create satisfaction invite: %s", e)

    return {
        "success": True,
        "message": "已结束人工服务",
    }
