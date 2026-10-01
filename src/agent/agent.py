from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
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
            # 注入模式（测试 / 自定义后端）：直接使用外部提供的 LLM 客户端。
            # 注入模式下不参与热重建：外部客户端由调用方负责生命周期，
            # 我们无从按新配置重建它（它可能根本不是 ChatOpenAI 实例）。
            self.llm = None
            self.agent = llm_client
            self._injected_llm = True
            self._llm_config_version = None
            return

        self._injected_llm = False
        # 工具与 System Prompt 只构造一次，重建 LLM 时复用：
        # 它们持有 retriever / 权限上下文，且不随 LLM 参数变化，没必要跟着重建。
        self._system_prompt = system_prompt
        # 构造时记下配置版本，供 _ensure_llm_current() 比对。
        # 取不到配置中心（例如纯脚本环境未初始化）时退化为 None，
        # 此时 _ensure_llm_current() 不做任何事，行为与改造前一致。
        self._llm_config_version = None
        self._build_llm_and_agent()
        self._llm_config_version = self._current_config_version()

    def _current_config_version(self):
        """读取配置中心当前版本号；不可用时返回 None

        为什么要用「配置中心版本」而不是自己拼一个配置指纹：
            配置中心已经在每次真实变更时自增 version（service.set_value），
            它才是「配置变过没有」的权威判据。自己拼指纹（如把所有 LLM 相关
            字段拼成元组）会漏字段，且与配置中心的变更语义脱节。
        """
        try:
            from src.config_center import get_config_center

            return get_config_center().version
        except Exception as e:  # noqa: BLE001
            logger.debug("配置中心不可用，LLM 热重建关闭: %s", e)
            return None

    def _build_llm_and_agent(self) -> None:
        """按当前 settings 构造 LLM 与内部 Agent

        单独抽成方法的原因：热更新时需要「重放一次构造」。
        生产中配置变更后要能用新参数重建，把这段逻辑内联在 __init__ 里
        就没法复用（测试也正是对着这个方法打桩的）。
        """
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
            system_prompt=getattr(self, "_system_prompt", None)
            or build_prompt(self.tools, memory_context=self.memory_context),
        )

    def _ensure_llm_current(self) -> None:
        """配置版本变化时重建 LLM 与内部 Agent；未变化则什么都不做

        为什么需要（热更新的缺口）：
            项目里图路径上的 Agent 是「每次调用新建」的（nodes.py 在节点函数内
            构造），这类调用天然读到最新 settings。但**同一个实例被复用**时
            （例如长连接会话、外部持有 agent 对象），__init__ 里构造的 ChatOpenAI
            会把当时的 temperature / max_tokens 固化下来，之后改配置不生效。
            本方法补上这个缺口。

        为什么用「比对版本号」而不是「每次都重建」：
            无条件重建会让每次 run() 都付一次 ChatOpenAI + create_agent 的
            构造成本，且会让实例 id 无意义地变化。版本号未变就跳过。

        注入模式（llm_client 非空）下直接返回：外部客户端的生命周期不归我们管。
        """
        if getattr(self, "_injected_llm", False):
            return

        current = self._current_config_version()
        if current is None:
            # 配置中心不可用，无法判定变更，保持现状（不冒险重建）
            return
        if current == self._llm_config_version:
            return

        logger.info(
            "LLM 配置版本变更 %s → %s，重建 LLM 与内部 Agent",
            self._llm_config_version,
            current,
        )
        self._build_llm_and_agent()
        self._llm_config_version = current

    def run(self, user_message: str, chat_history: list = None) -> str:
        """处理用户消息并返回回复

        Args:
            user_message: 用户输入
            chat_history: 对话历史，格式为 [(human_msg, ai_msg), ...]

        Returns:
            Agent 的最终回复
        """
        # 复用同一实例时，配置改了要能用新参数重建 LLM（见 _ensure_llm_current）
        self._ensure_llm_current()

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
            result = self._invoke_agent(messages)
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
        except GraphRecursionError:
            # 轮次耗尽：与「下游报错」性质不同，单独归类便于监控区分。
            # 触发意味着模型反复产出无法解析的工具调用，是提示词或工具描述
            # 需要调整的信号，不能和普通异常混在一起统计。
            logger.warning(
                "agent 命中轮次上限 req=%s max_turns=%s", request_id, self.max_turns
            )
            return (
                "抱歉，这个问题需要多步查询，我暂时没能收敛到答案。"
                "建议您把问题拆得更具体一些，或直接凭会话 ID 联系人工客服协助。"
            )
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

    def _build_run_config(self) -> dict:
        """把 max_turns 换算成 LangGraph 的 recursion_limit

        为什么必须有这个换算（真实线上故障，勿删）：
            max_reasoning_turns 曾是个从未被消费的死配置：它只被存进
            self.max_turns，而 self.agent.invoke() 没传 recursion_limit。
            模型一旦反复输出无法解析的工具调用，图会无限重试——实测一次提问
            产生 24 次 chat/completions、0 次工具执行、15 分钟无回答，
            客户端超时后服务端还在继续推理。

        公式取 2 * max_turns + 4：
            LangGraph 里一次「模型思考 + 执行工具」算 2 个 superstep，故主体是
            2 * max_turns；再加 4 个 superstep 作为首尾余量（入口/收尾各占一步）。
            实测 max_turns=5 得 14，与线上验证过的取值一致。

        边界：max_turns 为 0 或负数时取 1（否则 recursion_limit 会 <= 4，
        图可能一步都走不完就报错，反而把降级路径变成异常路径）。
        """
        turns = self.max_turns
        if not (isinstance(turns, int) and turns > 0):
            turns = 1
        return {"recursion_limit": 2 * turns + 4}

    def _invoke_agent(self, messages: list) -> dict:
        """调用内部 Agent 并返回原始结果

        两种实现协议不同，必须按模式分派：
            真实 LangGraph 图（self.llm 非 None）：invoke(input, config)，
                必须带上 recursion_limit，否则轮次上限形同虚设。
            注入的替身（self.llm 为 None）：替身按单参数协议实现
                （tests 的 _FakeGraph 只有一个位置参数），多传 config 会 TypeError。

        为什么单独抽一层（而不是各处直接 self.agent.invoke）：
            ① 测试可以在不打桩 LLM 的前提下替换它，避免真实网络调用；
            ② 热重建会替换 self.agent，直接内联调用会与重建逻辑耦合，
               抽出后替换点收敛在一处。
        """
        if self.llm is None:
            # 注入模式：保持单参数调用协议不变
            return self.agent.invoke({"messages": messages})
        return self.agent.invoke({"messages": messages}, self._build_run_config())

    def run_with_trace(self, user_message: str, chat_history: list = None) -> dict:
        """处理消息并返回完整结果（含中间步骤）"""
        # 与 run() 同源：复用实例时也要感知配置变更
        self._ensure_llm_current()

        history = chat_history or []

        messages = []
        for human_msg, ai_msg in history:
            messages.append(HumanMessage(content=human_msg))
            messages.append(AIMessage(content=ai_msg))
        messages.append(HumanMessage(content=user_message))

        try:
            result = self._invoke_agent(messages)
        except GraphRecursionError:
            # 轮次耗尽降级：必须保持与正常返回完全一致的结构，
            # 否则下游 rag_node（读 output / messages）会因缺键而二次报错。
            logger.warning(
                "run_with_trace 命中轮次上限 max_turns=%s", self.max_turns
            )
            return {
                "output": (
                    "抱歉，这个问题需要多步查询，我暂时没能收敛到答案。"
                    "建议您把问题拆得更具体一些。"
                ),
                "intermediate_steps": [],
                "messages": [],
            }

        output_messages = result.get("messages", [])
        output = ""
        if output_messages:
            last = output_messages[-1]
            if hasattr(last, "content"):
                output = last.content

        return {
            "output": output,
            "intermediate_steps": result.get("intermediate_steps", []),
            # LangGraph create_agent 的工具结果在 messages 的 ToolMessage 里，
            # 不在 intermediate_steps（那是旧 AgentExecutor 格式）。
            # rag_node 需要从这里抽资源工具的真实返回做「引用可溯源」气泡。
            "messages": output_messages,
        }
