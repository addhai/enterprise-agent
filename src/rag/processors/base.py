"""BaseProcessor 抽象基类 + ProcessingContext + IngestionPipeline"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc
else:
    _Doc = "Document"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ProcessingContext
# ---------------------------------------------------------------------------


@dataclass
class ProcessingContext:
    """处理器之间的共享状态

    管道中每个 Processor 通过 ctx 传递中间数据和统计信息。
    """

    # 文件信息（由数据源提供）
    file_info: Optional[Any] = None

    # 加载器产出的原始 Document 列表
    raw_docs: List[_Doc] = field(default_factory=list)

    # 管道处理后的 Document 列表（逐 Processor 过滤）
    docs: List[_Doc] = field(default_factory=list)

    # 全局统计
    stats: Dict[str, int] = field(default_factory=dict)

    # 警告信息列表
    warnings: List[str] = field(default_factory=list)

    # 任意中间数据（Processor 间通信）
    extra: Dict[str, Any] = field(default_factory=dict)

    def inc(self, key: str, delta: int = 1) -> None:
        """递增计数器"""
        self.stats[key] = self.stats.get(key, 0) + delta


# ---------------------------------------------------------------------------
# BaseProcessor
# ---------------------------------------------------------------------------


class BaseProcessor(ABC):
    """文档处理管道节点抽象基类

    每个 Processor 接收一个 Document，返回处理后的 Document 或 None。
    返回 None 表示该文档被拦截/丢弃。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """处理器名称（用于日志和统计）"""
        ...

    @abstractmethod
    def process(self, doc: _Doc, ctx: ProcessingContext) -> Optional[_Doc]:
        """处理单个文档

        Args:
            doc: 待处理的文档
            ctx: 共享处理上下文

        Returns:
            处理后的文档，或 None（丢弃）
        """
        ...


# ---------------------------------------------------------------------------
# BatchProcessor（批量处理器）
# ---------------------------------------------------------------------------


class BaseBatchProcessor(ABC):
    """批量处理器抽象基类

    适用于需要对整个文档列表进行操作的处理步骤（如去重）。
    与 BaseProcessor 不同，它接收整个列表而不是单个文档。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """处理器名称（用于日志和统计）"""
        ...

    @abstractmethod
    def process_batch(self, docs: List[_Doc], ctx: ProcessingContext) -> List[_Doc]:
        """批量处理文档列表

        Args:
            docs: 待处理的文档列表
            ctx: 共享处理上下文

        Returns:
            处理后的文档列表（可能被过滤/去重）
        """
        ...


# ---------------------------------------------------------------------------
# IngestionPipeline
# ---------------------------------------------------------------------------


class IngestionPipeline:
    """文档摄取管道

    按顺序执行一系列 Processor，支持动态增删步骤。

    Usage::

        pipeline = IngestionPipeline()
        pipeline.add(TextNormalizeProcessor())
        pipeline.add(NoiseFilterProcessor())
        pipeline.add(QualityCheckProcessor())
        pipeline.add_batch(DeduplicateProcessor(window=200))

        result = pipeline.run(raw_docs, file_info)
    """

    def __init__(self) -> None:
        self._processors: List[BaseProcessor] = []
        self._batch_processors: List[BaseBatchProcessor] = []

    def add(self, processor: BaseProcessor) -> "IngestionPipeline":
        """添加一个处理器到管道末尾"""
        self._processors.append(processor)
        logger.debug("Added processor: %s", processor.name)
        return self

    def add_batch(self, processor: BaseBatchProcessor) -> "IngestionPipeline":
        """添加一个批量处理器到管道末尾（在逐文档处理器之后执行）"""
        self._batch_processors.append(processor)
        logger.debug("Added batch processor: %s", processor.name)
        return self

    def remove(self, name: str) -> bool:
        """按名称移除一个处理器（包括批量处理器）"""
        for i, p in enumerate(self._processors):
            if p.name == name:
                self._processors.pop(i)
                logger.debug("Removed processor: %s", name)
                return True
        for i, p in enumerate(self._batch_processors):
            if p.name == name:
                self._batch_processors.pop(i)
                logger.debug("Removed batch processor: %s", name)
                return True
        return False

    def run(
        self,
        raw_docs: List[_Doc],
        file_info: Optional[Any] = None,
    ) -> List[_Doc]:
        """执行管道

        Args:
            raw_docs: 加载器产出的原始 Document 列表
            file_info: 文件信息（传递给 Processor）

        Returns:
            经过所有 Processor 处理后的 Document 列表
        """
        if not raw_docs:
            return []

        ctx = ProcessingContext(
            file_info=file_info,
            raw_docs=list(raw_docs),
            docs=list(raw_docs),
        )

        # 逐文档处理器
        for proc in self._processors:
            filtered: List[_Doc] = []
            for doc in ctx.docs:
                try:
                    result = proc.process(doc, ctx)
                    if result is not None:
                        filtered.append(result)
                except Exception as e:
                    logger.warning(
                        "Processor %s failed on %s: %s",
                        proc.name, doc.metadata.get("source", "unknown"), e,
                    )
                    ctx.warnings.append(f"{proc.name}: {e}")

            ctx.docs = filtered
            ctx.inc(f"{proc.name}_processed", len(ctx.raw_docs))
            ctx.inc(f"{proc.name}_dropped", len(ctx.raw_docs) - len(ctx.docs))

        # 批量处理器（如去重）
        for bproc in self._batch_processors:
            try:
                ctx.docs = bproc.process_batch(ctx.docs, ctx)
            except Exception as e:
                logger.warning("Batch processor %s failed: %s", bproc.name, e)
                ctx.warnings.append(f"{bproc.name}: {e}")

        logger.info(
            "Pipeline %s: %d → %d docs",
            " → ".join(p.name for p in self._processors) +
            (" + batch:" + " → ".join(p.name for p in self._batch_processors) if self._batch_processors else ""),
            len(raw_docs), len(ctx.docs),
        )
        return ctx.docs
