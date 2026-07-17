"""数据仪表盘 API — 核心业务指标统计

提供实时/近实时 KPI：会话量、AI 解决率、人工介入率、工单统计、满意度、活跃客户等。
"""
import os
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from collections import defaultdict
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.api.rbac import require_roles, Role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])


# ====================================================================
# API 路由
# ====================================================================

@router.get("/dashboard/kpi")
async def get_dashboard_kpi(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT, Role.VIEWER, Role.SUPERVISOR)),
):
    """获取仪表盘核心 KPI"""
    now = time.time()
    day_ago = now - 24 * 3600
    week_ago = now - 7 * 24 * 3600

    # 会话统计
    total_sessions = 0
    active_sessions = 0
    waiting_human = 0
    human_chat = 0
    ai_resolved = 0
    total_turns = 0
    sessions_today = 0
    sessions_week = []

    try:
        from src.websocket.session_manager import get_session_manager, SessionMode
        mgr = get_session_manager()
        sessions = list(mgr._sessions.values())
        total_sessions = len(sessions)

        for s in sessions:
            if s.last_active >= day_ago:
                active_sessions += 1
                sessions_today += 1
            if s.mode == SessionMode.WAITING_HUMAN:
                waiting_human += 1
            if s.mode == SessionMode.HUMAN_CHAT:
                human_chat += 1
            if not s.needs_human and s.turn_count > 0:
                ai_resolved += 1
            total_turns += s.turn_count

        # 近 7 天每日会话量
        daily = defaultdict(int)
        for s in sessions:
            if s.created_at >= week_ago:
                day = datetime.fromtimestamp(s.created_at).strftime("%m-%d")
                daily[day] += 1
        sessions_week = [{"date": d, "count": c} for d, c in sorted(daily.items())]
    except Exception as e:
        logger.warning("Failed to aggregate session stats: %s", e)

    # 工单统计
    ticket_stats = {"total": 0, "open": 0, "in_progress": 0, "unassigned": 0, "urgent": 0}
    try:
        from src.ticket.store import get_default_store
        from src.ticket.models import TicketListFilter, TicketPriority, TicketStatus
        store = get_default_store()
        tickets = store.list(TicketListFilter(tenant_id="default", limit=10000))
        ticket_stats["total"] = len(tickets)
        ticket_stats["open"] = sum(1 for t in tickets if t.status == TicketStatus.OPEN)
        ticket_stats["in_progress"] = sum(1 for t in tickets if t.status == TicketStatus.IN_PROGRESS)
        ticket_stats["unassigned"] = sum(1 for t in tickets if not t.assignee)
        ticket_stats["urgent"] = sum(1 for t in tickets if t.priority == TicketPriority.URGENT)
    except Exception as e:
        logger.warning("Failed to aggregate ticket stats: %s", e)

    # 满意度统计
    satisfaction = {"avg_score": 0, "csat_rate": 0, "total": 0}
    try:
        from src.api.satisfaction import _satisfaction_records
        records = [r for r in _satisfaction_records if r["created_at"] >= week_ago]
        if records:
            scores = [r["score"] for r in records]
            satisfaction["avg_score"] = round(sum(scores) / len(scores), 2)
            satisfaction["csat_rate"] = round(sum(1 for s in scores if s >= 4) / len(scores) * 100, 2)
            satisfaction["total"] = len(records)
    except Exception as e:
        logger.warning("Failed to aggregate satisfaction stats: %s", e)

    # 客户统计
    customer_stats = {"total": 0, "active_today": 0}
    try:
        from src.api.customers import _customers
        customers = list(_customers.values())
        customer_stats["total"] = len(customers)
        customer_stats["active_today"] = sum(1 for c in customers if c.get("last_seen_at", 0) >= day_ago)
    except Exception as e:
        logger.warning("Failed to aggregate customer stats: %s", e)

    # AI 解决率
    ai_resolution_rate = round(ai_resolved / total_sessions * 100, 2) if total_sessions > 0 else 0
    avg_turns = round(total_turns / total_sessions, 2) if total_sessions > 0 else 0

    return {
        "sessions": {
            "total": total_sessions,
            "active_today": active_sessions,
            "today_new": sessions_today,
            "waiting_human": waiting_human,
            "human_chat": human_chat,
            "ai_resolution_rate": ai_resolution_rate,
            "avg_turns": avg_turns,
        },
        "tickets": ticket_stats,
        "satisfaction": satisfaction,
        "customers": customer_stats,
        "sessions_week": sessions_week,
    }


@router.get("/dashboard/realtime")
async def get_realtime_activity(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT, Role.VIEWER, Role.SUPERVISOR)),
):
    """获取实时活动（最近会话、等待接入队列）"""
    try:
        from src.websocket.session_manager import get_session_manager, SessionMode
        mgr = get_session_manager()
        sessions = list(mgr._sessions.values())

        # 最近活跃的会话
        recent = sorted(sessions, key=lambda s: s.last_active, reverse=True)[:10]
        recent_sessions = []
        for s in recent:
            preview = ""
            if s.conversation_history:
                preview = s.conversation_history[-1].get("content", "")[:40]
            recent_sessions.append({
                "session_id": s.session_id,
                "user_id": s.user_id,
                "mode": s.mode.value,
                "last_active": s.last_active,
                "turn_count": s.turn_count,
                "preview": preview,
            })

        # 等待人工接入
        now = time.time()
        waiting = [
            {
                "session_id": s.session_id,
                "user_id": s.user_id,
                "wait_time": int(now - s.last_active),
                "last_message_preview": s.conversation_history[-1].get("content", "")[:50] if s.conversation_history else "",
            }
            for s in sessions if s.mode == SessionMode.WAITING_HUMAN
        ]
        waiting.sort(key=lambda x: x["wait_time"], reverse=True)

        return {
            "recent_sessions": recent_sessions,
            "waiting_queue": waiting[:20],
            "waiting_count": len(waiting),
        }
    except Exception as e:
        logger.warning("Failed to get realtime activity: %s", e)
        return {"recent_sessions": [], "waiting_queue": [], "waiting_count": 0}


@router.get("/dashboard/agent-performance")
async def get_agent_performance(
    days: int = 7,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT, Role.VIEWER, Role.SUPERVISOR)),
):
    """获取客服绩效排行"""
    cutoff = time.time() - days * 24 * 3600

    agents = {}
    try:
        from src.websocket.session_manager import get_session_manager, SessionMode
        mgr = get_session_manager()
        for s in mgr._sessions.values():
            if s.assigned_agent and s.last_active >= cutoff:
                if s.assigned_agent not in agents:
                    agents[s.assigned_agent] = {
                        "agent_id": s.assigned_agent,
                        "sessions": 0,
                        "messages": 0,
                        "avg_score": 0,
                    }
                agents[s.assigned_agent]["sessions"] += 1
                agents[s.assigned_agent]["messages"] += len(s.conversation_history)
    except Exception as e:
        logger.warning("Failed to aggregate agent sessions: %s", e)

    # 满意度
    try:
        from src.api.satisfaction import _satisfaction_records
        for r in _satisfaction_records:
            if r.get("agent_id") and r["created_at"] >= cutoff:
                agent_id = r["agent_id"]
                if agent_id not in agents:
                    agents[agent_id] = {"agent_id": agent_id, "sessions": 0, "messages": 0, "avg_score": 0}
                if "scores" not in agents[agent_id]:
                    agents[agent_id]["scores"] = []
                agents[agent_id]["scores"].append(r["score"])

        for a in agents.values():
            scores = a.pop("scores", [])
            if scores:
                a["avg_score"] = round(sum(scores) / len(scores), 2)
                a["satisfaction_count"] = len(scores)
            else:
                a["avg_score"] = 0
                a["satisfaction_count"] = 0
    except Exception as e:
        logger.warning("Failed to aggregate agent satisfaction: %s", e)

    result = sorted(agents.values(), key=lambda x: x["sessions"], reverse=True)
    return {"agents": result[:10]}


@router.get("/dashboard/intent-distribution")
async def get_intent_distribution(
    days: int = 7,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT, Role.VIEWER, Role.SUPERVISOR)),
):
    """获取用户意图分布"""
    cutoff = time.time() - days * 24 * 3600
    distribution = defaultdict(int)
    try:
        from src.websocket.session_manager import get_session_manager
        mgr = get_session_manager()
        for s in mgr._sessions.values():
            if s.created_at >= cutoff and s.handoff_context:
                intent = s.handoff_context.get("intent") or "unknown"
                distribution[intent] += 1
    except Exception as e:
        logger.warning("Failed to aggregate intent distribution: %s", e)

    return {
        "intents": [
            {"name": k, "value": v}
            for k, v in sorted(distribution.items(), key=lambda x: x[1], reverse=True)
        ]
    }
