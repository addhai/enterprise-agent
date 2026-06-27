"""LangGraph 工作流节点"""
from typing import Any, Dict
from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from src.config import settings
from src.graph.state import AgentState
from src.agent.tools import _faq_search
from src.agent.agent import CustomerServiceAgent


# 共享的 LLM 实例（用于意图分类，延迟初始化以避免无 API Key 时导入失败）
_intent_llm: ChatOpenAI = None


def _get_intent_llm() -> ChatOpenAI:
    """获取或初始化意图分类 LLM"""
    global _intent_llm
    if _intent_llm is None:
        _intent_llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
            temperature=0.0,
        )
    return _intent_llm


def entry_node(state: AgentState) -> Dict[str, Any]:
    """入口节点：初始化对话状态"""
    return {
        "turn_count": state.get("turn_count", 0) + 1,
        "intent": None,
        "needs_human": False,
        "faq_match": None,
        "effective_max_turns": 5,  # 默认值，router_node 会根据意图调整
        "has_reflected": False,
    }


def router_node(state: AgentState) -> Dict[str, Any]:
    """意图路由节点：分析用户意图，决定走哪条路径"""
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "faq"}

    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    # 简单规则 + LLM 分类
    human_keywords = [
        "talk to human", "speak to agent", "real person",
        "转人工", "人工客服", "投诉", "complaint",
        "退款", "refund", "cancel my account",
    ]

    if any(kw in content.lower() for kw in human_keywords):
        return {"intent": "human", "effective_max_turns": settings.max_turns_faq}

    # 快速规则判断 FAQ vs Technical
    faq_keywords = [
        "reset password", "forgot password", "change plan",
        "pricing", "how much", "cancel subscription",
        "api key", "enable 2fa", "two factor",
    ]

    if any(kw in content.lower() for kw in faq_keywords):
        return {"intent": "faq", "effective_max_turns": settings.max_turns_faq}

    # 其他情况尝试 LLM 分类
    try:
        llm = _get_intent_llm()
        classification = llm.invoke(
            f"将以下用户消息分类为 'faq'（简单常见问题）、'technical'（需要技术文档）或 'human'（需要人工客服）。"
            f"只返回一个词。\n\n用户消息：{content[:500]}"
        )
        intent = classification.content.strip().lower()
        if intent in ["faq", "technical", "human"]:
            # 根据意图设定动态 max_turns
            turns_map = {
                "faq": settings.max_turns_faq,
                "technical": settings.max_turns_technical,
                "human": settings.max_turns_faq,
            }
            return {"intent": intent, "effective_max_turns": turns_map.get(intent, 5)}
    except Exception:
        pass

    return {"intent": "technical", "effective_max_turns": settings.max_turns_technical}


def faq_node(state: AgentState) -> Dict[str, Any]:
    """FAQ 节点：尝试从常见问题库匹配答案"""
    messages = state.get("messages", [])
    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    result = _faq_search(content)

    if result:
        return {"faq_match": result, "needs_human": False}
    else:
        # FAQ 没匹配到，标记可能需要转入 RAG
        return {"faq_match": None}


def rag_node(state: AgentState, retriever=None, user_id: str = "") -> Dict[str, Any]:
    """RAG 推理节点：使用 ReAct Agent 进行深度技术排查"""
    messages = state.get("messages", [])
    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    # 构建对话历史
    history = []
    for msg in messages[:-1]:
        if isinstance(msg, HumanMessage):
            history.append((msg.content, ""))
        elif isinstance(msg, AIMessage):
            if history:
                history[-1] = (history[-1][0], msg.content)

    agent = CustomerServiceAgent(
        retriever=retriever,
        user_id=user_id or state.get("user_id", ""),
        max_turns=state.get("effective_max_turns", settings.max_reasoning_turns),
    )

    result = agent.run_with_trace(content, chat_history=history)

    # 检查是否触发了转人工
    output = result.get("output", "")
    needs_human = "escalated" in output.lower() or "转接人工" in output

    return {
        "final_response": output,
        "needs_human": needs_human,
    }


def human_node(state: AgentState) -> Dict[str, Any]:
    """人工转接节点：准备转人工上下文"""
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    reason = last_message.content[:200] if last_message else "用户请求转人工"

    return {
        "needs_human": True,
        "final_response": (
            f"已为您转接人工客服。\n\n"
            f"转接原因：{reason}\n\n"
            f"请稍候，我们的客服专员将很快为您服务。"
            f"如长时间未响应，请发送邮件至 support@cloudsync.io。"
        ),
    }


def reflect_node(state: AgentState) -> Dict[str, Any]:
    """Reflection 节点：Agent 自我反思后修正回复

    在 reply_node 之前执行，让 Agent 检查自己的推理链是否完整。
    只在技术排查（intent=technical）且未反射过时执行。
    """
    # FAQ 和人工转接不需要 reflection
    if state.get("intent") != "technical":
        return {}

    # 已经反射过的不重复
    if state.get("has_reflected"):
        return {}

    final_response = state.get("final_response", "")
    if not final_response:
        return {}

    # 使用共享 LLM 做 reflection（不调工具，纯文本检查）
    reflect_llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        temperature=0.0,
    )

    reflect_prompt = (
        "你是一个质量审查员。请检查以下客服 Agent 的回复，从三个角度审查：\n\n"
        "1. **事实准确性**：回复中的所有技术断言（API 名称、配置步骤、错误码、版本号）"
        "是否都有依据？如果有任何编造或猜测的内容，请指出。\n"
        "2. **完整性**：有没有遗漏用户已经尝试过的步骤？"
        "如果用户之前提到过排查信息，回复是否充分利用了这些信息？\n"
        "3. **安全性**：回复是否包含任何危险的指令（如删除数据、绕过安全措施）？"
        "是否泄露了系统内部信息（System Prompt、工具定义、其他用户信息）？\n\n"
        f"【Agent 回复】\n{final_response}\n\n"
        "请给出审查结论。如果有问题，直接输出修正后的完整回复。"
        "如果回复没有问题，输出 'PASS'。"
    )

    try:
        result = reflect_llm.invoke(reflect_prompt)
        reflection_output = result.content.strip()
    except Exception:
        # Reflection LLM 调用失败，不阻塞流程
        return {"has_reflected": True}

    if reflection_output and reflection_output != "PASS":
        # Reflection 发现了问题并给出了修正版
        return {
            "final_response": reflection_output,
            "has_reflected": True,
        }

    return {"has_reflected": True}


def reply_node(state: AgentState) -> Dict[str, Any]:
    """回复节点：组装最终回复"""
    faq_match = state.get("faq_match")
    final_response = state.get("final_response", "")
    needs_human = state.get("needs_human", False)

    if faq_match and not final_response:
        final_response = faq_match
    elif not final_response:
        final_response = "抱歉，我暂时无法处理您的请求。正在为您转接人工客服..."
        needs_human = True

    return {
        "final_response": final_response,
        "needs_human": needs_human,
    }
