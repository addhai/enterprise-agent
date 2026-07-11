"""监控端点 — 暴露效果评估指标

提供 HTTP API 供前端/运维查看实时指标：
    GET /api/v1/metrics/business     — 业务指标
    GET /api/v1/metrics/quality      — 质量指标
    GET /api/v1/metrics/risk         — 风险指标
    GET /api/v1/metrics/system       — 系统指标
    GET /api/v1/metrics/all          — 完整报告
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter

from src.evaluation.tracker import get_evaluation_tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/metrics", tags=["monitoring"])


@router.get("/all")
async def get_all_metrics():
    """获取完整的评估报告"""
    tracker = get_evaluation_tracker()
    return tracker.get_report()


@router.get("/business")
async def get_business_metrics():
    """业务指标：自主解决率、转人工率、平均轮数"""
    tracker = get_evaluation_tracker()
    return {
        "total_requests": tracker._counters.get("total_requests", 0),
        "resolved": tracker._counters.get("resolved", 0),
        "unresolved": tracker._counters.get("unresolved", 0),
        "resolution_rate": round(tracker.resolution_rate, 4),
        "escalation_rate": round(tracker.escalation_rate, 4),
        "avg_turns": round(tracker.avg_turns, 2),
    }


@router.get("/quality")
async def get_quality_metrics():
    """质量指标：平均质量分"""
    tracker = get_evaluation_tracker()
    return {
        "avg_quality_score": round(tracker.avg_quality_score, 4),
        "total_evaluated": len(tracker._quality_buf),
    }


@router.get("/risk")
async def get_risk_metrics():
    """风险指标：幻觉率"""
    tracker = get_evaluation_tracker()
    return {
        "hallucination_checks": tracker._counters.get("hallucination_checks", 0),
        "hallucinations_detected": tracker._counters.get("hallucinations_detected", 0),
        "hallucination_rate": round(tracker.hallucination_rate, 4),
    }


@router.get("/system")
async def get_system_metrics():
    """系统指标：工具调用成功率"""
    tracker = get_evaluation_tracker()
    return {
        "tool_success_rate": round(tracker.tool_success_rate, 4),
        "tool_calls_total": sum(
            v for k, v in tracker._counters.items() if k.startswith("tool_calls:")
        ),
    }
