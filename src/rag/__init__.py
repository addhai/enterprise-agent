"""RAG 知识库加载模块

核心导出：
    - DocumentLoader: 文档加载编排器
    - HybridChunker: 文档切分器
    - VectorStoreManager: 向量库管理
    - HybridRetriever: 混合检索器
    - Embedder: 文本向量化

新架构：
    - data_sources: 数据源抽象
    - loaders: 格式加载插件
    - processors: 处理管道
    - vision_engines: 视觉引擎插件
    - safety: 内容安全检测
    - version_history: 版本历史
    - concurrency: 限流熔断 + 并发加载
    - metrics: 指标采集
    - tracing: 处理追踪
    - sync_state / sync_models / file_sync_manager: 增量同步
"""

# ── 核心五件套 ──────────────────────────────────────────────
from src.rag.loader import DocumentLoader
from src.rag.chunker import HybridChunker, SentenceWindowSplitter
from src.rag.vector_store import VectorStoreManager
from src.rag.retriever import HybridRetriever
from src.rag.embedder import Embedder

# ── 数据源 ──────────────────────────────────────────────────
from src.rag.data_sources import (
    FileInfo,
    BaseDataSource,
    LocalDirectoryDataSource,
)

# ── 子包（格式加载插件） ────────────────────────────────────
from src.rag.loaders import BaseLoader, LoaderRegistry, register_loader

# ── 子包（处理管道） ────────────────────────────────────────
from src.rag.processors import (
    BaseProcessor,
    BaseBatchProcessor,
    ProcessingContext,
    IngestionPipeline,
    NormalizeTextProcessor,
    NoiseFilterProcessor,
    StructureDetectProcessor,
    MetadataEnrichProcessor,
    QualityCheckProcessor,
    DeduplicateProcessor,
)

# ── 子包（视觉引擎） ────────────────────────────────────────
from src.rag.vision_engines import (
    BaseVisionEngine,
    BaseOCREngine,
    VisionCircuitBreaker,
    VisionResult,
    VisionEngineRegistry,
    register_vision_engine,
    register_ocr,
)

# ── 并发控制 ────────────────────────────────────────────────
from src.rag.concurrency import (
    RateLimiter,
    CircuitBreakerOpenError,
    CircuitBreaker,
    GlobalLimits,
    ConcurrentLoader,
)

# ── 指标采集 ────────────────────────────────────────────────
from src.rag.metrics import PipelineMetrics

# ── 处理追踪 ────────────────────────────────────────────────
from src.rag.tracing import PipelineTracer, PipelineStep, FileTrace

# ── 增量同步 ────────────────────────────────────────────────
from src.rag.sync_state import SyncStatus, SyncStateEntry, SyncStateStore
from src.rag.sync_models import ChangeType, FileChange, SyncError, SyncResult
from src.rag.file_sync_manager import FileSyncManager

# ── 版本历史 ────────────────────────────────────────────────
from src.rag.version_history import VersionDiff, VersionSnapshot, VersionHistory

# ── 子包（内容安全） ────────────────────────────────────────
from src.rag.safety.pii_detector import PiiFinding, PiiResult, PiiDetector
from src.rag.safety.content_compliance import ComplianceResult, ContentComplianceChecker

__all__ = [
    # 核心五件套
    "DocumentLoader",
    "HybridChunker",
    "SentenceWindowSplitter",
    "VectorStoreManager",
    "HybridRetriever",
    "Embedder",
    # 数据源
    "FileInfo",
    "BaseDataSource",
    "LocalDirectoryDataSource",
    # 格式加载插件
    "BaseLoader",
    "LoaderRegistry",
    "register_loader",
    # 处理管道
    "BaseProcessor",
    "BaseBatchProcessor",
    "ProcessingContext",
    "IngestionPipeline",
    "NormalizeTextProcessor",
    "NoiseFilterProcessor",
    "StructureDetectProcessor",
    "MetadataEnrichProcessor",
    "QualityCheckProcessor",
    "DeduplicateProcessor",
    # 视觉引擎
    "BaseVisionEngine",
    "BaseOCREngine",
    "VisionCircuitBreaker",
    "VisionResult",
    "VisionEngineRegistry",
    "register_vision_engine",
    "register_ocr",
    # 并发控制
    "RateLimiter",
    "CircuitBreakerOpenError",
    "CircuitBreaker",
    "GlobalLimits",
    "ConcurrentLoader",
    # 指标采集
    "PipelineMetrics",
    # 处理追踪
    "PipelineTracer",
    "PipelineStep",
    "FileTrace",
    # 增量同步
    "SyncStatus",
    "SyncStateEntry",
    "SyncStateStore",
    "ChangeType",
    "FileChange",
    "SyncError",
    "SyncResult",
    "FileSyncManager",
    # 版本历史
    "VersionDiff",
    "VersionSnapshot",
    "VersionHistory",
    # 内容安全
    "PiiFinding",
    "PiiResult",
    "PiiDetector",
    "ComplianceResult",
    "ContentComplianceChecker",
]
