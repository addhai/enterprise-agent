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
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agent.agent import CustomerServiceAgent
from src.agent.cancellable_llm import CancellableChatOpenAI, make_chat_model
from src.agent.prompt import detect_prompt_injection
from src.agent.tools import _faq_search
from src.config import settings
from src.graph.cancellation import WorkflowCancelled, check_cancelled
from src.graph.state import AgentState
from src.rag.call_policy import (
    MODE_ALWAYS,
    MODE_NEVER,
    MODE_SMART,
    REASON_FALLBACK,
    REASON_RULE,
    REASON_SCORE,
    decide_retrieval,
    dedup_docs,
    resolve_mode,
    warn_if_over_budget,
)
from src.safety.topic_guard import (
    OUT_OF_SCOPE_RESPONSE,
    enforce_topic_guard,
    has_refusal_signal,
)

logger = logging.getLogger(__name__)


# 英文「转人工」意图识别正则。
#
# 设计取舍：纯字面子串列表维护成本低但召回差，"speak to agent" 无法命中
# "speak to a human agent"。这里用两条模式覆盖绝大多数自然表达，同时保持
# 零依赖、可预测（不引入分类模型的不确定性）：
#   1. 动词 + 若干插入词 + 人工角色名词
#      （speak to a human agent / connect me with a rep）
#   2. 限定词 + 角色名词（live agent / real person / human representative）
_ENGLISH_HANDOFF_RE = re.compile(
    r"(?:\b(?:speak|talk|chat|connect|transfer|escalate|forward)\b[\w\s,']{0,30}?"
    r"\b(?:human|agent|representative|rep|person|operator|advisor|staff)\b)"
    r"|(?:\b(?:live|real|actual|human|physical)\s+"
    r"(?:agent|person|representative|rep|operator|human|support|advisor)\b)",
    re.IGNORECASE,
)

# 共享的 LLM 实例（用于意图分类，延迟初始化以避免无 API Key 时导入失败）
_intent_llm: CancellableChatOpenAI | None = None
_clarify_llm: CancellableChatOpenAI | None = None


def _get_intent_llm() -> CancellableChatOpenAI:
    """获取或初始化意图分类 LLM"""
    global _intent_llm
    if _intent_llm is None:
        _intent_llm = make_chat_model(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
            temperature=0.0,
        )
    return _intent_llm


def _get_clarify_llm() -> CancellableChatOpenAI:
    """获取或初始化意图澄清 LLM"""
    global _clarify_llm
    if _clarify_llm is None:
        _clarify_llm = make_chat_model(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
            temperature=0.0,
        )
    return _clarify_llm


# ======================================================================
# Node 1: entry_node — 入口 + 长期记忆注入
# ======================================================================


def entry_node(state: AgentState, memory_manager=None) -> dict[str, Any]:
    """入口节点：初始化对话状态，注入长期记忆上下文

    职责：
        1. 递增对话轮次
        2. 通过 MemoryManager 注入长期记忆上下文到 state.memory_context
        3. 初始化其他状态字段
        4. 统一护栏检测（v0.7 新增，对齐 multi-agent 的 Guardrail Agent）
           - 正则快检（必跑）：detect_prompt_injection + InputGuard
           - LLM 越狱检测（可选）
           - 业务相关性检查（可选）
    """
    user_id = state.get("user_id", "anonymous")
    session_id = state.get("session_id", "")
    messages = state.get("messages", [])
    last_message = messages[-1].content if messages else ""

    # ===== 统一护栏检测（v0.7，对齐 multi-agent 的 guardrail_check）=====
    # 三层检查：正则快检 → LLM越狱(可选) → 相关性(可选)
    try:
        from src.graph.guardrails import get_guardrail_agent

        guardrail = get_guardrail_agent()
        gr_result = guardrail.check(last_message)

        if gr_result.blocked:
            # 被拦截：直接终止任务
            logger.warning(
                "Guardrail blocked: reason=%s, confidence=%.2f, user=%s",
                gr_result.block_reason,
                gr_result.confidence,
                user_id,
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
                "injection_type": gr_result.block_reason,
                "final_response": gr_result.suggested_response,
            }
    except Exception as e:
        # 护栏异常时降级到原有的 detect_prompt_injection（向后兼容）
        logger.warning("Guardrail agent failed, fallback to legacy check: %s", e)
        injection = detect_prompt_injection(last_message)
        if injection["is_injection"]:
            logger.warning(
                "Prompt injection detected (legacy): type=%s, confidence=%.2f, user=%s",
                injection["attack_type"],
                injection["confidence"],
                user_id,
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
                    "检测到异常请求，已自动终止。如需帮助请联系人工客服。"
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
            logger.warning(
                "Memory context injection failed, continuing without it", exc_info=True
            )

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


def clarify_node(state: AgentState) -> dict[str, Any]:
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
    content = (
        last_message.content if hasattr(last_message, "content") else str(last_message)
    )
    memory_context = state.get("memory_context", "")

    # ===== 检查是否是无意义输入（纯数字、乱码等）=====
    if _is_nonsensical_input(content):
        return {
            "clarity_status": "needs_clarification",
            "missing_info": ["问题描述"],
            "clarification_question": (
                "抱歉，我不太明白您输入的内容是什么意思～\n\n"
                "您可以试着描述一下您遇到的问题，比如：\n"
                "• 「F02故障代码怎么处理」\n"
                "• 「测温不准怎么校准」\n"
                "• 「怎么重置密码」\n\n"
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
    if re.match(r"^\d+$", stripped):
        return True

    # 纯符号/特殊字符
    if re.match(r"^[^\w\u4e00-\u9fa5]+$", stripped):
        return True

    # 重复字符（比如 "aaaaa"、"哈哈哈" 太多）
    if len(stripped) >= 3 and len(set(stripped)) <= 1:
        return True

    # 随机乱码：连续的无意义字符组合（中英文混合且没有语义）
    # 简单判断：如果长度大于5，但中文字符少于2个，英文字母少于3个，数字占比超过80%
    if len(stripped) > 5:
        chinese_count = len(re.findall(r"[\u4e00-\u9fa5]", stripped))
        english_count = len(re.findall(r"[a-zA-Z]", stripped))
        digit_count = len(re.findall(r"\d", stripped))
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
        r"^Action\s*:",
        r"^Action Input\s*:",
        r"^Observation\s*:",
        r"^Thought\s*:",
        r"^Final Answer\s*:",
        r"^Question\s*:",
        r"escalate_to_human",
        r"search_knowledge_base",
        r"search_faq",
        r"Action Input.*\{",
    ]

    for pattern in react_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True

    return False


def _is_refusal_response(text: str) -> bool:
    """判断 AI 的回复是否是拒答式的（说自己做不了/不支持）

    比如：
    - "我是设备客服，不唱歌"
    - "不支持音乐播放功能"
    - "我专注于解决设备故障问题"
    - "我是设备智能客服，专注解答设备使用问题"

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

    return any(re.search(pattern, text) for pattern in refusal_patterns)


def _detect_missing_info(content: str, memory_context: str) -> list[str]:
    """检测用户问题中缺失的关键信息

    Returns:
        缺失信息列表，如 ["SDK 版本", "错误码"]
    """
    content_lower = content.lower()
    missing: list[str] = []

    # 错误类问题必须有错误码
    error_indicators = ["error", "报错", "错误", "fail", "failed", "异常", "bug"]
    if any(kw in content_lower for kw in error_indicators):
        # 检查是否提供了错误码
        has_error_code = bool(re.search(r"\d{3,4}", content))
        has_error_msg = bool(
            re.search(r"ERR_|error_code|exception|traceback", content_lower)
        )
        if not has_error_code and not has_error_msg:
            missing.append("错误码或错误详情")

    # 配置类问题必须有设备型号或产品标识
    config_indicators = ["配置", "setup", "configure", "设置", "安装"]
    if any(kw in content_lower for kw in config_indicators):
        # 检查是否指定了具体设备型号/产品（含常见工业型号与固件/SDK 标识）
        product_names = [
            "型号",
            "t90",
            "t100",
            "thermosense",
            "固件",
            "firmware",
            "sdk",
            "api",
            "console",
            "app",
        ]
        if not any(kw in content_lower for kw in product_names):
            missing.append("设备型号或产品名称")

    # 排查类问题必须有技术环境
    troubleshoot_indicators = ["排查", "troubleshoot", "问题", "问题", "怎么"]
    if any(kw in content_lower for kw in troubleshoot_indicators):
        env_indicators = [
            "version",
            "v\\d",
            "sdk",
            "python",
            "javascript",
            "node",
            "java",
            "windows",
            "linux",
            "mac",
        ]
        if not any(re.search(ind, content_lower) for ind in env_indicators):
            missing.append("技术环境（SDK 版本/操作系统）")

    return missing


def _try_infer_from_memory(
    missing_info: list[str], memory_context: str
) -> dict[str, str]:
    """尝试从长期记忆中推断缺失信息

    Returns:
        {"SDK版本": "v2.3", "操作系统": "Linux"} 或 {}
    """
    if not memory_context:
        return {}

    inferred: dict[str, str] = {}
    memory_lower = memory_context.lower()

    # SDK 版本推断
    if "SDK 版本" in str(missing_info):
        version_match = re.search(
            r"(?:SDK|sdk)[\s：:]*([\w.-]+(?:v\d+\.\d+)?)", memory_lower
        )
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


def _rewrite_query(original: str, inferred: dict[str, str]) -> str:
    """根据推断信息改写查询"""
    if not inferred:
        return original

    additions = []
    for key, value in inferred.items():
        additions.append(f"{key}是{value}")

    addition_text = "，".join(additions)
    return f"{original}（补充信息：{addition_text}）"


def _generate_clarification_question(missing_info: list[str], original: str) -> str:
    """生成追问用户的提示"""
    if not missing_info:
        return ""

    questions = [f"您能否提供关于「{info}」的更多信息？" for info in missing_info]

    return (
        "为了更好地帮助您，我需要了解更多细节：\n\n"
        + "\n".join(f"• {q}" for q in questions)
        + "\n\n提供这些信息后我可以给您更准确的答案。"
    )


def _detect_negative_emotion(content: str) -> str | None:
    """检测用户消息中的强烈负面情绪（按场景分级转人工：情绪激动自动转）

    检测维度：
        1. 愤怒/辱骂词汇（中文 + 英文）
        2. 标点特征：连续多个感叹号/问号（!!! ??? 等）
        3. 重复抱怨词（同一负面词重复出现）

    Returns:
        情绪类型字符串（如 "愤怒"、"急躁"），无强烈情绪返回 None。
    """
    if not content:
        return None

    text = content.lower()

    # 1. 愤怒/辱骂词汇
    anger_words = [
        "气死",
        "气炸",
        "破系统",
        "破软件",
        "垃圾",
        "什么玩意",
        "太差劲",
        "差劲",
        "无语",
        "恶心",
        "骗人",
        "骗子",
        "坑人",
        "狗屎",
        "他妈",
        "卧槽",
        # 只能收明确脏话组合，禁止用单字「操」：子串匹配会误伤极高频
        # 正常词「操作/操作步骤」（实测 GP04 黑体校准操作、GP07 按键操作
        # 步骤被误判愤怒直接转人工）。「操你/操他/操蛋」不与「操作」共现。
        "操你",
        "操他",
        "操蛋",
        "shit",
        "fuck",
        "damn",
        "受不了",
        "受够了",
        "崩溃",
        "疯掉",
        "烦死",
        "讨厌",
        "什么破",
        "烂透了",
        "太烂了",
        "骗钱",
    ]
    if any(w in text for w in anger_words):
        return "愤怒"

    # 2. 标点特征：连续 3 个及以上感叹号/问号
    if re.search(r"[！!]{3,}", content) or re.search(r"[？?]{3,}", content):
        return "急躁"

    # 3. 重复抱怨：同一负面词重复出现 2 次以上
    complaint_words = ["不行", "不对", "不好", "不能用", "没法", "没办法", "解决不了"]
    for w in complaint_words:
        if text.count(w) >= 2:
            return "急躁"

    return None


# ======================================================================
# Node 2: router_node — 意图路由
# ======================================================================


def router_node(state: AgentState) -> dict[str, Any]:
    """意图路由节点：分析用户意图，决定走哪条路径"""
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "faq"}

    last_message = messages[-1]
    content = (
        last_message.content if hasattr(last_message, "content") else str(last_message)
    )

    # 问候语快速判断（走 FAQ 路径，避免转人工
    greeting_keywords = [
        "你好",
        "您好",
        "hello",
        "hi",
        "嗨",
        "在吗",
        "在不",
        "谢谢",
        "感谢",
        "thank you",
        "thanks",
        "再见",
        "拜拜",
        "bye",
        "goodbye",
    ]
    content_lower = content.lower().strip()
    if any(kw in content_lower for kw in greeting_keywords):
        return {"intent": "faq", "effective_max_turns": settings.max_turns_faq}

    # 强制转人工关键词（用户明确要求或敏感问题，直接转人工）
    force_human_keywords = [
        "转人工",
        "人工客服",
        "人工服务",
        "找人工",
        "接人工",
        "我要投诉",
        "投诉",
        "我要举报",
        "举报",
        "退款",
        "退费",
        "退钱",
        "我要退",
        "取消账户",
        "注销账户",
        "talk to human",
        "speak to agent",
        "real person",
        "human support",
        "complaint",
        "refund",
        "cancel my account",
    ]

    if any(kw in content.lower() for kw in force_human_keywords):
        return {"intent": "human", "effective_max_turns": settings.max_turns_faq}

    # 英文转人工请求：字面子串匹配太脆（例如 "speak to agent" 匹配不到
    # "speak to a human agent"，中间插了冠词与形容词）。改用容忍插入词的正则，
    # 覆盖 "connect me with a live representative" 这类自然表达。
    if _ENGLISH_HANDOFF_RE.search(content_lower):
        return {"intent": "human", "effective_max_turns": settings.max_turns_faq}

    # 情绪激动检测（按场景分级转人工：情绪激动自动转人工）
    emotion = _detect_negative_emotion(content)
    if emotion:
        logger.info("Negative emotion detected, auto-escalating: %s", emotion)
        return {
            "intent": "human",
            "effective_max_turns": settings.max_turns_faq,
            "escalation_reason": f"情绪激动：{emotion}",
        }

    # 快速规则判断 FAQ vs Technical
    faq_keywords = [
        "reset password",
        "forgot password",
        "change plan",
        "pricing",
        "how much",
        "cancel subscription",
        "api key",
        "enable 2fa",
        "two factor",
    ]

    if any(kw in content.lower() for kw in faq_keywords):
        return {"intent": "faq", "effective_max_turns": settings.max_turns_faq}

    # 其他情况尝试 LLM 分类
    try:
        llm = _get_intent_llm()
        classification = llm.invoke(
            f"将以下用户消息分类为 'faq'（简单常见问题）、"
            f"'technical'（需要技术文档）或 'human'（需要人工客服）。"
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
    except Exception as e:
        # 协作式取消透传，其余分类异常按默认 technical 降级
        if isinstance(e, WorkflowCancelled):
            raise

    return {"intent": "technical", "effective_max_turns": settings.max_turns_technical}


# ======================================================================
# Node 3: faq_node — FAQ 常见问题匹配
# ======================================================================


def faq_node(state: AgentState) -> dict[str, Any]:
    """FAQ 节点：只做本地常见问题库的确定性匹配。

    硬约束（2026-10-07 金标题库 GR01 等 12 题实测驱动）：
        未命中必须返回 faq_match=None，由 workflow 的 _decide_after_faq
        边路由到 rag 节点走真实检索。此前未命中时用 LLM 无资料裸答，
        导致医疗越界（GR01 编造「额温 37.3℃ 算发烧」）、规格参数编造
        （GF06 量程、GF16 电池容量等共 12 题零引用幻觉），整条绕过 RAG。
        提示词里的「不要编造」约束不住 7B 的参数化知识冲动，故删除该分支。
    """
    messages = state.get("messages", [])
    last_message = messages[-1]
    content = (
        last_message.content if hasattr(last_message, "content") else str(last_message)
    )

    result = _faq_search(content)

    if result:
        return {"faq_match": result, "needs_human": False}
    return {"faq_match": None, "needs_human": False}


# ======================================================================
# kb_call_mode 三模式辅助（Phase5 语义收口，判据见 src/rag/call_policy.py）
# ======================================================================

#: never 模式直答的系统约束：不声称查阅知识库，不确定的事实不编造
_NEVER_MODE_SYSTEM_PROMPT = (
    "你是智能客服助手，当前为纯对话模式，系统没有为你检索任何知识库资料。"
    "规则：1. 全程使用中文，依据你的通用知识与对话历史直接、简洁地回答；"
    "2. 不得声称自己查阅了知识库、文档或资料；"
    "3. 涉及具体参数、故障代码、政策细则等你无法核实的事实时，不要编造，"
    "诚实说明当前无法核实，并建议用户联系人工客服。"
)

#: 预检索/探测命中后拼进用户消息的上下文模板（小模型对「消息内事实」的
#: 遵从度高于工具返回，直接注入可降低 7B 模型无视检索结果的概率）
_PRE_RETRIEVED_HEADER = (
    "==== 系统已预先检索到以下知识库资料，请优先依据其中事实用中文直接回答；"
    "资料未覆盖的部分再结合你的判断，禁止编造资料中不存在的参数或来源 ===="
)

#: 高置信命中直答的系统提示词（旁路 ReAct 专用）。
#: 2026-10-05 实测：旧版 CloudSync SaaS 人设与工业设备知识库错位，7B 模型会
#: 无视已注入资料去调云资源工具。直答路径用中性设备技术支持人设，把模型钉在
#: 「只依据资料作答」这一件事上，不暴露任何具体产品或公司名。
#: 2026-10-06 起 ReAct 主提示词已同步收口为设备技术支持，两者人设口径一致。
#: 2026-10-08 金标 7B 生成质量归因：旧版「回复简洁直接」被小模型执行成提前收尾，
#: 多子问题漏问、长流程漏后半段、分档参数只答一档、资料已给判据却声称未给出。
#: 新版规则 2~5 把「完整覆盖」拆成可执行条款，简洁要求降为规则 6 并明确
#: 「完整性优先于简短」；只依据资料作答与无覆盖拒答（规则 1、7）保持不变。
#: 2026-10-08 晚 few-shot 具体范例实验证伪并回退：7B 会把示范中的虚构事实
#: （汽油/松香水禁忌）照抄进真实答案，污染危害大于其救回的 GF02 一题。
#: 结论：本 prompt 只保留规则约束，不得加入含具体事实的问答范例。
_DIRECT_ANSWER_SYSTEM_PROMPT = (
    "你是设备产品技术支持助手。请严格依据用户消息中提供的知识库资料原文事实，"
    "用简体中文回答用户的最后一个问题。\n"
    "规则：\n"
    "1. 答案必须来自资料，禁止编造资料中没有的参数、代码含义、步骤或结论；\n"
    "2. 完整性优先于简短。先找出问题中的每一个提问点，逐点作答，"
    "不得跳过或漏掉任何一问；\n"
    "3. 操作流程类问题按资料顺序分点列出全部步骤，资料有几步就写几步，"
    "禁止中途收尾；资料中的前提条件、禁忌与注意事项也要写出，"
    "保留关键数字与警示（如禁止拆卸等）；\n"
    "4. 周期、阈值、规格类参数，资料按场景分档时列出所有档位及适用条件，"
    "再说明用户场景对应哪一档；故障或错误代码先解释代码含义，再给处理方法；\n"
    "5. 资料已写明的判据、阈值、数字必须原样保留；资料中有明确内容时，"
    "禁止回答「未明确给出」，也不得省略；\n"
    "6. 语言简练，先给结论再给步骤，不要寒暄，不要复述问题，"
    "不要输出「根据文档第几条」这类元信息；\n"
    "7. 如果资料完全无法覆盖用户问题，只回复一句：资料中未找到该问题的相关信息，"
    "建议联系技术支持。\n"
    "8. 不要提及你是 AI、模型，也不要出现任何与设备无关的具体产品或公司名称。"
)

#: 直答输出被判为「模型自认答不出」的严格词集。命中说明高相似资料都没被用上，
#: 直答失败，回落 ReAct Agent 走既有兜底，而不是把这句话直接发给用户。
_DIRECT_UNANSWERED_MARKERS = (
    "资料中未找到",
    "未找到相关",
    "找不到相关",
    "没有相关信息",
    "无法回答",
    "无法核实",
    "知识库中不存在",
    "答不上来",
)


# ======================================================================
# M3：跨块综合专用编排（2026-10-09，设计见 docs/M3-跨块综合编排设计.md）
# ----------------------------------------------------------------------
# 针对 GS01/GS02/GP06 类跨块题：资料全在上下文，7B 却只盯最显著一块，
# 期限、保修状态、裁决依据等支撑事实系统性丢失。两板斧，均零额外 LLM 调用：
#   1. 标签化综合：强制模型先输出 <coverage>（提问点 + 逐块要点 + 覆盖表），
#      再输出 <answer>；服务端剥离，用户只看到答案段。
#   2. 信号保底补块：问题含保修/退货/裁决信号词时，用内存 BM25 毫秒级
#      把被 rerank 挤出 top_k 的政策块补注入（retriever.keyword_search）。
# 由 settings.synthesis_enabled 总开关控制，关闭时与 M2 prompt v1 逐字节一致。
# ======================================================================

#: 综合段标签正则。IGNORECASE 兼容 7B 偶发大写标签；非贪婪取第一个 answer。
_SYNTHESIS_COVERAGE_RE = re.compile(
    r"<coverage>\s*(.*?)\s*</coverage>", re.DOTALL | re.IGNORECASE
)
_SYNTHESIS_ANSWER_RE = re.compile(
    r"<answer>\s*(.*?)\s*</answer>", re.DOTALL | re.IGNORECASE
)
#: 7B 真机实测约 2/3 概率漏写闭合标签（只输出 <answer> 开头直接作答），
#: 这两个容错正则兜住「有开标签无闭标签」形态。
_COVERAGE_OPEN_RE = re.compile(
    r"<coverage>\s*(.*?)\s*<answer[\s>]", re.DOTALL | re.IGNORECASE
)
_ANSWER_OPEN_RE = re.compile(r"<answer>\s*(.*)$", re.DOTALL | re.IGNORECASE)
_LOOSE_TAG_RE = re.compile(r"</?(?:coverage|answer)\s*>", re.IGNORECASE)

#: M3 直答系统提示词：在 M2 八条规则外加强制两段式输出。
#: 注意（M2 few-shot 证伪教训）：格式示例只给占位结构，禁止出现任何
#: 具体设备事实，7B 会把示例里的虚构参数照抄进真实答案。
_SYNTHESIS_DIRECT_ANSWER_SYSTEM_PROMPT = (
    "你是设备产品技术支持助手。请严格依据用户消息中提供的知识库资料原文事实，"
    "用简体中文回答用户的最后一个问题。\n"
    "输出只能包含下面两个标签段，先写 coverage 再写 answer，"
    "两个标签都必须写出闭合标记，</answer> 是全文最后一个字符：\n"
    "<coverage>\n"
    "先用一行逐块列出每份文档与问题相关的关键事实（写「文档1：…」），"
    "数字、期限、天数、保修周期、冲突裁决依据照录；再用一行列出问题每个"
    "提问点（①②③）分别由哪份文档支撑，无资料的标注「无资料」。\n"
    "</coverage>\n"
    "<answer>\n"
    "1. 答案必须来自资料，禁止编造资料中没有的参数、步骤或结论；\n"
    "2. coverage 拆出的每个提问点逐点作答不得漏；完整性优先于简短；\n"
    "3. 操作流程按资料顺序列全部步骤，禁止提前收尾；前提条件、禁忌、"
    "关键数字与警示（如禁止拆卸）必须写出；\n"
    "4. 周期、天数、阈值、规格、保修按场景列全各档，并结合用户场景给"
    "结论（如购买时长是否在保、签收第几天适用哪条期限）；错误代码先"
    "解释含义再给处理方法；\n"
    "5. 资料写明的判据、数字、天数、期限原样保留，有明确内容不得省略；\n"
    "6. 先结论后步骤，不寒暄不复述问题，不出现①②③、「文档N」字样或"
    "任何标签；\n"
    "7. 资料完全无法覆盖时只回复：资料中未找到该问题的相关信息，"
    "建议联系技术支持。\n"
    "8. 不要提及你是 AI、模型，不要出现与设备无关的产品或公司名称。\n"
    "</answer>"
)

#: 提问点信号词 → BM25 保底查询词。命中即对该查询词做一次纯内存关键词
#: 检索，把被 rerank 挤出 top_k 的政策类支撑块补回来。
#: 元组顺序即补块优先级：保修/退货是实测丢分重灾区，裁决规则殿后。
_SYNTHESIS_SIGNAL_LEXICON: tuple[tuple[tuple[str, ...], str], ...] = (
    (("保修", "保内", "质保", "三包", "保修范围", "还在保"), "保修"),
    (("退货", "换货", "退吗", "退款", "无理由", "几天内退"), "退货"),
    (("以哪个为准", "以哪份", "为准", "不一致", "冲突", "矛盾"), "规格说明书 为准"),
)


def detect_synthesis_signals(question: str) -> list[str]:
    """识别需要保底补块的跨域信号，返回去重后的 BM25 查询词列表。

    纯规则、零外部依赖，供确定性单测直接断言。
    """
    hits: list[str] = []
    text = question or ""
    for words, bm25_query in _SYNTHESIS_SIGNAL_LEXICON:
        if any(w in text for w in words) and bm25_query not in hits:
            hits.append(bm25_query)
    return hits


#: 长流程/清单类提问的引导词。命中时跳过 coverage 逐块分析，直答走 M2 原
#: prompt。50 题 A/B 对照（2026-10-09）的实测分界：coverage 对短事实综合
#: 题（周期/参数冲突/在保判定，目标答案 50-150 字）净救回 4 题零新挂；
#: 对步骤清单题（目标答案 250-330 字）则挤占 2048 token 配额与注意力，
#: GP01 答案由 328 字 pass 退化为 232 字 fail、GS14 打满 600s 硬超时。
_SYNTHESIS_FLOW_BYPASS_RE = re.compile(
    r"步骤|流程|清单|规程|怎么操作|如何操作|操作顺序|前几步"
)


def _distinct_doc_sources(docs: list) -> set[str]:
    """提取注入文档的去重来源名，兼容 Document 与 (Document, score) 两种形态。"""
    sources: set[str] = set()
    for item in docs or []:
        doc = item[0] if isinstance(item, tuple | list) else item
        metadata = getattr(doc, "metadata", None)
        if isinstance(metadata, dict):
            source = metadata.get("source")
            if source:
                sources.add(str(source))
    return sources


def should_use_synthesis(question: str, docs: list) -> bool:
    """逐题判定是否启用 coverage 综合路径（总开关之外的二级门控）。

    必要条件（同时满足）：
      1. 注入资料来自至少 2 个不同来源文档。同一文档的多个相邻 chunk 只是
         长内容切片，不存在跨块综合，强上 coverage 只增延迟。
      2. 问题不含长流程/清单引导词（见 _SYNTHESIS_FLOW_BYPASS_RE）。
         这类题答案天然是长枚举，coverage 分析段挤占输出预算，M2 单段
         直答的完整性与延迟都更好。

    纯函数零外部依赖，确定性单测可覆盖全部边界。
    """
    return bool(
        question
        and len(_distinct_doc_sources(docs)) >= 2
        and not _SYNTHESIS_FLOW_BYPASS_RE.search(question)
    )


def merge_supplement_docs(
    primary: list,
    supplement: list,
    max_total: int,
) -> list:
    """把保底补块并入主检索结果，按内容前 100 字去重，受总量上限约束。

    去重口径与 _merge_standard_and_sentence 完全一致，避免同一块重复注入。
    """
    merged = list(primary or [])
    seen = {getattr(d, "page_content", "")[:100] for d in merged}
    for doc in supplement or []:
        if len(merged) >= max_total:
            break
        key = getattr(doc, "page_content", "")[:100]
        if key and key not in seen:
            seen.add(key)
            merged.append(doc)
    return merged


def _extract_synthesis_sections(output: str) -> tuple[str, str | None, bool]:
    """从模型原始输出剥离 coverage/answer 两段。

    真机实测 7B 常漏写闭合标签，按四级容错处理：
      1. <answer>..</answer> 完整：取内容，well_formed=True
      2. 只有 <answer> 开标签：取到文末，well_formed=False
      3. 无 answer 标签：剥掉 coverage 段取裸答案，well_formed=False
      4. 全空：降级原文
    任何返回路径都不允许标签残骸流向用户。
    """
    text = output or ""

    # coverage：闭合段优先，否则取 <coverage> 到 <answer> 之间
    cov_match = _SYNTHESIS_COVERAGE_RE.search(text)
    if cov_match:
        coverage = cov_match.group(1).strip()
    else:
        open_cov = _COVERAGE_OPEN_RE.search(text)
        coverage = open_cov.group(1).strip() if open_cov else None

    # 1. 完整闭合 answer
    ans = _SYNTHESIS_ANSWER_RE.search(text)
    if ans and ans.group(1).strip():
        return ans.group(1).strip(), coverage, True

    # 2. 有开标签无闭合：取到文末
    open_ans = _ANSWER_OPEN_RE.search(text)
    if open_ans and open_ans.group(1).strip():
        return open_ans.group(1).strip(), coverage, False

    # 3. 无 answer 标签：剥除 coverage（含无闭合形态）与所有标签残骸
    stripped = _SYNTHESIS_COVERAGE_RE.sub("", text)
    stripped = re.sub(r"<coverage>.*$", "", stripped, flags=re.DOTALL | re.IGNORECASE)
    stripped = _LOOSE_TAG_RE.sub("", stripped).strip()
    return (stripped or text.strip()), coverage, False


def _format_pre_retrieved_context(docs: list, max_docs: int = 5) -> str:
    """把预检索 Document 列表格式化成模型可读的参考资料块。"""
    blocks = []
    for i, doc in enumerate((docs or [])[:max_docs], start=1):
        meta = getattr(doc, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        source = meta.get("source") or meta.get("doc_id") or "未知来源"
        chapter = (
            meta.get("chapter_path") or meta.get("chapter") or meta.get("title") or ""
        )
        header = f"[文档{i}] 来源：{source}" + (f" 章节：{chapter}" if chapter else "")
        content = getattr(doc, "page_content", "") or ""
        blocks.append(f"{header}\n{content[:1500]}")
    return "\n\n".join(blocks)


def _build_agent_input(
    content: str, pre_retrieved_docs: list, max_docs: int = 5
) -> str:
    """always / smart 命中时，把预检索资料随用户消息一并交给 Agent。"""
    if not pre_retrieved_docs:
        return content
    context = _format_pre_retrieved_context(pre_retrieved_docs, max_docs=max_docs)
    return f"{content}\n\n{_PRE_RETRIEVED_HEADER}\n{context}"


def _supplement_pre_retrieved_docs(
    content: str,
    docs: list,
    retriever,
    user_id: str,
    tenant_id: str,
    user_access_levels: list | None,
) -> tuple[list, list[tuple[str, str]]]:
    """M3 信号保底：按问题信号词用内存 BM25 补入政策类支撑块。

    只在 synthesis_enabled 且主检索结果未达注入上限时执行；
    任何异常都静默返回原 docs，保底是增强不是依赖。

    Returns:
        (合并后的 docs, 实际补入的 [(信号词, 来源), ...] 供日志观测)
    """
    signals = detect_synthesis_signals(content)
    if not signals:
        return docs, []
    max_total = int(getattr(settings, "synthesis_max_injected_docs", 6) or 6)
    if len(docs) >= max_total or not hasattr(retriever, "keyword_search"):
        return docs, []

    supplemented = list(docs)
    added: list[tuple[str, str]] = []
    for keyword in signals[:2]:  # 最多两类信号，防过度注入
        try:
            hits = retriever.keyword_search(
                keyword,
                top_k=3,
                tenant_id=tenant_id,
                user_id=user_id,
                user_access_levels=user_access_levels,
            )
        except Exception:  # noqa: BLE001 - 保底失败不阻断主链路
            logger.warning("M3 信号保底检索失败（已忽略）：%s", keyword, exc_info=True)
            continue
        before = len(supplemented)
        supplemented = merge_supplement_docs(supplemented, hits, max_total)
        for doc in supplemented[before:]:
            source = (
                (doc.metadata or {}).get("source")
                if isinstance(getattr(doc, "metadata", None), dict)
                else "?"
            )
            added.append((keyword, str(source)))
        if len(supplemented) >= max_total:
            break
    if added:
        logger.info("M3 信号保底补块：%s", added)
    return supplemented, added


def _count_agent_kb_searches(messages: list) -> int:
    """事后统计 Agent 自主调用 search_knowledge_base 的次数（Phase5 §2.5）。

    LangGraph create_agent 的工具调用记录在 AIMessage.tool_calls 上。
    只计数、不阻断，超软上限由 warn_if_over_budget 出 warning。
    """
    count = 0
    for message in messages or []:
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            if isinstance(call, dict) and call.get("name") == "search_knowledge_base":
                count += 1
    return count


# 库外收口窄化判据（2026-10-07 金标题 GP04 误伤驱动）。
# 仅靠「直答自认未覆盖 + ReAct 零检索」会误杀高相关库内题（GP04 预检索
# top1 向量相似度 0.647、校准语料高相关，但 7B 直答保守地说「未找到」，
# 回落 ReAct 又偷懒零检索）。故追加两个确定性条件，四者同时成立才收口：
#   1. 预检索 top1 相似度低于此地板（GR05 打印机实测 0.463；GP04 0.647）
#   2. query 实词 2-gram 在召回语料的命中率低于此比例（GR05 约 0.05~0.10，
#      「打印机/卡纸」语料零出现；GP04 约 0.55，「校准/读数/稳定」高频）
# 50 题实测纯向量相似度对库外不可分（GR05 0.463 与正常题 GF15 0.465、
# GF16 0.464、GP02 0.460 混叠），词面覆盖用来解这个混叠。
_OUT_OF_SCOPE_SIM_FLOOR = 0.50
_OUT_OF_SCOPE_LEXICAL_RATIO = 0.12

# 中文 2-gram 里的疑问/客套停用组合，不计入实词覆盖
_LEXICAL_STOP_BIGRAMS = frozenset(
    {
        "怎么",
        "一个",
        "我们",
        "你们",
        "你好",
        "请问",
        "一下",
        "可以",
        "应该",
        "需要",
        "如何",
        "什么",
        "多少",
        "哪里",
        "为什",
        "顺便",
        "问一",
    }
)


def query_corpus_bigram_overlap(query: str, docs: list) -> float:
    """query 实词在召回文档全文中的 2-gram 命中率，用于库外确定性判定。

    中文取去停用的相邻两字 bigram，英文/数字取长度≥2 的整体词。
    返回命中数 / 实词数；提不出实词时返回 1.0（无法判定，按相关处理，
    宁可漏收口也不误伤）。纯函数，无 IO、无分词依赖。
    """
    # CJK 统一表意文字 U+4E00-U+9FFF
    zh_chars = "".join(re.findall(r"[一-鿿]", query or ""))
    grams: set[str] = set()
    for i in range(len(zh_chars) - 1):
        gram = zh_chars[i : i + 2]
        if gram not in _LEXICAL_STOP_BIGRAMS:
            grams.add(gram)
    for token in re.findall(r"[a-zA-Z0-9]+", query or ""):
        if len(token) >= 2:
            grams.add(token.casefold())
    if not grams:
        return 1.0

    corpus_parts = []
    for doc in docs or []:
        content = getattr(doc, "page_content", None)
        corpus_parts.append(content if isinstance(content, str) else str(doc))
    corpus = "".join(corpus_parts).casefold()
    hit = sum(1 for gram in grams if gram in corpus)
    return hit / len(grams)


def _direct_answer_without_retrieval(
    content: str, history: list, mode: str
) -> dict[str, Any]:
    """kb_call_mode=never：不构建 Agent、不检索，LLM 仅依据对话历史直答。

    LLM 失败时置 answer_status="refused"，保持空引用，绝不静默转去检索
    （模式契约不可被降级悄悄破坏，见拆解方案 §2.3）。
    """
    base = {
        "needs_human": False,
        "tool_sourced": False,
        "retrieved_docs": [],
        "kb_call_mode": mode,
        "retrieval_decided_by": MODE_NEVER,
        "retrieval_count": 0,
        "answer_path": "direct_no_retrieval",
    }
    try:
        llm = _get_intent_llm()
        direct_messages: list = [SystemMessage(content=_NEVER_MODE_SYSTEM_PROMPT)]
        for human_msg, ai_msg in history or []:
            direct_messages.append(HumanMessage(content=human_msg))
            if ai_msg:
                direct_messages.append(AIMessage(content=ai_msg))
        direct_messages.append(HumanMessage(content=content))
        response = llm.invoke(direct_messages)
        output = getattr(response, "content", None)
        output = str(output).strip() if output is not None else ""
        return {
            **base,
            "final_response": output,
            "quality_score": None,
            "answer_status": "answered",
        }
    except Exception as e:  # noqa: BLE001 - 直答异常只置拒答，不得触发检索
        if isinstance(e, WorkflowCancelled):
            raise
        logger.warning("never 模式直答失败，置 refused（不静默转检索）：%s", e)
        return {
            **base,
            "final_response": "",
            "quality_score": 0.2,
            "answer_status": "refused",
            "answer_path": "direct_no_retrieval",
        }


def _direct_synthesize_with_docs(
    content: str,
    history: list,
    docs: list,
    mode: str,
    retrieval_decided_by: str,
    retrieval_count: int,
) -> tuple[dict[str, Any] | None, str]:
    """高置信命中直答：不构建工具 Agent，单次 LLM 调用直接依据预检索资料合成。

    用于绕过 7B 模型在多工具 ReAct 下的误路由/不收敛（生产实测：F02 检索 top1
    相似度 0.55，资料含正确答案，Agent 仍 5 轮空转走兜底）。

    返回 ``(result, reason)``。result 非 None 时 reason 为空串；直答不可用时
    result 为 None，reason 取值：
      - ``"llm_error"``  LLM 调用异常
      - ``"empty"``      模型返回空串
      - ``"uncovered"``  模型自认资料未覆盖（命中 _DIRECT_UNANSWERED_MARKERS）。
        该信号是高质量的库外证据（注入资料后模型仍说没有），调用方回落
        ReAct 后应保留它，供输出侧库外收口双信号使用（GR05 缺陷修复）。
    """
    synthesis_enabled = bool(getattr(settings, "synthesis_enabled", False))
    # 二级门控：总开关开时仍逐题判定，只对多来源短综合题启用 coverage；
    # 单文档题与长流程清单题保持 M2 prompt（50 题对照实测，见
    # should_use_synthesis 注释）。
    synthesis_on = synthesis_enabled and should_use_synthesis(content, docs)
    if synthesis_enabled and not synthesis_on:
        logger.info(
            "M3 门控跳过 coverage：sources=%d flow_bypass=%s",
            len(_distinct_doc_sources(docs)),
            bool(_SYNTHESIS_FLOW_BYPASS_RE.search(content or "")),
        )
    system_prompt = (
        _SYNTHESIS_DIRECT_ANSWER_SYSTEM_PROMPT
        if synthesis_on
        else _DIRECT_ANSWER_SYSTEM_PROMPT
    )
    inject_max = (
        int(getattr(settings, "synthesis_max_injected_docs", 6) or 6)
        if synthesis_on
        else 5
    )
    try:
        llm = _get_intent_llm()
        messages: list = [SystemMessage(content=system_prompt)]
        for human_msg, ai_msg in history or []:
            messages.append(HumanMessage(content=human_msg))
            if ai_msg:
                messages.append(AIMessage(content=ai_msg))
        messages.append(
            HumanMessage(content=_build_agent_input(content, docs, max_docs=inject_max))
        )
        response = llm.invoke(messages)
        raw_output = str(getattr(response, "content", "") or "").strip()
    except Exception as e:  # noqa: BLE001 - 任何异常都回落 Agent
        # 协作式取消必须透传，否则断线/硬超时会被当成普通失败回落 ReAct
        if isinstance(e, WorkflowCancelled):
            raise
        logger.warning("高置信直答异常，回落 ReAct Agent：%s", e)
        return None, "llm_error"

    if not raw_output:
        logger.info("高置信直答返回空，回落 ReAct Agent")
        return None, "empty"

    if synthesis_on:
        # M3：剥离 <coverage> 分析段，只外发 <answer>；marker 检测必须在
        # 剥离后的答案上做，coverage 里「某提问点无资料」会含未覆盖词，
        # 用原文判定会误判成库外题。
        output, _coverage, well_formed = _extract_synthesis_sections(raw_output)
        if not well_formed:
            logger.warning(
                "M3 综合输出未遵守标签格式，已降级剥离，原文前 60 字：%s",
                raw_output[:60],
            )
    else:
        output = raw_output

    if any(marker in output for marker in _DIRECT_UNANSWERED_MARKERS):
        logger.info("高置信直答模型自认资料未覆盖，回落 ReAct Agent：%s", output[:60])
        return None, "uncovered"

    logger.info(
        "[kb_call_mode=%s] 高置信直答命中，旁路 ReAct：decided_by=%s docs=%d",
        mode,
        retrieval_decided_by,
        len(docs),
    )
    return {
        "needs_human": False,
        "tool_sourced": False,
        "final_response": output,
        # 高相似资料直答，token 量由检索侧保证；不预设低质分，交给 reply 正常组装
        "quality_score": None,
        "retrieved_docs": dedup_docs(list(docs)),
        "answer_status": "answered",
        "kb_call_mode": mode,
        "retrieval_decided_by": retrieval_decided_by,
        "retrieval_count": retrieval_count,
        "answer_path": "direct_synthesis",
        # 资料事实直答，reflect 的二次 LLM 审核既慢（CPU 多一次数分钟调用）
        # 又可能改坏答案，显式标记让 reflect_node 跳过（与 tool_sourced 同例）。
        "has_reflected": True,
    }, ""


# ======================================================================
# Node 4: rag_node — RAG + ReAct Agent 推理
# ======================================================================


def rag_node(
    state: AgentState,
    retriever=None,
    memory_manager=None,
    user_id: str = "",
) -> dict[str, Any]:
    """RAG 推理节点：使用 ReAct Agent 进行深度技术排查

    职责：
        1. 通过 MemoryManager 获取对话历史（替代原来的手动提取）
        2. 注入长期记忆上下文到 Agent 的 System Prompt
        3. 调用 CustomerServiceAgent 执行 ReAct 推理链
        4. 对检索结果进行幻觉检测
    """
    messages = state.get("messages", [])
    last_message = messages[-1]
    content = (
        last_message.content if hasattr(last_message, "content") else str(last_message)
    )

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
            logger.warning(
                "Memory on_rag_start failed, using manual extraction", exc_info=True
            )

    if memory_manager and session_id:
        try:
            memory_manager.on_rag_start(
                session_id=session_id,
                user_message=content,
            )
        except Exception:
            logger.debug("memory on_rag_start best-effort hook failed", exc_info=True)

    # ==================================================================
    # Phase5 kb_call_mode 三模式检索策略（语义契约见 call_policy 模块）
    #   always：强制 1 次预检索，资料直接注入用户消息（生产默认）
    #   smart ：A 段规则短路 → C 段探测判定，命中即复用探测结果（只检 1 次）
    #   never ：不构建 Agent、不检索，LLM 依据历史直答（下方提前 return）
    # 非法配置值由 resolve_mode 统一回落 always（决策 3，行为最可预测）。
    # ==================================================================
    mode, _mode_fell_back = resolve_mode(getattr(settings, "kb_call_mode", MODE_ALWAYS))
    retrieval_count = 0
    retrieval_decided_by = mode
    pre_retrieved_docs: list = []
    agent_input = content
    effective_tenant = state.get("tenant_id") or "default"
    effective_user = user_id or state.get("user_id", "")
    effective_access = state.get("user_access_levels", None)

    def _run_preretrieval_search() -> list:
        """预检索/探测共用同一次检索口径，参数与 always 预检索完全一致。"""
        top_k = min(50, max(1, int(getattr(settings, "retrieval_top_k", 5) or 5)))
        return retriever.search(
            content,
            top_k=top_k,
            user_id=effective_user,
            tenant_id=effective_tenant,
            user_access_levels=effective_access,
        )

    if mode == MODE_NEVER:
        logger.info("[kb_call_mode=never] decided_by=never retrieval_count=0")
        return _direct_answer_without_retrieval(content, history, mode)

    # ==================================================================
    # 前置话题硬闸门（2026-10-07 GR03 复测超时驱动前移）
    # ------------------------------------------------------------------
    # 四类确定性禁区（医疗/火焰/防爆/越权校准）语料有明文禁令，标准话术
    # 就是禁令口径，没必要再花一次 embedding + 直答 + ReAct（生产 CPU 实测
    # 350~400s，且清空注入后 ReAct 多轮会爆 600s 超时）。在任何检索与 LLM
    # 之前直接收口，零引用、零幻觉、毫秒级。
    # 输出侧闸门与 reply 最终防线保留作纵深防御（覆盖 never 模式与
    # faq 命中等其他入口）。库外问题（GR05）不命中话题词，仍走下方
    # 「直答未覆盖 + ReAct 零检索」双信号收口，不在此前置。
    # ==================================================================
    pre_guard = enforce_topic_guard(content, "")
    if pre_guard.blocked:
        logger.warning(
            "前置话题护栏收口 topic=%s question=%s",
            pre_guard.topic,
            content[:60],
        )
        return {
            "needs_human": False,
            "tool_sourced": False,
            "final_response": pre_guard.response,
            "retrieved_docs": [],
            "quality_score": 0.2,
            "answer_status": "refused",
            "kb_call_mode": mode,
            "retrieval_decided_by": "topic_guard",
            "retrieval_count": 0,
            "answer_path": "topic_guard",
            "safety_guard_topic": pre_guard.topic,
            "has_reflected": True,
        }

    if retriever is not None:
        if mode == MODE_ALWAYS:
            try:
                pre_retrieved_docs = _run_preretrieval_search()
                retrieval_count += 1
                warn_if_over_budget(
                    retrieval_count, query=content, source="pre_retrieval"
                )
            except Exception as e:  # noqa: BLE001 - 预检索失败回落 Agent 自主决策
                logger.warning("always 预检索失败，回落 Agent 自主决策：%s", e)
            if pre_retrieved_docs:
                agent_input = _build_agent_input(content, pre_retrieved_docs)
        else:  # MODE_SMART：A 段规则短路 → C 段探测判定
            policy = decide_retrieval(
                content,
                has_prior_citations=bool(state.get("retrieved_docs")),
            )
            retrieval_decided_by = policy.reason
            if policy.reason != REASON_RULE:
                try:
                    probe_docs = _run_preretrieval_search()
                    retrieval_count += 1
                    warn_if_over_budget(
                        retrieval_count, query=content, source="pre_retrieval"
                    )
                except Exception as e:  # noqa: BLE001 - 探测失败不阻断主链路
                    logger.warning("smart 探测检索异常，回落 Agent 自主决策：%s", e)
                    probe_docs = None
                    retrieval_decided_by = REASON_FALLBACK
                if probe_docs is not None:
                    # 判据自身异常（policy_error）时按「宁多检不漏检」直接注入；
                    # 正常路径把探测结果交给 C 段判分，命中即复用、绝不二次检索。
                    policy_error = (
                        policy.reason == REASON_FALLBACK and not policy.needs_probe
                    )
                    if policy_error:
                        pre_retrieved_docs = probe_docs
                        retrieval_decided_by = REASON_FALLBACK
                    else:
                        verdict = decide_retrieval(
                            content,
                            probe_docs=probe_docs,
                            min_vector_similarity=settings.kb_similarity_threshold,
                        )
                        retrieval_decided_by = verdict.reason
                        should_inject = verdict.probe_reused or (
                            verdict.reason == REASON_FALLBACK
                            and verdict.should_retrieve
                        )
                        if should_inject:
                            pre_retrieved_docs = probe_docs
                if pre_retrieved_docs:
                    agent_input = _build_agent_input(content, pre_retrieved_docs)

    # ==================================================================
    # M3 信号保底补块（两种模式汇合后统一执行一次）
    # 保修/退货/参数冲突类跨块题，政策块常被 rerank 挤出 top5；
    # 此处用内存 BM25 毫秒级补入，零额外 embedding/LLM 调用。
    # 补块后必须重建 agent_input，保证 ReAct 与下方直答看到同一份资料。
    # ==================================================================
    if (
        getattr(settings, "synthesis_enabled", False)
        and retriever is not None
        and pre_retrieved_docs
    ):
        pre_retrieved_docs, _supplement_log = _supplement_pre_retrieved_docs(
            content,
            pre_retrieved_docs,
            retriever,
            user_id=effective_user,
            tenant_id=effective_tenant,
            user_access_levels=effective_access,
        )
        agent_input = _build_agent_input(
            content,
            pre_retrieved_docs,
            max_docs=int(getattr(settings, "synthesis_max_injected_docs", 6) or 6),
        )

    logger.info(
        "[kb_call_mode=%s] decided_by=%s 预检索命中=%d tenant=%s",
        mode,
        retrieval_decided_by,
        len(pre_retrieved_docs),
        effective_tenant,
    )

    # ==================================================================
    # 高置信命中直答旁路（2026-10-06，生产实测驱动）
    # 预检索已有高相似度资料时，跳过工具 Agent 的多轮 ReAct，单次直答合成。
    # 触发口径刻意保守：
    #   - always：预检索 top1 绝对相似度 >= kb_direct_answer_threshold
    #   - smart ：仅限 score 判据命中（rule/fallback 不旁路，保持语义一致）
    # 任何不满足/直答失败的情形都继续走下方 Agent，行为可回退。
    # ==================================================================
    # direct_reason：直答自认未覆盖时为 "uncovered"，供输出侧库外收口双信号
    direct_reason = ""
    # uncovered_fallback：直答看注入资料自认未覆盖后回落 ReAct，
    # 此时已清空 agent_input 强制 ReAct 自主检索（见下方分支）
    uncovered_fallback = False
    # uncovered 回落时预检索 top1 相似度，供库外收口窄化判定；
    # 默认 1.0 保证未走该分支时绝不因分数条件收口
    uncovered_top_sim = 1.0
    if (
        getattr(settings, "kb_direct_answer_enabled", False)
        and pre_retrieved_docs
        and (
            mode == MODE_ALWAYS
            or (mode == MODE_SMART and retrieval_decided_by == REASON_SCORE)
        )
    ):
        top_sims = [
            float(d.metadata.get("vector_similarity"))
            for d in pre_retrieved_docs
            if isinstance(getattr(d, "metadata", None), dict)
            and d.metadata.get("vector_similarity") is not None
        ]
        top_sim = max(top_sims, default=0.0)
        if top_sim >= float(settings.kb_direct_answer_threshold):
            direct, direct_reason = _direct_synthesize_with_docs(
                content,
                history,
                pre_retrieved_docs,
                mode,
                retrieval_decided_by,
                retrieval_count,
            )
            if direct is not None:
                return direct
            # direct 为 None：helper 内部已记录原因（direct_reason），
            # 继续走 Agent 安全网。
            # GR05 修复策略（经真机两轮校准后的最终形态）：
            #   回落时保留预检索资料注入（不重置 agent_input）。早期版本
            #   曾在此清空注入以「强制自主检索」，但实测 GP04 高相关库内题
            #   7B 直答也会保守说未覆盖，清空后 ReAct 又偷懒零检索，反而无
            #   资料可用、输出空骨架并丢引用。库外与否统一交给输出侧四信号
            #   判定（sim 地板 + 词面覆盖 + 零检索 + 无拒答词），真库外在
            #   那里收口并整体清空引用，此处不提前破坏库内题的资料供给。
            if direct_reason == "uncovered":
                uncovered_fallback = True
                uncovered_top_sim = top_sim
                logger.info(
                    "直答自认未覆盖(top_sim=%.3f)，回落 ReAct，保留注入资料",
                    top_sim,
                )
        else:
            logger.info(
                "top_sim=%.3f 低于直答门槛 %.2f，走 ReAct Agent",
                top_sim,
                settings.kb_direct_answer_threshold,
            )

    # 构建 Agent（注入长期记忆上下文 + 权限信息）
    agent = CustomerServiceAgent(
        retriever=retriever,
        user_id=user_id or state.get("user_id", ""),
        max_turns=state.get("effective_max_turns", settings.max_reasoning_turns),
        memory_context=state.get("memory_context", ""),
        # 单租户 demo 场景：匿名/未携带租户时，tenant 默认归 default，
        # 否则会查不到 default 知识库里的文档（P0 修复后空 tenant 已被隔离）。
        # 用 `or "default"` 而非 get 默认值：state 里 tenant_id="" 是 falsy，
        # 需 fallback；evil-corp 这类真租户仍原样保留（多租户隔离不受影响）。
        tenant_id=state.get("tenant_id") or "default",
        user_access_levels=state.get("user_access_levels", None),
        user_roles=state.get("user_roles", []),
        user_plan=state.get("user_plan", "free"),
    )

    # always / smart 命中时 agent_input 已带预检索资料；其余情况等于原问题
    result = agent.run_with_trace(agent_input, chat_history=history)

    # 提前抽资源工具结果（create_agent 的工具结果在 messages 的 ToolMessage 里），
    # 供下方「引用气泡回填」「安全网」「强制精简跳过」三处使用，避免引用未定义变量。
    tool_docs = _extract_tool_citation_docs(result.get("messages", []))

    # Phase5 §2.5：事后统计 Agent 自主检索次数，超软上限只告警不阻断
    _agent_searches = _count_agent_kb_searches(result.get("messages", []))
    if _agent_searches:
        retrieval_count += _agent_searches
        warn_if_over_budget(retrieval_count, query=content, source="agent_tool")

    # 检查是否触发了转人工
    output = result.get("output", "")

    # 清理 ReAct 格式：提取最终回答部分（增强版）
    import re

    # 1. 先尝试找 Final Answer
    final_answer_match = re.search(r"Final Answer:\s*", output, flags=re.IGNORECASE)
    if final_answer_match:
        output = output[final_answer_match.end() :].strip()
    else:
        # 2. 查找最后一个内部标记之后的内容
        react_markers = [
            "Question:",
            "Thought:",
            "Action:",
            "Action Input:",
            "Observation:",
            "Final Answer:",
            "Thought ",
            "Action ",
        ]
        found_any = False
        for marker in react_markers:
            matches = list(re.finditer(re.escape(marker), output, flags=re.IGNORECASE))
            if matches:
                found_any = True
                last_match = matches[-1]
                candidate = output[last_match.end() :].strip()
                if candidate and not any(
                    candidate.lower().startswith(m.lower()) for m in react_markers
                ):
                    output = candidate
                    break

        # 3. 如果找到了 ReAct 标记但清理失败，说明输出格式异常，当成空处理
        if found_any and _looks_like_react_output(output):
            output = ""

    # 4. 再次检查：如果输出看起来还是 ReAct 格式，直接清空
    if _looks_like_react_output(output):
        output = ""

    # 🔧 资源工具结果优先：模型对工具返回的自然语言包装常出现「重复编号 + 缺空格」
    # 的畸形输出，且不可靠；而工具原始返回（[查询完成] 共 N 个资源…）本身结构清晰、
    # 是事实来源、能与引用气泡一一对应。有工具结果时直接用其作为回复，保证演示稳定、
    # 可读、可溯源（不再依赖正则去修补 LLM 畸形输出）。
    # 资源工具结果优先：多个工具（ECS+RDS 等）都被调用时，拼接全部结果，
    # 避免只取 [0] 丢脏数据；工具原文是事实来源，且能与引用气泡一一对应。
    if tool_docs:
        output = "\n".join(d.page_content for d in tool_docs)

    # 判断是否需要转人工：通过中间步骤判断 Agent 是否真正调用了 escalate_to_human 工具
    # 注意：不能通过输出文字判断，因为 AI 可能在回复里说"欢迎转接人工客服"之类的话
    needs_human = False
    intermediate_steps = result.get("intermediate_steps", [])
    for step in intermediate_steps:
        if (
            hasattr(step, "action")
            and hasattr(step.action, "tool")
            and step.action.tool == "escalate_to_human"
        ):
            needs_human = True
            break

    # 强制精简：如果回复超过120字，提取前3个要点。
    # 注意：资源工具结果（tool_docs 已存在）本身结构清晰，跳过精简避免截断/畸形。
    import re

    if len(output) > 120 and not tool_docs:
        # 兼容两种格式：编号点跨行（"1. a\n2. b"）或挤在同一行（"1. a 2. b 3. c"）。
        # 旧正则 [^\n]+ 在单行情形会贪心吞掉整行导致去重失效、回复出现重复编号，
        # 改用「匹配到下一个编号点或结尾」的非贪婪切分。
        points = re.findall(r"\d+\.\s*(.*?)(?=\s*\d+\.\s|$)", output, flags=re.DOTALL)
        if points:
            # 去重（LLM 偶发把同一编号点重复输出），再取前3个要点
            _seen = set()
            _dedup = []
            for p in points:
                ps = p.strip()
                if ps and ps not in _seen:
                    _seen.add(ps)
                    _dedup.append(ps)
            top3 = _dedup[:3]
            output = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(top3))
        else:
            # 没有编号列表，截断到第一句或前80字
            sentences = re.split(r"[。！？]", output)
            if len(sentences) >= 2:
                output = sentences[0] + "。" + sentences[1] + "。"
            else:
                output = output[:80] + "..."

    # ===== 幻觉防护 1: 检索置信度检查 =====
    # 如果 Agent 返回了"没有找到相关信息"，标记为拒答
    # （不强制转人工，由 reply_node 决定是否建议转人工）
    refusal_indicators = [
        "抱歉",
        "找不到",
        "未找到",
        "没有相关信息",
        "找不到相关文档",
        "无法回答",
        "我不知道",
        "知识库中不存在",
        "建议转人工",
    ]
    is_refusal = any(ind in output for ind in refusal_indicators)

    # ===== 幻觉防护 2: 检索完整性检查 =====
    # Phase5 §2.5：预检索/探测结果 + Agent 中间步骤文档 + 资源工具文档，
    # 在唯一合并点做内容级去重（sha1 全文指纹 + doc_id|page 辅键，同键留高分）。
    agent_retrieved_docs = _extract_retrieved_docs(result.get("intermediate_steps", []))
    # 预检索文档始终参与引用合并（含 uncovered 回落）：库内高相关题（GP04）
    # 需要这些真实相关文档作引用。真库外（GR05）的引用污染由输出侧四信号
    # 收口时整体 retrieved_docs=[] 清除，不靠在这里提前剔除（提前剔除会让
    # 库内题丢引用）。
    retrieved_docs = dedup_docs(
        list(pre_retrieved_docs) + (agent_retrieved_docs or []) + tool_docs
    )

    # ----------------------------------------------------------------------
    # 尾部引用补检（既有安全网）：Agent 跑完仍无文档时，用原始查询补一次
    # 结构化检索回填真实 Document 列表（search_knowledge_base 工具把 docs
    # 格式化成字符串喂模型，中间步骤里没有结构化 Document）。
    # never 模式已在上方提前 return，不会破坏其「0 检索」契约；
    # smart 的 A 段规则短路（闲聊/纯操作指令）契约是「0 检索、引用空」，
    # 尾部补检同样必须跳过；探测未命中（score_reject）按 §2.2.2 保留兜底。
    # 本次调用计入同一软上限计数（Phase5 §2.5）。
    if (
        not retrieved_docs
        and retriever is not None
        and retrieval_decided_by != REASON_RULE
    ):
        try:
            fallback_docs = retriever.search(
                content,
                top_k=3,
                user_id=effective_user,
                tenant_id=effective_tenant,
                user_access_levels=effective_access,
            )
            retrieval_count += 1
            warn_if_over_budget(retrieval_count, query=content, source="tail_backfill")
            if fallback_docs:
                # 给每个 doc 打 1/(rank+1) 伪相似度（search 返回的 Document 没 score）。
                # 只塞 metadata：langchain Document 是 pydantic BaseModel，
                # 不允许在实例上设未声明字段。路由层 _build_citations 从
                # metadata["rrf_score"] 兜底读，分数会传到前端气泡。
                for idx, doc in enumerate(fallback_docs):
                    fake_score = round(1.0 / (idx + 1), 4)
                    try:
                        doc.metadata["rrf_score"] = fake_score
                        doc.metadata["score"] = (
                            fake_score  # 双存一份兼容读 score 的代码
                        )
                    except Exception:
                        logger.debug("fallback doc metadata 盖戳失败", exc_info=True)
                retrieved_docs = fallback_docs
                logger.info(
                    "rag_node 引用补检：tenant=%s 命中 %d 条",
                    effective_tenant,
                    len(retrieved_docs),
                )
        except Exception as _fb_err:
            logger.debug("rag_node 引用补检失败，跳过：%s", _fb_err)
    # ----------------------------------------------------------------------

    # Phase5 可观测性三要素收口（进返回 state 与结构化日志，§2.4）
    logger.info(
        "[kb_call_mode=%s] decided_by=%s retrieval_count=%d docs=%d tenant=%s",
        mode,
        retrieval_decided_by,
        retrieval_count,
        len(retrieved_docs),
        effective_tenant,
    )
    quality_score: float | None = None
    if retrieved_docs:
        total_tokens = sum(
            len(doc.page_content if hasattr(doc, "page_content") else str(doc))
            for doc in retrieved_docs
        )
        if total_tokens < settings.retrieval_min_tokens:
            logger.warning(
                "Low retrieval token count: %d (threshold: %d)",
                total_tokens,
                settings.retrieval_min_tokens,
            )
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
                    logger.warning(
                        "Potential hallucination detected: %s",
                        h_result["hallucinated"][:5],
                    )
                    # 上报真实计数到 EvaluationTracker，供 /metrics/risk 暴露
                    try:
                        from src.evaluation.tracker import get_evaluation_tracker

                        get_evaluation_tracker().record_safety_event(
                            "hallucination_detected"
                        )
                    except Exception:
                        logger.debug(
                            "Failed to record hallucination_detected event",
                            exc_info=True,
                        )
        except Exception:
            logger.debug("Hallucination check skipped", exc_info=True)

    # ==================================================================
    # 输出侧安全硬闸门（2026-10-07 金标题库 GR01/GR02/GR04/GR05 实测驱动）
    # ------------------------------------------------------------------
    # 背景：REACT_SYSTEM_PROMPT 规则 2/7 只做行为约束，7B 会被诱导突破
    # （GR02 语料有禁令仍答「550℃ 以内可以测」；GR04 给出改增益步骤；
    #  GR05 无资料编造断电重启并挂 4 条无关引用）。故在唯一出答案点
    # 用确定性规则收口，零 LLM 调用。
    #   闸门 1 话题：输入命中用途禁区/越权校准 AND 输出无拒答信号 →
    #       替换语料口径标准话术，清空引用（禁止编造配权威引用）。
    #   闸门 2 库外（四信号合取，刻意收窄防误伤）：直答看注入资料自认
    #       未覆盖（uncovered_fallback），回落时已清空注入强制 ReAct 自主
    #       检索；ReAct 仍零工具调用 AND 无资源工具结果 AND 输出无拒答词
    #       AND 预检索 top1 相似度 < 地板 AND query 实词在召回语料命中率
    #       极低（话题实体在知识库近乎零出现）→ 判真库外收口。
    #       GP04 误伤教训：高相关库内题（sim 0.647、校准词高频）7B 直答也
    #       会保守说未覆盖、ReAct 也会偷懒零检索，故行为两信号不足以定库外，
    #       必须叠加相似度地板与词面覆盖两个确定性证据。
    # 两种收口都标记 has_reflected=True 跳过 reflect 二次 LLM 改写，
    # 避免标准话术被改坏，并省下 CPU 上一次数分钟的审核调用。
    # ==================================================================
    safety_topic = ""
    guard = enforce_topic_guard(content, output)
    lexical_overlap = query_corpus_bigram_overlap(content, pre_retrieved_docs)
    _out_of_scope = (
        uncovered_fallback
        and _agent_searches == 0
        and not tool_docs
        and not has_refusal_signal(output)
        and uncovered_top_sim < _OUT_OF_SCOPE_SIM_FLOOR
        and lexical_overlap < _OUT_OF_SCOPE_LEXICAL_RATIO
    )
    if guard.blocked:
        logger.warning(
            "输出侧话题护栏拦截 topic=%s question=%s",
            guard.topic,
            content[:60],
        )
        output = guard.response
        retrieved_docs = []
        is_refusal = True
        quality_score = 0.2
        safety_topic = guard.topic
    elif _out_of_scope:
        logger.warning(
            "库外四信号收口：top_sim=%.3f 词面覆盖=%.2f question=%s",
            uncovered_top_sim,
            lexical_overlap,
            content[:60],
        )
        output = OUT_OF_SCOPE_RESPONSE
        retrieved_docs = []
        is_refusal = True
        quality_score = 0.2
        safety_topic = "out_of_scope"

    return {
        "final_response": output,
        "needs_human": needs_human,
        "quality_score": quality_score,
        "retrieved_docs": retrieved_docs,
        "tool_sourced": bool(tool_docs),
        "answer_status": "refused" if is_refusal else "answered",
        # Phase5 可观测性三要素（§2.4）：模式、判据来源、实际检索次数
        "kb_call_mode": mode,
        "retrieval_decided_by": retrieval_decided_by,
        "retrieval_count": retrieval_count,
        # 答案合成路径：react_agent（高置信直答旁路见 _direct_synthesize_with_docs）
        "answer_path": "react_agent",
        # 安全护栏命中类型（空串=未命中），供监控与金标题复测定位
        "safety_guard_topic": safety_topic,
        # 护栏收口话术是最终结论，跳过 reflect 二次 LLM 改写
        "has_reflected": bool(safety_topic),
    }


# ======================================================================
# Node 5: human_node — 人工转接
# ======================================================================


def human_node(state: AgentState) -> dict[str, Any]:
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
    human_input = interrupt(
        {
            "type": "human_handoff",
            "context": handoff_context,
            "question": "请提供人工回复，或编辑 AI 的建议回复后提交",
        }
    )

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


def reflect_node(state: AgentState) -> dict[str, Any]:
    """Reflection 节点：Agent 自我反思后修正回复

    在 reply_node 之前执行，让 Agent 检查自己的推理链是否完整。
    只在技术排查（intent=technical）且未反射过时执行。
    """
    if state.get("intent") != "technical":
        return {}

    if state.get("has_reflected"):
        return {}

    # 工具来源的回复（云资源真实返回）已是事实文本，且与引用气泡一一对应，
    # 再喂给第二个 LLM 改写会偶发畸形、破坏溯源。直接保留，跳过反思改写。
    if state.get("tool_sourced"):
        return {"has_reflected": True}

    # 高置信直答（rag_node 资料事实单次合成）同理：答案严格来自检索资料，
    # 二次 LLM 审核在 CPU 上多花一次数分钟调用且可能把好答案改坏，直接放行。
    if state.get("answer_path") == "direct_synthesis":
        return {"has_reflected": True}

    final_response = state.get("final_response", "")
    if not final_response:
        return {}

    reflect_llm = make_chat_model(
        model=settings.llm_complex_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        temperature=0.0,
    )

    reflect_prompt = (
        "你是一个客服质量审核员。请检查以下客服回复是否准确、完整。\n\n"
        "【审核规则】\n"
        "1. 如果回复内容准确、清晰、有用，直接输出 'PASS'\n"
        "2. 如果回复有问题需要修改，直接输出修改后的完整回复文本，"
        "不要加任何解释、说明或审查结论\n"
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
            prompt = token_usage.get("prompt_tokens") or token_usage.get(
                "input_tokens", 0
            )
            completion = token_usage.get("completion_tokens") or token_usage.get(
                "output_tokens", 0
            )
            if prompt or completion:
                from src.api.metrics import record_llm_tokens

                record_llm_tokens(
                    model=settings.llm_complex_model,
                    prompt_tokens=int(prompt),
                    completion_tokens=int(completion),
                    tenant_id=state.get("tenant_id", "default"),
                )
        except Exception:
            logger.debug("reflect token 用量埋点失败", exc_info=True)
    except Exception as e:
        # 协作式取消透传；普通 LLM 失败按原策略跳过审核
        if isinstance(e, WorkflowCancelled):
            raise
        return {"has_reflected": True}

    if reflection_output and reflection_output.upper() != "PASS":
        return {
            "final_response": reflection_output,
            "has_reflected": True,
        }

    return {"has_reflected": True}


def _simplify_reply(text: str, *, technical: bool, tool_sourced: bool = False) -> str:
    """统一回复长度，保持聊天窗口可读。

    通用回答压到 100 字左右、最多 3 个编号要点。技术意图（intent=technical）
    的分步操作/多要点答案是用户的执行依据，压要点等于答错：金标题实测
    19 题因 100 字/3 点截断丢失后半段步骤（6 点列表被切到 3 点、横线
    列表被 80 字硬切出「M...」），技术意图放宽到 600 字、最多 6 要点。
    工具来源文本已与引用气泡一一对应，全程原样保留。
    """
    if tool_sourced or not text:
        return text

    budget = 600 if technical else 100
    keep = 6 if technical else 3

    if len(text) <= budget:
        return text

    # 超字数后才收编号点：技术答最多 6 点、通用答最多 3 点
    points = re.findall(r"\d+\.\s*([^\n]+)", text)
    if points:
        top = points[:keep]
        return "\n".join(f"{i + 1}. {p.strip()}" for i, p in enumerate(top))

    sentences = re.split(r"([。！？])", text)
    if technical:
        # 无编号的技术长答：按完整句子累积到 600 字，不做 80 字硬切
        out = ""
        for i in range(0, len(sentences) - 1, 2):
            piece = sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else "")
            if len(out) + len(piece) > 600:
                break
            out += piece
        return out or text[:600]

    if len(sentences) >= 4:
        return sentences[0] + sentences[1] + sentences[2] + sentences[3]
    if len(sentences) >= 2:
        return sentences[0] + sentences[1]
    return text[:80] + "..."


# ======================================================================
# Node 7: reply_node — 最终回复组装 + 记忆持久化 + 质量评估
# ======================================================================


def reply_node(state: AgentState, memory_manager=None) -> dict[str, Any]:
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
                    f"您可以补充设备型号、故障代码或具体现象后再问一次～"
                )
            else:
                final_response = (
                    "抱歉，我不太明白您的问题。"
                    "您可以试着描述一下遇到的问题，我会尽力帮您～"
                )
        else:
            final_response = (
                "抱歉，这个问题我暂时还答不上来。"
                "您可以换个方式描述设备型号、故障代码或具体现象，"
                "比如「F02故障代码怎么处理」～"
            )

        return {
            "final_response": final_response,
            "needs_human": False,
            "suggest_human": suggest_human,
            "failed_attempts": failed_attempts,
        }

    # ===== 安全护栏收口话术：原样送达，跳过一切"美化"后处理 =====
    # 触发来源有两类：
    #   1. rag_node 输出侧闸门已收口（state.safety_guard_topic 非空）；
    #   2. 最终防线：faq 命中文本等其他路径漏网，此处对成品再过一次
    #      话题闸门（纯函数、幂等，已含拒答词的答案会被放行）。
    # 必须早于 quality_score<0.3 替换、统一精简、_is_refusal_response
    # 三处后处理，否则明确禁令会被换成「答不上来」通用话术，丢失
    # 「不能作为医疗设备 / 禁止进入校准模式」等安全含义（GR01/GR04 实测）。
    reply_guard = enforce_topic_guard(last_message, final_response)
    guard_topic = state.get("safety_guard_topic") or (
        reply_guard.topic if reply_guard.blocked else ""
    )
    if guard_topic:
        if reply_guard.blocked and not state.get("safety_guard_topic"):
            logger.warning("reply 最终防线话题护栏拦截 topic=%s", reply_guard.topic)
            final_response = reply_guard.response
        return {
            "final_response": final_response,
            "needs_human": False,
            "suggest_human": state.get("suggest_human", False),
            "quality_score": quality_score,
            "safety_guard_topic": guard_topic,
            "failed_attempts": state.get("failed_attempts", 0),
        }

    # 如果检索置信度太低 → 友好回复，建议转人工（但不强制
    if quality_score is not None and quality_score < 0.3:
        failed_attempts = state.get("failed_attempts", 0) + 1
        suggest_human = failed_attempts >= 2
        if suggest_human:
            final_response = (
                "抱歉，我连续几次都没能准确理解您的问题。\n"
                "您可以换个方式描述，或者点击下方按钮转接人工客服，"
                "让人工客服帮您处理～"
            )
        else:
            final_response = (
                "抱歉，这个问题我暂时还答不上来。"
                "您可以换个方式描述设备型号、故障代码或具体现象，"
                "比如「F02故障代码怎么处理」～"
            )
        return {
            "final_response": final_response,
            "needs_human": False,
            "suggest_human": suggest_human,
            "quality_score": quality_score,
            "failed_attempts": failed_attempts,
        }

    # 统一精简：通用回答 100 字/3 要点；技术意图分步答案 600 字/6 要点，
    # 避免把操作步骤后半段截没（金标题 19 题实测，详见 _simplify_reply）。
    # 工具来源文本含 "ecs.g7.large" 这类数字点字符，重排会产生畸形，
    # tool_sourced 在辅助函数内原样返回。
    final_response = _simplify_reply(
        final_response,
        technical=intent == "technical",
        tool_sourced=bool(state.get("tool_sourced")),
    )

    # ===== 拒答式回复检测：如果 AI 说自己做不了，也算作一次失败 =====
    # （比如"我是设备客服，不唱歌"、"不支持这个功能"等）
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
                "您可以补充设备型号、故障代码或具体现象后再问，"
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
                # 评测 Judge 走离线 ChatOpenAI（无取消包装），进入前显式检查，
                # 避免断线/硬超时后白跑一次评测 LLM
                check_cancelled()
                judge = DialogueJudge()

                # 获取对话摘要作为评估上下文
                conv_summary = ""
                if memory_manager and session_id:
                    try:
                        ctx = memory_manager.get_context_for_evaluation(session_id)
                        conv_summary = ctx.get("summary", "")
                    except Exception:
                        logger.debug("评估上下文摘要读取失败", exc_info=True)

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
                        "LLM-as-Judge flagged for human review: overall=%.1f, flags=%s",
                        score["overall"],
                        score.get("flags", []),
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
        elif isinstance(msg, AIMessage) and history:
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


# 资源类工具名（与 src/mcp_tools/resource.py 保持一致）。
# 这些工具的返回是「真实云数据」，应在引用气泡里透出，让坐席/用户
# 看到本回答基于哪次云资源查询。KB 检索与资源查询走两条引用路径。
_RESOURCE_TOOL_NAMES = {"query_resources", "describe_resource", "get_resource_monitor"}


def _extract_tool_citation_docs(messages: list) -> list:
    """从 LangGraph create_agent 的 messages 里抽工具真实返回，转成引用卡片。

    create_agent（prebuilt ReAct）不填 intermediate_steps，工具结果在
    ToolMessage 里。rag_node 原先只读 intermediate_steps，导致资源查询
    调了工具、citations 却永远为空——「引用可溯源」对最亮眼的云资源演示失效。
    这里把资源类 ToolMessage 回填为 Document，让气泡正常显示。
    """
    from langchain_core.documents import Document
    from langchain_core.messages import ToolMessage

    docs = []
    for m in messages or []:
        if isinstance(m, ToolMessage) and m.name in _RESOURCE_TOOL_NAMES:
            content = m.content or ""
            if not isinstance(content, str):
                content = str(content)
            if not content.strip():
                continue
            docs.append(
                Document(
                    page_content=content[:1200],
                    metadata={
                        "source": f"tool/{m.name}",
                        "doc_id": f"tool-{m.name}-{m.tool_call_id}",
                        "title": f"云资源查询结果 · {m.name}",
                        "kb_id": "cloud-resource",
                        "score": 1.0,
                        "rrf_score": 1.0,
                    },
                )
            )
    return docs
