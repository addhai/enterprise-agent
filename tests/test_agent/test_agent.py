"""客服 Agent 单测 —— 确定性版本（迁移自旧的 test_agent.py）。

迁移说明（资深开发把关）：
    旧版 `test_agent.py` 直连真实大模型，且无 API Key 时直接 `pytest.skip`，
    导致 CI "假绿"、覆盖率失真、本地无法复现。
    现统一改用注入式 `FakeLLMClient`，三个原始场景原意不变，但完全确定性、
    不依赖网络 / API Key，CI 稳定可信。

    对真实 LLM 的端到端行为（如"达到 max_turns 后停止"）保留为
    显式开启的集成冒烟测试（见文件底部 `live_agent` fixture），默认跳过，
    避免污染确定性 CI，同时不丢失端到端覆盖。
"""

import os

import pytest

from src.agent.agent import CustomerServiceAgent
from src.agent.fake_llm import FakeLLMClient


def test_agent_answers_simple_question(make_agent):
    """场景1（迁移）：Agent 应能回答简单的 FAQ 问题。

    确定性改造：注入 FakeLLMClient 返回包含关键词的回复，取代真实模型调用。
    """
    agent = make_agent(
        reply="重置密码的方法是：进入设置页，点击「忘记密码」，按提示验证身份后重设即可。"
    )
    result = agent.run("How do I reset my password?")

    assert isinstance(result, str)
    assert len(result) > 20
    # 应提到密码重置相关词
    assert any(
        word in result.lower() for word in ["password", "reset", "密码", "重置"]
    )


def test_agent_handles_greeting(make_agent):
    """场景2（迁移）：Agent 应能处理问候。"""
    agent = make_agent(reply="你好！我是您的智能客服助手，有什么可以帮您？")
    result = agent.run("Hello!")

    assert isinstance(result, str)
    assert len(result) > 5


def test_agent_max_turns_configured(make_agent):
    """场景3（迁移）：对知识库外的刁钻问题，Agent 应给出安全、非空的终止回复，
    且 max_turns 配置已正确接线（正整数）。

    说明：原测试依赖真实 LangGraph agent 在多轮后停止；
    轮次终止是运行时行为（由集成测试覆盖）。确定性范式下，此处验证：
      1) 任意输入都能稳定返回、不挂起、不崩溃；
      2) max_turns 已接入配置（正整数），作为终止逻辑的前置契约。
    """
    agent = make_agent(reply="抱歉，这个问题我需要帮您转接人工客服。")
    assert isinstance(agent.max_turns, int) and agent.max_turns > 0

    result = agent.run(
        "What is the meaning of life and quantum physics applied to cloud sync?"
    )
    assert isinstance(result, str)
    assert result  # 非空、不挂起、不崩溃


# =============================================================================
# 集成冒烟测试（默认跳过，仅显式开启 + 配置 API Key 时运行）
# 目的：保留真实 LLM 端到端行为覆盖（如 max_turns 终止），不污染确定性 CI。
# =============================================================================
@pytest.fixture
def live_agent():
    """仅在显式开启集成测试且配置了 API Key 时返回真实 Agent。"""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    if not os.environ.get("RUN_INTEGRATION_TESTS"):
        pytest.skip("set RUN_INTEGRATION_TESTS=1 to run real-LLM integration tests")
    return CustomerServiceAgent(max_turns=3)


@pytest.mark.integration
def test_agent_real_stops_after_max_turns(live_agent):
    """真实 LLM 端到端：刁钻问题应在 max_turns 内停止并最终给出回复。"""
    result = live_agent.run(
        "What is the meaning of life and quantum physics applied to cloud sync?"
    )
    assert result is not None
    assert isinstance(result, str)
