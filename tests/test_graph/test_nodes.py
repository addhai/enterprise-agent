import pytest
from langchain_core.messages import HumanMessage
from src.graph.state import AgentState
from src.graph.nodes import entry_node, router_node, faq_node, human_node, reply_node


def _make_state(message: str = "Hello") -> AgentState:
    return AgentState(
        messages=[HumanMessage(content=message)],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
        user_id="test_user",
        faq_match=None,
    )


def test_entry_node_initializes_state():
    """entry_node 应初始化基本状态"""
    state = _make_state()
    result = entry_node(state)

    assert result["turn_count"] == 1
    assert result["intent"] is None
    assert result["needs_human"] is False


def test_router_node_classifies_intent():
    """router_node 应分类用户意图"""
    state = _make_state("How do I reset my password?")
    result = router_node(state)

    assert result["intent"] is not None
    assert result["intent"] in ["faq", "technical", "human"]


def test_router_detects_human_request():
    """router_node 应识别转人工请求"""
    state = _make_state("I want to talk to a real person")
    result = router_node(state)

    assert result["intent"] in ["human", "faq"]  # 可能直接路由到 human


def test_faq_node_attempts_match():
    """faq_node 应尝试 FAQ 匹配"""
    state = _make_state("need to reset password")
    result = faq_node(state)

    # 应该设置 faq_match（"reset password" 是 FAQ 关键词）
    assert result.get("faq_match") is not None


def test_human_node_sets_flag():
    """human_node 应设置转人工标记"""
    state = _make_state()
    result = human_node(state)

    assert result["needs_human"] is True


def test_reply_node_assembles_response():
    """reply_node 应组装最终回复"""
    state = _make_state()
    state["faq_match"] = "Here is your password reset link..."
    state["intent"] = "faq"

    result = reply_node(state)

    assert result["final_response"] is not None
    assert len(result["final_response"]) > 0
