"""文档加载与数据清洗模块

三层解耦架构：
    数据源 (data_sources.py) → 加载器 (loaders/) → 处理管道 (processors/)

功能：
    1. 多格式加载：Markdown / PDF / HTML / DOCX / 图片（PNG/JPG/GIF/WebP）
    2. 元数据保留：文件名、页码、章节标题、文档类别、时间戳、图片类型
    3. 文本规范化：全角半角统一、unicode 正规化、多余空白清理、特殊字符替换
    4. 质量过滤：跳过空段落、页眉页脚、纯导航文本
    5. 去重：基于内容哈希的同源文档块去重
    6. 结构感知：代码块、表格、列表保留结构化描述
    7. 编码检测：自动检测文件编码（UTF-8 / GBK / Latin-1）
    8. 多模态视觉管线：阿里百炼 Qwen-VL 理解 + OCR 降级（Paddle/Tesseract）
    9. 权限标注：文档入库前标注访问权限（public/internal/confidential/restricted）
    10. 业务域分类：按业务域（product/sales/support/engineering/legal）分类
    11. 质量拦截：低质量文档和过期文档拦截入库，防止污染检索

数据流：
    原始文件 → 数据源扫描 → 格式加载器 → 管道处理 → Document 列表

向后兼容：
    所有工具函数和类型仍然可以从本模块导入。
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from src.rag.data_sources import BaseDataSource, FileInfo, LocalDirectoryDataSource
from src.config import settings
from src.rag.loaders import BaseLoader, LoaderRegistry, register_loader
from src.rag.processors import (
    BaseBatchProcessor,
    BaseProcessor,
    IngestionPipeline,
    ProcessingContext,
)

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 自动注册所有格式加载器
# ---------------------------------------------------------------------------

# 导入所有加载器模块以触发 @register_loader 装饰器
from src.rag.loaders import markdown_loader  # noqa: F401
from src.rag.loaders import pdf_loader  # noqa: F401
from src.rag.loaders import html_loader  # noqa: F401
from src.rag.loaders import docx_loader  # noqa: F401
from src.rag.loaders import image_loader  # noqa: F401

# ---------------------------------------------------------------------------
# 向后兼容：重新导出所有类型和工具函数
# ---------------------------------------------------------------------------

# 类型（从 types.py 重新导出）
from src.rag.types import AccessLevel, BusinessDomain, QualityStatus

# 文本规范化
from src.rag.processors.normalize import normalize_text

# 噪声过滤
from src.rag.processors.noise_filter import (
    _filter_noise_paragraphs,
    _is_nav_noise,
    _process_page_header_footer,
    _try_extract_page,
    _try_extract_title,
)

# 结构感知
from src.rag.processors.structure_detect import _detect_structure, _structure_hint

# 编码检测
from src.rag.loader_utils import detect_encoding

# 权限标注
from src.rag.processors.metadata_enrich import classify_access_level, classify_business_domain

# 质量检查
from src.rag.processors.quality_check import assess_document_quality

# 去重（向后兼容：精确哈希函数）
from src.rag.processors.deduplicate import (
    DeduplicateProcessor,
    _exact_dedup,
    _normalize_for_hash,
    _content_hash,  # 向后兼容别名
)

# ---------------------------------------------------------------------------
# 内部工具（供加载器使用）
# ---------------------------------------------------------------------------


def _build_base_meta(info: FileInfo, encoding: str, default_tenant_id: str) -> dict:
    """构建基础元数据"""
    return {
        "source": info.name,
        "category": _get_category(info.ext),
        "created_time": info.metadata.get("created_time", ""),
        "modified_time": info.metadata.get("modified_time", ""),
        "encoding": encoding,
        "tenant_id": default_tenant_id,
    }


_CATEGORY_MAP = {
    ".md": "markdown",
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".docx": "docx",
}


def _get_category(ext: str) -> str:
    """根据扩展名获取文档类别"""
    return _CATEGORY_MAP.get(ext, "unknown")


# ---------------------------------------------------------------------------
# 文档加载器（薄包装编排器）
# ---------------------------------------------------------------------------


class DocumentLoader:
    """多模态文档加载器 + 数据清洗管线 + 阿里百炼视觉理解 + 质量拦截

    这是一个薄包装编排器，内部委托给：
        1. 数据源（LocalDirectoryDataSource）
        2. 加载器注册表（LoaderRegistry）
        3. 处理管道（IngestionPipeline）

    公共 API 保持不变：
        - load_directory(dir_path) → List[Document]
        - load_file(file_path) → List[Document]

    构造参数与原版完全一致，确保向后兼容。
    """

    # 文档类别映射（向后兼容）
    CATEGORY_MAP = _CATEGORY_MAP

    @staticmethod
    def compute_content_hash(normalized_text: str) -> str:
        """计算归一化文本的 SHA-256 哈希

        用于增量同步时检测文件内容是否变更。
        对归一化文本求哈希，确保内容不变但格式微调不会触发重新处理。
        """
        import hashlib
        return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_doc_id(file_path: str, content: str,
                        chunk_type: str, chunk_index: int) -> str:
        """基于文件路径 + 内容哈希生成确定性 document_id

        格式：doc:<normalized_path>:<content_hash_short>:<chunk_type>:<chunk_index>

        同一文件多次加载返回相同 ID，内容变化后 ID 变化。
        """
        import hashlib
        normalized_path = str(Path(file_path).resolve())
        normalized_content = _normalize_for_hash(content)
        content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()[:12]
        return f"doc:{normalized_path}:{content_hash}:{chunk_type}:{chunk_index}"

    def __init__(
        self,
        encoding: str = "utf-8",
        enable_dedup: bool = True,
        dedup_window: int = 200,
        default_tenant_id: str = "",
        enforce_quality: bool = True,
        max_days_outdated: int = 180,
        current_version: int = 302,
        vision_timeout: float = 10.0,
    ) -> None:
        self.encoding = encoding
        self.enable_dedup = enable_dedup
        self.dedup_window = dedup_window
        self.default_tenant_id = default_tenant_id
        self.enforce_quality = enforce_quality
        self.max_days_outdated = max_days_outdated
        self.current_version = current_version
        self.vision_timeout = vision_timeout

        # 统计
        self._stats: Dict[str, int] = {
            "loaded": 0,
            "rejected_quality": 0,
            "rejected_expired": 0,
            "warn_outdated": 0,
            "accepted": 0,
        }

    # --------------------------------------------------------------
    # 公共 API
    # --------------------------------------------------------------

    def load_directory(self, dir_path: str) -> List["_Doc"]:
        """加载目录下的所有文档（自动按扩展名分发 + 质量拦截）

        完整管线：
            数据源扫描 → 格式加载 → 管道处理 → 质量拦截 → 去重
        """
        # 初始化可观测性组件
        from src.rag.metrics import PipelineMetrics
        from src.rag.tracing import PipelineTracer

        metrics = PipelineMetrics()
        tracer = PipelineTracer()
        pipeline_start = time.time()

        all_docs: List["_Doc"] = []
        dir_p = Path(dir_path).resolve()

        if not dir_p.is_dir():
            logger.warning("Directory does not exist: %s", dir_p)
            return []

        # 1. 创建数据源
        source = LocalDirectoryDataSource(str(dir_p))

        # 2. 列出文件
        file_infos = source.list_files()
        metrics.record_count("files_scanned", len(file_infos))

        # 3. 逐个加载（带分级重试 + 死信队列）
        for info in file_infos:
            file_start = time.time()
            fmt = info.ext.lstrip(".")
            trace = tracer.start_trace(str(info.path), fmt)

            metrics.record_count("files_total", 1, {"format": fmt})

            try:
                docs = self._load_single_file_with_retry(info, source)
                metrics.record_count("files_loaded", len(docs),
                                   {"format": fmt, "status": "success"})

                # 记录加载耗时
                load_dur = time.time() - file_start
                metrics.record_duration("file_duration", load_dur, {"format": fmt})
                trace.add_step("load", load_dur * 1000, input_count=1, output_count=len(docs))

                all_docs.extend(docs)
                trace.complete(total_docs=len(docs))

            except Exception as e:
                error_dur = time.time() - file_start
                metrics.record_count("files_loaded", 1,
                                   {"format": fmt, "status": "error"})
                metrics.record_duration("file_duration", error_dur, {"format": fmt})
                trace.add_step("load", error_dur * 1000, error=str(e))
                trace.complete()
                logger.warning("Failed to load %s: %s", info.path, e)

        # 加载失败统计
        dlq_stats = self._dlq.stats() if hasattr(self, '_dlq') else {}
        self._stats["dlq_total"] = dlq_stats.get("total", 0)
        self._stats["dlq_pending"] = dlq_stats.get("pending", 0)

        self._stats["loaded"] = len(all_docs)

        # 4. 管道处理
        pipeline = self._build_pipeline()
        grouped: Dict[str, List["_Doc"]] = {}
        for doc in all_docs:
            source_name = doc.metadata.get("source", "unknown")
            grouped.setdefault(source_name, []).append(doc)

        processed_docs: List["_Doc"] = []
        pipeline_start2 = time.time()
        for source_name, docs in grouped.items():
            ctx = pipeline.run(docs)
            processed_docs.extend(ctx)
        pipeline_dur = time.time() - pipeline_start2
        metrics.record_duration("pipeline_duration", pipeline_dur)

        # 5. 质量拦截
        if self.enforce_quality:
            pre_quality = len(processed_docs)
            processed_docs = self._enforce_quality(processed_docs)
            rejected = pre_quality - len(processed_docs)
            metrics.record_count("files_rejected", rejected, {"reason": "quality"})
            metrics.record_count("files_quality_accepted", len(processed_docs))

        # 6. 去重
        if self.enable_dedup:
            pre_dedup = len(processed_docs)
            processed_docs = self._deduplicate(processed_docs)
            deduped = pre_dedup - len(processed_docs)
            metrics.record_count("files_deduped", deduped)

        # 记录管道总耗时
        total_dur = time.time() - pipeline_start
        metrics.record_duration("pipeline_duration", total_dur)

        # 输出报告和 Trace
        report = metrics.report()
        if report:
            logger.info(report)
        tracer.flush()

        # 7. 版本历史
        try:
            import uuid as _uuid
            from src.rag.version_history import VersionHistory, VersionSnapshot
            vh = VersionHistory()
            for doc in processed_docs:
                src = doc.metadata.get("source", "")
                if src:
                    versions = vh.get_versions(str(info.path))
                    next_version = (versions[-1].version + 1) if versions else 1
                    vh.save_snapshot(VersionSnapshot(
                        snapshot_id=str(_uuid.uuid4()),
                        file_path=str(info.path),
                        version=next_version,
                        content_hash=DocumentLoader.compute_content_hash(doc.page_content)[:16],
                        content_preview=doc.page_content[:200],
                        metadata_snapshot={k: v for k, v in doc.metadata.items() if k != "outline"},
                        doc_ids=[],
                        processed_at=datetime.now(timezone.utc),
                        processing_time_ms=total_dur * 1000,
                        quality_status=doc.metadata.get("quality_status"),
                    ))
        except Exception as e:
            logger.warning("Version history save failed: %s", e, exc_info=True)

        return processed_docs

    def load_file(self, file_path: str) -> List["_Doc"]:
        """加载单个文件"""
        p = Path(file_path).resolve()
        info = FileInfo(
            path=p,
            name=p.name,
            ext=p.suffix.lower(),
            size=p.stat().st_size,
        )
        source = LocalDirectoryDataSource("")  # dummy
        docs = self._load_single_file_info(info, source)

        if self.enable_dedup:
            docs = self._deduplicate(docs)

        return docs

    # --------------------------------------------------------------
    # 内部方法
    # --------------------------------------------------------------

    def _load_single_file_info(
        self, info: FileInfo, source: BaseDataSource
    ) -> List["_Doc"]:
        """根据 FileInfo 加载单个文件"""
        ext = info.ext
        encoding = detect_encoding(str(info.path))
        base_meta = _build_base_meta(info, encoding, self.default_tenant_id)
        base_meta["encoding"] = encoding

        # 从注册表查找加载器
        loader_cls = LoaderRegistry.get(ext)
        if loader_cls is None:
            logger.warning("No loader registered for extension: %s", ext)
            return []

        loader = loader_cls()
        docs = loader.load(info, base_meta)

        return docs

    def _build_pipeline(self) -> IngestionPipeline:
        """构建处理管道"""
        from src.rag.processors.normalize import NormalizeTextProcessor
        from src.rag.processors.noise_filter import NoiseFilterProcessor
        from src.rag.processors.structure_detect import StructureDetectProcessor
        from src.rag.processors.content_safety import ContentSafetyProcessor

        pipeline = IngestionPipeline()
        pipeline.add(NormalizeTextProcessor())
        pipeline.add(NoiseFilterProcessor())
        pipeline.add(StructureDetectProcessor())
        pipeline.add(ContentSafetyProcessor())
        return pipeline

    def _enforce_quality(self, docs: List["_Doc"]) -> List["_Doc"]:
        """质量拦截：权限标注 + 业务域分类 + 过期/低质量过滤"""
        from src.rag.processors.metadata_enrich import MetadataEnrichProcessor
        from src.rag.processors.quality_check import QualityCheckProcessor

        ctx = ProcessingContext(docs=list(docs))
        enrich_proc = MetadataEnrichProcessor()
        qc_proc = QualityCheckProcessor(
            max_days_outdated=self.max_days_outdated,
            current_version=self.current_version,
        )

        accepted: List["_Doc"] = []
        for doc in docs:
            # 1. 元数据增强
            doc = enrich_proc.process(doc, ctx)
            # 2. 质量检查
            result = qc_proc.process(doc, ctx)
            if result is not None:
                accepted.append(result)

        # 同步统计
        self._stats["accepted"] = ctx.stats.get("accepted", len(accepted))
        self._stats["rejected_quality"] = ctx.stats.get("rejected_quality", 0)
        self._stats["rejected_expired"] = ctx.stats.get("rejected_expired", 0)
        self._stats["warn_outdated"] = ctx.stats.get("warn_outdated", 0)

        return accepted

    def _deduplicate(self, docs: List["_Doc"]) -> List["_Doc"]:
        """基于三级去重处理器进行去重"""
        from src.rag.processors.deduplicate import DeduplicateProcessor

        ctx = ProcessingContext(docs=docs)
        dedup_proc = DeduplicateProcessor(
            window=self.dedup_window,
            simhash_enabled=self._get_simhash_enabled(),
            simhash_threshold=self._get_simhash_threshold(),
        )
        return dedup_proc.process_batch(docs, ctx)

    def _get_simhash_enabled(self) -> bool:
        """获取 SimHash 开关（构造函数参数优先，其次 settings）"""
        return getattr(self, "_simhash_enabled_override", settings.dedup_simhash_enabled)

    def _get_simhash_threshold(self) -> float:
        """获取 SimHash 阈值（构造函数参数优先，其次 settings）"""
        return getattr(self, "_simhash_threshold_override", settings.dedup_simhash_threshold)

    # --------------------------------------------------------------
    # 并发加载
    # --------------------------------------------------------------

    def _load_concurrent(
        self, file_infos: List["FileInfo"], source: BaseDataSource
    ) -> List["_Doc"]:
        """使用线程池并发加载文件"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        max_workers = settings.loader_max_workers
        logger.info(
            "Concurrent loading: %d files with %d workers",
            len(file_infos), max_workers,
        )

        all_docs: List["_Doc"] = []
        errors: List[str] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_info = {
                executor.submit(self._load_single_file_with_retry, info, source): info
                for info in file_infos
            }

            for future in as_completed(future_to_info):
                info = future_to_info[future]
                try:
                    docs = future.result()
                    all_docs.extend(docs)
                except Exception as e:
                    error_msg = f"{info.path}: {e}"
                    errors.append(error_msg)
                    logger.error("Concurrent load failed: %s", error_msg)

        if errors:
            logger.warning(
                "ConcurrentLoader: %d/%d files failed",
                len(errors), len(file_infos),
            )

        logger.info(
            "ConcurrentLoader: %d files → %d docs (%d errors)",
            len(file_infos), len(all_docs), len(errors),
        )
        return all_docs

    # --------------------------------------------------------------
    # 分级重试 + 死信队列
    # --------------------------------------------------------------

    def _load_single_file_with_retry(
        self, info: "FileInfo", source: BaseDataSource
    ) -> List["_Doc"]:
        """带分级重试的文件加载

        1. 分类错误类型
        2. 网络错误 → 自动重试 max_retries 次（指数退避）
        3. 重试仍失败 / 非网络错误 → 写入 DLQ
        """
        from src.rag.dead_letter_queue import (
            DLQEntry,
            ErrorCategory,
            DeadLetterQueue,
            classify_error,
        )

        max_retries = settings.dlq_max_retries
        delay_base = settings.dlq_retry_delay_base
        auto_retry = settings.dlq_auto_retry_network

        # 初始化 DLQ（懒加载）
        if not hasattr(self, "_dlq"):
            self._dlq = DeadLetterQueue()

        last_error: Optional[Exception] = None

        for attempt in range(1 + max_retries if auto_retry else 1):
            try:
                return self._load_single_file_info(info, source)
            except Exception as e:
                last_error = e
                error_cat = classify_error(e)
                logger.warning(
                    "Attempt %d/%d failed for %s: %s (%s)",
                    attempt, 1 + max_retries if auto_retry else 1,
                    info.path, e, error_cat.value,
                )

                # 非网络错误或不自动重试 → 直接进 DLQ
                if error_cat != ErrorCategory.NETWORK or not auto_retry:
                    break

                # 网络错误 → 指数退避后重试
                if attempt <= max_retries:
                    delay = delay_base * (2 ** (attempt - 1))
                    logger.info(
                        "Network error, retrying in %.1fs...", delay,
                    )
                    time.sleep(delay)

        # 所有重试耗尽 → 写入 DLQ
        error_cat = classify_error(last_error) if last_error else ErrorCategory.LOAD
        entry = DLQEntry(
            file_path=str(info.path.resolve()),
            error_type=error_cat.value,
            error_message=str(last_error) if last_error else "Unknown",
            failed_at=datetime.now(timezone.utc),
            retry_count=max_retries if last_error else 0,
            last_error=str(last_error) if last_error else "",
        )
        self._dlq.add(entry)
        return []

    def retry_dlq(self) -> dict:
        """批量重试 DLQ 中所有可重试的文件

        Returns:
            {"retried": int, "succeeded": int, "failed": int}
        """
        if not hasattr(self, "_dlq"):
            return {"retried": 0, "succeeded": 0, "failed": 0}

        pending = self._dlq.get_pending()
        if not pending:
            logger.info("DLQ: no pending entries to retry")
            return {"retried": 0, "succeeded": 0, "failed": 0}

        logger.info("DLQ: retrying %d entries", len(pending))
        succeeded = 0
        failed = 0
        errors: List[str] = []

        for entry in pending:
            try:
                # 重新加载文件
                source = LocalDirectoryDataSource(str(Path(entry.file_path).parent))
                docs = self._load_single_file_info(
                    FileInfo(
                        path=Path(entry.file_path).resolve(),
                        name=Path(entry.file_path).name,
                        ext=Path(entry.file_path).suffix.lower(),
                        size=Path(entry.file_path).stat().st_size,
                    ),
                    source,
                )
                if docs:
                    self._dlq.remove(entry.file_path)
                    succeeded += 1
                    logger.info("DLQ retry succeeded: %s", entry.file_path)
                else:
                    # 加载成功但无文档（质量拦截等），也算成功
                    self._dlq.remove(entry.file_path)
                    succeeded += 1
            except Exception as e:
                entry.retry_count += 1
                entry.last_error = str(e)
                self._dlq.add(entry)
                failed += 1
                errors.append(f"{entry.file_path}: {e}")

        result = {"retried": len(pending), "succeeded": succeeded, "failed": failed}
        logger.info("DLQ retry complete: %s", result)
        return result
