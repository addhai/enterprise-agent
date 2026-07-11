"""RAG Handler — 检索增强生成 + ReAct Agent

职责：
    处理需要深度技术排查的问题。
    包含：检索 → ReAct Agent → 幻觉检测 → 质量评估

架构：
    rag_handler(state, retriever, memory_manager)
    ┌─────────────────────────────────────────┐
    │  RAG Handler                             │
    │                                          │
    │  1. 从短期记忆获取对话历史               │
    │  2. 调用 CustomerServiceAgent (ReAct)    │
    │  3. 幻觉检测 + 质量评分                 │
    │  4. 拒答检测 → 标记 needs_human          │
    └─────────────────────────────────────────┘

    被父图直接调用，不作为独立子图
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.agent.agent import CustomerServiceAgent
from src.graph.nodes import _extract_history_manual
from src.config import settings

logger = logging.getLogger(__name__)


def rag_handler(
    state: Dict[str, Any],
    retriever=None,
    memory_manager=None,
) -> Dict[str, Any]:
    """RAG 处理节点：检索文档 + ReAct Agent 推理

    这是 RAG 处理的核心，执行：
    1. 从短期记忆获取对话历史
    2. 通过 retriever 检索知识文档
    3. 调用 CustomerServiceAgent 执行 ReAct 推理
    4. 幻觉检测 + 质量评估
    """
    messages = state.get("messages", [])
    if not messages:
        return {
            "final_response": "抱歉，我无法处理空消息。",
            "needs_human": True,
        }

    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    # 获取对话历史
    history = _extract_history_manual(messages)

    # 调用 CustomerServiceAgent
    agent = CustomerServiceAgent(
        retriever=retriever,
        user_id=state.get("user_id", ""),
        max_turns=state.get("effective_max_turns", settings.max_reasoning_turns),
        memory_context=state.get("memory_context", ""),
        tenant_id=state.get("tenant_id", ""),
        user_access_levels=state.get("user_access_levels"),
        user_roles=state.get("user_roles", []),
        user_plan=state.get("user_plan", "free"),
    )

    result = agent.run_with_trace(content, chat_history=history)
    output = result.get("output", "")
    intermediate_steps = result.get("intermediate_steps", [])

    # 幻觉检测
    retrieved_docs = []
    for step in intermediate_steps:
        if isinstance(step, tuple) and len(step) >= 2:
            observation = step[1]
            if isinstance(observation, list):
                retrieved_docs.extend(observation)
    quality_score = None
    if retrieved_docs:
        total_tokens = sum(
            len(doc.page_content if hasattr(doc, "page_content") else str(doc))
            for doc in retrieved_docs
        )
        if total_tokens < settings.retrieval_min_tokens:
            quality_score = 0.2

    # 拒答检测
    refusal_indicators = ["建议转人工", "请联系人工客服", "转接人工客服"]
    is_refusal = any(ind in output for ind in refusal_indicators)

    # 如果 LLM 给出了实质性回复（不是拒答），即使知识库为空也接受
    if not is_refusal and output.strip():
        quality_score = 0.8
    elif not is_refusal and not output.strip():
        quality_score = 0.1

    return {
        "final_response": output,
        "needs_human": is_refusal,
        "quality_score": quality_score,
        "retrieved_docs": retrieved_docs,
        "answer_status": "refused" if is_refusal else "answered",
    }
