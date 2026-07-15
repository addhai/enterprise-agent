"""监控端点 — 暴露效果评估指标 + Prometheus 原生 /metrics

提供 HTTP API 供前端/运维查看实时指标：
    GET /api/v1/metrics/prometheus     — Prometheus text format (被 K8s 抓取)
    GET /api/v1/metrics/business        — 业务指标
    GET /api/v1/metrics/quality         — 质量指标
    GET /api/v1/metrics/risk            — 风险指标
    GET /api/v1/metrics/system          — 系统指标
    GET /api/v1/metrics/all             — 完整报告
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Response

try:
    from src.evaluation.tracker import get_evaluation_tracker
except ImportError:
    get_evaluation_tracker = None  # type: ignore

from src.api.metrics import render_metrics

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/metrics", tags=["monitoring"])


@router.get("/prometheus")
async def prometheus_metrics():
    """Prometheus text format /metrics 端点（K8s prometheus.io 注解抓取此路径）"""
    return Response(content=render_metrics(), media_type="text/plain; charset=utf-8")


@router.get("/all")
async def get_all_metrics():
    """获取完整的评估报告"""
    if get_evaluation_tracker is None:
        return {"error": "evaluation tracker not available"}
    tracker = get_evaluation_tracker()
    return tracker.stats()


@router.get("/business")
async def get_business_metrics():
    """业务指标"""
    if get_evaluation_tracker is None:
        return {
            "total_requests": 0,
            "resolved": 0,
            "unresolved": 0,
            "resolution_rate": 0,
            "escalation_rate": 0,
            "avg_turns": 0,
        }
    tracker = get_evaluation_tracker()
    stats = tracker.stats()
    return {
        "total_requests": stats.get("total_requests", 0),
        "resolved": stats.get("resolved", 0),
        "unresolved": stats.get("unresolved", 0),
        "resolution_rate": stats.get("resolution_rate", 0),
        "escalation_rate": stats.get("escalation_rate", 0),
        "avg_turns": stats.get("avg_turns", 0),
    }


@router.get("/quality")
async def get_quality_metrics():
    """质量指标"""
    if get_evaluation_tracker is None:
        return {"error": "not available"}
    tracker = get_evaluation_tracker()
    stats = tracker.stats()
    return {
        "avg_quality_score": stats.get("avg_quality_score", 0),
    }


@router.get("/risk")
async def get_risk_metrics():
    """风险指标"""
    return {"hallucination_checks": 0, "hallucination_rate": 0}


@router.get("/system")
async def get_system_metrics():
    """系统指标"""
    return {"status": "ok"}
