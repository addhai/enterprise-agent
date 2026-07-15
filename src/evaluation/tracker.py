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
        self._sessions: Dict[str, dict] = {}
        self._start_time = time.time()

    def record_chat(
        self,
        session_id: str,
        intent: str,
        latency_ms: float,
        quality_score: Optional[float] = None,
        needs_human: bool = False,
        suggest_human: bool = False,
        turn_count: int = 1,
        resolved: Optional[bool] = None,
    ):
        """记录单轮对话"""
        self._records.append({
            "session_id": session_id,
            "intent": intent,
            "latency_ms": latency_ms,
            "quality_score": quality_score,
            "needs_human": needs_human,
            "suggest_human": suggest_human,
            "turn_count": turn_count,
            "resolved": resolved,
            "timestamp": time.time(),
        })

        # 更新会话统计
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "total_turns": 0,
                "needs_human": False,
                "resolved": None,
                "start_time": time.time(),
            }
        sess = self._sessions[session_id]
        sess["total_turns"] += 1
        if needs_human:
            sess["needs_human"] = True
        if resolved is not None:
            sess["resolved"] = resolved

    def stats(self) -> Dict[str, Any]:
        """返回汇总统计"""
        total = len(self._records)
        if total == 0:
            return {
                "total_requests": 0,
                "resolved": 0,
                "unresolved": 0,
                "resolution_rate": 0,
                "escalation_rate": 0,
                "avg_turns": 0,
            }

        latencies = [r["latency_ms"] for r in self._records[-100:]]
        scores = [r["quality_score"] for r in self._records[-100:] if r["quality_score"] is not None]
        human_count = sum(1 for r in self._records[-100:] if r["needs_human"])
        human_rate = human_count / min(total, 100)

        # 会话级统计
        total_sessions = len(self._sessions)
        resolved_sessions = sum(1 for s in self._sessions.values() if s.get("resolved") is True)
        unresolved_sessions = sum(1 for s in self._sessions.values() if s.get("resolved") is False or s.get("needs_human"))
        total_turns_all = sum(s["total_turns"] for s in self._sessions.values())
        avg_turns = total_turns_all / total_sessions if total_sessions > 0 else 0

        resolution_rate = resolved_sessions / total_sessions if total_sessions > 0 else 0

        return {
            "total_requests": total,
            "total_sessions": total_sessions,
            "resolved": resolved_sessions,
            "unresolved": unresolved_sessions,
            "resolution_rate": resolution_rate,
            "uptime_seconds": time.time() - self._start_time,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "avg_quality_score": sum(scores) / len(scores) if scores else 0,
            "escalation_rate": human_rate,
            "avg_turns": avg_turns,
        }


# ---- 全局单例 ----
_tracker: Optional[EvaluationTracker] = None


def get_evaluation_tracker() -> EvaluationTracker:
    global _tracker
    if _tracker is None:
        _tracker = EvaluationTracker()
    return _tracker
