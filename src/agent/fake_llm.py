"""可注入的 LLM 客户端抽象 —— 让 Agent 可测试、可替换。

背景（资深开发把关）：
    原 `CustomerServiceAgent` 在 `__init__` 里直接 `ChatOpenAI(**kwargs)` 并
    `create_agent(...)`，导致任何测试都必须真实调用大模型（或 `skip`）。
    这正是测试"假绿"、覆盖率上不去的根因。

修复思路：
    1. 定义 `LLMClient` 协议（最小接口），Agent 只依赖协议，不依赖具体实现。
    2. 生产用 `OpenAILLMClient`（包装 ChatOpenAI）；测试用 `FakeLLMClient`。
    3. Agent 通过构造参数 `llm_client` 注入，默认走生产实现，保持向后兼容。

这样单测可完全确定性运行，不依赖网络 / API Key，CI 才能稳定、快速、可信。
"""

from __future__ import annotations

from typing import Any, List, Optional, Protocol, runtime_checkable

from langchain_core.messages import AIMessage, BaseMessage


@runtime_checkable
class LLMClient(Protocol):
    """Agent 对 LLM 的最小依赖契约。

    只暴露 Agent 真正用到的方法，避免把整个 LangChain 链暴露给业务层，
    也方便在测试里用极简假实现替代。
    """

    def invoke(self, input: dict) -> dict:
        """执行一次推理，返回与 LangGraph agent 相同结构的 dict。

        约定返回结构： {"messages": [..., AIMessage]}
        """
        ...


class OpenAILLMClient:
    """生产实现：包装 ChatOpenAI + LangGraph create_agent。

    把"如何构建 agent"的细节收敛到这里，业务代码（Agent）只认 LLMClient 协议。
    """

    def __init__(
        self,
        tools: List[Any],
        system_prompt: str,
        *,
        model: str,
        api_key: str,
        base_url: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        enable_thinking: bool = False,
    ) -> None:
        from langchain_openai import ChatOpenAI
        from langchain.agents import create_agent

        llm_kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if enable_thinking:
            llm_kwargs["model_kwargs"] = {"extra_body": {"enable_thinking": True}}

        self.llm = ChatOpenAI(**llm_kwargs)
        self.agent = create_agent(self.llm, tools=tools, system_prompt=system_prompt)

    def invoke(self, input: dict) -> dict:
        return self.agent.invoke(input)


class FakeLLMClient:
    """测试用假实现：完全确定性，不触网、不需要 API Key。

    用法：
        fake = FakeLLMClient([AIMessage(content="重置密码：...")])
        agent = CustomerServiceAgent(llm_client=fake, ...)
        assert "重置" in agent.run("如何重置密码？")
    """

    def __init__(
        self,
        messages: Optional[List[BaseMessage]] = None,
        *,
        content: str = "这是一个确定性的假回复。",
        raise_on_invoke: Optional[Exception] = None,
    ) -> None:
        # 允许直接传字符串，也允许传完整消息列表
        if messages is not None:
            self._messages = list(messages)
        else:
            self._messages = [AIMessage(content=content)]
        self._raise = raise_on_invoke

    def invoke(self, input: dict) -> dict:  # noqa: ANN001 - 保持与协议一致
        if self._raise is not None:
            raise self._raise
        # 透传输入里的历史消息，再追加预设的"最终回复"，模拟真实 agent 结构
        history: List[BaseMessage] = list(input.get("messages", []))
        return {"messages": history + self._messages}
