from src.graph.state import AgentState


def test_agent_state_has_required_fields():
    """State 必须包含所有必要字段"""
    state = AgentState(
        messages=[],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
    )

    assert state["intent"] is None
    assert state["needs_human"] is False
    assert state["turn_count"] == 0
    assert state["retrieved_docs"] == []
    assert state["final_response"] == ""


def test_agent_state_mutable_fields():
    """State 字段应该是可变的"""
    state = AgentState(
        messages=[],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
    )

    state["intent"] = "faq"
    state["turn_count"] = 1
    state["retrieved_docs"].append({"content": "test"})

    assert state["intent"] == "faq"
    assert state["turn_count"] == 1
    assert len(state["retrieved_docs"]) == 1
