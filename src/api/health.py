"""
Agent 健康检查 REST API

端点:
    GET  /api/v1/health/agents           — 列出所有 Agent 健康状态
    GET  /api/v1/health/agents/{agent_id} — 查看单个 Agent 状态
    POST /api/v1/health/agents/{agent_id}/heartbeat — 手动上报心跳
    POST /api/v1/health/agents/{agent_id}/circuit/reset — 重置熔断器
    GET  /api/v1/health/stats             — 健康检查 + 熔断器统计
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


def _get_checker():
    """获取 HealthChecker 单例"""
    try:
        from src.protocols.health_checker import get_health_checker
        return get_health_checker()
    except Exception as e:
        logger.error("Failed to get health checker: %s", e)
        raise HTTPException(status_code=500, detail=f"health checker unavailable: {e}")


def _get_registry():
    from src.protocols.agent_registry import registry
    return registry


@router.get("/agents")
async def list_agent_health():
    """列出所有 Agent 的健康状态"""
    checker = _get_checker()
    return checker.get_status()


@router.get("/agents/{agent_id}")
async def get_agent_health(agent_id: str):
    """查看单个 Agent 的健康状态"""
    registry = _get_registry()
    entry = registry.get(agent_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")

    checker = _get_checker()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return {
        "agent_id": entry.agent_id,
        "name": entry.name,
        "url": entry.url,
        "status": entry.status,
        "last_heartbeat": entry.last_heartbeat.isoformat(),
        "last_heartbeat_age_sec": int((now - entry.last_heartbeat).total_seconds()),
        "circuit_state": checker.circuit_breaker.state(agent_id),
        "failures": checker.circuit_breaker._failures.get(agent_id, 0),
        "registered_at": entry.registered_at.isoformat(),
    }


@router.post("/agents/{agent_id}/heartbeat")
async def report_heartbeat(agent_id: str):
    """手动上报心跳（Agent 启动时调用，或运维触发）"""
    registry = _get_registry()
    ok = registry.heartbeat(agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not registered")
    return {"agent_id": agent_id, "status": "online", "message": "heartbeat updated"}


@router.post("/agents/{agent_id}/circuit/reset")
async def reset_circuit(agent_id: str):
    """重置某个 Agent 的熔断器"""
    checker = _get_checker()
    checker.circuit_breaker.reset(agent_id)
    return {"agent_id": agent_id, "circuit_state": "closed", "message": "circuit reset"}


@router.get("/stats")
async def health_stats():
    """健康检查 + 熔断器综合统计"""
    checker = _get_checker()
    registry = _get_registry()
    registry_stats = registry.get_stats()
    return {
        "registry": registry_stats,
        "circuit_breakers": checker.circuit_breaker.stats(),
        "checker_config": {
            "threshold_seconds": int(checker.threshold.total_seconds()),
            "scan_interval_seconds": checker.scan_interval,
            "probe_enabled": checker.probe_enabled,
            "probe_interval_seconds": checker.probe_interval,
        },
    }
