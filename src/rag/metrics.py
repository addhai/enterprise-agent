"""流水线指标采集 + Prometheus 支持

全链路埋点，采集核心指标：
    - 各格式加载成功率、失败率
    - 各步骤耗时（直方图）
    - 质量拦截各规则占比
    - 去重率

支持两种上报方式：
    1. 内存统计（始终可用）：get_metrics() 返回结构化数据
    2. Prometheus（可选）：自动注册 Counter/Histogram 指标
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 指标采集器
# ---------------------------------------------------------------------------


@dataclass
class _Counter:
    """计数器"""
    count: int = 0
    labels: Dict[str, int] = field(default_factory=dict)


@dataclass
class _Histogram:
    """直方图"""
    samples: List[float] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def sum(self) -> float:
        return sum(self.samples) if self.samples else 0.0

    @property
    def avg(self) -> float:
        return self.sum / self.count if self.count > 0 else 0.0

    @property
    def min(self) -> float:
        return min(self.samples) if self.samples else 0.0

    @property
    def max(self) -> float:
        return max(self.samples) if self.samples else 0.0

    def pctile(self, p: float) -> float:
        """计算百分位数"""
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * p / 100)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]


class PipelineMetrics:
    """流水线指标采集器

    记录各步骤的计数器（成功/失败/拦截）和直方图（耗时）。
    同时支持 Prometheus 客户端自动注册。
    """

    def __init__(self, prometheus_enabled: Optional[bool] = None) -> None:
        self.enabled = settings.observability_metrics_enabled
        self._prometheus_enabled = prometheus_enabled or settings.observability_prometheus_enabled

        # 内部计数器
        self._counters: Dict[str, _Counter] = defaultdict(lambda: _Counter())
        self._histograms: Dict[str, _Histogram] = defaultdict(_Histogram)

        # Prometheus 客户端（懒加载）
        self._prom_client = None
        self._prom_counter_objs: Dict[str, Any] = {}
        self._prom_histogram_objs: Dict[str, Any] = {}

        if self._prometheus_enabled:
            try:
                from prometheus_client import Counter, Histogram, REGISTRY
                self._prom_registry = REGISTRY
                self._prom_counter_cls = Counter
                self._prom_histogram_cls = Histogram
                self._setup_prometheus()
            except ImportError:
                logger.info("prometheus_client not installed, disabling Prometheus export")
                self._prometheus_enabled = False

    def _setup_prometheus(self) -> None:
        """初始化 Prometheus 指标对象"""
        # 文件加载计数
        self._prom_counter_objs["files_total"] = self._prom_counter_cls(
            "rag_loader_files_total", "Total files scanned by format",
            ["format"], registry=self._prom_registry,
        )
        self._prom_counter_objs["files_loaded"] = self._prom_counter_cls(
            "rag_loader_files_loaded", "Files successfully loaded by format and status",
            ["format", "status"], registry=self._prom_registry,
        )
        self._prom_counter_objs["files_rejected"] = self._prom_counter_cls(
            "rag_loader_files_rejected", "Files rejected by reason",
            ["reason"], registry=self._prom_registry,
        )
        self._prom_counter_objs["files_deduped"] = self._prom_counter_cls(
            "rag_loader_files_deduped", "Files removed by deduplication",
            [], registry=self._prom_registry,
        )

        # 耗时直方图
        self._prom_histogram_objs["file_duration"] = self._prom_histogram_cls(
            "rag_loader_file_duration_seconds",
            "Time to process a single file",
            ["format"], buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0],
            registry=self._prom_registry,
        )
        self._prom_histogram_objs["pipeline_duration"] = self._prom_histogram_cls(
            "rag_loader_pipeline_duration_seconds",
            "Total pipeline processing time",
            buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0],
            registry=self._prom_registry,
        )

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def record_count(self, name: str, value: int = 1, labels: Optional[Dict[str, str]] = None) -> None:
        """记录计数器"""
        if not self.enabled:
            return

        key = name
        if labels:
            key = f"{name}:{'|'.join(f'{k}={v}' for k, v in sorted(labels.items()))}"

        self._counters[key].count += value
        if labels:
            for k, v in labels.items():
                self._counters[key].labels[k] = self._counters[key].labels.get(k, 0) + value

        # Prometheus
        if self._prometheus_enabled and key in self._prom_counter_objs:
            try:
                self._prom_counter_objs[key].labels(**labels).inc(value)
            except Exception:
                pass

    def record_duration(self, name: str, duration: float, labels: Optional[Dict[str, str]] = None) -> None:
        """记录耗时（直方图）"""
        if not self.enabled:
            return

        self._histograms[name].samples.append(duration)

        # Prometheus
        if self._prometheus_enabled and name in self._prom_histogram_objs:
            try:
                self._prom_histogram_objs[name].labels(**(labels or {})).observe(duration)
            except Exception:
                pass

    def get_metrics(self) -> Dict[str, Any]:
        """返回结构化指标数据"""
        histograms = {}
        for name, h in self._histograms.items():
            histograms[name] = {
                "count": h.count,
                "sum": round(h.sum, 6),
                "avg": round(h.avg, 6),
                "min": round(h.min, 6),
                "max": round(h.max, 6),
                "p50": round(h.pctile(50), 6),
                "p95": round(h.pctile(95), 6),
                "p99": round(h.pctile(99), 6),
            }

        return {
            "counters": {k: {"count": v.count, "labels": dict(v.labels)}
                        for k, v in self._counters.items()},
            "histograms": histograms,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def report(self) -> str:
        """输出人类可读的统计报告"""
        if not self.enabled:
            return ""

        lines = []
        lines.append("=" * 60)
        lines.append("  RAG Loader Pipeline Metrics Report")
        lines.append("=" * 60)

        # 计数器
        lines.append("\n--- Counters ---")
        for key, counter in sorted(self._counters.items()):
            if "|" in key:
                name, label_str = key.split(":", 1)
                lines.append(f"  {name} ({label_str}): {counter.count}")
            else:
                lines.append(f"  {key}: {counter.count}")

        # 直方图
        lines.append("\n--- Duration (seconds) ---")
        for name, h in sorted(self._histograms.items()):
            if h.count > 0:
                lines.append(
                    f"  {name}: count={h.count} avg={h.avg:.4f} "
                    f"min={h.min:.4f} max={h.max:.4f} "
                    f"p50={h.pctile(50):.4f} p95={h.pctile(95):.4f}"
                )

        # 关键比率
        total = self._counters.get("files_total", _Counter(count=0)).count
        loaded = self._counters.get("files_loaded:status=success", _Counter(count=0)).count
        rejected = sum(
            v.count for k, v in self._counters.items()
            if k.startswith("files_rejected:")
        )
        deduped = self._counters.get("files_deduped", _Counter(count=0)).count

        lines.append("\n--- Key Ratios ---")
        if total > 0:
            lines.append(f"  Total files scanned: {total}")
        if deduped > 0 and total > 0:
            lines.append(f"  Dedup ratio: {deduped/total*100:.1f}% ({deduped}/{total})")
        lines.append(f"  Total duration: {self._histograms.get('pipeline_duration', _Histogram()).avg:.3f}s avg")

        lines.append("=" * 60)
        return "\n".join(lines)
