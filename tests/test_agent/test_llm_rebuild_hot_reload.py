"""LLM 实例重建的热更新验证（temperature / max_tokens / max_reasoning_turns）

先讲清楚「谁在让热更新生效」，否则测出来的结论会张冠李戴
--------------------------------------------------------
排查发现本项目的 Agent 是**每次图调用新建**的（`src/graph/nodes.py:826`
在节点函数体内 `CustomerServiceAgent(...)`，无 lru_cache、无模块级单例）。
因此图路径上「改配置生效」靠的是「新实例构造时读到了最新 settings」，
而不是重建逻辑。

真正需要「重建」的是**同一个实例被复用**的情形，代码在
`src/agent/agent.py`：
  - `_build_llm_and_agent()`（71 行）     按当前配置构造 LLM 与 Agent，并记下配置版本
  - `_ensure_llm_current()`（102 行）     版本变了就重建
  - `_llm_config_version`（98 行赋值）    上次构造时所用的配置版本
两个入口 `run()`（141 行）与 `run_with_trace()`（225 行）开头都会调用它。

因此本测试**刻意只保留一个 Agent 实例**，中途改配置再触发，才能验证重建逻辑。
如果每次改配置都新建 Agent，`id()` 必然变化，那样的断言什么都证明不了。

为什么可以断言 id()
--------------------
不是拿 id() 单独当判据，而是与「参数值是否跟着变」一起看：
id 相同 → 未重建；id 不同且新值正确 → 重建且读到了新配置。
另外专门有一条反例测试：配置没变时 id **不应**变化，否则说明重建是无条件触发的。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.server import app

    return TestClient(app)


@pytest.fixture
def admin_headers(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture(autouse=True)
def restore_llm_config():
    """还原被测配置，避免污染其它用例"""
    from src.config import settings

    original = (
        settings.llm_temperature,
        settings.llm_max_tokens,
        settings.max_reasoning_turns,
    )
    yield
    (
        settings.llm_temperature,
        settings.llm_max_tokens,
        settings.max_reasoning_turns,
    ) = original


def _make_agent():
    """构造一个真实的 CustomerServiceAgent

    ChatOpenAI 构造只校验参数、不发起网络请求，因此无需真实 API key；
    测试环境若没有 key，补一个占位值即可（不会真的被使用）。
    """
    from src.config import settings

    if not settings.openai_api_key:
        settings.openai_api_key = "test-key-not-used"

    from src.agent.agent import CustomerServiceAgent

    return CustomerServiceAgent(user_id="admin-default", tenant_id="default")


def _stub_inner_agent(agent, recorder: dict):
    """把 Agent 内部的 LangGraph agent 换成桩件，避免真实推理

    `_ensure_llm_current()` 会连 `self.agent` 一起重建，所以每次重建后都要重新打桩。
    """

    class _FakeInner:
        def invoke(self, payload):
            recorder["invoked"] = True
            return {"messages": [], "intermediate_steps": []}

    agent.agent = _FakeInner()
    return agent


class TestLLMInstanceRebuild:
    def test_temperature_change_rebuilds_llm_with_new_value(self, client, admin_headers):
        """核心：改 temperature 后，同一 Agent 实例的 LLM 被重建且带新值"""
        from src.config import settings

        agent = _make_agent()
        old_llm = agent.llm
        old_id = id(old_llm)
        assert old_llm.temperature == settings.llm_temperature

        resp = client.put(
            "/api/v1/config/llm_temperature",
            json={"value": 0.2},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.json()

        agent._ensure_llm_current()

        new_llm = agent.llm
        assert id(new_llm) != old_id, "配置版本已变，LLM 实例应当被重建"
        assert new_llm.temperature == 0.2, (
            f"新实例的 temperature 应为 0.2，实际 {new_llm.temperature}"
        )

    def test_max_tokens_change_rebuilds_llm_with_new_value(self, client, admin_headers):
        """改 max_tokens（此前曾被误判为敏感字段而无法修改）"""
        agent = _make_agent()
        old_id = id(agent.llm)

        resp = client.put(
            "/api/v1/config/llm_max_tokens",
            json={"value": 512},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.json()

        agent._ensure_llm_current()
        assert id(agent.llm) != old_id, "LLM 实例应当被重建"
        assert agent.llm.max_tokens == 512, (
            f"新实例的 max_tokens 应为 512，实际 {agent.llm.max_tokens}"
        )

    def test_no_config_change_means_no_rebuild(self, client, admin_headers):
        """反例：配置没动时不应重建，否则说明重建是无条件触发的"""
        agent = _make_agent()
        old_id = id(agent.llm)

        agent._ensure_llm_current()   # 版本未变
        assert id(agent.llm) == old_id, (
            "配置未变更却重建了实例，说明版本号检查没起作用"
        )

    def test_sequence_and_restore(self, client, admin_headers):
        """连续切换 0.2 → 0.9 → 回到原值，每次都重建且值正确"""
        from src.config import settings

        original = settings.llm_temperature
        agent = _make_agent()
        observed = []

        for value in [0.2, 0.9, original]:
            client.put(
                "/api/v1/config/llm_temperature",
                json={"value": value},
                headers=admin_headers,
            )
            before_id = id(agent.llm)
            agent._ensure_llm_current()
            observed.append({
                "value": value,
                "rebuilt": id(agent.llm) != before_id,
                "effective": agent.llm.temperature,
            })

        assert all(o["rebuilt"] for o in observed), f"每次都该重建：{observed}"
        assert [o["effective"] for o in observed] == [0.2, 0.9, original], observed

    def test_rebuild_happens_through_run_with_trace(self, client, admin_headers):
        """集成路径：run_with_trace 开头会触发重建（不只是私有方法能跑）"""
        from src.config import settings
        agent = _make_agent()
        old_id = id(agent.llm)
        client.put(
            "/api/v1/config/llm_temperature",
            json={"value": 0.7},
            headers=admin_headers,
        )
        # 重建会把内部 agent 一起换掉，桩会失效；直接拦 _invoke_agent，避免真实 LLM 调用
        agent._invoke_agent = lambda messages: {"messages": [], "intermediate_steps": []}
        agent.run_with_trace("测试问题")
        assert id(agent.llm) != old_id, "run_with_trace 应触发 LLM 重建"
        assert agent.llm.temperature == 0.7


    def test_rebuild_does_not_lose_tenant_or_user(self, client, admin_headers):
        """重建只换 LLM/内部 agent，不应丢掉 Agent 自身的身份字段"""
        agent = _make_agent()
        agent.user_id = "u-123"
        agent.tenant_id = "tenant-x"

        client.put(
            "/api/v1/config/llm_temperature",
            json={"value": 0.3},
            headers=admin_headers,
        )
        agent._ensure_llm_current()

        assert agent.user_id == "u-123"
        assert agent.tenant_id == "tenant-x"


class TestMaxReasoningTurnsHotReload:
    """max_reasoning_turns 走的是另一条链路（不是 LLM 重建）

    它由调用方在构造 AgentState 时读取（`src/api/routes.py` 与
    `src/websocket/routes.py` 的 effective_max_turns 字段）。
    此前这两处写死 5，导致改配置无效；现改为读 settings。
    """

    def test_chat_handler_uses_configured_max_turns(self, client, admin_headers, monkeypatch):
        from src.config import settings

        captured: dict = {}

        class _FakeWorkflow:
            def invoke(self, state, config=None):
                captured["state"] = state
                return {"final_response": "ok"}

        monkeypatch.setattr(
            "src.api.routes.get_workflow", lambda: _FakeWorkflow()
        )

        settings.max_reasoning_turns = 3
        resp = client.post(
            "/api/v1/chat", json={"message": "测试"}, headers=admin_headers
        )
        assert resp.status_code == 200, resp.json()
        assert captured["state"]["effective_max_turns"] == 3, (
            "调用方应把配置里的 max_reasoning_turns 写进 effective_max_turns，"
            f"实际 {captured['state']['effective_max_turns']}"
        )

        # 改配置后再次调用，应立即跟随（无需重启、无需重建实例）
        settings.max_reasoning_turns = 8
        client.post("/api/v1/chat", json={"message": "再测"}, headers=admin_headers)
        assert captured["state"]["effective_max_turns"] == 8, (
            "max_reasoning_turns 应在每次请求时重新读取，实际未跟随"
        )
