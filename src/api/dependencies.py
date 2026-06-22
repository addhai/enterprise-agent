"""
API 依赖注入：管理全局单例对象的生命周期
"""
import logging
from src.rag.retriever import HybridRetriever
from src.graph.workflow import create_workflow

logger = logging.getLogger(__name__)

_retriever: HybridRetriever = None
_workflow = None


def get_retriever() -> HybridRetriever:
    """获取全局 HybridRetriever 实例（懒加载）"""
    global _retriever
    if _retriever is None:
        logger.info("Initializing HybridRetriever...")
        _retriever = HybridRetriever()
    return _retriever


def get_workflow():
    """获取编译好的 LangGraph 工作流（懒加载）"""
    global _workflow
    if _workflow is None:
        logger.info("Compiling LangGraph workflow...")
        _workflow = create_workflow(retriever=get_retriever())
    return _workflow
