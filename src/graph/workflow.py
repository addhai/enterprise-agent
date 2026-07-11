"""LangGraph 工作流装配入口

v2.0 扁平化单图架构：
    所有 handler（faq/rag/reflect/expert）是普通函数，
    由单层 StateGraph 直接编排。
    不再有子图嵌套、不再有桥接函数。

工作流 DAG：
    entry → classify → {faq_handle | rag_handle | human}
                              ↓
                      reflect? → reply → END
                              ↓
                      expert_delegate? → reflect → reply

    条件路由：
    - classify → faq_handle（intent=faq）
    - classify → rag_handle（intent=technical）
    - classify → human_handle（intent=human）
    - faq_handle → reply（命中）或 rag_handle（未命中）
    - rag_handle → reflect（高质量）或 expert（低质量）
    - reflect → reply（通过）
    - expert → reflect → reply
    - human → reply
"""
from functools import partial

from langgraph.graph import StateGraph, START, END

from src.graph.state import AgentState
from src.graph.nodes import entry_node, classify_node, human_node, reply_node
from src.agents import faq_handler, rag_handler, reflect_handler


def create_workflow(retriever=None, memory_manager=None):
    """创建单层 StateGraph 工作流

    Args:
        retriever: HybridRetriever 实例
        memory_manager: MemoryManager 实例

    Returns:
        编译好的 StateGraph
    """
    # Partially bind retriever and memory_manager
    entry_bound = partial(entry_node, memory_manager=memory_manager)
    rag_bound = partial(rag_handler, retriever=retriever)
    reply_bound = partial(reply_node, memory_manager=memory_manager)

    # 创建父级工作流
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("entry", entry_bound)
    workflow.add_node("classify", classify_node)
    workflow.add_node("faq_handle", faq_handler)
    workflow.add_node("rag_handle", rag_bound)
    workflow.add_node("reflect", reflect_handler)
    workflow.add_node("expert", lambda s: expert_delegate_node(s))
    workflow.add_node("human", human_node)
    workflow.add_node("reply", reply_bound)

    # 添加边
    workflow.set_entry_point("entry")
    workflow.add_edge("entry", "classify")

    # classify 决策：faq → faq_handle, human → human, 其他 → rag
    workflow.add_conditional_edges(
        "classify",
        lambda s: "faq_handle" if s.get("intent") == "faq" else
                  "human" if s.get("intent") == "human" else
                  "rag_handle",
        {
            "faq_handle": "faq_handle",
            "rag_handle": "rag_handle",
            "human": "human",
        }
    )

    # FAQ 决策：命中 → reply，未命中 → RAG
    workflow.add_conditional_edges(
        "faq_handle",
        lambda s: "reply" if s.get("faq_match") else "rag_handle",
        {
            "reply": "reply",
            "rag_handle": "rag_handle",
        }
    )

    # RAG 决策：需要专家委托 → expert，否则 → reflect
    workflow.add_conditional_edges(
        "rag_handle",
        lambda s: "expert" if s.get("needs_expert_delegation") else "reflect",
        {
            "expert": "expert",
            "reflect": "reflect",
        }
    )

    # Expert → Reflect → Reply
    workflow.add_edge("expert", "reflect")
    workflow.add_edge("reflect", "reply")
    workflow.add_edge("human", "reply")

    # Reply 节点结束
    workflow.add_edge("reply", END)

    # 编译
    return workflow.compile()


# 别名，保持向后兼容
create_parent_workflow = create_workflow
