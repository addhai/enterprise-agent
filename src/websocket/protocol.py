"""消息协议定义

WebSocket 通信使用统一的 JSON 消息格式，区分消息类型（type）：

客户端 → 服务端：
    chat_message      — 用户发送聊天消息
    heartbeat         — 心跳保活
    ack               — 确认收到消息
    agent_login       — 人工坐席登录
    agent_send_reply  — 坐席回复用户
    agent_logout      — 坐席登出

服务端 → 客户端（用户）：
    streaming_chunk   — 流式输出片段
    typing_indicator  — 打字指示器
    session_ready     — 会话就绪
    transfer_notice   — 转接通知
    handoff_context   — 转接上下文（用户不可见，内部用）
    error             — 错误
    heartbeat_ack     — 心跳响应

服务端 → 人工坐席：
    new_transfer      — 新转接通知
    session_update    — 会话状态变更
    agent_chat_message — 用户发送给坐席的消息
    agent_chat_reply  — 坐席回复确认
    copilot_suggestion — AI 建议回复
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ====================================================================
# 消息类型常量
# ====================================================================

# 客户端 → 服务端
TYPE_CLIENT_CHAT = "chat_message"
TYPE_CLIENT_HEARTBEAT = "heartbeat"
TYPE_CLIENT_ACK = "ack"
TYPE_AGENT_LOGIN = "agent_login"
TYPE_AGENT_SEND_REPLY = "agent_send_reply"
TYPE_AGENT_LOGOUT = "agent_logout"

# 服务端 → 用户客户端
TYPE_STREAMING_CHUNK = "streaming_chunk"
TYPE_TYPING_INDICATOR = "typing_indicator"
TYPE_SESSION_READY = "session_ready"
TYPE_TRANSFER_NOTICE = "transfer_notice"
TYPE_HANDOFF_CONTEXT = "handoff_context"
TYPE_ERROR = "error"
TYPE_HEARTBEAT_ACK = "heartbeat_ack"

# 服务端 → 人工坐席
TYPE_NEW_TRANSFER = "new_transfer"
TYPE_SESSION_UPDATE = "session_update"
TYPE_AGENT_CHAT_MESSAGE = "agent_chat_message"
TYPE_AGENT_CHAT_REPLY = "agent_chat_reply"
TYPE_COPILOT_SUGGESTION = "copilot_suggestion"


# ====================================================================
# 消息构建工具
# ====================================================================

def build_client_message(msg_type: str, **kwargs) -> Dict[str, Any]:
    """构建客户端发出的消息"""
    return {
        "type": msg_type,
        "timestamp": time.time(),
        **kwargs,
    }


def build_server_message(msg_type: str, session_id: str = "", **kwargs) -> Dict[str, Any]:
    """构建服务端发出的消息"""
    return {
        "type": msg_type,
        "session_id": session_id,
        "timestamp": time.time(),
        **kwargs,
    }


def build_streaming_chunk(
    session_id: str,
    text: str,
    done: bool = False,
    delta: Optional[str] = None,
    suggest_human: bool = False,
) -> Dict[str, Any]:
    """构建流式输出片段"""
    return build_server_message(
        TYPE_STREAMING_CHUNK,
        session_id=session_id,
        text=text,
        done=done,
        delta=delta or text,
        suggest_human=suggest_human,
    )


def build_typing_indicator(session_id: str, is_typing: bool = True, status: str = "") -> Dict[str, Any]:
    """构建打字指示器"""
    msg = build_server_message(
        TYPE_TYPING_INDICATOR,
        session_id=session_id,
        is_typing=is_typing,
    )
    if status:
        msg["status"] = status
    return msg


def build_transfer_notice(
    session_id: str,
    reason: str = "",
    estimated_wait: int = 30,
) -> Dict[str, Any]:
    """构建转接通知"""
    return build_server_message(
        TYPE_TRANSFER_NOTICE,
        session_id=session_id,
        reason=reason,
        estimated_wait_seconds=estimated_wait,
        message="正在为您转接人工客服，请稍候...",
    )


def build_handoff_context(
    session_id: str,
    summary: str,
    conversation: list,
    user_profile: dict,
    attempted_solutions: list,
    quality_score: Optional[float] = None,
) -> Dict[str, Any]:
    """构建转接上下文包"""
    return build_server_message(
        TYPE_HANDOFF_CONTEXT,
        session_id=session_id,
        summary=summary,
        conversation=conversation,
        user_profile=user_profile,
        attempted_solutions=attempted_solutions,
        quality_score=quality_score,
    )


def build_error(session_id: str, code: str, message: str) -> Dict[str, Any]:
    """构建错误消息"""
    return build_server_message(
        TYPE_ERROR,
        session_id=session_id,
        error_code=code,
        error_message=message,
    )


def build_new_transfer(
    transfer_id: str,
    session_id: str,
    user_id: str,
    summary: str,
    conversation: list,
    user_profile: dict,
    urgency: str = "normal",  # low / normal / high / critical
) -> Dict[str, Any]:
    """构建新转接通知（发给人工坐席）"""
    return {
        "type": TYPE_NEW_TRANSFER,
        "transfer_id": transfer_id,
        "session_id": session_id,
        "user_id": user_id,
        "summary": summary,
        "conversation": conversation,
        "user_profile": user_profile,
        "urgency": urgency,
        "timestamp": time.time(),
    }


def build_session_update(
    session_id: str,
    mode: str,
    assigned_agent: Optional[str] = None,
    **extra,
) -> Dict[str, Any]:
    """构建会话状态更新"""
    return build_server_message(
        TYPE_SESSION_UPDATE,
        session_id=session_id,
        mode=mode,
        assigned_agent=assigned_agent,
        **extra,
    )


def build_copilot_suggestion(
    session_id: str,
    suggestions: List[str],
    confidence_scores: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """构建 AI 建议回复（Copilot 模式）"""
    return {
        "type": TYPE_COPILOT_SUGGESTION,
        "session_id": session_id,
        "suggestions": suggestions,
        "confidence": confidence_scores or [0.8] * len(suggestions),
        "timestamp": time.time(),
    }
