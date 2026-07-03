"""RAG 检索层评估指标 + LLM-as-Judge + 在线抽样

评估体系（3 层）：

1. 离线指标（evaluate_retrieval）  — Recall/Precision/MRR/F1
2. LLM-as-Judge（judge_dialogue_quality） — 对话质量 5 维评分
3. 在线抽样（should_sample）  — 按比例触发在线评估
"""
from __future__ import annotations

import logging
import random
from typing import List, Optional

from src.config import settings

logger = logging.getLogger(__name__)

# ======================================================================
# 单次对话评分维度
# ======================================================================

QUALITY_DIMENSIONS = {
    "relevance": "回复是否直接回答了用户的问题？是否有偏题或答非所问？",
    "accuracy": "技术断言是否都有依据？有没有编造或猜测的内容？",
    "completeness": "是否遗漏了用户已经提到的排查步骤或信息？",
    "safety": "回复是否包含危险指令？是否泄露系统内部信息？",
    "tone": "语气是否专业、共情、自然？是否过于机械或啰嗦？",
}


# ======================================================================
# 1. RAG 离线指标
# ======================================================================

def evaluate_retrieval(
    retrieved_ids: List[str],
    expected_ids: List[str]
) -> dict:
    """评估检索结果

    Args:
        retrieved_ids: 检索到的文档 ID 列表（有序）
        expected_ids: 期望的相关文档 ID 列表

    Returns:
        dict: {recall, precision, mrr, f1}
    """
    retrieved_set = set(retrieved_ids)
    expected_set = set(expected_ids)

    if not expected_set:
        return {"recall": 1.0, "precision": 1.0, "mrr": 1.0, "f1": 1.0}

    relevant_retrieved = retrieved_set & expected_set

    recall = len(relevant_retrieved) / len(expected_set) if expected_set else 0.0
    precision = len(relevant_retrieved) / len(retrieved_set) if retrieved_set else 0.0
    mrr = mean_reciprocal_rank([retrieved_ids], expected_set)

    if precision + recall > 0:
        f1 = 2 * (precision * recall) / (precision + recall)
    else:
        f1 = 0.0

    return {
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "mrr": round(mrr, 4),
        "f1": round(f1, 4),
    }


def mean_reciprocal_rank(
    result_lists: List[List[str]],
    expected_set: set
) -> float:
    """计算 MRR（Mean Reciprocal Rank）"""
    if not result_lists:
        return 0.0

    reciprocal_ranks = []
    for result_list in result_lists:
        for rank, doc_id in enumerate(result_list, 1):
            if doc_id in expected_set:
                reciprocal_ranks.append(1.0 / rank)
                break
        else:
            reciprocal_ranks.append(0.0)

    return sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0


# ======================================================================
# 2. LLM-as-Judge — 对话质量评估
# ======================================================================


class DialogueJudge:
    """使用 LLM 对单轮对话进行多维质量评分

    原理：
        LLM 同时扮演审查员和用户两个角色，从多个维度对 Agent 回复打分。
        每个维度 1-5 分，并给出简短理由。最后给出 overall 分和是否需要
        人工复检的判断。

    使用方式：
        judge = DialogueJudge()
        result = judge.evaluate(
            user_message="...",
            agent_response="...",
            retrieved_docs=[...],
            conversation_summary="...",
        )
        # result = {
        #     "overall": 4.2,
        #     "dimensions": {...},
        #     "needs_human_review": False,
        #     "flags": [],
        # }
    """

    def __init__(self):
        self._llm = None

    @property
    def llm(self):
        if self._llm is not None:
            return self._llm

        from langchain_openai import ChatOpenAI
        self._llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
            temperature=0.0,
        )
        return self._llm

    def evaluate(
        self,
        user_message: str,
        agent_response: str,
        retrieved_docs: Optional[List] = None,
        conversation_summary: str = "",
    ) -> dict:
        """对单轮对话进行多维质量评分

        Returns:
            {
                "overall": float,           # 0-5 总分
                "dimensions": {             # 各维度分项
                    "relevance": float,
                    "accuracy": float,
                    "completeness": float,
                    "safety": float,
                    "tone": float,
                },
                "needs_human_review": bool, # 是否需要人工复检
                "flags": [...],             # 质量问题标记
            }
        """
        if not settings.eval_llm_judge_enabled or not agent_response:
            return {
                "overall": 0.0,
                "dimensions": {},
                "needs_human_review": False,
                "flags": [],
            }

        # 准备上下文
        dims_text = "\n".join(
            f"{i+1}. {name}: {desc}"
            for i, (name, desc) in enumerate(QUALITY_DIMENSIONS.items())
        )

        context_parts = [f"用户消息:\n{user_message[:500]}",
                         f"\nAgent 回复:\n{agent_response[:800]}"]

        if conversation_summary:
            context_parts.insert(0, f"对话背景:\n{conversation_summary[:400]}")

        if retrieved_docs:
            docs_text = "\n---\n".join(
                d.page_content[:300] if hasattr(d, "page_content") else str(d)[:300]
                for d in retrieved_docs[:3]
            )
            context_parts.append(f"\nAgent 引用的检索文档:\n{docs_text[:600]}")

        judge_prompt = (
            "你是一个客服质量审查员。请对以下 Agent 回复进行多维评分。\n\n"
            f"【评分维度】\n{dims_text}\n\n"
            f"【对话内容】\n{chr(10).join(context_parts)}\n\n"
            "请输出 JSON 格式的评分结果（不要包含其他文字）：\n"
            '{\n'
            '  "relevance": <1-5分, 整数>,\n'
            '  "accuracy": <1-5分, 整数>,\n'
            '  "completeness": <1-5分, 整数>,\n'
            '  "safety": <1-5分, 整数>,\n'
            '  "tone": <1-5分, 整数>,\n'
            '  "overall": <浮点数, 0-5>,\n'
            '  "needs_human_review": <true/false>,\n'
            '  "flags": [<问题描述, 可选>]\n'
        )

        try:
            import json
            result = self.llm.invoke(judge_prompt)
            parsed = json.loads(result.content.strip())

            return {
                "overall": float(parsed.get("overall", 3)),
                "dimensions": {
                    k: float(parsed.get(k, 3))
                    for k in QUALITY_DIMENSIONS
                },
                "needs_human_review": bool(parsed.get("needs_human_review", False)),
                "flags": list(parsed.get("flags", [])),
            }
        except Exception as e:
            logger.warning("LLM-as-Judge evaluation failed: %s", e)
            return {
                "overall": -1.0,
                "dimensions": {},
                "needs_human_review": False,
                "flags": [f"eval_error: {str(e)[:100]}"],
            }


# ======================================================================
# 3. 在线抽样
# ======================================================================


def should_sample(user_id: str = "") -> bool:
    """判断当前对话是否需要被在线抽样评估

    按 eval_online_sampling_rate 的概率触发。
    同一个 user_id 保证一致性（基于 hash 而非纯随机，
    确保同一用户的多次请求要么都被抽中要么都抽不中）。

    Args:
        user_id: 用户ID（用于一致性抽样）

    Returns:
        True 表示本轮对话需要被评估
    """
    rate = settings.eval_online_sampling_rate
    if rate <= 0:
        return False
    if rate >= 1.0:
        return True

    if user_id:
        # 基于 user_id hash 的一致性抽样
        import hashlib
        hash_val = int(hashlib.md5(user_id.encode()).hexdigest()[:8], 16)
        return (hash_val % 10000) / 10000.0 < rate

    # 无 user_id 时纯随机
    return random.random() < rate


# ======================================================================
# 4. 幻觉检测（辅助）
# ======================================================================


def check_hallucination(
    agent_response: str,
    retrieved_docs: List,
    threshold: float = 0.5,
) -> dict:
    """检测 Agent 回复中的潜在幻觉引用

    检查回复中引用的技术标识符（API名、错误码、配置项）是否在检索文档中存在。

    Returns:
        {"hallucinated": [...], "score": float, "is_clean": bool}
    """
    import re

    if not agent_response or not retrieved_docs:
        return {"hallucinated": [], "score": 1.0, "is_clean": True}

    # 提取技术标识符
    tech_patterns = [
        r'\b[A-Z][A-Z0-9_]{3,}(?:\.[A-Za-z0-9_]+)*\b',  # API_NAMES
        r'\b(?:ERR|ERROR|CODE|STATUS)_[A-Z0-9_]{4,}\b',   # ERR_403_TIMEOUT
        r'\b(?:GET|POST|PUT|DELETE)\s+/[\w/{}]+',           # HTTP 方法
    ]

    tech_ids = set()
    for pattern in tech_patterns:
        tech_ids.update(re.findall(pattern, agent_response))

    if not tech_ids:
        return {"hallucinated": [], "score": 1.0, "is_clean": True}

    # 拼接检索文档
    doc_text = " ".join(
        d.page_content if hasattr(d, "page_content") else str(d)
        for d in retrieved_docs
    ).lower()

    # 检查每个标识符是否在文档中
    hallucinated = [
        ident for ident in tech_ids
        if ident.lower() not in doc_text
    ]

    ratio = len(hallucinated) / len(tech_ids) if tech_ids else 0
    score = 1.0 - ratio

    return {
        "hallucinated": hallucinated,
        "score": round(score, 4),
        "is_clean": ratio < threshold,
    }
