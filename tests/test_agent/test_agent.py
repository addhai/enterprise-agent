import pytest
import os
from src.agent.agent import CustomerServiceAgent


@pytest.fixture
def agent():
    """创建 Agent（需要 API Key）"""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    return CustomerServiceAgent(max_turns=3)


def test_agent_answers_simple_question(agent):
    """Agent 应能回答简单的 FAQ 问题"""
    result = agent.run("How do I reset my password?")

    assert result is not None
    assert len(result) > 20
    # 应该提到密码重置
    assert any(word in result.lower() for word in ["password", "reset", "密码"])


def test_agent_handles_greeting(agent):
    """Agent 应能处理问候"""
    result = agent.run("Hello!")
    assert result is not None
    assert len(result) > 5


def test_agent_stops_after_max_turns(agent):
    """Agent 应在达到最大回合后停止"""
    # 问一个知识库里没有的刁钻问题
    result = agent.run("What is the meaning of life and quantum physics applied to cloud sync?")
    assert result is not None
    # Agent 应该在几轮后调用 escalate_to_human 或给出最终回答
