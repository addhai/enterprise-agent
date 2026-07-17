"""满意度调查 API — CSAT/NPS 评分收集与统计

在会话结束后或人工服务结束时，向用户推送满意度评价。
支持 1-5 星评分、标签、文字留言。
"""
import os
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.api.rbac import get_current_user, require_permissions, Permission

logger = logging.getLogger(__name__)
router = APIRouter(tags=["satisfaction"])


# ====================================================================
# 内存数据存储
# ====================================================================

_satisfaction_records: List[Dict[str, Any]] = []
_records_lock = threading.Lock()


# ====================================================================
# Pydantic 模型
# ====================================================================

class SubmitSatisfactionRequest(BaseModel):
    """提交满意度评价"""
    session_id: str = Field(..., description="会话ID")
    user_id: str = Field(..., description="用户ID")
    score: int = Field(..., ge=1, le=5, description="1-5星评分")
    tags: List[str] = Field(default_factory=list, description="评价标签，如[解决问题, 响应慢]")
    comment: str = Field(default="", max_length=500, description="文字评价")
    agent_id: Optional[str] = Field(None, description="人工客服ID（如有）")


class SatisfactionStats(BaseModel):
    """满意度统计"""
    total: int = 0
    average_score: float = 0.0
    csat_rate: float = 0.0   # 4-5星占比
    distribution: Dict[str, int] = Field(default_factory=lambda: {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0})
    recent_trend: List[Dict[str, Any]] = Field(default_factory=list)


# ====================================================================
# API 路由
# ====================================================================

@router.get("/satisfaction")
async def list_satisfaction(
    user_id: Optional[str] = Query(None, description="按用户筛选"),
    session_id: Optional[str] = Query(None, description="按会话筛选"),
    agent_id: Optional[str] = Query(None, description="按客服筛选"),
    limit: int = Query(50, ge=1, le=200),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.SATISFACTION_VIEW)),
):
    """获取满意度评价列表"""
    with _records_lock:
        records = list(_satisfaction_records)

    if user_id:
        records = [r for r in records if r["user_id"] == user_id]
    if session_id:
        records = [r for r in records if r["session_id"] == session_id]
    if agent_id:
        records = [r for r in records if r.get("agent_id") == agent_id]

    records.sort(key=lambda r: r["created_at"], reverse=True)
    return {"total": len(records), "records": records[:limit]}


@router.post("/satisfaction")
async def submit_satisfaction(request: SubmitSatisfactionRequest):
    """提交满意度评价（公开接口，无需登录）"""
    if not 1 <= request.score <= 5:
        raise HTTPException(status_code=400, detail="评分必须在 1-5 之间")

    record = {
        "id": f"SAT-{int(time.time() * 1000)}",
        "session_id": request.session_id,
        "user_id": request.user_id,
        "score": request.score,
        "tags": list(set(request.tags)),
        "comment": request.comment,
        "agent_id": request.agent_id,
        "created_at": time.time(),
    }

    with _records_lock:
        _satisfaction_records.append(record)

    logger.info("Satisfaction submitted: session=%s user=%s score=%s", request.session_id, request.user_id, request.score)

    # 触发通知
    try:
        from src.api.notifications import add_notification
        level = "success" if request.score >= 4 else "warning" if request.score == 3 else "error"
        add_notification(
            type="satisfaction",
            level=level,
            title=f"满意度评价 {request.score} 星",
            message=f"用户 {request.user_id} 对会话 {request.session_id[:8]} 评价 {request.score} 星",
            target_roles=["super_admin", "admin"],
        )
    except Exception as e:
        logger.warning("Failed to send satisfaction notification: %s", e)

    return {"success": True, "record": record}


@router.get("/satisfaction/stats")
async def get_satisfaction_stats(
    days: int = Query(7, ge=1, le=90, description="统计最近 N 天"),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.SATISFACTION_VIEW)),
):
    """获取满意度统计"""
    cutoff = time.time() - days * 24 * 3600
    with _records_lock:
        records = [r for r in _satisfaction_records if r["created_at"] >= cutoff]

    stats = SatisfactionStats(total=len(records))
    if records:
        scores = [r["score"] for r in records]
        stats.average_score = round(sum(scores) / len(scores), 2)
        stats.csat_rate = round(sum(1 for s in scores if s >= 4) / len(scores) * 100, 2)
        for s in scores:
            stats.distribution[str(s)] += 1

    # 近 N 天趋势
    from collections import defaultdict
    daily = defaultdict(list)
    for r in records:
        day = datetime.fromtimestamp(r["created_at"]).strftime("%m-%d")
        daily[day].append(r["score"])

    sorted_days = sorted(daily.keys())
    stats.recent_trend = [
        {"date": d, "avg_score": round(sum(daily[d]) / len(daily[d]), 2), "count": len(daily[d])}
        for d in sorted_days
    ]

    return stats.dict()


@router.get("/satisfaction/agent/{agent_id}/stats")
async def get_agent_satisfaction_stats(
    agent_id: str,
    days: int = Query(7, ge=1, le=90),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.SATISFACTION_VIEW)),
):
    """获取指定客服的满意度统计"""
    cutoff = time.time() - days * 24 * 3600
    with _records_lock:
        records = [r for r in _satisfaction_records if r.get("agent_id") == agent_id and r["created_at"] >= cutoff]

    if not records:
        return {"agent_id": agent_id, "total": 0, "average_score": 0, "csat_rate": 0}

    scores = [r["score"] for r in records]
    return {
        "agent_id": agent_id,
        "total": len(records),
        "average_score": round(sum(scores) / len(scores), 2),
        "csat_rate": round(sum(1 for s in scores if s >= 4) / len(scores) * 100, 2),
    }


# ====================================================================
# 公共函数（供其他模块调用）
# ====================================================================

def create_satisfaction_invite(session_id: str, user_id: str, agent_id: Optional[str] = None) -> Dict[str, Any]:
    """创建满意度评价邀请（由会话关闭/人工服务结束时调用）"""
    return {
        "invite_id": f"INV-{int(time.time() * 1000)}",
        "session_id": session_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "created_at": time.time(),
        "message": "请问您对本次服务是否满意？",
    }
