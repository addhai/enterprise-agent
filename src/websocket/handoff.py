"""转接上下文构建器

将 AgentState 中的丰富信息压缩为人工客服可读的转接摘要：
    1. 对话摘要（LLM 生成或启发式）
    2. 用户画像（从 memory_context 提取）
    3. 已尝试方案（从 RAG 中间步骤提取）
    4. 紧急度评估
    5. 完整对话记录
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, AIMessage

from src.config import settings

logger = logging.getLogger(__name__)


def _build_summary(messages: list, intent: str, quality_score: Optional[float]) -> str:
    """构建对话摘要（启发式，避免额外 LLM 调用）"""
    if not messages:
        return "用户刚进入对话即要求转人工"

    # 提取用户最后几条消息
    user_msgs = []
    for msg in reversed(messages[-6:]):  # 最近 6 条
        if isinstance(msg, HumanMessage):
            user_msgs.append(msg.content[:150])

    if not user_msgs:
        return f"意图: {intent}，用户请求转人工"

    # 构建简要摘要
    first_query = user_msgs[-1] if len(user_msgs) > 1 else user_msgs[0]
    last_query = user_msgs[-1]

    if len(user_msgs) == 1:
        summary = f"用户问题: {first_query}"
    else:
        summary = f"初始问题: {first_query}\n后续追问: {' → '.join(user_msgs[1:])}"

    if quality_score is not None:
        if quality_score < 0.3:
            summary += f"\nAI 评估: 低置信度 (score={quality_score:.2f})，无法提供满意答案"
        elif quality_score < 0.6:
            summary += f"\nAI 评估: 中等置信度 (score={quality_score:.2f})，答案可能不完整"

    return summary


def _build_attempted_solutions(messages: list, retrieved_docs: list) -> List[str]:
    """提取 AI 已尝试的解决方案

    增强：
        - 从 AI 回复中提取排查步骤
        - 从检索文档推断
        - 从对话历史中提取已确认的信息
    """
    attempts = []
    confirmed_info = []

    # 从对话历史提取 AI 的排查步骤
    for msg in messages:
        if isinstance(msg, AIMessage):
            content = msg.content if hasattr(msg, "content") else str(msg)
            # 识别排查步骤
            if any(kw in content.lower() for kw in ["step", "步骤", "请尝试", "检查", "查看", "config", "配置"]):
                attempts.append(content[:200])
            # 识别 AI 确认的信息
            if any(kw in content.lower() for kw in ["确认", "已知", "了解", "明白", "根据您"]):
                confirmed_info.append(content[:150])

    # 从检索文档推断
    if retrieved_docs:
        attempts.append(f"检索了 {len(retrieved_docs)} 篇相关知识文档")

    # 从用户消息中提取已提供的信息
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content if hasattr(msg, "content") else str(msg)
            # 检测错误码
            import re
            if re.search(r'ERR_\d+|error_code|exception|traceback', content, re.IGNORECASE):
                confirmed_info.append(f"用户提供了错误信息: {content[:100]}")
            # 检测版本号
            if re.search(r'v\d+\.\d+', content):
                confirmed_info.append(f"用户提到了版本信息: {content[:100]}")

    if not attempts:
        attempts.append("AI 未能找到匹配的解决方案")

    return {
        "steps": attempts,
        "confirmed_info": confirmed_info,
    }


def _build_user_profile(memory_context: str, user_plan: str, user_roles: list) -> Dict[str, Any]:
    """构建用户画像摘要"""
    profile = {
        "plan": user_plan or "unknown",
        "roles": user_roles or [],
        "has_history": bool(memory_context),
    }

    # 从 memory_context 提取关键信息
    if memory_context:
        # 简单解析长期记忆中的关键信息
        lines = memory_context.split("\n")
        extracted = {}
        for line in lines:
            if "订阅计划" in line or "plan" in line.lower():
                extracted["plan_detail"] = line.strip()
            elif "偏好" in line or "prefer" in line.lower():
                extracted["preference"] = line.strip()
            elif "tech" in line.lower():
                extracted["tech_stack"] = line.strip()
        if extracted:
            profile["details"] = extracted

    return profile


def build_handoff_context(
    state: Dict[str, Any],
    messages: list,
    intent: str = "unknown",
    quality_score: Optional[float] = None,
) -> Dict[str, Any]:
    """构建完整的转接上下文包

    Args:
        state: AgentState 字典
        messages: 对话消息列表
        intent: 识别的意图
        quality_score: AI 回答质量评分

    Returns:
        包含所有人工客服需要的信息的字典
    """
    # 1. 对话摘要
    summary = _build_summary(messages, intent, quality_score)

    # 2. 已尝试方案
    retrieved_docs = state.get("retrieved_docs", [])
    attempted = _build_attempted_solutions(messages, retrieved_docs)

    # 3. 用户画像
    memory_ctx = state.get("memory_context", "")
    user_plan = state.get("user_plan", "free")
    user_roles = state.get("user_roles", [])
    user_id = state.get("user_id", "anonymous")
    tenant_id = state.get("tenant_id", "")
    access_levels = state.get("user_access_levels", [])
    profile = _build_user_profile(memory_ctx, user_plan, user_roles)
    profile["user_id"] = user_id
    profile["tenant_id"] = tenant_id
    profile["access_levels"] = access_levels

    # 4. 转接原因
    last_message = ""
    if messages and hasattr(messages[-1], "content"):
        last_message = messages[-1].content

    needs_human = state.get("needs_human", False)
    injection_blocked = state.get("injection_blocked", False)
    clarity_status = state.get("clarity_status", "")

    reason_parts = []
    if injection_blocked:
        reason_parts.append("检测到注入攻击，已自动拦截")
    elif needs_human:
        # 判断转接原因
        if clarity_status == "needs_clarification":
            reason_parts.append("意图澄清失败，无法理解用户需求")
        elif clarity_status == "rewritten":
            reason_parts.append("查询改写后仍无法检索到有效答案")
        elif quality_score is not None and quality_score < 0.3:
            reason_parts.append(f"检索置信度过低 (score={quality_score:.2f})")
        else:
            reason_parts.append("用户明确要求转人工")

    if not reason_parts:
        reason_parts.append("系统判定需要人工协助")

    # 5. 紧急度评估
    urgency = _assess_urgency(last_message, user_plan, intent)

    # 6. 完整对话记录（精简版）
    conversation = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "user"
            content = msg.content if hasattr(msg, "content") else str(msg)
        elif isinstance(msg, AIMessage):
            role = "assistant"
            content = msg.content if hasattr(msg, "content") else str(msg)
        else:
            continue
        conversation.append({"role": role, "content": content[:500]})

    # 7. 当前卡点分析
    blocker = _analyze_blocker(state, messages)

    # 8. 转接元信息
    metadata = {
        "session_id": state.get("session_id", ""),
        "turn_count": state.get("turn_count", 0),
        "intent": intent,
        "injection_blocked": injection_blocked,
        "access_filtered": state.get("access_filtered", 0),
        "clarity_status": clarity_status,
    }

    return {
        "summary": summary,
        "reason": "；".join(reason_parts),
        "attempted_solutions": attempted,
        "user_profile": profile,
        "conversation": conversation,
        "urgency": urgency,
        "current_blocker": blocker,
        "metadata": metadata,
        "built_at": time.time(),
    }


def _analyze_blocker(state: Dict[str, Any], messages: list) -> Dict[str, Any]:
    """分析当前卡点

    判断 AI 为什么无法继续解决问题：
        - 信息缺失 → 追问但未得到
        - 知识不足 → RAG 检索不到
        - 权限不足 → 用户 plan 不够
        - 工具失败 → 系统调用错误
        - 用户投诉 → 情绪化问题
    """
    blockers = []
    clarity_status = state.get("clarity_status", "")
    quality_score = state.get("quality_score")
    needs_human = state.get("needs_human", False)
    injection_blocked = state.get("injection_blocked", False)
    faq_match = state.get("faq_match")
    intent = state.get("intent", "")

    if injection_blocked:
        blockers.append({
            "type": "security",
            "detail": "检测到注入攻击，已自动拦截",
            "severity": "high",
        })

    if clarity_status == "needs_clarification":
        clarification_q = state.get("clarification_question", "")
        blockers.append({
            "type": "missing_info",
            "detail": clarification_q or "信息缺失，追问未果",
            "severity": "medium",
        })

    if clarity_status == "rewritten":
        rewritten = state.get("rewritten_query", "")
        blockers.append({
            "type": "query_failed",
            "detail": f"查询改写后仍无法检索: {rewritten[:100]}",
            "severity": "medium",
        })

    if quality_score is not None and quality_score < 0.3:
        blockers.append({
            "type": "low_confidence",
            "detail": f"检索置信度过低 (score={quality_score:.2f})",
            "severity": "high",
        })

    if not faq_match and intent == "faq":
        blockers.append({
            "type": "faq_miss",
            "detail": "FAQ 未命中，问题不在常见问题库中",
            "severity": "low",
        })

    if not blockers:
        blockers.append({
            "type": "general",
            "detail": "用户明确要求人工协助",
            "severity": "info",
        })

    return {
        "count": len(blockers),
        "items": blockers,
    }


def _assess_urgency(last_message: str, user_plan: str, intent: str) -> str:
    """评估转接紧急度

    规则：
        - enterprise 用户 + 投诉/退款 → critical
        - enterprise 用户 + 技术问题 → high
        - pro 用户 + 投诉/退款 → high
        - 其他 + 投诉/退款 → normal
        - 其他 → low
    """
    content_lower = last_message.lower()
    is_complaint = any(kw in content_lower for kw in ["投诉", "complaint", "退款", "refund", "取消", "cancel"])

    if user_plan == "enterprise" and is_complaint:
        return "critical"
    if user_plan == "enterprise" and intent == "technical":
        return "high"
    if user_plan == "pro" and is_complaint:
        return "high"
    if is_complaint:
        return "normal"
    return "low"
