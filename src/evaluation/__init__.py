"""评估模块 — RAG 系统质量评估

提供 ragas 集成的评估能力，量化 RAG 系统质量。
"""

from .ragas_adapter import RAGASEvaluator, RAGASResult, get_diagnostic_message

__all__ = [
    "RAGASEvaluator",
    "RAGASResult",
    "get_diagnostic_message",
]