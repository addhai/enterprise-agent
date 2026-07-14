"""评估追踪器 — 对话质量评估与在线抽样

供 monitoring.py 引用。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class EvaluationTracker:
    """评估追踪器 — 记录对话评估指标

    供 api/monitoring.py 的 /metrics 端点读取。
    """

    def __init__(self):
        self._records: list = []
        self._start_time = time.time()

    def record_chat(
        self,
        session_id: str,
        intent: str,
        latency_ms: float,
        quality_score: Optional[float] = None,
        needs_human: bool = False,
    ):
        self._records.append({
            "session_id": session_id,
            "intent": intent,
            "latency_ms": latency_ms,
            "quality_score": quality_score,
            "needs_human": needs_human,
            "timestamp": time.time(),
        })

    def stats(self) -> Dict[str, Any]:
        """返回汇总统计"""
        total = len(self._records)
        if total == 0:
            return {"total_requests": 0}

        latencies = [r["latency_ms"] for r in self._records[-100:]]
        scores = [r["quality_score"] for r in self._records[-100:] if r["quality_score"] is not None]
        human_rate = sum(1 for r in self._records[-100:] if r["needs_human"]) / min(total, 100)

        return {
            "total_requests": total,
            "uptime_seconds": time.time() - self._start_time,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "avg_quality_score": sum(scores) / len(scores) if scores else 0,
            "escalation_rate": human_rate,
        }


# ---- 全局单例 ----
_tracker: Optional[EvaluationTracker] = None


def get_evaluation_tracker() -> EvaluationTracker:
    global _tracker
    if _tracker is None:
        _tracker = EvaluationTracker()
    return _tracker
