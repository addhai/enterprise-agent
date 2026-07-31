"""公共测试 fixtures —— 团队测试范式样板。

资深开发把关要点：
    1. 测试一律确定性：外部依赖（LLM / DB / Redis / HTTP）走注入或 mock，
       不依赖真实 API Key、不触网。CI 才能稳定、快速、可信。
    2. `asyncio_mode=auto` 已在 pyproject.toml 配置，异步测试无需手标。
"""

import pytest

from src.agent.fake_llm import FakeLLMClient


@pytest.fixture
def fake_llm_client():
    """返回一个确定性假 LLM：固定回复，不涉及任何外部调用。"""
    return FakeLLMClient(
        content="这是一段确定性的测试回复，包含关键词：密码重置。"
    )


@pytest.fixture
def fake_llm_error():
    """返回一个会抛出可重试错误的假 LLM，用于验证异常安全路径。"""
    return FakeLLMClient(
        content="",
        raise_on_invoke=RuntimeError("upstream 503 Service Unavailable"),
    )


@pytest.fixture
def make_agent():
    """工厂 fixture：用注入式假 LLM 构造 Agent，无需 API Key。

    用法：
        def test_xxx(make_agent):
            agent = make_agent(reply="你好，我是客服。")
            assert "客服" in agent.run("你好")
    """

    def _make(reply: str = "默认回复", raise_on_invoke=None):
        from src.agent.agent import CustomerServiceAgent

        client = FakeLLMClient(content=reply, raise_on_invoke=raise_on_invoke)
        return CustomerServiceAgent(
            user_id="test_user",
            tenant_id="test_tenant",
            llm_client=client,
        )

    return _make
