"""可协作式取消的 ChatOpenAI

只做一件事：在每次同步 ``_generate`` 前后调用
:func:`src.graph.cancellation.check_cancelled`。会话被取消或硬超时到期时，
在下一次 LLM 调用边界抛 WorkflowCancelled，让 langgraph 快速收卷，
避免 WS 断开后 7B 在 CPU 上继续跑完整个 ReAct（生产实测空跑 88 分钟）。

为什么放在 _generate 这一层：
    意图分类、澄清、直答合成、反思、ReAct 内部多轮工具调用，所有同步对话
    补全都经过 BaseChatModel._generate（bind_tools 返回的 RunnableBinding
    最终也回调被绑定模型的 _generate）。守住这里就守住了全部 LLM 调用边界，
    无需往每个图节点里撒检查点。

未绑定 workflow_run 的场景（离线评测、脚本、单测）检查为空操作，
行为与原生 ChatOpenAI 完全一致。
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from src.config import settings
from src.graph.cancellation import check_cancelled


class CancellableChatOpenAI(ChatOpenAI):
    """带协作式取消检查的 ChatOpenAI（同步路径）"""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ):
        # 请求前：取消信号已到就不发这次 HTTP 请求，直接收卷
        check_cancelled()
        result = super()._generate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )
        # 请求后：在途期间断开/超时的信号也要生效，阻止进入下一轮 ReAct
        check_cancelled()
        return result


def make_chat_model(**kwargs: Any) -> CancellableChatOpenAI:
    """构造对话补全模型的统一工厂。

    默认补单次请求超时（CPU ollama 上单次生成可能数分钟，无超时则一次挂死
    就会永久占住线程，协作式取消也得等它返回）。显式传入 timeout 可覆盖。
    """
    kwargs.setdefault("timeout", float(settings.llm_request_timeout))
    return CancellableChatOpenAI(**kwargs)
