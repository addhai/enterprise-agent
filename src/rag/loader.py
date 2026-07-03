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
from datetime import datetime
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
        all_docs: List["_Doc"] = []
        dir_p = Path(dir_path).resolve()

        if not dir_p.is_dir():
            logger.warning("Directory does not exist: %s", dir_p)
            return []

        # 1. 创建数据源
        source = LocalDirectoryDataSource(str(dir_p))

        # 2. 列出所有文件
        file_infos = source.list_files()

        # 3. 逐个加载
        for info in file_infos:
            try:
                docs = self._load_single_file_info(info, source)
                all_docs.extend(docs)
            except Exception as e:
                logger.warning("Failed to load %s: %s", info.path, e)

        self._stats["loaded"] = len(all_docs)

        # 4. 管道处理（编码检测 + 文本规范化 + 噪声过滤 + 结构感知）
        encoding = self.encoding
        pipeline = self._build_pipeline()

        # 按文件分组处理（每个文件独立管道）
        grouped: Dict[str, List["_Doc"]] = {}
        for doc in all_docs:
            source_name = doc.metadata.get("source", "unknown")
            grouped.setdefault(source_name, []).append(doc)

        processed_docs: List["_Doc"] = []
        for source_name, docs in grouped.items():
            ctx = pipeline.run(docs)
            processed_docs.extend(ctx)

        # 5. 质量拦截
        if self.enforce_quality:
            processed_docs = self._enforce_quality(processed_docs)

        # 6. 去重
        if self.enable_dedup:
            processed_docs = self._deduplicate(processed_docs)

        logger.info(
            "Loaded %d docs, accepted %d, rejected %d, outdated_warn %d",
            self._stats["loaded"],
            self._stats["accepted"],
            self._stats["rejected_quality"] + self._stats["rejected_expired"],
            self._stats["warn_outdated"],
        )
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

        # 对加载结果应用管道（编码检测已在 base_meta 中）
        pipeline = self._build_pipeline()
        ctx = pipeline.run(docs, file_info=info)
        return list(ctx)

    def _build_pipeline(self) -> IngestionPipeline:
        """构建处理管道"""
        from src.rag.processors.normalize import NormalizeTextProcessor
        from src.rag.processors.noise_filter import NoiseFilterProcessor
        from src.rag.processors.structure_detect import StructureDetectProcessor

        pipeline = IngestionPipeline()
        pipeline.add(NormalizeTextProcessor())
        pipeline.add(NoiseFilterProcessor())
        pipeline.add(StructureDetectProcessor())
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
