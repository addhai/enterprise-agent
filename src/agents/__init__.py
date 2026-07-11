"""Agent 包 — 多 Agent 架构定义

Handler 模块：
    每个 handler 是一个独立职责的 Agent 函数。
    它们不是 LangGraph 子图，而是被父图直接调用的普通函数。
    这样保持了职责分离，同时避免了子图嵌套的复杂性。

架构：
    ┌─────────────────────────────────────────┐
    │  faq_handler    — FAQ 匹配 + 闲聊回复   │
    │  rag_handler    — RAG 检索 + ReAct 推理 │
    │  reflect_handler — 四维质量审查         │
    │  expert_delegate — A2A 远程委托（预留） │
    └─────────────────────────────────────────┘

    父图 workflow.py 编排这些 handler，定义数据流。
"""
from src.agents.faq_handler import faq_handler
from src.agents.rag_handler import rag_handler
from src.agents.reflect_handler import reflect_handler

# expert_delegate_node 需要 a2a 模块，延迟导入
def __getattr__(name):
    if name == "expert_delegate_node":
        from src.agents.expert_delegate import expert_delegate_node
        return expert_delegate_node
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "faq_handler",
    "rag_handler",
    "reflect_handler",
    "expert_delegate_node",
]
