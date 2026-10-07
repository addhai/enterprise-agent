from langchain_core.messages import HumanMessage
from src.graph.nodes import (
    _simplify_reply,
    entry_node,
    faq_node,
    human_node,
    reply_node,
    router_node,
)
from src.graph.state import AgentState


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
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
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
        Command(
            resume={"response": "您好，已由人工为您处理。", "agent_id": "agent-007"}
        ),
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


# ======================================================================
# _simplify_reply：通用 100 字/3 要点，技术意图 600 字/6 要点
# 金标题 GP02/GP10 等 19 题实测：旧逻辑无差别 100 字截断，把分步
# 操作答案后半段切没（6 点列表剩 3 点，横线列表 80 字硬切成 M...）
# ======================================================================

_SIX_STEPS = "\n".join(
    f"{i}. 第{i}步的操作说明内容要写得足够具体确保整段超过一百个汉字的门槛"
    for i in range(1, 7)
)
_DASH_LIST = (
    "- 开机正常，屏幕显示完整无坏点"
    "- 所有按键功能正常，每个按键都要单独验证"
    "- 激光定位正常开启和关闭，红点清晰可见"
    "- 单位切换正常，摄氏度与华氏度来回切换"
    "- 存储位置调用正常，历史记录可完整翻阅"
    "- 测量精度复核合格，与标准源偏差在允差内"
    "- 蓝牙与数据导出正常，报表文件能在电脑端打开"
    "- 固件版本号与校准有效期已确认无误并登记入册"
)


def test_simplify_technical_multiline_six_points_kept():
    """技术意图 6 步列表（约 160 字）必须完整保留。"""
    out = _simplify_reply(_SIX_STEPS, technical=True)
    assert out == _SIX_STEPS
    assert out.count("\n") == 5


def test_simplify_non_technical_multiline_cut_to_three():
    """非技术回答沿用旧契约：编号列表只留前 3 点。"""
    out = _simplify_reply(_SIX_STEPS, technical=False)
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 3
    assert lines[0].startswith("1. ")
    assert lines[2].startswith("3. ")


def test_simplify_technical_dash_list_not_hard_cut():
    """技术意图无编号横线列表（GP10 型）在 600 字内原样保留，不得 80 字硬切。"""
    assert len(_DASH_LIST) > 100
    out = _simplify_reply(_DASH_LIST, technical=True)
    assert out == _DASH_LIST
    assert not out.endswith("...")


def test_simplify_non_technical_dash_list_hard_cut():
    """非技术无句号长文本仍按旧逻辑 80 字硬切加省略号。"""
    out = _simplify_reply(_DASH_LIST, technical=False)
    assert out == _DASH_LIST[:80] + "..."


def test_simplify_technical_long_paragraph_sentence_boundary():
    """技术意图超 600 字段落按完整句子收，不做 80 字硬切。"""
    para = "".join(f"这是第{i}个完整句子要表达一个明确的操作要点。" for i in range(30))
    assert len(para) > 600
    out = _simplify_reply(para, technical=True)
    assert len(out) <= 600
    assert out.endswith("。")
    assert not out.endswith("...")


def test_simplify_technical_long_points_capped_to_six():
    """技术意图超 600 字的多点长答保留前 6，不拖垮聊天窗口。"""
    ten = "\n".join(
        f"{i}. 第{i}步的操作说明内容要写得足够具体，覆盖事前准备、现场执行、"
        "事后判定与异常处理各个环节，并注明所需工具和安全注意事项"
        for i in range(1, 11)
    )
    assert len(ten) > 600
    out = _simplify_reply(ten, technical=True)
    assert len(out.splitlines()) == 6
    assert "第7步" not in out


def test_simplify_tool_sourced_always_untouched():
    """工具来源文本无论意图与长度都原样保留。"""
    long_text = "ecs.g7.large 规格。" * 200
    assert _simplify_reply(long_text, technical=False, tool_sourced=True) == long_text
    assert _simplify_reply(long_text, technical=True, tool_sourced=True) == long_text


def test_simplify_empty_string():
    assert _simplify_reply("", technical=True) == ""
    assert _simplify_reply("", technical=False) == ""


def test_reply_node_technical_answer_not_truncated():
    """reply_node 端到端：technical 意图的 6 步答案不得被精简。"""
    state = _make_state("专业黑体校准时，一个校准点的数据采集怎么操作？")
    state["intent"] = "technical"
    state["final_response"] = _SIX_STEPS

    result = reply_node(state)

    assert result["final_response"] == _SIX_STEPS


def test_reply_node_faq_answer_still_compressed():
    """reply_node 端到端：faq 意图长答案仍压到 3 要点，守住聊天短答风格。"""
    state = _make_state("need to reset my password step by step")
    state["intent"] = "faq"
    state["final_response"] = _SIX_STEPS

    result = reply_node(state)

    lines = [line for line in result["final_response"].splitlines() if line.strip()]
    assert len(lines) == 3
