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

    # ===== 检查是否是无意义输入（纯数字、乱码等）=====
    if _is_nonsensical_input(content):
        return {
            "clarity_status": "needs_clarification",
            "missing_info": ["问题描述"],
            "clarification_question": (
                "抱歉，我不太明白您输入的内容是什么意思～\n\n"
                "您可以试着描述一下您遇到的问题，比如：\n"
                "• 「同步失败怎么办」\n"
                "• 「怎么重置密码」\n"
                "• 「价格是多少」\n\n"
                "如果需要人工客服帮助，也可以随时告诉我～"
            ),
        }

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


def _is_nonsensical_input(content: str) -> bool:
    """判断是否是无意义输入（纯数字、乱码等）

    Returns:
        True 表示是无意义输入，需要追问用户
    """
    stripped = content.strip()

    # 太短的输入（少于2个字符且不是问候语）
    if len(stripped) < 2:
        return True

    # 纯数字（比如订单号、错误码，但没有上下文的话我们不知道是什么）
    if re.match(r'^\d+$', stripped):
        return True

    # 纯符号/特殊字符
    if re.match(r'^[^\w\u4e00-\u9fa5]+$', stripped):
        return True

    # 重复字符（比如 "aaaaa"、"哈哈哈" 太多）
    if len(stripped) >= 3 and len(set(stripped)) <= 1:
        return True

    # 随机乱码：连续的无意义字符组合（中英文混合且没有语义）
    # 简单判断：如果长度大于5，但中文字符少于2个，英文字母少于3个，数字占比超过80%
    if len(stripped) > 5:
        chinese_count = len(re.findall(r'[\u4e00-\u9fa5]', stripped))
        english_count = len(re.findall(r'[a-zA-Z]', stripped))
        digit_count = len(re.findall(r'\d', stripped))
        total_alpha = chinese_count + english_count
        if total_alpha < 2 and digit_count / len(stripped) > 0.8:
            return True

    return False


def _looks_like_react_output(text: str) -> bool:
    """判断文本是否看起来还是 ReAct 格式的输出（没有被正确清理）

    Returns:
        True 表示看起来还是 ReAct 内部格式，需要进一步处理
    """
    if not text:
        return False

    # 常见的 ReAct 标记模式
    react_patterns = [
        r'^Action\s*:',
        r'^Action Input\s*:',
        r'^Observation\s*:',
        r'^Thought\s*:',
        r'^Final Answer\s*:',
        r'^Question\s*:',
        r'escalate_to_human',
        r'search_knowledge_base',
        r'search_faq',
        r'Action Input.*\{',
    ]

    for pattern in react_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True

    return False


def _is_refusal_response(text: str) -> bool:
    """判断 AI 的回复是否是拒答式的（说自己做不了/不支持）

    比如：
    - "我是 CloudSync 客服，不唱歌"
    - "不支持音乐播放功能"
    - "我专注于解决数据同步问题"
    - "我是 CloudSync 智能客服，专注解答数据同步问题"

    Returns:
        True 表示是拒答式回复，应该计数失败次数
    """
    if not text:
        return False

    # 拒答式回复的关键词模式
    refusal_patterns = [
        r"我是.*客服.*不[^，。！？]*[唱歌|讲故事|放歌|聊天|玩游戏|找新地球|讲故事]",
        r"不支持[^，。！？。]*[功能|服务|播放]",
        r"不提供[^，。！？。]*[功能|服务]",
        r"专注[^，。！？。]*[问题|服务|解答]",
        r"主要解决[^，。！？。]*[问题|服务]",
        r"无法为您提供[^，。！？。]*[帮助|服务]",
        r"我.*客服.*不负责",
        r"是一款.*工具.*不支持",
        r"是.*服务.*不提供",
    ]

    for pattern in refusal_patterns:
        if re.search(pattern, text):
            return True

    return False


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

    # 问候语快速判断（走 FAQ 路径，避免转人工
    greeting_keywords = [
        "你好", "您好", "hello", "hi", "嗨", "在吗", "在不",
        "谢谢", "感谢", "thank you", "thanks",
        "再见", "拜拜", "bye", "goodbye",
    ]
    content_lower = content.lower().strip()
    if any(kw in content_lower for kw in greeting_keywords):
        return {"intent": "faq", "effective_max_turns": settings.max_turns_faq}

    # 强制转人工关键词（用户明确要求或敏感问题，直接转人工）
    force_human_keywords = [
        "转人工", "人工客服", "人工服务", "找人工", "接人工",
        "我要投诉", "投诉", "我要举报", "举报",
        "退款", "退费", "退钱", "我要退", "取消账户", "注销账户",
        "talk to human", "speak to agent", "real person", "human support",
        "complaint", "refund", "cancel my account",
    ]

    if any(kw in content.lower() for kw in force_human_keywords):
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
            # 注意：LLM 分类为 human 时，不直接强制转人工，而是走 technical 路径
            # 让它通过 RAG 失败机制触发 suggest_human，由用户自己决定是否转人工
            # 只有关键词匹配的 human 才会强制转人工
            if intent == "human":
                intent = "technical"
            turns_map = {
                "faq": settings.max_turns_faq,
                "technical": settings.max_turns_technical,
            }
            return {"intent": intent, "effective_max_turns": turns_map.get(intent, 5)}
    except Exception:
        pass

    return {"intent": "technical", "effective_max_turns": settings.max_turns_technical}


# ======================================================================
# Node 3: faq_node — FAQ 常见问题匹配
# ======================================================================

def faq_node(state: AgentState) -> Dict[str, Any]:
    """FAQ 节点：尝试从常见问题库匹配答案，未匹配时用 LLM + 对话历史回答"""
    messages = state.get("messages", [])
    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    result = _faq_search(content)

    if result:
        return {"faq_match": result, "needs_human": False}
    else:
        try:
            llm = _get_intent_llm()
            history_text = ""
            if len(messages) > 1:
                history_parts = []
                for msg in messages[:-1]:
                    if isinstance(msg, HumanMessage):
                        history_parts.append(f"用户: {msg.content}")
                    elif isinstance(msg, AIMessage):
                        history_parts.append(f"客服: {msg.content}")
                history_text = "\n".join(history_parts)

            system_prompt = (
                "你是 CloudSync 智能客服助手。请根据对话历史回答用户的问题。\n"
                "如果是关于产品功能、定价、使用方法等问题，尽量简洁回答。\n"
                "如果是闲聊或身份确认类问题，根据对话历史友好回应。\n"
                "如果问题涉及你不知道的技术细节，请诚实说你不确定，建议用户描述具体问题。"
            )

            user_prompt = f"{system_prompt}\n\n"
            if history_text:
                user_prompt += f"对话历史:\n{history_text}\n\n"
            user_prompt += f"用户当前问题: {content}\n\n请回答:"

            response = llm.invoke(user_prompt)
            answer = response.content.strip()
            return {"faq_match": answer, "needs_human": False, "faq_from_llm": True}
        except Exception as e:
            logger.warning(f"FAQ fallback LLM failed: {e}")
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
    # 接入点 2: 获取对话历史
    # 优先从 state.messages 中提取（最可靠），MemoryManager 用于长期记忆
    # ==================================================================
    session_id = state.get("session_id", "")

    history = _extract_history_manual(messages)

    if memory_manager and session_id and not history:
        try:
            history = memory_manager.on_rag_start(
                session_id=session_id,
                user_message=content,
            )
        except Exception:
            logger.warning("Memory on_rag_start failed, using manual extraction",
                           exc_info=True)

    if memory_manager and session_id:
        try:
            memory_manager.on_rag_start(
                session_id=session_id,
                user_message=content,
            )
        except Exception:
            pass

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
    
    # 清理 ReAct 格式：提取最终回答部分（增强版）
    import re
    
    # 1. 先尝试找 Final Answer
    final_answer_match = re.search(r'Final Answer:\s*', output, flags=re.IGNORECASE)
    if final_answer_match:
        output = output[final_answer_match.end():].strip()
    else:
        # 2. 查找最后一个内部标记之后的内容
        react_markers = [
            'Question:', 'Thought:', 'Action:', 'Action Input:', 
            'Observation:', 'Final Answer:', 'Thought ', 'Action '
        ]
        found_any = False
        for marker in react_markers:
            matches = list(re.finditer(re.escape(marker), output, flags=re.IGNORECASE))
            if matches:
                found_any = True
                last_match = matches[-1]
                candidate = output[last_match.end():].strip()
                if candidate and not any(candidate.lower().startswith(m.lower()) for m in react_markers):
                    output = candidate
                    break
        
        # 3. 如果找到了 ReAct 标记但清理失败，说明输出格式异常，当成空处理
        if found_any and _looks_like_react_output(output):
            output = ""
    
    # 4. 再次检查：如果输出看起来还是 ReAct 格式，直接清空
    if _looks_like_react_output(output):
        output = ""
    
    # 判断是否需要转人工：通过中间步骤判断 Agent 是否真正调用了 escalate_to_human 工具
    # 注意：不能通过输出文字判断，因为 AI 可能在回复里说"欢迎转接人工客服"之类的话
    needs_human = False
    intermediate_steps = result.get("intermediate_steps", [])
    for step in intermediate_steps:
        if hasattr(step, 'action') and hasattr(step.action, 'tool'):
            if step.action.tool == 'escalate_to_human':
                needs_human = True
                break

    # 强制精简：如果回复超过120字，提取前3个要点
    import re
    if len(output) > 120:
        # 尝试提取编号列表（1. 2. 3.）
        points = re.findall(r'\d+\.\s*([^\n]+)', output)
        if points:
            # 只保留前3个要点
            top3 = points[:3]
            output = "\n".join(f"{i+1}. {p.strip()}" for i, p in enumerate(top3))
        else:
            # 没有编号列表，截断到第一句或前80字
            sentences = re.split(r'[。！？]', output)
            if len(sentences) >= 2:
                output = sentences[0] + "。" + sentences[1] + "。"
            else:
                output = output[:80] + "..."

    # ===== 幻觉防护 1: 检索置信度检查 =====
    # 如果 Agent 返回了"没有找到相关信息"，标记为拒答（不强制转人工，由 reply_node 决定是否建议转人工）
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

    # 如果是拒答且没有明确的转人工指令，标记低置信度（由 reply_node 决定是否建议转人工）
    if is_refusal and not needs_human and quality_score is None:
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
        "needs_human": needs_human,
        "quality_score": quality_score,
        "retrieved_docs": retrieved_docs,
        "answer_status": "refused" if is_refusal else "answered",
    }


# ======================================================================
# Node 5: human_node — 人工转接
# ======================================================================

def human_node(state: AgentState) -> Dict[str, Any]:
    """人工转接节点（HITL）：使用 interrupt() 暂停工作流，等待人工客服介入

    工作流在此节点暂停，把完整上下文推送给人工客服。
    人工客服审核后通过 Command(resume=...) 恢复工作流，
    本节点拿到人工的回复后继续执行后续节点（reply → END）。

    如果人工未响应（超时/离线），由调用方（arbitrator）返回兜底回复。
    """
    from langgraph.types import interrupt

    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    user_message = last_message.content[:500] if last_message else ""

    # 生成简洁的转接原因
    reason = _generate_handoff_reason(user_message)

    # 准备推送给人工客服的完整上下文
    retrieved_docs = state.get("retrieved_docs") or []
    handoff_context = {
        "user_id": state.get("user_id"),
        "session_id": state.get("session_id"),
        "tenant_id": state.get("tenant_id"),
        "user_message": user_message,
        "conversation_history": [
            {"role": _msg_role_name(m), "content": getattr(m, "content", "")[:300]}
            for m in messages[-10:]  # 最近 10 条对话
        ],
        "reason": reason,
        "ai_suggested_response": state.get("final_response", ""),
        "retrieved_docs": [
            {
                "text": getattr(d, "page_content", str(d))[:200],
                "score": getattr(d, "score", 0),
            }
            for d in retrieved_docs
        ][:3],  # 最多 3 个相关文档
        "intent": state.get("intent"),
        "turn_count": state.get("turn_count", 0),
    }

    # 暂停工作流，等待人工恢复
    human_input = interrupt({
        "type": "human_handoff",
        "context": handoff_context,
        "question": "请提供人工回复，或编辑 AI 的建议回复后提交",
    })

    # 工作流恢复后，从 human_input 取回人工回复
    human_response = (human_input or {}).get("response", "")
    human_agent_id = (human_input or {}).get("agent_id")

    return {
        "needs_human": False,  # 人工已介入，不再标记需要转人工
        "awaiting_human": False,
        "final_response": human_response or "已由人工客服为您处理。",
        "human_response": human_response,
        "human_agent_id": human_agent_id,
        "handoff_reason": reason,
        "human_handoff_context": handoff_context,
        "human_handled": True,
    }


def _msg_role_name(message) -> str:
    """从 LangChain message 对象提取角色名"""
    msg_type = getattr(message, "type", "") or ""
    if msg_type == "human":
        return "user"
    if msg_type == "ai":
        return "assistant"
    if msg_type == "system":
        return "system"
    return msg_type or "unknown"


def _generate_handoff_reason(user_message: str) -> str:
    """生成简洁的转接原因"""
    if not user_message:
        return "用户请求转人工"
    
    # 检测常见的转人工原因
    if any(kw in user_message for kw in ["转人工", "人工客服", "找人工", "人工"]):
        return "用户主动要求人工客服"
    if any(kw in user_message for kw in ["投诉", "举报", "维权"]):
        return "用户投诉"
    if any(kw in user_message for kw in ["退款", "退费", "退订", "退款"]):
        return "用户申请退款"
    if any(kw in user_message for kw in ["注销", "销户", "删除账户"]):
        return "用户申请注销账户"
    
    # 默认：取前 20 个字
    if len(user_message) > 20:
        return user_message[:20] + "..."
    return user_message


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
        model=settings.llm_complex_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        temperature=0.0,
    )

    reflect_prompt = (
        "你是一个客服质量审核员。请检查以下客服回复是否准确、完整。\n\n"
        "【审核规则】\n"
        "1. 如果回复内容准确、清晰、有用，直接输出 'PASS'\n"
        "2. 如果回复有问题需要修改，直接输出修改后的完整回复文本，不要加任何解释、说明或审查结论\n"
        "3. 不要输出'审查结论'、'事实准确性'、'问题分析'等任何审核过程文字\n"
        "4. 只输出最终给用户看的回复内容\n\n"
        f"【客服回复】\n{final_response}\n\n"
        "请输出结果："
    )

    try:
        result = reflect_llm.invoke(reflect_prompt)
        reflection_output = result.content.strip()
        # 上报 token 用量（reflect 用 complex model）
        try:
            meta = getattr(result, "response_metadata", None) or {}
            token_usage = meta.get("token_usage") or meta.get("usage") or {}
            prompt = token_usage.get("prompt_tokens") or token_usage.get("input_tokens", 0)
            completion = token_usage.get("completion_tokens") or token_usage.get("output_tokens", 0)
            if prompt or completion:
                from src.api.metrics import record_llm_tokens
                record_llm_tokens(
                    model=settings.llm_complex_model,
                    prompt_tokens=int(prompt),
                    completion_tokens=int(completion),
                    tenant_id=state.get("tenant_id", "default"),
                )
        except Exception:
            pass
    except Exception:
        return {"has_reflected": True}

    if reflection_output and reflection_output.upper() != "PASS":
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
    # 如果注入攻击被拦截，直接返回终止消息（强制转人工）
    injection_blocked = state.get("injection_blocked", False)
    if injection_blocked:
        return {
            "final_response": state.get("final_response", ""),
            "needs_human": True,
            "suggest_human": False,
            "quality_score": None,
        }

    # ===== 优先级最高：如果需要追问用户，直接返回追问内容 =====
    # （即使 final_response 已经有值，也优先用追问内容，避免显示 ReAct 脏数据）
    if clarity_status == "needs_clarification":
        clarification_q = state.get("clarification_question", "")
        if clarification_q:
            return {
                "final_response": clarification_q,
                "needs_human": False,
                "suggest_human": False,
                "quality_score": None,
                "failed_attempts": state.get("failed_attempts", 0),
            }
    
    if faq_match and not final_response:
        final_response = faq_match
    elif not final_response:
        failed_attempts = state.get("failed_attempts", 0) + 1
        suggest_human = failed_attempts >= 2
        # 检查是否是意图澄清阶段
        if clarity_status == "needs_clarification":
            # 需要追问用户
            clarification_q = state.get("clarification_question", "")
            if clarification_q:
                final_response = clarification_q
                suggest_human = False
            else:
                final_response = (
                    "抱歉，我不太明白您的问题。"
                    "您可以试着描述一下遇到的问题，我会尽力帮您～"
                )
        elif clarity_status == "rewritten":
            # 改写后的查询，使用改写后的内容重新检索
            rewritten = state.get("rewritten_query", "")
            if rewritten:
                final_response = (
                    f"抱歉，关于「{rewritten}」我暂时还答不上来。"
                    f"您可以换个方式描述，或者试试问我同步、定价、账户相关的问题～"
                )
            else:
                final_response = (
                    "抱歉，我不太明白您的问题。"
                    "您可以试着描述一下遇到的问题，我会尽力帮您～"
                )
        else:
            final_response = (
                "抱歉，这个问题我暂时还答不上来。"
                "您可以试着问我关于CloudSync的使用问题，比如同步、定价、账户等～"
            )
        
        return {
            "final_response": final_response,
            "needs_human": False,
            "suggest_human": suggest_human,
            "failed_attempts": failed_attempts,
        }

    # 如果检索置信度太低 → 友好回复，建议转人工（但不强制
    if quality_score is not None and quality_score < 0.3:
        failed_attempts = state.get("failed_attempts", 0) + 1
        suggest_human = failed_attempts >= 2
        if suggest_human:
            final_response = (
                "抱歉，我还是没能理解您的问题。"
                "您可以换个方式描述试试～"
            )
        else:
            final_response = (
                "抱歉，这个问题我暂时还答不上来。"
                "您可以试着问我关于CloudSync的使用问题，比如同步、定价、账户等～"
            )
        return {
            "final_response": final_response,
            "needs_human": False,
            "suggest_human": suggest_human,
            "quality_score": quality_score,
            "failed_attempts": failed_attempts,
        }

    # 统一精简：确保回复简洁，不超过3个要点，100字左右
    import re
    if len(final_response) > 100:
        # 尝试提取编号列表
        points = re.findall(r'\d+\.\s*([^\n]+)', final_response)
        if points:
            top3 = points[:3]
            final_response = "\n".join(f"{i+1}. {p.strip()}" for i, p in enumerate(top3))
        else:
            # 没有编号，截取前两句
            sentences = re.split(r'([。！？])', final_response)
            if len(sentences) >= 4:
                final_response = sentences[0] + sentences[1] + sentences[2] + sentences[3]
            elif len(sentences) >= 2:
                final_response = sentences[0] + sentences[1]
            else:
                final_response = final_response[:80] + "..."
    
    # ===== 拒答式回复检测：如果 AI 说自己做不了，也算作一次失败 =====
    # （比如"我是 CloudSync 客服，不唱歌"、"不支持这个功能"等）
    # 检测到后增加 failed_attempts，连续 2 次显示转人工按钮
    suggest_human = state.get("suggest_human", False)
    failed_attempts = state.get("failed_attempts", 0)
    
    if not needs_human and not suggest_human and _is_refusal_response(final_response):
        failed_attempts += 1
        if failed_attempts >= 2:
            suggest_human = True
            # 第 2 次拒答时，回复稍微调整一下
            final_response = (
                "抱歉，这个问题我暂时帮不上忙。\n"
                "您可以试着问我关于 CloudSync 的使用问题，"
                "或者点击下方按钮转接人工客服～"
            )

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

    # 返回最终结果
    # 如果是拒答式回复，保留 failed_attempts 和 suggest_human；否则重置
    # 重要：把 AI 回复添加到 messages 中，确保历史对话能被正确读取
    ai_message = AIMessage(content=final_response)
    if _is_refusal_response(final_response) and not needs_human:
        return {
            "messages": [ai_message],
            "final_response": final_response,
            "needs_human": needs_human,
            "suggest_human": suggest_human,
            "quality_score": quality_score,
            "failed_attempts": failed_attempts,
        }
    else:
        return {
            "messages": [ai_message],
            "final_response": final_response,
            "needs_human": needs_human,
            "suggest_human": False,
            "quality_score": quality_score,
            "failed_attempts": 0,
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
