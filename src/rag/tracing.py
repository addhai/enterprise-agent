"""处理 Trace — 文件级全链路追踪

为每个文件生成处理 Trace，记录经过的步骤、耗时、结果。
支持日志输出和 JSON 文件持久化，方便追溯单个文件的拦截原因。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trace 数据模型
# ---------------------------------------------------------------------------


@dataclass
class PipelineStep:
    """处理管道中的一个步骤"""
    name: str                    # 步骤名（如 "load", "normalize", "quality_check"）
    duration_ms: float           # 耗时（毫秒）
    input_count: int = 0         # 输入文档数
    output_count: int = 0        # 输出文档数
    dropped_count: int = 0       # 丢弃文档数
    error: Optional[str] = None  # 错误信息


@dataclass
class FileTrace:
    """单个文件的完整处理 Trace"""
    file_path: str               # 文件路径
    format: str                  # 文件格式（如 "markdown", "pdf"）
    start_time: float            # 启动时间戳
    end_time: Optional[float] = None
    steps: List[PipelineStep] = field(default_factory=list)
    rejected_reason: Optional[str] = None
    quality_status: Optional[str] = None
    total_docs: int = 0          # 最终产出文档数

    def add_step(self, name: str, duration_ms: float,
                 input_count: int = 0, output_count: int = 0,
                 error: Optional[str] = None) -> None:
        """添加一个步骤记录"""
        dropped = max(0, input_count - output_count)
        self.steps.append(PipelineStep(
            name=name, duration_ms=duration_ms,
            input_count=input_count, output_count=output_count,
            dropped_count=dropped, error=error,
        ))

    def complete(self, total_docs: int = 0,
                 rejected_reason: Optional[str] = None,
                 quality_status: Optional[str] = None) -> None:
        """标记 Trace 完成"""
        self.end_time = time.monotonic()
        self.total_docs = total_docs
        self.rejected_reason = rejected_reason
        self.quality_status = quality_status

    @property
    def total_duration_ms(self) -> float:
        """总耗时（毫秒）"""
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "file_path": self.file_path,
            "format": self.format,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "total_docs": self.total_docs,
            "rejected_reason": self.rejected_reason,
            "quality_status": self.quality_status,
            "steps": [asdict(s) for s in self.steps],
        }

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 追踪管理器
# ---------------------------------------------------------------------------


class PipelineTracer:
    """处理 Trace 管理器

    为每个文件生成 Trace，支持：
        - 日志输出（INFO 级别）
        - JSON 文件持久化（按日期分文件）
    """

    def __init__(self, tracing_dir: Optional[str] = None) -> None:
        self.enabled = settings.observability_tracing_enabled
        self.file_enabled = settings.observability_tracing_file_enabled

        if tracing_dir:
            self.tracing_dir = Path(tracing_dir)
        else:
            # 默认放在 chroma 数据目录下
            from src.config import settings as cfg
            self.tracing_dir = Path(cfg.chroma.persist_dir) / ".traces"

        self._traces: List[FileTrace] = []

    def start_trace(self, file_path: str, file_format: str) -> FileTrace:
        """开始跟踪一个文件"""
        if not self.enabled:
            return FileTrace(file_path=file_path, format=file_format,
                           start_time=time.monotonic())

        trace = FileTrace(
            file_path=file_path,
            format=file_format,
            start_time=time.monotonic(),
        )
        self._traces.append(trace)
        return trace

    def flush(self) -> None:
        """刷新所有 Trace（写入日志和文件）"""
        if not self.enabled:
            return

        # 日志输出
        for trace in self._traces:
            if self.total_duration_ms > 0:
                logger.info(
                    "Trace: %s format=%s duration=%.1fms docs=%d steps=%d",
                    Path(trace.file_path).name,
                    trace.format,
                    trace.total_duration_ms,
                    trace.total_docs,
                    len(trace.steps),
                )
                if trace.rejected_reason:
                    logger.info("  Rejected: %s", trace.rejected_reason)

        # JSON 文件持久化
        if self.file_enabled:
            self._write_json()

        self._traces.clear()

    @property
    def total_duration_ms(self) -> float:
        """所有 Trace 的总耗时"""
        return sum(t.total_duration_ms for t in self._traces)

    @property
    def total_files(self) -> int:
        """处理的文件总数"""
        return len(self._traces)

    @property
    def rejected_files(self) -> int:
        """被拦截的文件数"""
        return sum(1 for t in self._traces if t.rejected_reason)

    def _write_json(self) -> None:
        """将 Trace 写入 JSON 文件"""
        self.tracing_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        trace_file = self.tracing_dir / f"{date_str}.json"

        # 追加写入
        existing: List[dict] = []
        if trace_file.exists():
            try:
                with open(trace_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.extend(t.to_dict() for t in self._traces)

        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        logger.info(
            "Traced %d files (%.1fms total, %d rejected) -> %s",
            self.total_files, self.total_duration_ms,
            self.rejected_files, trace_file,
        )
