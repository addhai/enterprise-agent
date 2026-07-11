"""FAQ Handler — 常见问题匹配 + 闲聊处理

职责：
    处理高频、标准化、低风险的问题（FAQ 匹配）和闲聊对话。
    零 LLM 调用，纯关键词匹配 + 规则引擎。

设计原则：
    - 轻量级，不依赖外部服务
    - 命中则返回答案，未命中则返回空，由父图决定下一步
    - 闲聊消息直接由 LLM 快速回复

架构：
    faq_handler(state) → { faq_match → final_response | no_match → {} }
    chat_handler(content) → LLM 快速回复

    被父图直接调用，不作为独立子图
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langchain_openai import ChatOpenAI

from src.config import settings
from src.agent.tools import _faq_search, _FAQ_STORE

logger = logging.getLogger(__name__)

# 闲聊关键词列表
_CASUAL_KEYWORDS = [
    "你好", "hello", "hi", "嗨", "hey", "在吗", "有人在吗",
    "早上好", "晚上好", "下午好", "谢谢", "thank", "thanks",
    "再见", "bye", "ok", "好的", "嗯", "哦",
]


def _find_matching_keyword(content: str, answer: str) -> Optional[str]:
    """反向查找命中的关键词（用于分析统计）"""
    content_lower = content.lower()
    for keyword in _FAQ_STORE:
        if keyword in content_lower:
            return keyword
    return None


def faq_handler(state: Dict[str, Any]) -> Dict[str, Any]:
    """FAQ 处理节点：关键词匹配常见问题库

    从最新消息中提取用户输入，在 _FAQ_STORE 中做关键词匹配。
    命中则设置 faq_match 和 final_response。
    未命中则返回空字典，由父图决定是否走 RAG 路径。
    """
    messages = state.get("messages", [])
    if not messages:
        return {"faq_match": None, "needs_human": False}

    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    # 1. 先尝试闲聊回复
    if any(kw in content.lower() for kw in _CASUAL_KEYWORDS):
        return chat_handler(content)

    # 2. 尝试 FAQ 匹配
    result = _faq_search(content)
    if result:
        logger.info("FAQ matched for message: %s", content[:50])
        return {
            "faq_match": result,
            "faq_matched_keyword": _find_matching_keyword(content, result),
            "final_response": result,
            "needs_human": False,
        }
    else:
        logger.debug("FAQ not matched for message: %s", content[:50])
        return {"faq_match": None}


def chat_handler(content: str) -> Dict[str, Any]:
    """闲聊回复：直接让 LLM 回复，不走知识库"""
    llm = ChatOpenAI(
        model=settings.llm_light,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        temperature=0.7,
        max_tokens=200,
    )

    prompt = (
        "你是一个友好的智能客服。用户发来了一条简单的问候或闲聊消息，"
        "请用简短、自然的中文回复，不要长篇大论。"
        "如果用户在说谢谢，回应'不客气'；"
        "如果用户在说再见，回应'再见，祝您生活愉快'；"
        "如果用户在打招呼，友好回应并询问需要什么帮助。\n\n"
        f"用户消息：{content}"
    )

    try:
        resp = llm.invoke(prompt)
        return {
            "final_response": resp.content.strip(),
            "needs_human": False,
        }
    except Exception as e:
        logger.warning("Chat reply LLM failed: %s", e)
        return {
            "final_response": "你好，有什么可以帮助你的吗？",
            "needs_human": False,
        }
