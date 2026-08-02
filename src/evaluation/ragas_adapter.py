"""
RAGAS 评估适配器 — 量化 RAG 系统质量

集成 ragas 的核心指标：
- Faithfulness（忠实度）：生成内容是否忠于检索上下文（幻觉检测）
- Context Recall（上下文召回）：检索是否覆盖答案所需关键信息
- Context Precision（上下文精确度）：检索上下文的信噪比
- Answer Relevancy（答案相关性）：回答是否切题
- Answer Correctness（答案准确性）：回答是否正确

参考项目：C:\\Users\\hai\\Desktop\\ragas-main
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


@dataclass
class RAGASResult:
    """RAGAS 评估结果"""
    faithfulness: float = 0.0       # 忠实度 0-1，越高越不幻觉
    context_recall: float = 0.0     # 召回率 0-1，越高越完整
    context_precision: float = 0.0  # 精确度 0-1，越高信噪比越好
    answer_relevancy: float = 0.0   # 相关性 0-1，越高越切题
    answer_correctness: float = 0.0 # 正确性 0-1，越高越准确

    def to_dict(self) -> dict:
        return {
            "faithfulness": self.faithfulness,
            "context_recall": self.context_recall,
            "context_precision": self.context_precision,
            "answer_relevancy": self.answer_relevancy,
            "answer_correctness": self.answer_correctness,
        }

    @property
    def overall_score(self) -> float:
        """综合评分（几何平均）"""
        scores = [
            self.faithfulness,
            self.context_recall,
            self.context_precision,
            self.answer_relevancy,
            self.answer_correctness,
        ]
        # 过滤掉 0 值（未计算的指标）
        valid_scores = [s for s in scores if s > 0]
        if not valid_scores:
            return 0.0
        # 几何平均（对低分更敏感）
        product = 1.0
        for s in valid_scores:
            product *= s
        return product ** (1.0 / len(valid_scores))


class RAGASEvaluator:
    """RAGAS 评估器 — 封装 ragas 指标计算

    使用方式：
        evaluator = RAGASEvaluator(llm)

        # 评估单次问答
        result = evaluator.evaluate(
            query="如何重置密码？",
            contexts=["重置密码请点击登录页面的'忘记密码'链接。"],
            answer="您可以在登录页面点击'忘记密码'链接重置密码。"
        )

        # 批量评估
        results = evaluator.evaluate_batch(samples)

    指标说明：
        - faithfulness 低 → 检查幻觉，可能需要增强 grounding 或降低温度
        - context_recall 低 → 增大 top_k / 降低相似度阈值 / 优化切片
        - context_precision 低 → 提高相似度阈值 / 加入重排序
        - answer_relevancy 低 → 优化 prompt / 检查意图理解
        - answer_correctness 低 → 检查知识库内容准确性
    """

    def __init__(self, llm: BaseChatModel):
        """初始化评估器

        Args:
            llm: 用于 LLM-as-Judge 的语言模型（推荐用强模型如 qwen-max）
        """
        self.llm = llm
        self._ragas_available = self._check_ragas_available()

        if self._ragas_available:
            logger.info("RAGAS library available, using native implementation")
        else:
            logger.info("RAGAS library not installed, using fallback LLM evaluation")

    def _check_ragas_available(self) -> bool:
        """检查 ragas 库是否可用"""
        try:
            from ragas.metrics import (  # noqa: F401
                faithfulness,
                context_recall,
                context_precision,
                answer_relevancy,
                answer_correctness,
            )
            return True
        except ImportError:
            return False

    def evaluate(
        self,
        query: str,
        contexts: List[str],
        answer: str,
        ground_truth: Optional[str] = None,
        metrics: Optional[List[str]] = None,
    ) -> RAGASResult:
        """评估单次问答

        Args:
            query: 用户问题
            contexts: 检索到的上下文列表
            answer: 生成的回答
            ground_truth: 标准答案（可选，用于 correctness）
            metrics: 要计算的指标列表，默认全部

        Returns:
            RAGASResult: 评估结果
        """
        if self._ragas_available:
            return self._evaluate_with_ragas(
                query, contexts, answer, ground_truth, metrics
            )
        else:
            return self._evaluate_with_llm(query, contexts, answer)

    def evaluate_batch(
        self,
        samples: List[dict],
        metrics: Optional[List[str]] = None,
    ) -> List[RAGASResult]:
        """批量评估

        Args:
            samples: 样本列表，每个样本包含 query/contexts/answer/ground_truth
            metrics: 要计算的指标列表

        Returns:
            评估结果列表
        """
        results = []
        for sample in samples:
            result = self.evaluate(
                query=sample.get("query", ""),
                contexts=sample.get("contexts", []),
                answer=sample.get("answer", ""),
                ground_truth=sample.get("ground_truth"),
                metrics=metrics,
            )
            results.append(result)
        return results

    def _evaluate_with_ragas(
        self,
        query: str,
        contexts: List[str],
        answer: str,
        ground_truth: Optional[str],
        metrics: Optional[List[str]],
    ) -> RAGASResult:
        """使用 ragas 库计算指标"""
        from ragas.metrics import (
            faithfulness,
            context_recall,
            context_precision,
            answer_relevancy,
            answer_correctness,
        )
        from ragas.dataset_schema import SingleTurnSample

        result = RAGASResult()

        # 构造 ragas 样本
        sample = SingleTurnSample(
            user_input=query,
            retrieved_contexts=contexts,
            response=answer,
            reference=ground_truth,
        )

        # 计算各项指标
        all_metrics = metrics or [
            "faithfulness",
            "context_recall",
            "context_precision",
            "answer_relevancy",
            "answer_correctness",
        ]

        async def compute_metrics():
            tasks = []
            metric_names = []

            if "faithfulness" in all_metrics:
                tasks.append(faithfulness.ascore(sample))
                metric_names.append("faithfulness")
            if "context_recall" in all_metrics and ground_truth:
                tasks.append(context_recall.ascore(sample))
                metric_names.append("context_recall")
            if "context_precision" in all_metrics:
                tasks.append(context_precision.ascore(sample))
                metric_names.append("context_precision")
            if "answer_relevancy" in all_metrics:
                tasks.append(answer_relevancy.ascore(sample))
                metric_names.append("answer_relevancy")
            if "answer_correctness" in all_metrics and ground_truth:
                tasks.append(answer_correctness.ascore(sample))
                metric_names.append("answer_correctness")

            scores = await asyncio.gather(*tasks, return_exceptions=True)

            for name, score in zip(metric_names, scores):
                if isinstance(score, Exception):
                    logger.warning(f"Failed to compute {name}: {score}")
                    continue
                if name == "faithfulness":
                    result.faithfulness = float(score)
                elif name == "context_recall":
                    result.context_recall = float(score)
                elif name == "context_precision":
                    result.context_precision = float(score)
                elif name == "answer_relevancy":
                    result.answer_relevancy = float(score)
                elif name == "answer_correctness":
                    result.answer_correctness = float(score)

        # 运行异步计算
        try:
            asyncio.get_event_loop().run_until_complete(compute_metrics())
        except RuntimeError:
            # 如果没有事件循环，创建一个新的
            asyncio.run(compute_metrics())

        return result

    def _evaluate_with_llm(
        self,
        query: str,
        contexts: List[str],
        answer: str,
    ) -> RAGASResult:
        """LLM fallback 评估（当 ragas 不可用时）

        简化版评估，只计算 faithfulness 和 answer_relevancy
        """
        result = RAGASResult()

        # 1. Faithfulness（忠实度）—— 检查答案是否基于上下文
        faithfulness_prompt = f"""请评估以下回答是否忠实于给定的上下文信息。

上下文：
{chr(10).join(f'{i+1}. {ctx}' for i, ctx in enumerate(contexts))}

回答：
{answer}

评分标准：
- 1.0：回答完全基于上下文，无幻觉
- 0.5：回答部分基于上下文，有小量推测
- 0.0：回答与上下文矛盾或大量虚构

请只返回一个 0-1 之间的数字，不要解释。"""

        try:
            response = self.llm.invoke(faithfulness_prompt)
            score_text = response.content.strip()
            # 提取数字
            import re
            match = re.search(r'[0-9]*\.?[0-9]+', score_text)
            if match:
                result.faithfulness = float(match.group())
        except Exception as e:
            logger.warning(f"Faithfulness evaluation failed: {e}")

        # 2. Answer Relevancy（答案相关性）—— 检查答案是否切题
        relevancy_prompt = f"""请评估以下回答是否切题地回答了用户的问题。

问题：
{query}

回答：
{answer}

评分标准：
- 1.0：回答完全切题，信息完整
- 0.5：回答部分切题，有遗漏或跑题
- 0.0：回答不相关或完全跑题

请只返回一个 0-1 之间的数字，不要解释。"""

        try:
            response = self.llm.invoke(relevancy_prompt)
            score_text = response.content.strip()
            import re
            match = re.search(r'[0-9]*\.?[0-9]+', score_text)
            if match:
                result.answer_relevancy = float(match.group())
        except Exception as e:
            logger.warning(f"Answer relevancy evaluation failed: {e}")

        return result


def get_diagnostic_message(result: RAGASResult) -> str:
    """根据评估结果生成诊断建议

    Args:
        result: RAGAS 评估结果

    Returns:
        诊断建议文本
    """
    messages = []

    if result.faithfulness < 0.7:
        messages.append(
            f"⚠️ 忠实度较低({result.faithfulness:.2f})：回答可能存在幻觉。"
            "建议：降低 LLM 温度、增强提示词中的 grounding 要求、加入事实核查工具。"
        )

    if result.context_recall < 0.7:
        messages.append(
            f"⚠️ 召回率较低({result.context_recall:.2f})：检索可能遗漏关键信息。"
            "建议：增大 top_k（当前默认 5）、降低相似度阈值（当前默认 0.2）、优化切片策略。"
        )

    if result.context_precision < 0.7:
        messages.append(
            f"⚠️ 精确度较低({result.context_precision:.2f})：检索上下文噪声多。"
            "建议：提高相似度阈值、加入重排序模型、优化查询改写。"
        )

    if result.answer_relevancy < 0.7:
        messages.append(
            f"⚠️ 相关性较低({result.answer_relevancy:.2f})：回答可能跑题。"
            "建议：优化系统提示词、检查意图识别准确性、考虑多轮对话上下文截断。"
        )

    if result.answer_correctness < 0.7:
        messages.append(
            f"⚠️ 正确性较低({result.answer_correctness:.2f})：回答可能不准确。"
            "建议：检查知识库内容准确性、更新过时文档、考虑多知识库权重调整。"
        )

    if not messages:
        messages.append(
            f"✅ 评估通过，综合评分 {result.overall_score:.2f}。"
            "系统运行正常，建议持续监控。"
        )

    return "\n".join(messages)