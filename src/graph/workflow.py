"""LangGraph complete workflow assembly"""
from functools import partial
from langgraph.graph import StateGraph, END
from src.graph.state import AgentState
from src.graph.nodes import (
    entry_node,
    router_node,
    faq_node,
    rag_node,
    human_node,
    reflect_node,
    reply_node,
)


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


def create_workflow(retriever=None):
    """Create a complete customer service workflow

    Args:
        retriever: HybridRetriever instance

    Returns:
        Compiled StateGraph (Runnable)
    """

    # Partially bind retriever to rag_node
    rag_node_bound = partial(rag_node, retriever=retriever)

    # Create graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("entry", entry_node)
    workflow.add_node("router", router_node)
    workflow.add_node("faq", faq_node)
    workflow.add_node("rag", rag_node_bound)
    workflow.add_node("reflect", reflect_node)
    workflow.add_node("human", human_node)
    workflow.add_node("reply", reply_node)

    # Add edges
    workflow.set_entry_point("entry")
    workflow.add_edge("entry", "router")

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

    # Compile
    app = workflow.compile()
    return app
