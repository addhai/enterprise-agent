"""客户管理 API — 客户画像、标签、服务历史

客户数据来自会话中的 user_id，通过聚合会话、工单、满意度记录生成 360° 画像。
"""
import os
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.api.rbac import get_current_user, require_permissions, Permission

logger = logging.getLogger(__name__)
router = APIRouter(tags=["customers"])


# ====================================================================
# 内存数据存储
# ====================================================================

_customers: Dict[str, Dict[str, Any]] = {}
_customer_tags: Dict[str, List[str]] = {}


# ====================================================================
# Pydantic 模型
# ====================================================================

class CustomerTagUpdateRequest(BaseModel):
    """客户标签更新请求"""
    tags: List[str] = Field(default_factory=list, description="标签列表")


class CustomerNoteUpdateRequest(BaseModel):
    """客户备注更新请求"""
    note: str = Field(..., description="备注内容")


class Customer(BaseModel):
    """客户画像"""
    user_id: str
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    plan: str = "free"
    status: str = "active"
    tags: List[str] = Field(default_factory=list)
    note: str = ""
    first_seen_at: float
    last_seen_at: float
    session_count: int = 0
    ticket_count: int = 0
    satisfaction_score: Optional[float] = None
    satisfaction_count: int = 0
    total_messages: int = 0


# ====================================================================
# 辅助函数
# ====================================================================

def _ensure_customer(user_id: str, username: Optional[str] = None) -> Dict[str, Any]:
    """确保客户记录存在，不存在则初始化"""
    if user_id not in _customers:
        now = time.time()
        display_name = username or user_id[:8]
        _customers[user_id] = {
            "user_id": user_id,
            "username": display_name,
            "email": None,
            "phone": None,
            "company": None,
            "plan": "free",
            "status": "active",
            "tags": [],
            "note": "",
            "first_seen_at": now,
            "last_seen_at": now,
            "session_count": 0,
            "ticket_count": 0,
            "satisfaction_score": None,
            "satisfaction_count": 0,
            "total_messages": 0,
        }
    return _customers[user_id]


def _customer_to_dict(c: Dict[str, Any]) -> Dict[str, Any]:
    """将客户记录转为可序列化字典"""
    return dict(c)


def _refresh_customer_stats(user_id: str):
    """刷新客户统计（从会话和工单聚合）"""
    c = _ensure_customer(user_id)

    # 从 WebSocket 会话管理器聚合会话数据
    try:
        from src.websocket.session_manager import get_session_manager
        mgr = get_session_manager()
        sessions = [s for s in mgr._sessions.values() if s.user_id == user_id]
        c["session_count"] = len(sessions)
        if sessions:
            c["last_seen_at"] = max(s.last_active for s in sessions)
            c["first_seen_at"] = min(s.created_at for s in sessions)
            c["total_messages"] = sum(len(s.conversation_history) for s in sessions)
            # 尝试从会话中提取用户名/计划
            for s in sessions:
                if s.user_id == user_id:
                    # 从 user_profile 或上下文获取 plan
                    if s.handoff_context and s.handoff_context.get("user_profile"):
                        profile = s.handoff_context["user_profile"]
                        c["plan"] = profile.get("plan", c["plan"])
                        c["company"] = profile.get("company", c["company"])
                    break
    except Exception as e:
        logger.warning("Failed to refresh session stats for %s: %s", user_id, e)

    # 从工单存储聚合工单数
    try:
        from src.ticket.store import get_default_store
        from src.ticket.models import TicketListFilter
        store = get_default_store()
        tickets = store.list(TicketListFilter(user_id=user_id, limit=1000))
        c["ticket_count"] = len(tickets)
    except Exception as e:
        logger.warning("Failed to refresh ticket stats for %s: %s", user_id, e)

    # 从满意度存储聚合评分
    try:
        from src.api.satisfaction import _satisfaction_records
        records = [r for r in _satisfaction_records if r["user_id"] == user_id]
        if records:
            scores = [r["score"] for r in records]
            c["satisfaction_score"] = round(sum(scores) / len(scores), 2)
            c["satisfaction_count"] = len(records)
    except Exception as e:
        logger.warning("Failed to refresh satisfaction stats for %s: %s", user_id, e)


# ====================================================================
# API 路由
# ====================================================================

@router.get("/customers")
async def list_customers(
    search: Optional[str] = Query(None, description="搜索用户名/user_id"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    plan: Optional[str] = Query(None, description="按计划筛选"),
    tag: Optional[str] = Query(None, description="按标签筛选"),
    limit: int = Query(50, ge=1, le=200),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CUSTOMER_VIEW)),
):
    """获取客户列表"""
    # 先刷新所有已知客户的统计
    for user_id in list(_customers.keys()):
        _refresh_customer_stats(user_id)

    # 也尝试从会话中发掘新客户
    try:
        from src.websocket.session_manager import get_session_manager
        mgr = get_session_manager()
        for s in mgr._sessions.values():
            _ensure_customer(s.user_id)
            _refresh_customer_stats(s.user_id)
    except Exception as e:
        logger.warning("Failed to scan sessions for customers: %s", e)

    results = list(_customers.values())

    if search:
        s = search.lower()
        results = [
            c for c in results
            if s in c["user_id"].lower() or s in c["username"].lower()
            or (c.get("email") and s in c["email"].lower())
            or (c.get("company") and s in c["company"].lower())
        ]
    if status:
        results = [c for c in results if c.get("status") == status]
    if plan:
        results = [c for c in results if c.get("plan") == plan]
    if tag:
        results = [c for c in results if tag in c.get("tags", [])]

    # 按最后活跃时间倒序
    results.sort(key=lambda c: c.get("last_seen_at", 0), reverse=True)

    return {
        "total": len(results),
        "customers": [_customer_to_dict(c) for c in results[:limit]],
    }


@router.get("/customers/{user_id}")
async def get_customer_detail(
    user_id: str,
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CUSTOMER_VIEW)),
):
    """获取客户详情及服务历史"""
    _refresh_customer_stats(user_id)
    c = _ensure_customer(user_id)

    # 会话历史
    sessions = []
    try:
        from src.websocket.session_manager import get_session_manager
        mgr = get_session_manager()
        sessions = [
            {
                "session_id": s.session_id,
                "mode": s.mode.value,
                "created_at": s.created_at,
                "last_active": s.last_active,
                "turn_count": s.turn_count,
                "last_message_preview": _last_message_preview(s.conversation_history),
            }
            for s in mgr._sessions.values() if s.user_id == user_id
        ]
        sessions.sort(key=lambda x: x["last_active"], reverse=True)
    except Exception as e:
        logger.warning("Failed to get sessions for customer %s: %s", user_id, e)

    # 工单历史
    tickets = []
    try:
        from src.ticket.store import get_default_store
        from src.ticket.models import TicketListFilter
        store = get_default_store()
        tickets = [t.dict() for t in store.list(TicketListFilter(user_id=user_id, limit=100))]
    except Exception as e:
        logger.warning("Failed to get tickets for customer %s: %s", user_id, e)

    # 满意度记录
    satisfaction = []
    try:
        from src.api.satisfaction import _satisfaction_records
        satisfaction = [r for r in _satisfaction_records if r["user_id"] == user_id]
        satisfaction.sort(key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        logger.warning("Failed to get satisfaction for customer %s: %s", user_id, e)

    return {
        "customer": _customer_to_dict(c),
        "sessions": sessions,
        "tickets": tickets,
        "satisfaction": satisfaction,
    }


@router.put("/customers/{user_id}/tags")
async def update_customer_tags(
    user_id: str,
    request: CustomerTagUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CUSTOMER_MANAGE)),
):
    """更新客户标签"""
    c = _ensure_customer(user_id)
    c["tags"] = list(set(request.tags))
    return {"success": True, "user_id": user_id, "tags": c["tags"]}


@router.put("/customers/{user_id}/note")
async def update_customer_note(
    user_id: str,
    request: CustomerNoteUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CUSTOMER_MANAGE)),
):
    """更新客户备注"""
    c = _ensure_customer(user_id)
    c["note"] = request.note
    return {"success": True, "user_id": user_id, "note": c["note"]}


@router.put("/customers/{user_id}/status")
async def update_customer_status(
    user_id: str,
    status: str = Query(..., description="状态"),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CUSTOMER_MANAGE)),
):
    """更新客户状态"""
    if status not in ("active", "inactive", "suspended"):
        raise HTTPException(status_code=400, detail="无效的状态")
    c = _ensure_customer(user_id)
    c["status"] = status
    return {"success": True, "user_id": user_id, "status": status}


@router.get("/customers/{user_id}/timeline")
async def get_customer_timeline(
    user_id: str,
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CUSTOMER_VIEW)),
):
    """获取客户时间线"""
    events = []

    # 会话事件
    try:
        from src.websocket.session_manager import get_session_manager
        mgr = get_session_manager()
        for s in mgr._sessions.values():
            if s.user_id == user_id:
                events.append({
                    "type": "session",
                    "title": "发起会话",
                    "time": s.created_at,
                    "detail": f"会话 {s.session_id[:8]}...",
                })
    except Exception:
        pass

    # 工单事件
    try:
        from src.ticket.store import get_default_store
        from src.ticket.models import TicketListFilter
        store = get_default_store()
        for t in store.list(TicketListFilter(user_id=user_id, limit=100)):
            events.append({
                "type": "ticket",
                "title": f"工单 {t.status}",
                "time": t.created_at.timestamp(),
                "detail": t.title,
            })
    except Exception:
        pass

    # 满意度事件
    try:
        from src.api.satisfaction import _satisfaction_records
        for r in _satisfaction_records:
            if r["user_id"] == user_id:
                events.append({
                    "type": "satisfaction",
                    "title": f"满意度评价 {r['score']} 星",
                    "time": r["created_at"],
                    "detail": r.get("comment", ""),
                })
    except Exception:
        pass

    events.sort(key=lambda x: x["time"], reverse=True)
    return {"total": len(events), "events": events[:50]}


# ====================================================================
# 辅助函数
# ====================================================================

def _last_message_preview(history: list, max_length: int = 50) -> str:
    if not history:
        return ""
    content = history[-1].get("content", "")
    if len(content) > max_length:
        return content[:max_length] + "..."
    return content


def touch_customer(user_id: str, username: Optional[str] = None):
    """外部调用：当有新会话时更新客户活跃时间"""
    c = _ensure_customer(user_id)
    c["last_seen_at"] = time.time()
    if username:
        c["username"] = username
