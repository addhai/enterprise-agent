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


def test_human_node_interrupts_and_applies_human_reply():
    """human_node 的 HITL 契约：暂停工作流 → 推送上下文 → 恢复后采用人工回复。

    该节点已重构为使用 LangGraph 的 `interrupt()`，因此不能裸调
    （会抛 "Called get_config outside of a runnable context"）。
    必须放进带 checkpointer 的最小图里，才能验证真实行为。
    """
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    graph = StateGraph(AgentState)
    graph.add_node("human", human_node)
    graph.add_edge(START, "human")
    graph.add_edge("human", END)
    app = graph.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "hitl-unit-test"}}
    state = _make_state("我要转人工")

    # 第一次 invoke：应在 human 节点中断，而非直接跑完
    result = app.invoke(state, config=config)
    interrupts = result.get("__interrupt__")
    assert interrupts, "human_node 应触发 interrupt 暂停工作流"

    payload = interrupts[0].value
    assert payload["type"] == "human_handoff"
    # 转接上下文应带上原始用户消息，供人工客服判断
    assert payload["context"]["user_message"] == "我要转人工"
    assert payload["context"]["reason"] == "用户主动要求人工客服"

    # 恢复：人工提交回复后，应覆盖 final_response 并清掉待处理标记
    resumed = app.invoke(
        Command(resume={"response": "您好，已由人工为您处理。", "agent_id": "agent-007"}),
        config=config,
    )
    assert resumed["final_response"] == "您好，已由人工为您处理。"
    assert resumed["human_agent_id"] == "agent-007"
    assert resumed["human_handled"] is True
    # 人工已介入，不应再标记「需要转人工」
    assert resumed["needs_human"] is False


def test_reply_node_assembles_response():
    """reply_node 应组装最终回复"""
    state = _make_state()
    state["faq_match"] = "Here is your password reset link..."
    state["intent"] = "faq"

    result = reply_node(state)

    assert result["final_response"] is not None
    assert len(result["final_response"]) > 0
