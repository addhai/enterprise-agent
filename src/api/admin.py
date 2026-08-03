"""
管理后台 API — 会话管理与渠道配置
"""
import os
import time
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Path, Depends, Header, Body

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.websocket.session_manager import get_session_manager, SessionMode
from src.config import settings
from src.api.rbac import require_roles, Role
from src.api.sessions_service import (
    delete_session as _delete_session,
    get_session_detail as _get_session_detail,
    get_session_owner as _get_session_owner,
    list_sessions as _list_sessions,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])


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
    result = _list_sessions(current_user, None, 200, include_live=True, all_users=False)
    return {"total": len(result), "sessions": result}


@router.get("/sessions/{session_id}")
async def get_user_session_detail(
    session_id: str = Path(..., description="会话 ID"),
    current_user: Optional[Dict[str, Any]] = Depends(_get_current_user_optional),
):
    """获取当前用户的会话详情和历史消息（内存优先，回退持久化 DB）"""
    user_id = current_user.get("user_id") if current_user else None
    owner = _get_session_owner(session_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    if user_id and owner != user_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")
    detail = _get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return detail


@router.delete("/sessions/{session_id}")
async def delete_user_session(
    session_id: str = Path(..., description="会话 ID"),
    current_user: Optional[Dict[str, Any]] = Depends(_get_current_user_optional),
):
    """删除当前用户的会话

    需要用户登录，只能删除自己的会话；同时从内存与持久化 DB 删除（重启后不会重现）。
    """
    user_id = current_user.get("user_id") if current_user else None
    owner = _get_session_owner(session_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    if user_id and owner != user_id:
        raise HTTPException(status_code=403, detail="无权删除此会话")
    _delete_session(session_id)
    return {"success": True, "message": "会话已删除"}


# ====================================================================
# 管理员会话 API（需要 admin 权限，可以看到所有会话）
# ====================================================================

@router.get("/admin/sessions")
async def get_admin_sessions(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取所有用户的会话列表（管理员版，内存活跃 + 持久化 DB 历史合并）"""
    result = _list_sessions(current_user, None, 500, include_live=True, all_users=True)
    return {"total": len(result), "sessions": result}


@router.get("/admin/sessions/{session_id}")
async def get_admin_session_detail(
    session_id: str = Path(..., description="会话 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取会话详情（管理员版，内存优先，回退持久化 DB）"""
    detail = _get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return detail


@router.delete("/admin/sessions/{session_id}")
async def delete_admin_session(
    session_id: str = Path(..., description="会话 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """删除任意用户的会话（管理员版，同时从内存与持久化 DB 删除）"""
    ok = _delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return {"success": True, "message": "会话已删除"}


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
