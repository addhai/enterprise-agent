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
    """风险指标

    当前基于评估追踪器的真实运行数据派生：
      - escalation_rate：转人工 / 升级率（越高代表自助解决越差）
      - low_quality_rate：低质量回复占比（quality_score < 0.5）
      - unresolved_rate：未解决会话占比
      - hallucinations_detected / hallucinations_blocked：
        reflect_node 的 check_hallucination 检测计数 / output_guard 拦截计数
    """
    if get_evaluation_tracker is None:
        return {
            "escalation_rate": 0,
            "low_quality_rate": 0,
            "unresolved_rate": 0,
            "tracked_sessions": 0,
            "instrumented": False,
        }
    tracker = get_evaluation_tracker()
    stats = tracker.stats()
    total = stats.get("total_requests", 0)
    # 低质量：最近 100 条里 quality_score 非空且 < 0.5 的比例
    low_quality_rate = 0.0
    try:
        recent = [r for r in tracker._records[-100:] if r.get("quality_score") is not None]
        if recent:
            low = sum(1 for r in recent if r["quality_score"] < 0.5)
            low_quality_rate = low / len(recent)
    except Exception:
        low_quality_rate = 0.0
    return {
        "escalation_rate": round(stats.get("escalation_rate", 0), 4),
        "low_quality_rate": round(low_quality_rate, 4),
        "unresolved_rate": round(
            1 - stats.get("resolution_rate", 0), 4
        ) if stats.get("resolution_rate") is not None else 0.0,
        "avg_quality_score": round(stats.get("avg_quality_score", 0), 4),
        "tracked_sessions": stats.get("total_sessions", 0),
        "total_requests": total,
        "prompt_injections_blocked": stats.get("prompt_injections_blocked", 0),
        "safety_violations": stats.get("safety_violations", 0),
        "hallucinations_detected": stats.get("hallucinations_detected", 0),
        "hallucinations_blocked": stats.get("hallucinations_blocked", 0),
        "safety_events": stats.get("safety_events", {}),
        "instrumented": True,
    }


@router.get("/system")
async def get_system_metrics():
    """系统指标 — 真实运行时健康数据

    包含：服务运行时长、数据库可达性与后端类型、CPU / 内存占用（psutil 可选）、
    活跃 WebSocket 会话与在线坐席数。
    """
    import os

    metrics: dict = {"status": "ok"}

    # 运行时长（来自评估追踪器单例，与服务同生命周期）
    if get_evaluation_tracker is not None:
        try:
            metrics["uptime_seconds"] = round(
                get_evaluation_tracker().stats().get("uptime_seconds", 0), 1
            )
        except Exception:
            metrics["uptime_seconds"] = 0

    # 数据库健康 + 后端类型
    db_info: dict = {"reachable": False, "backend": "unknown"}
    try:
        from src.db.engine import get_engine
        engine = get_engine()
        db_info["backend"] = str(engine.url).split(":")[0]
        with engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("SELECT 1"))
        db_info["reachable"] = True
    except Exception as e:
        db_info["reachable"] = False
        db_info["error"] = str(e)[:120]
    metrics["database"] = db_info

    # CPU / 内存（psutil 可选，缺失则跳过）
    try:
        import psutil
        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        vm = psutil.virtual_memory()
        metrics["memory_percent"] = vm.percent
        metrics["memory_used_mb"] = round(vm.used / (1024 * 1024), 1)
        metrics["memory_total_mb"] = round(vm.total / (1024 * 1024), 1)
    except Exception:
        metrics["cpu_percent"] = None
        metrics["memory_percent"] = None

    # 活跃 WebSocket 会话 + 在线坐席
    try:
        from src.websocket.session_manager import get_session_manager
        stats = get_session_manager().get_stats()
        metrics["active_sessions"] = stats.get("total_sessions", 0)
        metrics["online_agents"] = stats.get("online_agents", 0)
        metrics["sessions_by_mode"] = stats.get("sessions_by_mode", {})
    except Exception:
        metrics["active_sessions"] = None
        metrics["online_agents"] = None

    metrics["pid"] = os.getpid()
    return metrics
