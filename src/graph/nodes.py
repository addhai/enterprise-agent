"""LangGraph 工作流节点

六节点 DAG：
    entry → classify → {faq_handle | rag_handle | human} → reply → END

记忆接入（三处）：
    entry → MemoryManager.on_entry()    注入长期记忆 + 用户画像
    rag   → MemoryManager.on_rag_start()  提取对话历史
    reply → MemoryManager.on_completion() 持久化长期记忆 + 质量评估

v1.0 更新（2026-07-11）：
    - classify_node：合并 clarify + router，先意图分类再决定是否需要追问
    - faq_handler 豁免：FAQ 类问题不触发追问
    - 情绪检测前置：愤怒/紧急用户直接标记
    - 追问仅对 technical 意图生效
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI

from src.config import settings
from src.graph.state import AgentState
from src.agent.tools import _faq_search
from src.agent.agent import CustomerServiceAgent
from src.agent.prompt import detect_prompt_injection

logger = logging.getLogger(__name__)

# 共享的 LLM 实例（用于意图分类，延迟初始化以避免无 API Key 时导入失败）
_intent_llm: Optional[ChatOpenAI] = None


def _get_intent_llm() -> ChatOpenAI:
    """获取或初始化意图分类 LLM（使用 Lite 模型）"""
    global _intent_llm
    if _intent_llm is None:
        _intent_llm = ChatOpenAI(
            model=settings.llm_light,
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
            temperature=0.0,
        )
    return _intent_llm


# ======================================================================
# Node 1: entry_node — 入口 + 长期记忆注入
# ======================================================================

def entry_node(state: AgentState, memory_manager=None) -> Dict[str, Any]:
    """入口节点：初始化对话状态，注入长期记忆上下文

    职责：
        1. 递增对话轮次
        2. 通过 MemoryManager 注入长期记忆上下文到 state.memory_context
        3. 初始化其他状态字段
        4. 注入式攻击检测（v0.6 新增）
    """
    user_id = state.get("user_id", "anonymous")
    session_id = state.get("session_id", "")
    messages = state.get("messages", [])
    last_message = messages[-1].content if messages else ""

    # ===== 注入式攻击检测（v0.6） =====
    # 核心原则：系统提示词不当安全边界，关键资源靠服务端鉴权
    # 如果检测到注入意图，直接终止任务，不让 LLM 有机会执行
    injection = detect_prompt_injection(last_message)
    if injection["is_injection"]:
        logger.warning(
            "Prompt injection detected: type=%s, confidence=%.2f, user=%s",
            injection["attack_type"], injection["confidence"], user_id,
        )
        return {
            "turn_count": state.get("turn_count", 0) + 1,
            "intent": None,
            "needs_human": True,
            "faq_match": None,
            "effective_max_turns": 1,
            "has_reflected": False,
            "memory_context": "",
            "injection_blocked": True,
            "injection_type": injection["attack_type"],
            "final_response": (
                f"检测到异常请求，已自动终止。"
                f"如需帮助请联系人工客服。"
            ),
        }

    # 注入长期记忆上下文
    memory_context = ""
    if memory_manager and session_id and user_id != "anonymous":
        try:
            memory_context = memory_manager.on_entry(
                session_id=session_id,
                user_id=user_id,
                user_message=last_message,
            )
        except Exception:
            logger.warning("Memory context injection failed, continuing without it",
                           exc_info=True)

    return {
        "turn_count": state.get("turn_count", 0) + 1,
        "intent": None,
        "needs_human": False,
        "faq_match": None,
        "effective_max_turns": 5,
        "has_reflected": False,
        "memory_context": memory_context,
        "injection_blocked": False,
        "needs_expert_delegation": False,
        "expert_response": None,
    }


# ======================================================================
# Node 1.5: classify_node — 意图分类 + 情绪检测 + 追问决策
# ======================================================================

# FAQ 豁免列表 — 这些问题不需要追问技术环境
_FAQ_EXEMPTION_KEYWORDS = [
    # 中文
    "重置密码", "修改密码", "忘记密码", "密码",
    "更改计划", "修改计划", "订阅", "取消订阅",
    "定价", "价格", "多少钱",
    "api key", "密钥",
    "403", "404", "500", "错误",
    "ss", "sso", "单点登录",
    "加密", "2fa", "两步验证", "双因素",
    "同步", "退款", "取消订单",
    # 英文
    "reset password", "forgot password", "change plan",
    "pricing", "how much", "cancel subscription",
    "api key", "two factor", "encryption",
    "sync not working", "403 error", "sso",
]

# 闲聊关键词
_CASUAL_KEYWORDS = [
    "你好", "hello", "hi", "嗨", "hey", "在吗", "有人在吗",
    "早上好", "晚上好", "下午好", "谢谢", "thank", "thanks",
    "再见", "bye", "ok", "好的", "嗯", "哦",
]

# 转人工关键词
_HUMAN_KEYWORDS = [
    "talk to human", "speak to agent", "real person",
    "转人工", "人工客服", "投诉", "complaint",
    "退款", "refund", "cancel my account",
]


def classify_node(state: AgentState) -> Dict[str, Any]:
    """意图分类节点：合并 classify + clarify 的职责

    执行顺序：
    1. 情绪检测（愤怒/紧急 → 直接标记）
    2. 闲聊检测 → intent=faq, is_casual=True
    3. FAQ 豁免检测 → intent=faq（不需要追问）
    4. 转人工检测 → intent=human
    5. 技术排查检测 → intent=technical（需要追问）
    6. LLM 兜底分类
    """
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "faq", "effective_max_turns": 5}

    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)
    content_lower = content.lower()
    memory_context = state.get("memory_context", "")

    # ================================================================
    # 1. 情绪检测兜底
    # ================================================================
    try:
        from src.sentiment.analyzer import get_sentiment_analyzer
        analyzer = get_sentiment_analyzer()
        sentiment = analyzer.analyze(content)

        if analyzer.should_escalate_immediately(sentiment):
            return {
                "intent": "human",
                "effective_max_turns": 1,
                "clarity_status": "sentiment_escalation",
                "sentiment": sentiment.sentiment,
                "urgency": sentiment.urgency,
                "keywords": sentiment.keywords_found,
            }
        elif analyzer.should_skip_clarification(sentiment):
            return {
                "intent": "faq",  # 先走 FAQ 路由，reply_node 会处理情绪标记
                "effective_max_turns": settings.max_turns_faq,
                "clarity_status": "sentiment_warning",
                "sentiment": sentiment.sentiment,
                "urgency": sentiment.urgency,
                "keywords": sentiment.keywords_found,
            }
    except Exception:
        pass  # 情绪分析失败不影响主流程

    # ================================================================
    # 2. 闲聊检测
    # ================================================================
    if any(kw in content_lower for kw in _CASUAL_KEYWORDS):
        return {
            "intent": "faq",
            "effective_max_turns": 1,
            "is_casual": True,
            "clarity_status": "clear",
        }

    # ================================================================
    # 3. FAQ 豁免检测 — 这些关键词不需要追问
    # ================================================================
    if any(kw in content_lower for kw in _FAQ_EXEMPTION_KEYWORDS):
        return {
            "intent": "faq",
            "effective_max_turns": settings.max_turns_faq,
            "clarity_status": "clear",
        }

    # ================================================================
    # 4. 转人工检测
    # ================================================================
    if any(kw in content_lower for kw in _HUMAN_KEYWORDS):
        return {
            "intent": "human",
            "effective_max_turns": settings.max_turns_faq,
            "clarity_status": "clear",
        }

    # ================================================================
    # 5. 追问检测 — 仅对 technical 意图触发
    # ================================================================
    missing_info = _detect_missing_info(content, memory_context)

    if missing_info:
        # 尝试从长期记忆中推断
        inferred = _try_infer_from_memory(missing_info, memory_context)
        if inferred:
            rewritten = _rewrite_query(content, inferred)
            return {
                "clarity_status": "rewritten",
                "original_query": content,
                "rewritten_query": rewritten,
                "intent": "technical",  # 改写后走 RAG
                "effective_max_turns": settings.max_turns_technical,
            }

        # 无法推断 → 追问（仅 technical 意图）
        clarification_question = _generate_clarification_question(missing_info, content)
        return {
            "clarity_status": "needs_clarification",
            "missing_info": missing_info,
            "clarification_question": clarification_question,
            "intent": "technical",
            "effective_max_turns": settings.max_turns_technical,
        }

    # ================================================================
    # 6. 默认 LLM 分类
    # ================================================================
    try:
        llm = _get_intent_llm()
        classification = llm.invoke(
            f"将以下用户消息分类为 'faq'（简单常见问题）、'technical'（需要技术文档查询）或 'human'（需要人工客服）。"
            f"只有当用户明确表达投诉、退款、转人工意愿时才分类为 'human'。"
            f"普通的问候语如'你好'、'在吗'应分类为 'faq'。\n"
            f"只返回一个词，不要有其他内容。\n\n用户消息：{content[:500]}"
        )
        intent = classification.content.strip().lower()
        if intent in ["faq", "technical", "human"]:
            turns_map = {
                "faq": settings.max_turns_faq,
                "technical": settings.max_turns_technical,
                "human": settings.max_turns_faq,
            }
            return {
                "intent": intent,
                "effective_max_turns": turns_map.get(intent, 5),
                "clarity_status": "clear",
            }
    except Exception:
        pass

    # 默认走技术排查
    return {
        "intent": "technical",
        "effective_max_turns": settings.max_turns_technical,
        "clarity_status": "clear",
    }


def _detect_missing_info(content: str, memory_context: str) -> List[str]:
    """检测用户问题中缺失的关键信息

    Returns:
        缺失信息列表，如 ["SDK 版本", "错误码"]
    """
    content_lower = content.lower()
    missing: List[str] = []

    # 错误类问题必须有错误码
    error_indicators = ["error", "报错", "错误", "fail", "failed", "异常", "bug"]
    if any(kw in content_lower for kw in error_indicators):
        # 检查是否提供了错误码
        has_error_code = bool(re.search(r'\d{3,4}', content))
        has_error_msg = bool(re.search(r'ERR_|error_code|exception|traceback', content_lower))
        if not has_error_code and not has_error_msg:
            missing.append("错误码或错误详情")

    # 排查类问题必须有技术环境
    troubleshoot_indicators = ["排查", "troubleshoot", "怎么排查", "怎么解决", "怎么处理", "怎么办"]
    if any(kw in content_lower for kw in troubleshoot_indicators):
        env_indicators = ["version", r"v\d", "sdk", "python", "javascript", "node", "java", "windows", "linux", "mac", "系统"]
        if not any(re.search(ind, content_lower) for ind in env_indicators):
            missing.append("技术环境（SDK 版本/操作系统）")

    return missing


def _try_infer_from_memory(missing_info: List[str], memory_context: str) -> Dict[str, str]:
    """尝试从长期记忆中推断缺失信息

    Returns:
        {"SDK版本": "v2.3", "操作系统": "Linux"} 或 {}
    """
    if not memory_context:
        return {}

    inferred: Dict[str, str] = {}
    memory_lower = memory_context.lower()

    # SDK 版本推断
    if "SDK 版本" in str(missing_info):
        version_match = re.search(r"(?:SDK|sdk)[\s：:]*([\w.-]+(?:v\d+\.\d+)?)", memory_lower)
        if version_match:
            inferred["SDK 版本"] = version_match.group(1)

    # 操作系统推断
    if "技术环境" in str(missing_info):
        if "windows" in memory_lower:
            inferred["操作系统"] = "Windows"
        elif "linux" in memory_lower:
            inferred["操作系统"] = "Linux"
        elif "mac" in memory_lower or "darwin" in memory_lower:
            inferred["操作系统"] = "macOS"

    return inferred


def _rewrite_query(original: str, inferred: Dict[str, str]) -> str:
    """根据推断信息改写查询"""
    if not inferred:
        return original

    additions = []
    for key, value in inferred.items():
        additions.append(f"{key}是{value}")

    addition_text = "，".join(additions)
    return f"{original}（补充信息：{addition_text}）"


def _generate_clarification_question(missing_info: List[str], original: str) -> str:
    """生成追问用户的提示"""
    if not missing_info:
        return ""

    questions = []
    for info in missing_info:
        questions.append(f"您能否提供关于「{info}」的更多信息？")

    return (
        f"为了更好地帮助您，我需要了解更多细节：\n\n"
        + "\n".join(f"• {q}" for q in questions)
        + "\n\n提供这些信息后我可以给您更准确的答案。"
    )


# ======================================================================
# Node 3: human_node — 人工转接
# ======================================================================

def human_node(state: AgentState) -> Dict[str, Any]:
    """人工转接节点：准备转人工上下文

    v1.0 更新：
        - 构建完整的转接上下文包（对话摘要 + 用户画像 + 已尝试方案）
        - 返回转接 ID 供前端追踪
    """
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    reason = last_message.content[:200] if last_message else "用户请求转人工"

    # 注意：handle_escalation 是 async 函数，但 human_node 是同步的
    # 这里只构建上下文信息，实际的 WebSocket 推送由 WebSocket 路由层处理
    session_id = state.get("session_id", "")
    user_id = state.get("user_id", "anonymous")
    user_plan = state.get("user_plan", "free")
    intent = state.get("intent", "unknown")
    quality_score = state.get("quality_score")

    # 构建转接上下文（同步，不依赖 WebSocket）
    try:
        from src.websocket.handoff import build_handoff_context
        handoff_context = build_handoff_context(
            state=state,
            messages=messages,
            intent=intent,
            quality_score=quality_score,
        )
        transfer_id = f"transfer_{session_id[-8:]}" if session_id else ""
    except Exception:
        handoff_context = {}
        transfer_id = ""

    return {
        "needs_human": True,
        "final_response": (
            "已为您转接人工客服。\n\n"
            "转接原因：{reason}\n\n"
            "请稍候，我们的客服专员将很快为您服务。"
        ).format(reason=reason),
        "_transfer_id": transfer_id,
        "_handoff_context": handoff_context,
    }


# ======================================================================
# Node 5: reply_node — 最终回复组装 + 记忆持久化 + 质量评估
# ======================================================================

def reply_node(state: AgentState, memory_manager=None) -> Dict[str, Any]:
    """回复节点：组装最终回复，完成记忆持久化和质量评估

    职责：
        1. 组装最终回复（FAQ 命中用 FAQ 文本，否则用 RAG/转人工结果）
        2. 接入点 3: 调用 MemoryManager.on_completion() 持久化长期记忆
        3. 在线抽样评估（LLM-as-Judge）
        4. 返回最终回复和 needs_human 标志
    """
    faq_match = state.get("faq_match")
    final_response = state.get("final_response", "")
    needs_human = state.get("needs_human", False)
    intent = state.get("intent", "unknown")
    session_id = state.get("session_id", "")
    user_id = state.get("user_id", "anonymous")
    messages = state.get("messages", [])
    last_message = messages[-1].content if messages else ""
    clarity_status = state.get("clarity_status", "")
    quality_score = state.get("quality_score")

    # 组装回复
    # 如果注入攻击被拦截，直接返回终止消息
    injection_blocked = state.get("injection_blocked", False)
    if injection_blocked:
        return {
            "final_response": state.get("final_response", ""),
            "needs_human": True,
            "quality_score": None,
        }

    # ================================================================
    # 情绪兜底（v1.0 新增）
    # ================================================================
    if clarity_status == "sentiment_escalation":
        # 愤怒/合规风险 → 直接转人工
        return {
            "final_response": (
                "检测到您的问题需要紧急处理，已为您优先转接人工客服。"
                "我们的客服专员将尽快为您解决。"
            ),
            "needs_human": True,
        }
    elif clarity_status == "sentiment_warning":
        # 紧急/不满 → 标记给下游节点注意
        pass  # 继续正常流程，但 reply_node 会记录情绪标记

    if faq_match and not final_response:
        final_response = faq_match
    elif not final_response:
        # 检查是否是意图澄清阶段
        if clarity_status == "needs_clarification":
            # 需要追问用户
            clarification_q = state.get("clarification_question", "")
            if clarification_q:
                final_response = clarification_q
                needs_human = False
            else:
                final_response = "抱歉，我暂时无法处理您的请求。正在为您转接人工客服..."
                needs_human = True
        elif clarity_status == "rewritten":
            # 改写后的查询，使用改写后的内容重新检索
            rewritten = state.get("rewritten_query", "")
            if rewritten:
                final_response = (
                    f"我理解您想了解的是：「{rewritten}」。"
                    f"基于当前知识库，我无法提供准确答案。建议转人工客服。"
                )
                needs_human = True
            else:
                final_response = "抱歉，我暂时无法处理您的请求。正在为您转接人工客服..."
                needs_human = True
        else:
            final_response = "抱歉，我暂时无法处理您的请求。正在为您转接人工客服..."
            needs_human = True

    # 如果检索置信度太低 → 拒答
    if quality_score is not None and quality_score < 0.3:
        final_response = (
            "抱歉，我检索到的信息不足以准确回答您的问题。"
            "建议转人工客服获取更专业的帮助。"
        )
        needs_human = True

    # ==================================================================
    # 接入点 3: 持久化长期记忆
    # ==================================================================
    if memory_manager and session_id and user_id != "anonymous":
        try:
            memory_manager.on_completion(
                session_id=session_id,
                user_id=user_id,
                intent=intent or "unknown",
                final_response=final_response,
                user_message=last_message,
                is_escalated=needs_human,
            )
        except Exception:
            logger.warning("Memory on_completion failed", exc_info=True)

    # ==================================================================
    # 在线抽样评估（LLM-as-Judge）
    # ==================================================================
    quality_score = state.get("quality_score")
    if settings.eval_llm_judge_enabled and final_response:
        try:
            from src.evaluation.metrics import DialogueJudge, should_sample

            if should_sample(user_id):
                judge = DialogueJudge()

                # 获取对话摘要作为评估上下文
                conv_summary = ""
                if memory_manager and session_id:
                    try:
                        ctx = memory_manager.get_context_for_evaluation(session_id)
                        conv_summary = ctx.get("summary", "")
                    except Exception:
                        pass

                score = judge.evaluate(
                    user_message=last_message,
                    agent_response=final_response,
                    retrieved_docs=state.get("retrieved_docs", []),
                    conversation_summary=conv_summary,
                )

                quality_score = score["overall"]

                if memory_manager and session_id:
                    memory_manager.record_quality(
                        session_id=session_id,
                        user_id=user_id,
                        score=score["overall"],
                        dimensions=score.get("dimensions", {}),
                    )

                if score.get("needs_human_review"):
                    logger.info(
                        "LLM-as-Judge flagged for human review: overall=%.1f, "
                        "flags=%s",
                        score["overall"], score.get("flags", []),
                    )
        except Exception:
            logger.debug("Online evaluation skipped", exc_info=True)

    # ==================================================================
    # 效果评估埋点（v1.0 新增）
    # ==================================================================
    try:
        from src.evaluation.tracker import get_evaluation_tracker
        tracker = get_evaluation_tracker()
        # 根据意图判断使用的模型 tier
        model_tier = {
            "faq": "lite",
            "technical": "medium",
            "human": "none",
        }.get(intent, "medium")
        tracker.track_resolution(
            session_id=session_id,
            resolved=(not needs_human) and bool(final_response),
            turns=state.get("turn_count", 0),
            intent=intent or "unknown",
            model_tier=model_tier,
        )
        if needs_human:
            tracker.track_escalation(
                session_id=session_id,
                reason=_get_escalation_reason(state, clarity_status),
                urgency=_assess_escalation_urgency(state, last_message),
                turns=state.get("turn_count", 0),
                sentiment=_get_sentiment_from_state(state),
            )
        if quality_score is not None:
            tracker.track_quality_score(
                session_id=session_id,
                score=quality_score,
                intent=intent or "unknown",
                resolved=(not needs_human),
            )
    except Exception:
        pass  # 埋点失败不影响主流程

    return {
        "final_response": final_response,
        "needs_human": needs_human,
        "quality_score": quality_score,
    }


def _get_escalation_reason(state: AgentState, clarity_status: str) -> str:
    """获取转接原因标签"""
    if state.get("injection_blocked"):
        return "injection_blocked"
    if clarity_status == "needs_clarification":
        return "clarification_failed"
    if clarity_status == "rewritten":
        return "rewrite_failed"
    if clarity_status == "sentiment_escalation":
        return "sentiment_critical"
    if clarity_status == "sentiment_warning":
        return "sentiment_warning"
    quality_score = state.get("quality_score")
    if quality_score is not None and quality_score < 0.3:
        return "low_confidence"
    return "user_request"


def _assess_escalation_urgency(state: AgentState, last_message: str) -> str:
    """评估转接紧急度"""
    try:
        from src.sentiment.analyzer import get_sentiment_analyzer
        analyzer = get_sentiment_analyzer()
        sentiment = analyzer.analyze(last_message)
        return sentiment.urgency
    except Exception:
        return "normal"


def _get_sentiment_from_state(state: AgentState) -> str:
    """从状态中提取情绪标记"""
    clarity_status = state.get("clarity_status", "")
    if clarity_status == "sentiment_escalation":
        return "angry"
    if clarity_status == "sentiment_warning":
        return "urgent"
    return "neutral"


# ======================================================================
# Helpers
# ======================================================================

def _extract_history_manual(messages: list) -> list:
    """从 messages 列表中手动提取对话历史（MemoryManager 不可用时的降级方案）"""
    history = []
    for msg in messages[:-1]:
        if isinstance(msg, HumanMessage):
            history.append((msg.content, ""))
        elif isinstance(msg, AIMessage):
            if history:
                history[-1] = (history[-1][0], msg.content)
    return history


def _extract_retrieved_docs(intermediate_steps: list) -> list:
    """从 Agent 中间步骤中提取检索到的文档"""
    docs = []
    for step in intermediate_steps:
        if isinstance(step, tuple) and len(step) >= 2:
            observation = step[1]
            # langchain 格式: (action, observation)
            if isinstance(observation, str):
                # 尝试提取文档标题
                pass
            elif isinstance(observation, list):
                docs.extend(observation)
    return docs
