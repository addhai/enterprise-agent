"""
API 依赖注入：管理全局单例对象的生命周期

单例对象：
    - HybridRetriever（RAG 检索器）
    - MemoryManager（记忆中枢）
    - LangGraph workflow（编译后的状态图）
"""
import logging
from src.rag.retriever import HybridRetriever
from src.memory.manager import MemoryManager
from src.graph.workflow import create_workflow

logger = logging.getLogger(__name__)

_retriever: HybridRetriever = None
_memory_manager: MemoryManager = None
_workflow = None


def get_retriever() -> HybridRetriever:
    """获取全局 HybridRetriever 实例（懒加载）"""
    global _retriever
    if _retriever is None:
        logger.info("Initializing HybridRetriever...")
        _retriever = HybridRetriever()
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
