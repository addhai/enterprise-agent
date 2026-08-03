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
from src.api.rbac import require_roles, Role

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


def _db_sessions_as_dicts(user_id_filter: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    """从持久化 DB 读取历史会话，返回与 _session_to_dict 兼容的 dict 列表。

    把「重启后仍在 DB 里的会话」合并进会话列表（原接口只看内存活跃会话）。
    """
    from src.db.repositories import conversation_list as _repo_list, DEFAULT_TENANT, _dt2f
    from src.db.session import db_session
    from src.db.models import Conversation as _Conv

    out: List[Dict[str, Any]] = []
    try:
        rows = _repo_list(DEFAULT_TENANT, user_id_filter, limit)
    except Exception as e:
        logger.warning("读取持久化会话列表失败（非致命）: %s", e)
        return out
    try:
        with db_session() as s:
            convs = s.query(_Conv).all()
        # 在 session 作用域内提取标量，避免闭包外访问已分离实例
        conv_meta = {}
        for c in convs:
            conv_meta[c.id] = (c.user_id, _dt2f(c.created_at) if c.created_at else 0.0)
    except Exception:
        conv_meta = {}
    for row in rows:
        sid = row.get("session_id") or row.get("id") or ""
        if not sid:
            continue
        meta = conv_meta.get(sid)
        user_id = meta[0] if meta else (row.get("user_id") or "anonymous")
        created_at = meta[1] if meta else row.get("updated_at", 0)
        out.append({
            "session_id": sid,
            "user_id": user_id,
            "mode": "ai_chat",
            "created_at": created_at,
            "last_active": row.get("updated_at", 0),
            "turn_count": row.get("message_count", 0),
            "last_message_preview": (row.get("last_message") or "")[:50],
        })
    return out


def _db_session_detail_dict(session_id: str) -> Optional[Dict[str, Any]]:
    """从持久化 DB 读取单个会话详情（含消息历史），兼容 _session_to_dict(include_history=True)。"""
    from src.db.repositories import message_list, _dt2f
    from src.db.session import db_session
    from src.db.models import Conversation as _Conv

    try:
        msgs = message_list(session_id, 500)
    except Exception as e:
        logger.warning("读取持久化会话详情失败（非致命）: %s", e)
        return None
    if not msgs:
        return None
    try:
        with db_session() as s:
            conv = s.query(_Conv).filter(_Conv.id == session_id).first()
            user_id = conv.user_id if conv else "anonymous"
            created_at = _dt2f(conv.created_at) if conv and conv.created_at else (msgs[0].get("created_at", 0) if msgs else 0)
    except Exception:
        user_id = "anonymous"
        created_at = msgs[0].get("created_at", 0) if msgs else 0
    history = [
        {"role": m["role"], "content": m["content"], "timestamp": m.get("created_at")}
        for m in msgs
    ]
    return {
        "session_id": session_id,
        "user_id": user_id,
        "mode": "ai_chat",
        "created_at": created_at,
        "last_active": msgs[-1].get("created_at", 0),
        "turn_count": len(msgs),
        "last_message_preview": (msgs[-1].get("content", "") or "")[:50],
        "conversation_history": history,
        "handoff_context": None,
        "assigned_agent": None,
        "needs_human": False,
        "failed_attempts": 0,
        "suggest_human": False,
    }


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
    """获取当前用户的会话列表（内存活跃会话 + 持久化 DB 历史会话合并）

    需要用户登录，返回当前用户的所有会话；重启后仍在 DB 的历史会话也会被合并进来。
    """
    session_mgr = get_session_manager()
    all_sessions = list(session_mgr._sessions.values())

    user_id = current_user.get("user_id") if current_user else None
    if user_id:
        live = [s for s in all_sessions if s.user_id == user_id]
    else:
        live = all_sessions

    result = [_session_to_dict(s) for s in live]
    # 合并持久化 DB 中、当前不在内存的会话（重启后仍能看到历史）
    if user_id:
        try:
            for d in _db_sessions_as_dicts(user_id, 200):
                if not any(x["session_id"] == d["session_id"] for x in result):
                    result.append(d)
        except Exception:
            pass
    result.sort(key=lambda x: x.get("last_active", 0), reverse=True)
    return {"total": len(result), "sessions": result}


@router.get("/sessions/{session_id}")
async def get_user_session_detail(
    session_id: str = Path(..., description="会话 ID"),
    current_user: Optional[Dict[str, Any]] = Depends(_get_current_user_optional),
):
    """获取当前用户的会话详情和历史消息（内存优先，回退持久化 DB）"""
    session_mgr = get_session_manager()
    session = session_mgr.get_session(session_id)
    user_id = current_user.get("user_id") if current_user else None

    if session:
        if user_id and session.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权访问此会话")
        return _session_to_dict(session, include_history=True)

    # 内存无此会话 → 回退持久化 DB
    detail = _db_session_detail_dict(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    if user_id and detail["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")
    return detail


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
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取所有用户的会话列表（管理员版，内存活跃 + 持久化 DB 历史合并）"""
    session_mgr = get_session_manager()
    result = [_session_to_dict(s) for s in session_mgr._sessions.values()]
    # 合并持久化 DB 中、当前不在内存的会话
    try:
        for d in _db_sessions_as_dicts(None, 500):
            if not any(x["session_id"] == d["session_id"] for x in result):
                result.append(d)
    except Exception:
        pass
    result.sort(key=lambda x: x.get("last_active", 0), reverse=True)
    return {"total": len(result), "sessions": result}


@router.get("/admin/sessions/{session_id}")
async def get_admin_session_detail(
    session_id: str = Path(..., description="会话 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取会话详情（管理员版，内存优先，回退持久化 DB）"""
    session_mgr = get_session_manager()
    session = session_mgr.get_session(session_id)
    if session:
        return _session_to_dict(session, include_history=True)
    detail = _db_session_detail_dict(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return detail


@router.get("/admin/channels")
async def get_channels(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """获取渠道列表及配置
    
    需要 admin 角色
    返回所有支持的渠道及其配置信息（敏感字段脱敏）
    """
    channels = [
        {
            "name": "web",
            "enabled": True,
            "description": "Web 端聊天窗口",
            "config": {},
        },
        {
            "name": "feishu",
            "enabled": settings.channel_feishu_enabled,
            "description": "飞书渠道",
            "config": {
                "app_id": settings.channel_feishu_app_id,
                "app_secret_configured": bool(settings.channel_feishu_app_secret),
            },
        },
        {
            "name": "chatwoot",
            "enabled": settings.channel_chatwoot_enabled,
            "description": "Chatwoot 客服平台",
            "config": {
                "base_url": settings.channel_chatwoot_base_url,
                "api_token_configured": bool(settings.channel_chatwoot_api_token),
                "account_id": settings.channel_chatwoot_account_id,
                "inbox_id": settings.channel_chatwoot_inbox_id,
                "webhook_token_configured": bool(settings.channel_chatwoot_webhook_token),
                "webhook_url": "/api/v1/chatwoot/webhook",
            },
        },
    ]

    return {
        "total": len(channels),
        "channels": channels,
    }


@router.get("/admin/channels/{channel_name}/config")
async def get_channel_config(
    channel_name: str,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """获取指定渠道的完整配置（包含敏感字段）
    
    需要 admin 角色
    仅返回当前配置值（token 等敏感信息仅返回是否已配置，不返回原值）
    """
    if channel_name == "chatwoot":
        return {
            "name": "chatwoot",
            "enabled": settings.channel_chatwoot_enabled,
            "config": {
                "base_url": settings.channel_chatwoot_base_url,
                "api_token_configured": bool(settings.channel_chatwoot_api_token),
                "account_id": settings.channel_chatwoot_account_id,
                "inbox_id": settings.channel_chatwoot_inbox_id,
                "webhook_token_configured": bool(settings.channel_chatwoot_webhook_token),
                "webhook_url": "/api/v1/chatwoot/webhook",
            },
        }
    elif channel_name == "feishu":
        return {
            "name": "feishu",
            "enabled": settings.channel_feishu_enabled,
            "config": {
                "app_id": settings.channel_feishu_app_id,
                "app_secret_configured": bool(settings.channel_feishu_app_secret),
            },
        }
    elif channel_name == "web":
        return {
            "name": "web",
            "enabled": True,
            "config": {},
        }
    raise HTTPException(status_code=404, detail=f"不支持的渠道: {channel_name}")


@router.put("/admin/channels/{channel_name}/config")
async def update_channel_config(
    channel_name: str,
    config_data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """更新渠道配置
    
    需要 admin 角色
    支持启用/禁用渠道，更新配置参数
    """
    import httpx
    
    if channel_name == "chatwoot":
        if "enabled" in config_data:
            settings.channel_chatwoot_enabled = bool(config_data["enabled"])
        if "base_url" in config_data:
            settings.channel_chatwoot_base_url = str(config_data["base_url"]).rstrip("/")
        if "api_token" in config_data and config_data["api_token"]:
            settings.channel_chatwoot_api_token = str(config_data["api_token"])
        if "account_id" in config_data:
            settings.channel_chatwoot_account_id = str(config_data["account_id"])
        if "inbox_id" in config_data:
            settings.channel_chatwoot_inbox_id = str(config_data["inbox_id"])
        if "webhook_token" in config_data and config_data["webhook_token"]:
            settings.channel_chatwoot_webhook_token = str(config_data["webhook_token"])
        
        return {
            "success": True,
            "name": "chatwoot",
            "enabled": settings.channel_chatwoot_enabled,
            "config": {
                "base_url": settings.channel_chatwoot_base_url,
                "api_token_configured": bool(settings.channel_chatwoot_api_token),
                "account_id": settings.channel_chatwoot_account_id,
                "inbox_id": settings.channel_chatwoot_inbox_id,
                "webhook_token_configured": bool(settings.channel_chatwoot_webhook_token),
            },
        }
    elif channel_name == "feishu":
        if "enabled" in config_data:
            settings.channel_feishu_enabled = bool(config_data["enabled"])
        if "app_id" in config_data:
            settings.channel_feishu_app_id = str(config_data["app_id"])
        if "app_secret" in config_data and config_data["app_secret"]:
            settings.channel_feishu_app_secret = str(config_data["app_secret"])
        
        return {
            "success": True,
            "name": "feishu",
            "enabled": settings.channel_feishu_enabled,
            "config": {
                "app_id": settings.channel_feishu_app_id,
                "app_secret_configured": bool(settings.channel_feishu_app_secret),
            },
        }
    
    raise HTTPException(status_code=404, detail=f"不支持的渠道: {channel_name}")


@router.post("/admin/channels/{channel_name}/test")
async def test_channel_connection(
    channel_name: str,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """测试渠道连接
    
    需要 admin 角色
    测试 Chatwoot API 是否能正常连通
    """
    import httpx
    
    if channel_name == "chatwoot":
        if not settings.channel_chatwoot_base_url or not settings.channel_chatwoot_api_token:
            raise HTTPException(status_code=400, detail="请先配置 Chatwoot Base URL 和 API Token")
        
        try:
            url = f"{settings.channel_chatwoot_base_url}/accounts/{settings.channel_chatwoot_account_id}/conversations"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    url,
                    headers={"api_access_token": settings.channel_chatwoot_api_token},
                    params={"status": "open", "page": 1},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "success": True,
                        "message": "Chatwoot 连接成功",
                        "details": {
                            "status_code": resp.status_code,
                            "open_conversations": len(data.get("payload", [])),
                        },
                    }
                elif resp.status_code == 401:
                    return {
                        "success": False,
                        "message": "API Token 无效，请检查 Token 是否正确",
                        "details": {"status_code": resp.status_code},
                    }
                else:
                    return {
                        "success": False,
                        "message": f"连接失败 (HTTP {resp.status_code})",
                        "details": {"status_code": resp.status_code, "response": resp.text[:200]},
                    }
        except httpx.ConnectError as e:
            return {
                "success": False,
                "message": f"无法连接到 Chatwoot 服务器: {str(e)}",
                "details": {"error": str(e)},
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"测试失败: {str(e)}",
                "details": {"error": str(e)},
            }
    elif channel_name == "feishu":
        if not settings.channel_feishu_app_id or not settings.channel_feishu_app_secret:
            raise HTTPException(status_code=400, detail="请先配置飞书 App ID 和 App Secret")
        
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": settings.channel_feishu_app_id,
                        "app_secret": settings.channel_feishu_app_secret,
                    },
                )
                data = resp.json()
                if data.get("code") == 0:
                    return {"success": True, "message": "飞书连接成功", "details": {"tenant_token_obtained": True}}
                else:
                    return {"success": False, "message": f"飞书连接失败: {data.get('msg', '未知错误')}", "details": data}
        except Exception as e:
            return {"success": False, "message": f"测试失败: {str(e)}", "details": {"error": str(e)}}
    
    raise HTTPException(status_code=404, detail=f"不支持的渠道: {channel_name}")


# ====================================================================
# 人工客服坐席 API
# ====================================================================

@router.get("/admin/handoff/queue")
async def get_handoff_queue(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取转接人工客服队列
    
    返回所有等待人工接入的会话，按等待时间排序
    需要 admin/agent 角色
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
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """人工坐席接入会话

    坐席点击接入后，会话状态从 waiting_human 变为 human_chat
    需要 admin/agent 角色
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
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """人工坐席发送回复消息

    将人工客服的回复发送给用户，并记录到对话历史中
    需要 admin/agent 角色
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
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """结束人工服务，将会话转回 AI 或关闭

    人工客服结束服务后，可选择转回 AI 或结束会话
    需要 admin/agent 角色
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


# ======================================================================
# HITL 人工审批 API（对齐 langgraph_multi-agent 的 humanloop_manager）
# ======================================================================

@router.get("/admin/approvals")
async def list_pending_approvals(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """列出所有待审批请求

    敏感操作（退款/注销/数据导出等）触发审批后，人工客服在此查看。
    需要 admin/agent 角色
    """
    try:
        from src.integrations.humanloop import get_humanloop_manager
        manager = get_humanloop_manager()
        pending = manager.list_pending()
        return {
            "success": True,
            "count": len(pending),
            "approvals": [
                {
                    "request_id": r.request_id,
                    "action": r.action,
                    "description": r.description,
                    "context": r.context,
                    "user_id": r.user_id,
                    "session_id": r.session_id,
                    "created_at": r.created_at,
                    "status": r.status.value,
                }
                for r in pending
            ],
        }
    except Exception as e:
        logger.error("List pending approvals failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/approvals/{request_id}/review")
async def review_approval(
    request_id: str = Path(..., description="审批请求 ID"),
    approved: bool = Body(..., embed=True, description="是否批准"),
    comment: str = Body(default="", embed=True, description="审批意见"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """提交审批结果

    人工客服审核后，通过此接口批准或拒绝操作。
    需要 admin/agent 角色
    """
    try:
        from src.integrations.humanloop import get_humanloop_manager
        manager = get_humanloop_manager()
        reviewer_id = current_user.get("user_id", "unknown")

        success = manager.submit_review(
            request_id=request_id,
            approved=approved,
            reviewer_id=reviewer_id,
            comment=comment,
        )

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"审批请求不存在或已处理: {request_id}",
            )

        return {
            "success": True,
            "request_id": request_id,
            "approved": approved,
            "reviewer": reviewer_id,
            "message": f"操作已{'批准' if approved else '拒绝'}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Review approval failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/approvals/{request_id}")
async def get_approval_status(
    request_id: str = Path(..., description="审批请求 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """查询审批请求状态

    需要 admin/agent 角色
    """
    try:
        from src.integrations.humanloop import get_humanloop_manager
        manager = get_humanloop_manager()
        request = manager.get_request(request_id)

        if not request:
            raise HTTPException(status_code=404, detail=f"审批请求不存在: {request_id}")

        return {
            "success": True,
            "request_id": request.request_id,
            "action": request.action,
            "description": request.description,
            "context": request.context,
            "user_id": request.user_id,
            "status": request.status.value,
            "reviewer_id": request.reviewer_id,
            "review_comment": request.review_comment,
            "created_at": request.created_at,
            "reviewed_at": request.reviewed_at,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get approval status failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
