"""效果评估埋点系统

职责：
    记录所有维度的客服 Agent 指标，支持：
    1. 业务指标：自主解决率、转人工率、处理时长、单问题成本
    2. 质量指标：回答正确率、任务完成率、知识命中率
    3. 风险指标：幻觉率、错误承诺率、高风险漏转率
    4. 系统指标：工具调用成功率、响应时长、人工转接成功率

存储方式：
    - 内存缓冲区（每 100 条或 5 秒刷盘）
    - 文件持久化（JSON Lines 格式）
    - 可扩展到 PostgreSQL / Prometheus

使用方式：
    tracker = get_evaluation_tracker()
    tracker.track_resolution(session_id="s1", resolved=True, turns=2)
    tracker.track_escalation(session_id="s1", reason="low_confidence", urgency="high")
"""
from __future__ import annotations

import json
import logging
import os
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ====================================================================
# 指标数据结构
# ====================================================================

@dataclass
class ResolutionRecord:
    """自主解决记录"""
    session_id: str
    resolved: bool
    turns: int
    intent: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class EscalationRecord:
    """转人工记录"""
    session_id: str
    reason: str
    urgency: str
    turns: int
    sentiment: str = "neutral"
    timestamp: float = field(default_factory=time.time)


@dataclass
class HallucinationRecord:
    """幻觉检测记录"""
    session_id: str
    detected: bool
    details: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ToolCallRecord:
    """工具调用记录"""
    tool_name: str
    success: bool
    latency_ms: int
    error: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class QualityScoreRecord:
    """质量评分记录"""
    session_id: str
    score: float
    intent: str
    resolved: bool
    timestamp: float = field(default_factory=time.time)


# ====================================================================
# 评估跟踪器
# ====================================================================

class EvaluationTracker:
    """效果评估埋点跟踪器"""

    def __init__(self, log_dir: str = "./logs/evaluation"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓冲区
        self._resolution_buf: List[ResolutionRecord] = []
        self._escalation_buf: List[EscalationRecord] = []
        self._hallucination_buf: List[HallucinationRecord] = []
        self._tool_call_buf: List[ToolCallRecord] = []
        self._quality_buf: List[QualityScoreRecord] = []

        # 计数器（用于实时指标计算）
        self._counters = defaultdict(int)

        # 线程锁
        self._lock = threading.Lock()

        # 日志文件
        self._log_files = {}
        for name in ["resolution", "escalation", "hallucination", "tool_call", "quality"]:
            self._log_files[name] = open(
                self.log_dir / f"{name}.jsonl", "a", encoding="utf-8"
            )

    # ------------------------------------------------------------------
    # 业务指标
    # ------------------------------------------------------------------

    def track_resolution(self, session_id: str, resolved: bool, turns: int, intent: str = "unknown", model_tier: str = "medium"):
        """记录自主解决情况"""
        record = ResolutionRecord(
            session_id=session_id,
            resolved=resolved,
            turns=turns,
            intent=intent,
        )
        with self._lock:
            self._resolution_buf.append(record)
            self._counters["total_requests"] += 1
            self._counters[f"model_usage:{model_tier}"] += 1
            if resolved:
                self._counters["resolved"] += 1
            else:
                self._counters["unresolved"] += 1
        self._flush_buffer_if_needed("resolution")

    @property
    def resolution_rate(self) -> float:
        """自主解决率"""
        with self._lock:
            total = self._counters.get("total_requests", 0)
            if total == 0:
                return 0.0
            return self._counters["resolved"] / total

    @property
    def avg_turns(self) -> float:
        """平均处理轮数"""
        with self._lock:
            if not self._resolution_buf:
                return 0.0
            return sum(r.turns for r in self._resolution_buf) / len(self._resolution_buf)

    # ------------------------------------------------------------------
    # 转人工指标
    # ------------------------------------------------------------------

    def track_escalation(self, session_id: str, reason: str, urgency: str,
                         turns: int = 0, sentiment: str = "neutral"):
        """记录转人工情况"""
        record = EscalationRecord(
            session_id=session_id,
            reason=reason,
            urgency=urgency,
            turns=turns,
            sentiment=sentiment,
        )
        with self._lock:
            self._escalation_buf.append(record)
            self._counters["total_escalations"] += 1
        self._flush_buffer_if_needed("escalation")

    @property
    def escalation_rate(self) -> float:
        """转人工率"""
        with self._lock:
            total = self._counters.get("total_requests", 0)
            if total == 0:
                return 0.0
            return self._counters["total_escalations"] / total

    # ------------------------------------------------------------------
    # 风险指标
    # ------------------------------------------------------------------

    def track_hallucination(self, session_id: str, detected: bool, details: str = ""):
        """记录幻觉检测结果"""
        record = HallucinationRecord(
            session_id=session_id,
            detected=detected,
            details=details,
        )
        with self._lock:
            self._hallucination_buf.append(record)
            self._counters["hallucination_checks"] += 1
            if detected:
                self._counters["hallucinations_detected"] += 1
        self._flush_buffer_if_needed("hallucination")

    @property
    def hallucination_rate(self) -> float:
        """幻觉率"""
        with self._lock:
            checks = self._counters.get("hallucination_checks", 0)
            if checks == 0:
                return 0.0
            return self._counters["hallucinations_detected"] / checks

    # ------------------------------------------------------------------
    # 系统指标
    # ------------------------------------------------------------------

    def track_tool_call(self, tool_name: str, success: bool, latency_ms: int, error: str = ""):
        """记录工具调用情况"""
        record = ToolCallRecord(
            tool_name=tool_name,
            success=success,
            latency_ms=latency_ms,
            error=error,
        )
        with self._lock:
            self._tool_call_buf.append(record)
            self._counters[f"tool_calls:{tool_name}"] += 1
            if success:
                self._counters[f"tool_success:{tool_name}"] += 1
            else:
                self._counters[f"tool_fail:{tool_name}"] += 1
        self._flush_buffer_if_needed("tool_call")

    @property
    def tool_success_rate(self, tool_name: Optional[str] = None) -> float:
        """工具调用成功率"""
        with self._lock:
            if tool_name:
                total = self._counters.get(f"tool_calls:{tool_name}", 0)
                success = self._counters.get(f"tool_success:{tool_name}", 0)
            else:
                total = sum(
                    v for k, v in self._counters.items() if k.startswith("tool_calls:")
                )
                success = sum(
                    v for k, v in self._counters.items() if k.startswith("tool_success:")
                )
            if total == 0:
                return 0.0
            return success / total

    # ------------------------------------------------------------------
    # 质量指标
    # ------------------------------------------------------------------

    def track_quality_score(self, session_id: str, score: float, intent: str = "unknown",
                            resolved: bool = False):
        """记录质量评分"""
        record = QualityScoreRecord(
            session_id=session_id,
            score=score,
            intent=intent,
            resolved=resolved,
        )
        with self._lock:
            self._quality_buf.append(record)
        self._flush_buffer_if_needed("quality")

    @property
    def avg_quality_score(self) -> float:
        """平均质量分"""
        with self._lock:
            if not self._quality_buf:
                return 0.0
            return sum(r.score for r in self._quality_buf) / len(self._quality_buf)

    # ------------------------------------------------------------------
    # 统计报告
    # ------------------------------------------------------------------

    def get_report(self) -> Dict[str, Any]:
        """获取完整的评估报告"""
        # 模型使用情况
        model_usage = {}
        for k, v in self._counters.items():
            if k.startswith("model_usage:"):
                tier = k.split(":", 1)[1]
                model_usage[tier] = v

        return {
            # 业务指标
            "business": {
                "total_requests": self._counters.get("total_requests", 0),
                "resolved": self._counters.get("resolved", 0),
                "unresolved": self._counters.get("unresolved", 0),
                "resolution_rate": round(self.resolution_rate, 4),
                "avg_turns": round(self.avg_turns, 2),
                "escalation_rate": round(self.escalation_rate, 4),
            },
            # 质量指标
            "quality": {
                "avg_quality_score": round(self.avg_quality_score, 4),
                "total_evaluated": len(self._quality_buf),
            },
            # 风险指标
            "risk": {
                "hallucination_checks": self._counters.get("hallucination_checks", 0),
                "hallucinations_detected": self._counters.get("hallucinations_detected", 0),
                "hallucination_rate": round(self.hallucination_rate, 4),
            },
            # 系统指标
            "system": {
                "tool_success_rate": round(self.tool_success_rate, 4),
                "tool_calls_total": sum(
                    v for k, v in self._counters.items() if k.startswith("tool_calls:")
                ),
            },
            # 模型使用统计（多模型路由）
            "model_usage": model_usage,
            # 转接统计
            "escalation_breakdown": self._get_escalation_breakdown(),
        }

    def _get_escalation_breakdown(self) -> Dict[str, int]:
        """转接原因分解"""
        breakdown = defaultdict(int)
        with self._lock:
            for record in self._escalation_buf:
                breakdown[record.reason] += 1
        return dict(breakdown)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _flush_buffer_if_needed(self, buffer_name: str):
        """缓冲区满或超过 100 条时刷盘"""
        buf = getattr(self, f"_{buffer_name}_buf", [])
        if len(buf) >= 100:
            self._flush_buffer(buffer_name, buf)

    def _flush_buffer(self, buffer_name: str, buf: list):
        """将缓冲区写入日志文件"""
        if not buf:
            return
        log_file = self._log_files.get(buffer_name)
        if not log_file:
            return
        try:
            for record in buf:
                log_file.write(json.dumps(
                    record.__dict__, default=str, ensure_ascii=False
                ) + "\n")
            log_file.flush()
            buf.clear()
        except Exception as e:
            logger.warning("Failed to flush %s buffer: %s", buffer_name, e)

    def close(self):
        """关闭所有日志文件"""
        for f in self._log_files.values():
            try:
                f.close()
            except Exception:
                pass

    def __del__(self):
        self.close()


# 全局单例
_tracker: Optional[EvaluationTracker] = None


def get_evaluation_tracker(log_dir: str = "./logs/evaluation") -> EvaluationTracker:
    global _tracker
    if _tracker is None:
        _tracker = EvaluationTracker(log_dir=log_dir)
    return _tracker
