"""Phase4b L5：ReAct 图必须有轮次上限，且耗尽时要降级而不是挂死。

背景（真实线上故障，务必保留这段注释，它解释了为什么要有这些断言）：
`max_reasoning_turns` 曾经是一个从未被消费的死配置——`CustomerServiceAgent`
把它存成 `self.max_turns` 后再无任何引用，`self.agent.invoke()` 也没有传
`recursion_limit`。于是模型一旦反复输出无法解析的工具调用，就会无限重试：
实测一次提问产生 24 次 chat/completions、0 次工具执行、15 分钟无回答，
客户端 WebSocket 超时后服务端仍在继续推理。

本文件锁定三件事：
1. max_turns 真的被换算成 recursion_limit 传进了图；
2. 注入模式（测试替身，单参数协议）不受影响；
3. 命中 GraphRecursionError 时两个入口都返回降级答复而非抛出。
"""

from langgraph.errors import GraphRecursionError

from src.agent.agent import CustomerServiceAgent
from src.config import settings


class _FakeGraph:
    """记录 invoke 收到的参数；raise_on_invoke 模拟触发轮次上限。"""

    def __init__(self, raise_on_invoke=False):
        self.calls = []
        self.raise_on_invoke = raise_on_invoke

    def invoke(self, input, config=None):  # noqa: A002 - 对齐 LangGraph 签名
        self.calls.append((input, config))
        if self.raise_on_invoke:
            raise GraphRecursionError("recursion limit reached")
        return {"messages": [{"content": "ok"}]}


class _StubAIMessage:
    content = "ok"

    def __init__(self):  # 让 bash tool 之外的实例化可用
        self.response_metadata = {}


def _make_agent(max_turns=5, graph=None):
    """构造一个不走真实 LLM 的 Agent：llm_client 注入 + llm 置 None 走替身分支。

    注意：一旦把 self.llm 设成非 None（模拟真实图），run()/run_with_trace()
    开头的 _ensure_llm_current() 会因为配置版本不匹配而走 _build_llm_and_agent()
    重建真实 LLM，把替身图覆盖掉。所以这里必须把版本号同步为当前值。
    """
    agent = CustomerServiceAgent(retriever=None, user_id="t", llm_client=_FakeGraph())
    agent.max_turns = max_turns
    agent.llm = graph if graph is not None else None
    if graph is not None:
        agent.agent = graph
        from src.config_center import get_config_center

        agent._llm_config_version = get_config_center().version
    return agent


# ---------------------------------------------------------------------------
# 1. max_turns -> recursion_limit 的换算
# ---------------------------------------------------------------------------


def test_max_turns_is_translated_into_recursion_limit():
    """max_turns 必须真的进入图配置：每工具轮 2 个 superstep，首尾留余量。"""
    agent = _make_agent(max_turns=5)
    assert agent._build_run_config() == {"recursion_limit": 14}

    agent = _make_agent(max_turns=3)
    assert agent._build_run_config() == {"recursion_limit": 10}

    # 0 / None 不应产生 0 或负数的 recursion_limit（那会让图一步都跑不了）
    assert agent._build_run_config()["recursion_limit"] > 0
    degenerate = _make_agent(max_turns=0)
    assert degenerate._build_run_config()["recursion_limit"] > 0


def test_default_turns_follows_settings():
    """未显式指定时沿用 settings.max_reasoning_turns，避免配置与实现脱节。"""
    agent = CustomerServiceAgent(retriever=None, user_id="t", llm_client=_FakeGraph())
    assert agent.max_turns == settings.max_reasoning_turns


# ---------------------------------------------------------------------------
# 2. 真实图路径：必须带 config；注入替身路径：不能带第二个参数
# ---------------------------------------------------------------------------


def test_invoke_passes_config_for_real_graph():
    """self.llm 存在 => 真实 LangGraph 图，必须带上 recursion_limit。"""
    graph = _FakeGraph()
    agent = _make_agent(max_turns=5, graph=graph)
    agent._invoke_agent([{"role": "user"}])

    assert len(graph.calls) == 1
    _, config = graph.calls[0]
    assert config == {"recursion_limit": 14}


def test_invoke_keeps_single_argument_for_injected_client():
    """注入模式下替身协议只有一个位置参数，多传 config 会 TypeError。"""
    fake = _FakeGraph()
    agent = _make_agent()
    agent.agent = fake
    agent.llm = None
    agent._invoke_agent([{"role": "user"}])

    assert len(fake.calls) == 1
    _, config = fake.calls[0]
    assert config is None


# ---------------------------------------------------------------------------
# 3. 轮次耗尽时的降级
# ---------------------------------------------------------------------------


def test_run_degrades_gracefully_on_recursion_limit():
    """run() 命中上限必须返回可展示的答复，不能抛给调用方。"""
    agent = _make_agent(max_turns=5, graph=_FakeGraph(raise_on_invoke=True))
    out = agent.run("帮我查一下有哪些云服务器")

    assert isinstance(out, str)
    assert out  # 非空
    assert "抱歉" in out


def test_run_with_trace_degrades_gracefully_on_recursion_limit():
    """run_with_trace() 是图节点真实路径，降级必须保持返回结构一致。"""
    agent = _make_agent(max_turns=5, graph=_FakeGraph(raise_on_invoke=True))
    result = agent.run_with_trace("帮我查一下有哪些云服务器")

    assert set(result.keys()) >= {"output", "intermediate_steps", "messages"}
    assert result["output"]  # 非空答复
    # messages 必须存在且可迭代：下游 _extract_tool_citation_docs 会读它
    assert list(result["messages"]) == []
