"""反馈闭环：低分评价 → 难例挖掘 → 金标候选回流。

解决的问题（2026-11 RAG 评估 P0 第 4 项）：
    满意度数据此前只服务 dashboard 聚合统计，点踩信号与对话内容、
    检索元数据从未关联，线上失败无法沉淀为离线改进资产。

设计取舍：
    1. 不新增数据表。难例是 satisfaction + messages 的派生视图，避免在
       冻结题库体系外再造一套需要迁移的状态存储；产物以 JSONL 落盘，
       经人工评审后通过既有 bank_lock.py 流程进入金标库
    2. 金标候选只挑 RAG 链路回答（metadata 带 answer_path/retrieval_count），
       人工会话与闲聊不进候选，防止污染金标分布
    3. 按问题归一化 SHA1 去重，同一问法反复点踩只产一条难例，计数累加
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from src.db.repositories import message_list, negative_satisfaction_list

logger = logging.getLogger(__name__)


@dataclass
class HardCase:
    """一条可回流的线上失败样本。"""

    case_id: str  # 归一化问题的 SHA1 前 16 位
    session_id: str
    user_id: str
    score: int
    tags: list[str]
    comment: str
    question: str
    answer: str
    answer_metadata: dict[str, Any]
    feedback_created_at: float
    occurrence: int = 1  # 同指纹问题累计出现次数
    golden_candidate: bool = False


def _fingerprint(question: str) -> str:
    normalized = " ".join(question.strip().split())
    # sha1 仅作问题去重指纹，不承担安全职责
    return hashlib.sha1(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()[
        :16
    ]


def _extract_last_qa(messages: list[dict]) -> tuple[str, str, dict]:
    """从会话消息中提取评价发生前最后一组 user/assistant 问答。

    取最后一条 assistant 消息及其之前最近的 user 消息。
    找不到完整配对时返回空串，调用方据此跳过该条评价。
    """
    last_ai_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            last_ai_idx = i
            break
    if last_ai_idx <= 0:
        return "", "", {}

    question = ""
    for j in range(last_ai_idx - 1, -1, -1):
        if messages[j].get("role") == "user":
            question = messages[j].get("content", "") or ""
            break

    ai_msg = messages[last_ai_idx]
    answer = ai_msg.get("content", "") or ""
    metadata = ai_msg.get("metadata") or {}
    return question, answer, metadata


def _is_golden_candidate(answer_metadata: dict, answer: str) -> bool:
    """RAG 链路且实际产出内容的回答才具备金标候选资格。"""
    if not answer.strip():
        return False
    if answer_metadata.get("answer_path"):
        return True
    retrieval_count = answer_metadata.get("retrieval_count")
    try:
        return retrieval_count is not None and int(retrieval_count) > 0
    except (TypeError, ValueError):
        return False


def mine_hard_cases(
    tenant_id: str,
    score_threshold: int = 2,
    limit: int = 50,
) -> list[HardCase]:
    """挖掘低分评价对应的难例，按问题指纹去重并按出现次数降序。"""
    records = negative_satisfaction_list(
        tenant_id=tenant_id, max_score=score_threshold, limit=limit
    )
    if not records:
        return []

    cases: dict[str, HardCase] = {}
    skipped_no_qa = 0

    for record in records:
        session_id = record.get("session_id", "")
        if not session_id:
            skipped_no_qa += 1
            continue

        try:
            messages = message_list(session_id, tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001 - 单会话查询失败不拖垮整批挖掘
            logger.warning("Load messages failed for session %s: %s", session_id, e)
            skipped_no_qa += 1
            continue

        question, answer, metadata = _extract_last_qa(messages)
        if not question or not answer:
            skipped_no_qa += 1
            continue

        case_id = _fingerprint(question)
        if case_id in cases:
            cases[case_id].occurrence += 1
            # 保留最低分（最严重）评价的标签与留言
            if record["score"] < cases[case_id].score:
                cases[case_id].score = record["score"]
                cases[case_id].tags = record.get("tags", [])
                cases[case_id].comment = record.get("comment", "")
            continue

        cases[case_id] = HardCase(
            case_id=case_id,
            session_id=session_id,
            user_id=record.get("user_id", ""),
            score=record["score"],
            tags=record.get("tags", []),
            comment=record.get("comment", ""),
            question=question,
            answer=answer,
            answer_metadata=metadata,
            feedback_created_at=record.get("created_at", 0.0),
            golden_candidate=_is_golden_candidate(metadata, answer),
        )

    result = sorted(cases.values(), key=lambda c: (-c.occurrence, c.score))
    logger.info(
        "Hard cases mined: records=%d unique_cases=%d skipped=%d golden_candidates=%d",
        len(records),
        len(result),
        skipped_no_qa,
        sum(1 for c in result if c.golden_candidate),
    )
    return result


def export_jsonl(cases: list[HardCase]) -> str:
    """渲染为 JSONL 字符串，供 ops 脚本落盘与金标评审使用。"""
    return "\n".join(json.dumps(asdict(c), ensure_ascii=False) for c in cases)
