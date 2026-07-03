from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from src.config import settings
from src.agent.prompt import build_prompt
from src.agent.tools import create_tools


class CustomerServiceAgent:
    """基于 ReAct 范式的客服 Agent (使用 langchain create_agent + LangGraph)"""

    def __init__(self, retriever=None, user_id: str = "", max_turns: int = None,
                 memory_context: str = "", tenant_id: str = "",
                 user_access_levels: Optional[List[str]] = None,
                 user_roles: Optional[List[str]] = None,
                 user_plan: str = "free"):
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
        self.tools = create_tools(
            retriever=retriever,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            user_access_levels=self.user_access_levels,
            roles=self.user_roles,
            plan=self.user_plan,
        )

        # 创建 LLM
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
            temperature=0.1,
        )

        # 构建 System Prompt（含工具描述 + 长期记忆上下文）
        system_prompt = build_prompt(self.tools, memory_context=memory_context)

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

        # 将历史消息转换为 langchain 消息格式
        messages = []
        for human_msg, ai_msg in history:
            messages.append(HumanMessage(content=human_msg))
            messages.append(AIMessage(content=ai_msg))
        messages.append(HumanMessage(content=user_message))

        try:
            result = self.agent.invoke({"messages": messages})
            # 提取最后的 AI 消息作为输出
            output_messages = result.get("messages", [])
            if output_messages:
                last = output_messages[-1]
                if hasattr(last, "content"):
                    return last.content
            return "抱歉，我暂时无法处理您的请求。"
        except Exception as e:
            return f"处理您的请求时出现错误。正在为您转接人工客服。[{str(e)[:100]}]"

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
