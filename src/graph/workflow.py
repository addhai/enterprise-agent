"""LangGraph complete workflow assembly

工作流 DAG（v0.5）：
    entry → clarify → router → faq/rag/human → reflect → reply → END

记忆管理接入：
    - entry_node(_, memory_manager)  → 注入长期记忆上下文
    - rag_node(_, retriever, memory_manager) → 提取对话历史
    - reply_node(_, memory_manager)  → 持久化长期记忆 + 质量评估

v0.5 新增：
    - clarify_node：意图澄清（补全/追问/放行）
    - 条件路由：clarify 结果决定走 router 还是 reply（追问）
"""
from functools import partial
from langgraph.graph import StateGraph, END
from src.graph.state import AgentState
from src.graph.nodes import (
    entry_node,
    clarify_node,
    router_node,
    faq_node,
    rag_node,
    human_node,
    reflect_node,
    reply_node,
)


def _decide_clarity_route(state: AgentState) -> str:
    """clarify 节点后的条件路由"""
    status = state.get("clarity_status", "clear")
    if status == "needs_clarification":
        return "reply"  # 追问用户
    return "router"  # 放行到路由


def _decide_route(state: AgentState) -> str:
    """Conditional route: decide next node based on intent"""
    intent = state.get("intent", "faq")

    if intent == "human":
        return "human"
    elif intent == "faq":
        return "faq"
    else:
        return "rag"


def _decide_after_faq(state: AgentState) -> str:
    """Decision after FAQ: match found -> reply, otherwise escalate to RAG"""
    if state.get("faq_match"):
        return "reply"
    else:
        return "rag"


def create_workflow(retriever=None, memory_manager=None):
    """Create a complete customer service workflow

    Args:
        retriever: HybridRetriever instance
        memory_manager: MemoryManager instance（记忆中枢）

    Returns:
        Compiled StateGraph (Runnable)
    """

    # Partially bind retriever and memory_manager to nodes
    rag_node_bound = partial(
        rag_node,
        retriever=retriever,
        memory_manager=memory_manager,
    )

    entry_node_bound = partial(
        entry_node,
        memory_manager=memory_manager,
    )

    reply_node_bound = partial(
        reply_node,
        memory_manager=memory_manager,
    )

    # Create graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("entry", entry_node_bound)
    workflow.add_node("clarify", clarify_node)
    workflow.add_node("router", router_node)
    workflow.add_node("faq", faq_node)
    workflow.add_node("rag", rag_node_bound)
    workflow.add_node("reflect", reflect_node)
    workflow.add_node("human", human_node)
    workflow.add_node("reply", reply_node_bound)

    # Add edges
    workflow.set_entry_point("entry")
    workflow.add_edge("entry", "clarify")

    # Clarify decision: clear/rewritten → router, needs_clarification → reply
    workflow.add_conditional_edges(
        "clarify",
        _decide_clarity_route,
        {
            "router": "router",
            "reply": "reply",
        }
    )

    # Conditional branches
    workflow.add_conditional_edges(
        "router",
        _decide_route,
        {
            "faq": "faq",
            "rag": "rag",
            "human": "human",
        }
    )

    # FAQ decision: success -> reply, failure -> RAG
    workflow.add_conditional_edges(
        "faq",
        _decide_after_faq,
        {
            "reply": "reply",
            "rag": "rag",
        }
    )

    # RAG goes to reflect first, then to reply
    # Human goes directly to reply (no reflection needed)
    workflow.add_edge("rag", "reflect")
    workflow.add_edge("reflect", "reply")
    workflow.add_edge("human", "reply")

    # Reply node ends
    workflow.add_edge("reply", END)

    # Compile with checkpointer — HITL 必需
    # MemorySaver 保存每个 thread_id 的状态，支持 interrupt() 暂停 + Command(resume=) 恢复
    # 生产环境可替换为 PostgresSaver 实现持久化
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)
    return app
