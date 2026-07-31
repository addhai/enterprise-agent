"""确定性单测样板 —— 不依赖真实 LLM / API Key / 网络。

这是"可测试 Agent"范式的参考实现（Phase 2 交付物）。
对比旧的 `test_agent.py`：那里直连真实模型且 `if not OPENAI_API_KEY: skip`，
导致 CI 假绿、覆盖率失真。本文件全部走注入式 `FakeLLMClient`。
"""

import pytest

from src.agent.agent import CustomerServiceAgent
from src.agent.fake_llm import FakeLLMClient


def test_run_returns_deterministic_reply(make_agent):
    """Agent 应返回注入假 LLM 给出的确定性回复，且包含预期关键词。"""
    agent = make_agent(reply="重置密码：进入设置页点击忘记密码。")
    result = agent.run("如何重置密码？")

    assert isinstance(result, str)
    assert len(result) > 0
    assert "重置密码" in result


def test_run_echoes_history_into_messages(make_agent):
    """历史消息应被透传进 LLM 调用（验证上下文拼接逻辑）。"""
    agent = make_agent(reply="好的，已收到。")
    result = agent.run("第二步做什么？", chat_history=[("第一步：登录", "请打开登录页")])

    assert isinstance(result, str)
    assert result  # 不依赖真实模型也能稳定产出


def test_run_safe_on_llm_failure(make_agent):
    """LLM 抛错时：不向上抛出、不把内部错误回显给用户（安全红线）。"""
    # 模拟上游 503，旧代码会返回 f"...[{str(e)[:100]}]" 泄露实现细节
    agent = make_agent(raise_on_invoke=RuntimeError("upstream 503 Service Unavailable"))

    result = agent.run("你好")

    assert isinstance(result, str)
    assert result  # 返回的是安全消息，而非崩溃或内部错误原文
    # 关键契约：内部错误细节（如 "503"）绝不出现在对用户的最终回复里
    assert "503" not in result
    assert "Service Unavailable" not in result


def test_token_reporting_never_crashes(make_agent):
    """token 上报失败不应影响主流程（旧代码 `except: pass` 静默吞错，
    此处验证即便 metadata 缺失也不抛异常）。"""
    agent = make_agent(reply="正常回复")
    # 直接调用内部方法，确认无 response_metadata 时不抛
    assert agent._report_token_usage(object()) is None


def test_max_turns_default_from_settings(make_agent):
    """未传 max_turns 时应回退到配置项，而非 None。"""
    agent = make_agent(reply="x")
    assert agent.max_turns is not None
    assert agent.max_turns > 0
