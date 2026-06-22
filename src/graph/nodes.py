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
        return {"intent": "human"}

    # 快速规则判断 FAQ vs Technical
    faq_keywords = [
        "reset password", "forgot password", "change plan",
        "pricing", "how much", "cancel subscription",
        "api key", "enable 2fa", "two factor",
    ]

    if any(kw in content.lower() for kw in faq_keywords):
        return {"intent": "faq"}

    # 其他情况尝试 LLM 分类
    try:
        llm = _get_intent_llm()
        classification = llm.invoke(
            f"将以下用户消息分类为 'faq'（简单常见问题）、'technical'（需要技术文档）或 'human'（需要人工客服）。"
            f"只返回一个词。\n\n用户消息：{content[:500]}"
        )
        intent = classification.content.strip().lower()
        if intent in ["faq", "technical", "human"]:
            return {"intent": intent}
    except Exception:
        pass

    return {"intent": "technical"}  # 默认走技术排查


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
