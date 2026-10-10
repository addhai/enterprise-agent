"""
API 依赖注入：管理全局单例对象的生命周期

单例对象：
    - HybridRetriever（RAG 检索器）
    - MemoryManager（记忆中枢）
    - LangGraph workflow（编译后的状态图）
"""

import logging

from src.config import settings
from src.graph.workflow import create_workflow
from src.memory.manager import MemoryManager
from src.rag.retriever import HybridRetriever

logger = logging.getLogger(__name__)

_retriever: HybridRetriever = None
_memory_manager: MemoryManager = None
_workflow = None


def _init_retriever() -> HybridRetriever:
    """构造全局检索单例并接通两条历史缺失的检索通道。

    2026-10-09 审计修复：
      1. 必须显式传 collection_name，否则 sentence_store 恒为 None，
         knowledge_base_sentences（2834 条）建了库但从不参与检索。
      2. BM25 是纯内存索引，生产启动不经过灌库路径，需从已落盘的
         Chroma 集合 warmup 重建；此前混合检索长期只有向量一路。
    warmup 失败不阻断启动（退化为向量单路，与旧行为一致）。
    """
    retriever = HybridRetriever(collection_name=settings.chroma_collection_name)
    if settings.rag_bm25_warmup_enabled:
        try:
            n_docs = retriever.warmup_bm25_from_store()
            logger.info(
                "Retriever ready: bm25_docs=%d sentence_channel=%s",
                n_docs,
                "on" if retriever.sentence_store else "off",
            )
        except Exception:
            logger.warning("BM25 warmup failed, running vector-only", exc_info=True)
    else:
        logger.warning(
            "Retriever ready: BM25 warmup disabled by RAG_BM25_WARMUP_ENABLED"
        )
    return retriever


def get_retriever() -> HybridRetriever:
    """获取全局 HybridRetriever 实例（懒加载）"""
    global _retriever
    if _retriever is None:
        logger.info("Initializing HybridRetriever...")
        _retriever = _init_retriever()
    return _retriever


def get_memory_manager() -> MemoryManager:
    """获取全局 MemoryManager 实例（懒加载）

    MemoryManager 持有：
        - ShortTermMemory 池（session_id → Redis/内存）
        - LongTermMemory 单例（PG + Chroma / 内存 fallback）
    """
    global _memory_manager
    if _memory_manager is None:
        logger.info("Initializing MemoryManager...")
        _memory_manager = MemoryManager()
    return _memory_manager


def get_workflow():
    """获取编译好的 LangGraph 工作流（懒加载）

    工作流集成了 retriever 和 memory_manager，通过 partial 绑定到节点函数。
    """
    global _workflow
    if _workflow is None:
        logger.info("Compiling LangGraph workflow with MemoryManager...")
        _workflow = create_workflow(
            retriever=get_retriever(),
            memory_manager=get_memory_manager(),
        )
    return _workflow


def cleanup_resources():
    """服务器关闭时清理资源"""
    global _retriever, _memory_manager, _workflow

    if _memory_manager:
        try:
            _memory_manager.cleanup_expired(max_age_seconds=0)
            logger.info("MemoryManager cleaned up")
        except Exception as e:
            logger.warning("MemoryManager cleanup failed: %s", e)

    _retriever = None
    _memory_manager = None
    _workflow = None
