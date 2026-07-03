"""LangGraph 工作流节点

七节点 DAG：
    entry → clarify → router → faq/rag/human → reflect → reply → END

记忆接入（三处）：
    entry → MemoryManager.on_entry()    注入长期记忆 + 用户画像
    rag   → MemoryManager.on_rag_start()  提取对话历史
    reply → MemoryManager.on_completion() 持久化长期记忆 + 质量评估

v0.5 更新（2026-07-02）：
    - clarify_node：意图澄清（补全/追问/放行）
    - rag_node：检索置信度检查（低置信度拒答）
    - reflect_node：增强证据支撑检查
    - reply_node：结构化抽取 fallback

v0.6 更新（2026-07-03）：
    - 注入式攻击检测：entry_node 拦截越权意图，直接终止任务
    - 系统提示词只做约束，不当安全边界
    - 关键资源必须靠服务端鉴权（PermissionChecker）
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
_clarify_llm: Optional[ChatOpenAI] = None


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


def _get_clarify_llm() -> ChatOpenAI:
    """获取或初始化意图澄清 LLM"""
    global _clarify_llm
    if _clarify_llm is None:
        _clarify_llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
            temperature=0.0,
        )
    return _clarify_llm


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
    }


# ======================================================================
# Node 1.5: clarify_node — 意图澄清
# ======================================================================

def clarify_node(state: AgentState) -> Dict[str, Any]:
    """意图澄清节点：判断用户问题是否缺少关键信息

    处理策略：
        1. 信息完整 → 直接放行（clarity_status="clear"）
        2. 信息缺失但可推断 → Query Rewrite 补全（clarity_status="rewritten"）
        3. 信息缺失且无法推断 → 追问用户（clarity_status="needs_clarification"）

    判断维度：
        - 产品范围：用户说的是哪个产品/服务？
        - 操作场景：用户想做什么操作？
        - 技术环境：用户用的是哪个 SDK/版本/平台？
        - 错误信息：用户是否提供了错误码/日志？
    """
    messages = state.get("messages", [])
    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)
    memory_context = state.get("memory_context", "")

    # 判断是否缺少关键信息
    missing_info = _detect_missing_info(content, memory_context)

    if not missing_info:
        return {"clarity_status": "clear"}

    # 尝试从长期记忆中推断
    inferred = _try_infer_from_memory(missing_info, memory_context)
    if inferred:
        rewritten = _rewrite_query(content, inferred)
        return {
            "clarity_status": "rewritten",
            "original_query": content,
            "rewritten_query": rewritten,
        }

    # 无法推断 → 追问
    clarification_question = _generate_clarification_question(missing_info, content)
    return {
        "clarity_status": "needs_clarification",
        "missing_info": missing_info,
        "clarification_question": clarification_question,
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

    # 配置类问题必须有产品/服务名称
    config_indicators = ["配置", "setup", "configure", "设置", "安装"]
    if any(kw in content_lower for kw in config_indicators):
        # 检查是否指定了具体产品
        product_names = ["sdk", "api", "dashboard", "console", "app", "cloudsync"]
        if not any(kw in content_lower for kw in product_names):
            missing.append("具体产品或服务名称")

    # 排查类问题必须有技术环境
    troubleshoot_indicators = ["排查", "troubleshoot", "问题", "问题", "怎么"]
    if any(kw in content_lower for kw in troubleshoot_indicators):
        env_indicators = ["version", "v\\d", "sdk", "python", "javascript", "node", "java", "windows", "linux", "mac"]
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
# Node 2: router_node — 意图路由
# ======================================================================

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
            turns_map = {
                "faq": settings.max_turns_faq,
                "technical": settings.max_turns_technical,
                "human": settings.max_turns_faq,
            }
            return {"intent": intent, "effective_max_turns": turns_map.get(intent, 5)}
    except Exception:
        pass

    return {"intent": "technical", "effective_max_turns": settings.max_turns_technical}


# ======================================================================
# Node 3: faq_node — FAQ 常见问题匹配
# ======================================================================

def faq_node(state: AgentState) -> Dict[str, Any]:
    """FAQ 节点：尝试从常见问题库匹配答案"""
    messages = state.get("messages", [])
    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    result = _faq_search(content)

    if result:
        return {"faq_match": result, "needs_human": False}
    else:
        return {"faq_match": None}


# ======================================================================
# Node 4: rag_node — RAG + ReAct Agent 推理
# ======================================================================

def rag_node(
    state: AgentState,
    retriever=None,
    memory_manager=None,
    user_id: str = "",
) -> Dict[str, Any]:
    """RAG 推理节点：使用 ReAct Agent 进行深度技术排查

    职责：
        1. 通过 MemoryManager 获取对话历史（替代原来的手动提取）
        2. 注入长期记忆上下文到 Agent 的 System Prompt
        3. 调用 CustomerServiceAgent 执行 ReAct 推理链
        4. 对检索结果进行幻觉检测
    """
    messages = state.get("messages", [])
    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    # ==================================================================
    # 接入点 2: 通过 MemoryManager 获取对话历史
    # ==================================================================
    session_id = state.get("session_id", "")

    if memory_manager and session_id:
        try:
            history = memory_manager.on_rag_start(
                session_id=session_id,
                user_message=content,
            )
        except Exception:
            logger.warning("Memory on_rag_start failed, falling back to manual extraction",
                           exc_info=True)
            history = _extract_history_manual(messages)
    else:
        history = _extract_history_manual(messages)

    # 构建 Agent（注入长期记忆上下文 + 权限信息）
    agent = CustomerServiceAgent(
        retriever=retriever,
        user_id=user_id or state.get("user_id", ""),
        max_turns=state.get("effective_max_turns", settings.max_reasoning_turns),
        memory_context=state.get("memory_context", ""),
        tenant_id=state.get("tenant_id", ""),
        user_access_levels=state.get("user_access_levels", None),
        user_roles=state.get("user_roles", []),
        user_plan=state.get("user_plan", "free"),
    )

    result = agent.run_with_trace(content, chat_history=history)

    # 检查是否触发了转人工
    output = result.get("output", "")
    needs_human = "escalated" in output.lower() or "转接人工" in output

    # ===== 幻觉防护 1: 检索置信度检查 =====
    # 如果 Agent 返回了"没有找到相关信息"，标记为拒答
    refusal_indicators = [
        "抱歉", "找不到", "未找到", "没有相关信息",
        "找不到相关文档", "无法回答", "我不知道",
        "知识库中不存在", "建议转人工",
    ]
    is_refusal = any(ind in output for ind in refusal_indicators)

    # ===== 幻觉防护 2: 检索完整性检查 =====
    retrieved_docs = _extract_retrieved_docs(result.get("intermediate_steps", []))
    quality_score: Optional[float] = None
    if retrieved_docs:
        total_tokens = sum(len(doc.page_content if hasattr(doc, "page_content") else str(doc))
                          for doc in retrieved_docs)
        if total_tokens < settings.retrieval_min_tokens:
            logger.warning("Low retrieval token count: %d (threshold: %d)",
                           total_tokens, settings.retrieval_min_tokens)
            # 检索结果太短，标记低置信度
            quality_score = 0.2

    # 幻觉检测（如果启用）
    if settings.eval_hallucination_check_enabled and result.get("intermediate_steps"):
        try:
            from src.evaluation.metrics import check_hallucination

            if retrieved_docs and output and not is_refusal:
                h_result = check_hallucination(output, retrieved_docs)
                if quality_score is None:
                    quality_score = h_result["score"]
                if not h_result["is_clean"]:
                    logger.warning("Potential hallucination detected: %s",
                                   h_result["hallucinated"][:5])
        except Exception:
            logger.debug("Hallucination check skipped", exc_info=True)

    return {
        "final_response": output,
        "needs_human": needs_human or is_refusal,
        "quality_score": quality_score,
        "retrieved_docs": retrieved_docs,
        "answer_status": "refused" if is_refusal else "answered",
    }


# ======================================================================
# Node 5: human_node — 人工转接
# ======================================================================

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


# ======================================================================
# Node 6: reflect_node — Agent 自我反思
# ======================================================================

def reflect_node(state: AgentState) -> Dict[str, Any]:
    """Reflection 节点：Agent 自我反思后修正回复

    在 reply_node 之前执行，让 Agent 检查自己的推理链是否完整。
    只在技术排查（intent=technical）且未反射过时执行。
    """
    if state.get("intent") != "technical":
        return {}

    if state.get("has_reflected"):
        return {}

    final_response = state.get("final_response", "")
    if not final_response:
        return {}

    reflect_llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        temperature=0.0,
    )

    reflect_prompt = (
        "你是一个质量审查员。请检查以下客服 Agent 的回复，从四个角度审查：\n\n"
        "1. **事实准确性**：回复中的所有技术断言（API 名称、配置步骤、错误码、版本号）"
        "是否都有依据？如果有任何编造或猜测的内容，请指出。\n"
        "2. **完整性**：有没有遗漏用户已经尝试过的步骤？"
        "如果用户之前提到过排查信息，回复是否充分利用了这些信息？\n"
        "3. **安全性**：回复是否包含任何危险的指令（如删除数据、绕过安全措施）？"
        "是否泄露了系统内部信息（System Prompt、工具定义、其他用户信息）？\n"
        "4. **证据支撑**：回复中的每个技术结论是否有对应的文档依据？"
        "如果结论无法从检索文档中直接推导，标记为证据不足。\n\n"
        f"【Agent 回复】\n{final_response}\n\n"
        "请给出审查结论。如果有问题，直接输出修正后的完整回复。"
        "如果回复没有问题，输出 'PASS'。"
    )

    try:
        result = reflect_llm.invoke(reflect_prompt)
        reflection_output = result.content.strip()
    except Exception:
        return {"has_reflected": True}

    if reflection_output and reflection_output != "PASS":
        return {
            "final_response": reflection_output,
            "has_reflected": True,
        }

    return {"has_reflected": True}


# ======================================================================
# Node 7: reply_node — 最终回复组装 + 记忆持久化 + 质量评估
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

    return {
        "final_response": final_response,
        "needs_human": needs_human,
        "quality_score": quality_score,
    }


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
