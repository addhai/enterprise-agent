"""情绪分析模块

职责：
    检测用户消息的情绪状态，用于兜底决策。

情绪分类：
    neutral — 正常咨询
    negative — 不满/抱怨
    angry — 愤怒/投诉
    urgent — 紧急/急躁
    satisfied — 满意/感谢

兜底规则：
    angry → 跳过追问，直接转人工（附情绪标记）
    urgent → 跳过追问，直接转人工（附紧急标记）
    negative → 减少追问轮次，优先转人工
    satisfied → 标记为已解决，记录正面反馈
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SentimentResult:
    """情绪分析结果"""
    sentiment: str = "neutral"  # neutral / negative / angry / urgent / satisfied
    confidence: float = 0.0
    keywords_found: List[str] = field(default_factory=list)
    urgency: str = "none"  # none / low / medium / high / critical
    action: str = "continue"  # continue / empathy_then_escalation / immediate_escalation / none


class SentimentAnalyzer:
    """情绪分析器 — 基于关键词 + 上下文"""

    # 负面情绪关键词
    ANGRY_KEYWORDS = [
        "投诉", "举报", "退款", "骗人", "最差", "恶心",
        "complaint", "fraud", "refund", "worst", "terrible", "horrible",
        "骗子", "黑心", "烂", "无语", "服了", "够了",
    ]

    # 紧急关键词
    URGENT_KEYWORDS = [
        "马上", "立刻", "急", "现在就要", "忍无可忍",
        "urgent", "asap", "right now", "immediately", "emergency",
        "加急", "十万火急", "火烧眉毛",
    ]

    # 不满关键词
    NEGATIVE_KEYWORDS = [
        "不满意", "不好", "没用", "垃圾服务",
        "disappointed", "frustrated", "annoyed", "upset", "unsatisfied",
        "太差", "不行", "没用", "浪费", "坑", "差劲",
    ]

    # 满意关键词
    SATISFIED_KEYWORDS = [
        "谢谢", "很好", "解决了", "满意", "感谢", "好评",
        "thanks", "great", "solved", "perfect", "excellent", "helpful",
        "好的", "明白了", "懂了",
    ]

    # 资产/合规敏感词
    RISK_KEYWORDS = [
        "报警", "起诉", "律师", "消协", "工信部", "银监会",
        "12315", "blacklist", "lawsuit", "lawyer", "police",
        "诉讼", "仲裁", "媒体曝光", "微博投诉",
    ]

    def analyze(self, message: str, conversation_history: Optional[list] = None) -> SentimentResult:
        """分析单条消息的情绪

        Args:
            message: 当前用户消息
            conversation_history: 对话历史（可选，用于上下文判断）

        Returns:
            SentimentResult
        """
        content_lower = message.lower()
        keywords_found = []

        # 1. 检测愤怒
        angry_matches = [kw for kw in self.ANGRY_KEYWORDS if kw in content_lower]
        if angry_matches:
            keywords_found.extend(angry_matches)
            # 检查是否有资产/合规敏感词
            risk_matches = [kw for kw in self.RISK_KEYWORDS if kw in content_lower]
            if risk_matches:
                keywords_found.extend(risk_matches)
                return SentimentResult(
                    sentiment="angry",
                    confidence=0.95,
                    keywords_found=list(set(keywords_found)),
                    urgency="critical",
                    action="immediate_escalation",
                )
            return SentimentResult(
                sentiment="angry",
                confidence=0.85,
                keywords_found=list(set(keywords_found)),
                urgency="high",
                action="immediate_escalation",
            )

        # 2. 检测紧急
        urgent_matches = [kw for kw in self.URGENT_KEYWORDS if kw in content_lower]
        if urgent_matches:
            keywords_found.extend(urgent_matches)
            return SentimentResult(
                sentiment="urgent",
                confidence=0.80,
                keywords_found=list(set(keywords_found)),
                urgency="high",
                action="empathy_then_escalation",
            )

        # 3. 检测不满
        negative_matches = [kw for kw in self.NEGATIVE_KEYWORDS if kw in content_lower]
        if negative_matches:
            keywords_found.extend(negative_matches)
            return SentimentResult(
                sentiment="negative",
                confidence=0.75,
                keywords_found=list(set(keywords_found)),
                urgency="medium",
                action="empathy_then_escalation",
            )

        # 4. 检测满意
        satisfied_matches = [kw for kw in self.SATISFIED_KEYWORDS if kw in content_lower]
        if satisfied_matches:
            keywords_found.extend(satisfied_matches)
            return SentimentResult(
                sentiment="satisfied",
                confidence=0.80,
                keywords_found=list(set(keywords_found)),
                urgency="none",
                action="none",
            )

        # 5. 默认中性
        return SentimentResult(
            sentiment="neutral",
            confidence=0.60,
            keywords_found=[],
            urgency="none",
            action="continue",
        )

    def analyze_batch(self, messages: list) -> SentimentResult:
        """分析整段对话的情绪（取最严重的）"""
        worst = SentimentResult(sentiment="neutral", confidence=0.0, urgency="none")

        for msg in messages:
            content = msg.content if hasattr(msg, "content") else str(msg)
            result = self.analyze(content)

            # 比较严重程度
            severity_order = {
                "neutral": 0,
                "satisfied": 0,
                "negative": 1,
                "urgent": 2,
                "angry": 3,
            }

            if severity_order.get(result.sentiment, 0) > severity_order.get(worst.sentiment, 0):
                worst = result

        return worst

    def should_skip_clarification(self, result: SentimentResult) -> bool:
        """是否应该跳过追问（直接转人工）"""
        return result.urgency in ("high", "critical") or result.action == "immediate_escalation"

    def should_escalate_immediately(self, result: SentimentResult) -> bool:
        """是否应该立即转人工（不经过 RAG）"""
        return result.action == "immediate_escalation"


# 全局单例
_analyzer: Optional[SentimentAnalyzer] = None


def get_sentiment_analyzer() -> SentimentAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentAnalyzer()
    return _analyzer
