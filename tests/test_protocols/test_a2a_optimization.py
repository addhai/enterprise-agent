"""Agent 通信与协调效率优化测试

覆盖本轮三处优化：
  A. A2A Agent Card + Client 缓存（delegate_to_expert 不再每次重拉 Card）
  B. 专家委托 LangChain 工具异步化（去掉 _asyncio.run，真正成为 async 工具）
  C. Orchestrator 并行扇出 + 聚合（多专家协同真正并发，异常隔离）
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# ===========================================================================
# A. AgentCardCache 单元测试（纯逻辑，无需网络）
# ===========================================================================


class TestAgentCardCache:
    @pytest.mark.asyncio
    async def test_set_then_get(self):
        from src.protocols.a2a_cache import AgentCardCache

        cache = AgentCardCache(default_ttl=60.0)
        await cache.set("http://x:1", "card1", "client1")
        card, client = await cache.get("http://x:1")
        assert card == "card1"
        assert client == "client1"

    @pytest.mark.asyncio
    async def test_expiry(self):
        from src.protocols.a2a_cache import AgentCardCache

        cache = AgentCardCache(default_ttl=0.01)
        await cache.set("http://x:2", "card2", "client2")
        await asyncio.sleep(0.02)
        card, client = await cache.get("http://x:2")
        assert card is None
        assert client is None
        # 过期条目应已被剔除
        assert cache.size() == 0

    @pytest.mark.asyncio
    async def test_clear(self):
        from src.protocols.a2a_cache import AgentCardCache

        cache = AgentCardCache(default_ttl=60.0)
        await cache.set("http://x:3", "c", "cl")
        await cache.clear()
        assert cache.size() == 0


# ===========================================================================
# A. delegate_to_expert 缓存命中：同一 URL 只拉一次 Card
# ===========================================================================


class _FakeResolver:
    calls = 0

    def __init__(self, http_client, url):
        self.http_client = http_client
        self.url = url

    async def get_agent_card(self):
        _FakeResolver.calls += 1
        return SimpleNamespace(name="fake-expert", description="fake")


class _FakeEvent:
    def __init__(self, text):
        self.parts = [SimpleNamespace(text=text)]


class _FakeAgentClient:
    def __init__(self, text):
        self._text = text

    async def send_message(self, message):
        yield _FakeEvent(self._text)


class _FakeFactory:
    def __init__(self, config):
        self.config = config

    def create(self, card):
        return _FakeAgentClient("EXPERT-OK")


class TestDelegateToExpertCaching:
    def setup_method(self):
        _FakeResolver.calls = 0

    def teardown_method(self):
        asyncio.run(_close_and_reset())

    def test_card_fetched_once_across_two_delegations(self):
        async def _run():
            from src.protocols.a2a_cache import reset_agent_card_cache
            from src.protocols.a2a_server import delegate_to_expert

            await reset_agent_card_cache()
            url = "http://localhost:9911"

            with (
                patch("a2a.client.A2ACardResolver", _FakeResolver),
                patch("a2a.client.ClientFactory", _FakeFactory),
            ):
                r1 = await delegate_to_expert("q", url, timeout=5)
                r2 = await delegate_to_expert("q", url, timeout=5)

            assert r1 == "EXPERT-OK"
            assert r2 == "EXPERT-OK"
            # 第二次委托应命中缓存，不再调用 get_agent_card
            assert _FakeResolver.calls == 1

        asyncio.run(_run())


async def _close_and_reset():
    from src.protocols.a2a_cache import get_agent_card_cache, reset_agent_card_cache

    cache = get_agent_card_cache()
    # 关闭缓存中遗留的 httpx client，避免资源泄漏
    for _, client, _ in list(cache._store.values()):
        try:
            if client is not None:
                await client.aclose()
        except Exception:
            pass
    await reset_agent_card_cache()


# ===========================================================================
# B. 专家委托 LangChain 工具异步化
# ===========================================================================


class TestDelegationTools:
    def test_sync_invoke_returns_expert_result(self):
        """向后兼容：原有 .invoke（同步）调用仍可用，返回本地回退的专家结果"""
        from src.protocols.a2a_server import delegate_to_performance_expert

        # 真实路径下会尝试 A2A 失败 → 本地回退，断言结构不崩即可
        res = delegate_to_performance_expert.invoke(
            {"query": "sync stuck for 30 minutes"}
        )
        assert isinstance(res, str)
        assert "性能专家诊断结果" in res
        assert "同步卡住" in res

    def test_tool_bridges_to_async_delegation(self):
        """工具通过 _asyncio.run 正确桥接到底层异步委托协程（封闭变更点）"""
        from src.protocols.a2a_server import delegate_to_performance_expert

        async def fake_delegate(query):
            return "MOCK PERF RESULT"

        with patch(
            "src.protocols.a2a_server.delegate_to_perf_expert", new=fake_delegate
        ):
            res = delegate_to_performance_expert.invoke({"query": "x"})

        assert res == "[性能专家诊断结果]\nMOCK PERF RESULT"


# ===========================================================================
# C. Orchestrator 并行扇出 + 聚合 + 异常隔离
# ===========================================================================


class TestOrchestratorFanOut:
    def setup_method(self):
        from src.protocols.agent_registry import register_default_agents, registry

        registry.clear()
        register_default_agents()

    def test_fan_out_parallel_and_aggregate(self):
        from src.protocols.orchestrator_agent import Orchestrator

        orch = Orchestrator()

        async def fake_delegate(aid, query):
            return f"response-from-{aid}"

        orch.delegate_to_agent = fake_delegate

        # "stuck" 命中性能，"api key" 命中安全；"api key" 同时是客服关键词 → 三者协同
        result = asyncio.run(
            orch.orchestrate("My sync is stuck and my API key leaked on GitHub")
        )

        matched = result["routing"]["matched_agents"]
        # 并行委托了全部命中 agent
        assert len(result["responses"]) == len(matched)
        for a in matched:
            assert a["agent_id"] in result["responses"]

        # 聚合结果包含各 agent 来源标注
        assert all(a["agent_id"] in result["final_response"] for a in matched)
        # coordinated_agents 与 responses 一致（可观测）
        assert set(result["coordinated_agents"]) == set(result["responses"].keys())

    def test_fan_out_exception_isolation(self):
        from src.protocols.orchestrator_agent import Orchestrator

        orch = Orchestrator()

        async def fake_delegate(aid, query):
            if aid == "performance_expert":
                raise RuntimeError("boom")
            return f"response-from-{aid}"

        orch.delegate_to_agent = fake_delegate

        result = asyncio.run(
            orch.orchestrate("My sync is stuck and my API key leaked on GitHub")
        )

        # 单个 agent 失败 → 标记 No response，不影响其他 agent
        assert result["responses"]["performance_expert"] == "No response"
        assert (
            result["responses"].get("security_expert")
            == "response-from-security_expert"
        )
        # 聚合时失败 agent 不应让整体崩掉
        assert "security_expert" in result["final_response"]

    def test_single_agent_backward_compat(self):
        """单 agent 命中时 final_response 语义与旧版一致（直接取该 agent 回复）"""
        from src.protocols.orchestrator_agent import Orchestrator

        orch = Orchestrator()

        async def fake_delegate(aid, query):
            return f"response-from-{aid}"

        orch.delegate_to_agent = fake_delegate

        result = asyncio.run(orch.orchestrate("How do I set up SSO?"))
        assert result["routing"]["best_match"] == "customer_service"
        assert result["final_response"] == "response-from-customer_service"
