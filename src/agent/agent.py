from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from src.config import settings
from src.agent.prompt import build_prompt
from src.agent.tools import create_tools
from src.agent.fake_llm import LLMClient
from src.core.exceptions import AgentRuntimeError, safe_message
from src.core.logging import get_logger, new_request_id

logger = get_logger(__name__)


class CustomerServiceAgent:
    """基于 ReAct 范式的客服 Agent (使用 langchain create_agent + LangGraph)

    依赖注入：通过 `llm_client` 参数注入 LLM 实现，默认使用生产实现
    `OpenAILLMClient`。测试可传入 `FakeLLMClient` 获得完全确定性的行为，
    无需真实 API Key / 网络（见 `tests/test_agent/test_agent_deterministic.py`）。
    """

    def __init__(self, retriever=None, user_id: str = "", max_turns: int = None,
                 memory_context: str = "", tenant_id: str = "",
                 user_access_levels: Optional[List[str]] = None,
                 user_roles: Optional[List[str]] = None,
                 user_plan: str = "free",
                 llm_client: Optional[LLMClient] = None):
        self.max_turns = max_turns or settings.max_reasoning_turns
        self.user_id = user_id or "anonymous"
        self.tenant_id = tenant_id
        self.user_access_levels = user_access_levels or [
            "public", "internal", "confidential", "restricted"
        ]
        self.user_roles = user_roles or []
        self.user_plan = user_plan
        self.memory_context = memory_context

        # 创建工具（传入完整身份上下文 + 权限检查器）
        # 对话 Agent 显式开启工单 + 资源查询工具，使"对话中开工单 / 查资源"可用
        self.tools = create_tools(
            retriever=retriever,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            user_access_levels=self.user_access_levels,
            roles=self.user_roles,
            plan=self.user_plan,
            include_ticket=True,
            include_resource=True,
        )

        # 构建 System Prompt（含工具描述 + 长期记忆上下文）
        system_prompt = build_prompt(self.tools, memory_context=memory_context)

        if llm_client is not None:
            # 注入模式（测试 / 自定义后端）：直接使用外部提供的 LLM 客户端
            self.llm = None
            self.agent = llm_client
            return

        # 生产模式：创建 LLM（对齐阿里云百炼 AI 助理参数）
        llm_kwargs = {
            "model": settings.llm_model,
            "api_key": settings.openai_api_key,
            "base_url": settings.openai_api_base,
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
        }
        # 思考模式（仅在启用时传递，避免不支持的模型报错）
        if settings.llm_enable_thinking:
            llm_kwargs["model_kwargs"] = {"extra_body": {"enable_thinking": True}}
        self.llm = ChatOpenAI(**llm_kwargs)

        # 创建 Agent (LangGraph-based)
        self.agent = create_agent(
            self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
        )

    def run(self, user_message: str, chat_history: list = None) -> str:
        """处理用户消息并返回回复

        Args:
            user_message: 用户输入
            chat_history: 对话历史，格式为 [(human_msg, ai_msg), ...]

        Returns:
            Agent 的最终回复
        """
        history = chat_history or []

        # 按 context_rounds 截断（对齐阿里云百炼携带上下文轮数）
        # getattr 防御：旧版 config.py 可能无此字段，默认 10 轮
        _ctx_rounds = getattr(settings, "context_rounds", 10)
        if _ctx_rounds > 0:
            history = history[-_ctx_rounds:]

        # 将历史消息转换为 langchain 消息格式
        messages = []
        for human_msg, ai_msg in history:
            messages.append(HumanMessage(content=human_msg))
            messages.append(AIMessage(content=ai_msg))
        messages.append(HumanMessage(content=user_message))

        # 每次请求生成 request_id，用于日志关联与用户反馈（对外仅暴露 ID，不暴露细节）
        request_id = new_request_id()
        try:
            result = self.agent.invoke({"messages": messages})
            # 提取最后的 AI 消息作为输出
            output_messages = result.get("messages", [])
            if output_messages:
                last = output_messages[-1]
                # 上报 token 用量（从 response_metadata 提取）
                self._report_token_usage(last)
                if hasattr(last, "content"):
                    return last.content
            logger.warning("agent returned no message req=%s", request_id)
            return "抱歉，我暂时无法处理您的请求。如持续异常请凭会话 ID 联系支持。"
        except Exception as e:  # noqa: BLE001 - 兜底，但必须安全处理
            # 内部细节（堆栈/第三方报错）只进日志，绝不回显给用户（安全红线）
            logger.error("agent invoke failed req=%s", request_id, exc_info=e)
            return AgentRuntimeError(
                f"处理您的请求时出现错误，已为您转接人工客服。"
                f"如持续异常请凭会话 ID {request_id} 联系支持。",
                request_id=request_id,
                cause=e,
            ).safe_message

    def _report_token_usage(self, message) -> None:
        """从 AIMessage.response_metadata 提取 token 用量并上报 metrics"""
        try:
            meta = getattr(message, "response_metadata", None) or {}
            token_usage = meta.get("token_usage") or meta.get("usage") or {}
            prompt = token_usage.get("prompt_tokens") or token_usage.get("input_tokens", 0)
            completion = token_usage.get("completion_tokens") or token_usage.get("output_tokens", 0)
            if prompt or completion:
                from src.api.metrics import record_llm_tokens
                record_llm_tokens(
                    model=settings.llm_model,
                    prompt_tokens=int(prompt),
                    completion_tokens=int(completion),
                    tenant_id=self.tenant_id or "default",
                )
        except Exception as e:  # noqa: BLE001 - 上报失败不影响主流程，但必须可观测
            # 旧代码为 `except Exception: pass`，导致线上完全盲区。
            # 改为结构化日志：至少留痕，便于排查 token 计费/上报链路问题。
            logger.warning(
                "token usage report skipped tenant=%s: %s", self.tenant_id or "default", e
            )

    def run_with_trace(self, user_message: str, chat_history: list = None) -> dict:
        """处理消息并返回完整结果（含中间步骤）"""
        history = chat_history or []

        messages = []
        for human_msg, ai_msg in history:
            messages.append(HumanMessage(content=human_msg))
            messages.append(AIMessage(content=ai_msg))
        messages.append(HumanMessage(content=user_message))

        result = self.agent.invoke({"messages": messages})

        output_messages = result.get("messages", [])
        output = ""
        if output_messages:
            last = output_messages[-1]
            if hasattr(last, "content"):
                output = last.content

        return {
            "output": output,
            "intermediate_steps": result.get("intermediate_steps", []),
        }
