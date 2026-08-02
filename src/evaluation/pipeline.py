"""评估流水线 — 批量测试集 → 运行工作流 → RAGAS 评估 → 聚合报告

将 ragas_adapter 的单次评估能力扩展为端到端评估流水线：
    1. 加载测试集（query + ground_truth）
    2. 对每个样本调用 LangGraph 工作流，获取 answer + retrieved_docs
    3. 用 RAGASEvaluator 计算 5 项指标（faithfulness/recall/precision/relevancy/correctness）
    4. 聚合统计（均值/P50/P90/通过率）+ 诊断建议

用途：
    - 量化 P1-P4 改进效果（重排序/DeepDoc/护栏/HITL）
    - 回归测试（知识库更新前后对比）
    - SLA 监控（定期评估质量是否下降）

数据集格式对齐 RAGAS：
    样本包含 query（必填）+ ground_truth（可选，用于 correctness/recall）
"""
from __future__ import annotations

import logging
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.evaluation.ragas_adapter import RAGASResult, get_diagnostic_message
from src.mcp_tools.common import (
    TenantIsolatedStore,
    current_utc_time,
    generate_id,
)

logger = logging.getLogger(__name__)


# ====================================================================
# 数据模型
# ====================================================================

class EvaluationSample(BaseModel):
    """测试样本 — 对齐 RAGAS SingleTurnSample"""
    query: str = Field(..., description="用户问题")
    ground_truth: Optional[str] = Field(None, description="标准答案（用于 correctness/recall）")
    expected_intent: Optional[str] = Field(None, description="期望意图（用于路由准确率）")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class EvaluationDataset(BaseModel):
    """评估数据集"""
    id: str
    tenant_id: str
    name: str
    description: str = ""
    samples: List[EvaluationSample] = Field(default_factory=list)
    created_at: str
    created_by: str = ""
    tags: List[str] = Field(default_factory=list)


class SampleResult(BaseModel):
    """单样本评估结果"""
    query: str
    answer: str = ""
    contexts: List[str] = Field(default_factory=list)
    ground_truth: Optional[str] = None
    intent: Optional[str] = None
    expected_intent: Optional[str] = None
    needs_human: bool = False
    latency_ms: int = 0
    error: str = ""
    ragas: Optional[Dict[str, float]] = None  # RAGASResult.to_dict()


class RunStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationRun(BaseModel):
    """评估运行记录"""
    id: str
    tenant_id: str
    dataset_id: str
    dataset_name: str = ""
    status: str = RunStatus.PENDING
    started_at: str
    completed_at: Optional[str] = None
    results: List[SampleResult] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    workflow_id: str = ""        # 使用的 workflow ID（空=默认）
    created_by: str = ""


# ====================================================================
# 持久化存储
# ====================================================================

_dataset_store: TenantIsolatedStore[EvaluationDataset] = TenantIsolatedStore(
    max_items_per_tenant=50, name="eval_dataset"
)
_run_store: TenantIsolatedStore[EvaluationRun] = TenantIsolatedStore(
    max_items_per_tenant=200, name="eval_run"
)


def _utc_iso() -> str:
    return current_utc_time().isoformat()


# ====================================================================
# 流水线核心
# ====================================================================

class EvaluationPipeline:
    """评估流水线执行器

    使用方式：
        pipeline = EvaluationPipeline()
        run = pipeline.run(dataset, workflow_app=app, llm=llm)
    """

    def __init__(self, llm: Optional[Any] = None):
        """初始化

        Args:
            llm: 用于 RAGAS 评估的语言模型（推荐 qwen-max）
                 None 则延迟初始化
        """
        self._llm = llm

    def _get_llm(self):
        """懒加载 LLM"""
        if self._llm is not None:
            return self._llm
        try:
            from langchain_openai import ChatOpenAI
            from src.config import settings
            self._llm = ChatOpenAI(
                model=settings.llm_complex_model,
                api_key=settings.openai_api_key,
                base_url=settings.openai_api_base,
                temperature=0.0,
            )
        except Exception as e:
            logger.warning("LLM 初始化失败，评估将跳过 RAGAS 指标: %s", e)
        return self._llm

    def _get_evaluator(self):
        """获取 RAGAS 评估器"""
        llm = self._get_llm()
        if llm is None:
            return None
        from src.evaluation.ragas_adapter import RAGASEvaluator
        return RAGASEvaluator(llm)

    def run_sample(
        self,
        sample: EvaluationSample,
        workflow_app: Any,
    ) -> SampleResult:
        """执行单个样本评估

        Args:
            sample: 测试样本
            workflow_app: 编译好的 LangGraph 工作流（Runnable）

        Returns:
            SampleResult: 含 answer/contexts/ragas 指标
        """
        from src.graph.state import AgentState
        from langchain_core.messages import HumanMessage

        result = SampleResult(
            query=sample.query,
            ground_truth=sample.ground_truth,
            expected_intent=sample.expected_intent,
        )

        start_time = time.time()

        try:
            # 构造初始状态
            import uuid
            session_id = str(uuid.uuid4())
            state = AgentState(
                messages=[HumanMessage(content=sample.query)],
                intent=None,
                retrieved_docs=[],
                needs_human=False,
                turn_count=0,
                final_response="",
                user_id="eval_bot",
                session_id=session_id,
                tenant_id="default",
                user_access_levels=["public", "internal", "confidential", "restricted"],
                user_roles=[],
                user_plan="free",
                faq_match=None,
                effective_max_turns=5,
                has_reflected=False,
                memory_context="",
                quality_score=None,
                access_filtered=0,
                needs_expert_delegation=False,
                expert_response=None,
                injection_blocked=False,
                injection_type=None,
                failed_attempts=0,
                suggest_human=False,
            )

            # 调用工作流
            output = workflow_app.invoke(
                state,
                config={"configurable": {"thread_id": session_id}},
            )

            result.answer = output.get("final_response", "")
            result.intent = output.get("intent")
            result.needs_human = output.get("needs_human", False)

            # 提取检索上下文
            retrieved = output.get("retrieved_docs", [])
            result.contexts = [
                getattr(doc, "page_content", str(doc))[:500]
                for doc in retrieved
            ]

        except Exception as e:
            result.error = f"工作流执行失败: {e}"
            logger.exception("Sample execution failed: query=%s", sample.query)

        result.latency_ms = int((time.time() - start_time) * 1000)

        # RAGAS 评估（仅当有 answer 时）
        if result.answer and not result.error:
            evaluator = self._get_evaluator()
            if evaluator is not None:
                try:
                    ragas_result = evaluator.evaluate(
                        query=sample.query,
                        contexts=result.contexts,
                        answer=result.answer,
                        ground_truth=sample.ground_truth,
                    )
                    result.ragas = ragas_result.to_dict()
                except Exception as e:
                    logger.warning("RAGAS 评估失败: %s", e)
                    result.error = f"RAGAS 评估失败: {e}"

        return result

    def run(
        self,
        dataset: EvaluationDataset,
        workflow_app: Any,
        workflow_id: str = "",
        created_by: str = "",
        tenant_id: str = "default",
    ) -> EvaluationRun:
        """执行完整评估流水线

        Args:
            dataset: 测试数据集
            workflow_app: 编译好的 LangGraph 工作流
            workflow_id: 工作流 ID（记录用）
            created_by: 触发者
            tenant_id: 租户 ID

        Returns:
            EvaluationRun: 含所有样本结果与聚合统计
        """
        run = EvaluationRun(
            id=generate_id("EVAL"),
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            status=RunStatus.RUNNING,
            started_at=_utc_iso(),
            workflow_id=workflow_id,
            created_by=created_by,
        )
        _run_store.save(tenant_id, run.id, run)

        logger.info(
            "Evaluation run started: id=%s dataset=%s samples=%d",
            run.id, dataset.name, len(dataset.samples),
        )

        try:
            for i, sample in enumerate(dataset.samples):
                logger.info(
                    "Evaluating sample %d/%d: %s",
                    i + 1, len(dataset.samples), sample.query[:50],
                )
                result = self.run_sample(sample, workflow_app)
                run.results.append(result)
                # 增量保存（支持中途查看进度）
                _run_store.save(tenant_id, run.id, run)

            # 聚合统计
            run.summary = self._compute_summary(run.results, dataset.samples)
            run.status = RunStatus.COMPLETED
            run.completed_at = _utc_iso()

        except Exception as e:
            run.status = RunStatus.FAILED
            run.error = str(e)
            run.completed_at = _utc_iso()
            logger.exception("Evaluation run failed: %s", e)

        _run_store.save(tenant_id, run.id, run)
        logger.info(
            "Evaluation run completed: id=%s status=%s overall=%.2f",
            run.id, run.status, run.summary.get("overall_score", 0),
        )
        return run

    def _compute_summary(
        self,
        results: List[SampleResult],
        samples: List[EvaluationSample],
    ) -> Dict[str, Any]:
        """计算聚合统计

        包含：
            - 各指标均值/P50/P90
            - 通过率（overall >= 0.7）
            - 路由准确率（intent 匹配）
            - 平均延迟
            - 转人工率
            - 诊断建议
        """
        summary: Dict[str, Any] = {
            "total_samples": len(results),
            "successful": 0,
            "failed": 0,
        }

        # 收集各指标分数
        metric_scores: Dict[str, List[float]] = {
            "faithfulness": [],
            "context_recall": [],
            "context_precision": [],
            "answer_relevancy": [],
            "answer_correctness": [],
        }
        overall_scores: List[float] = []
        latencies: List[int] = []
        needs_human_count = 0

        # 路由准确率
        intent_match = 0
        intent_total = 0

        for i, result in enumerate(results):
            if result.error and not result.ragas:
                summary["failed"] += 1
                continue
            summary["successful"] += 1

            if result.ragas:
                for metric, score in result.ragas.items():
                    if score > 0:
                        metric_scores[metric].append(score)

                # 综合分（几何平均）
                valid = [s for s in result.ragas.values() if s > 0]
                if valid:
                    product = 1.0
                    for s in valid:
                        product *= s
                    overall_scores.append(product ** (1.0 / len(valid)))

            latencies.append(result.latency_ms)
            if result.needs_human:
                needs_human_count += 1

            # 路由准确率
            expected = samples[i].expected_intent if i < len(samples) else None
            if expected and result.intent:
                intent_total += 1
                if result.intent == expected:
                    intent_match += 1

        # 各指标统计
        metrics_summary: Dict[str, Dict[str, float]] = {}
        for metric, scores in metric_scores.items():
            if scores:
                metrics_summary[metric] = {
                    "mean": round(statistics.mean(scores), 4),
                    "p50": round(statistics.median(scores), 4),
                    "p90": round(self._percentile(scores, 90), 4),
                    "count": len(scores),
                }
        summary["metrics"] = metrics_summary

        # 综合分
        if overall_scores:
            summary["overall_score"] = round(statistics.mean(overall_scores), 4)
            summary["pass_rate"] = round(
                sum(1 for s in overall_scores if s >= 0.7) / len(overall_scores), 4
            )
        else:
            summary["overall_score"] = 0.0
            summary["pass_rate"] = 0.0

        # 延迟
        if latencies:
            summary["avg_latency_ms"] = round(statistics.mean(latencies))
            summary["p90_latency_ms"] = round(self._percentile(latencies, 90))

        # 转人工率
        summary["needs_human_rate"] = round(needs_human_count / max(1, len(results)), 4)

        # 路由准确率
        if intent_total > 0:
            summary["intent_accuracy"] = round(intent_match / intent_total, 4)

        # 诊断建议
        if overall_scores:
            avg_result = RAGASResult(
                faithfulness=statistics.mean(metric_scores["faithfulness"]) if metric_scores["faithfulness"] else 0,
                context_recall=statistics.mean(metric_scores["context_recall"]) if metric_scores["context_recall"] else 0,
                context_precision=statistics.mean(metric_scores["context_precision"]) if metric_scores["context_precision"] else 0,
                answer_relevancy=statistics.mean(metric_scores["answer_relevancy"]) if metric_scores["answer_relevancy"] else 0,
                answer_correctness=statistics.mean(metric_scores["answer_correctness"]) if metric_scores["answer_correctness"] else 0,
            )
            summary["diagnostics"] = get_diagnostic_message(avg_result)

        return summary

    @staticmethod
    def _percentile(data: List[float], p: float) -> float:
        """计算百分位数"""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * p / 100
        f = int(k)
        c = min(f + 1, len(sorted_data) - 1)
        if f == c:
            return sorted_data[f]
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


# ====================================================================
# 便捷函数
# ====================================================================

def get_pipeline(llm: Optional[Any] = None) -> EvaluationPipeline:
    """获取评估流水线实例"""
    return EvaluationPipeline(llm=llm)


def save_dataset(dataset: EvaluationDataset, tenant_id: str = "default") -> EvaluationDataset:
    """保存数据集"""
    _dataset_store.save(tenant_id, dataset.id, dataset)
    return dataset


def get_dataset(dataset_id: str, tenant_id: str = "default") -> Optional[EvaluationDataset]:
    return _dataset_store.get(tenant_id, dataset_id)


def list_datasets(tenant_id: str = "default", limit: int = 50) -> List[EvaluationDataset]:
    return _dataset_store.list(tenant_id, limit)


def delete_dataset(dataset_id: str, tenant_id: str = "default") -> bool:
    return _dataset_store.delete(tenant_id, dataset_id)


def get_run(run_id: str, tenant_id: str = "default") -> Optional[EvaluationRun]:
    return _run_store.get(tenant_id, run_id)


def list_runs(tenant_id: str = "default", limit: int = 50) -> List[EvaluationRun]:
    return _run_store.list(tenant_id, limit)


def delete_run(run_id: str, tenant_id: str = "default") -> bool:
    return _run_store.delete(tenant_id, run_id)


def dataset_to_dict(ds: EvaluationDataset) -> Dict[str, Any]:
    return {
        "id": ds.id,
        "name": ds.name,
        "description": ds.description,
        "sample_count": len(ds.samples),
        "tags": ds.tags,
        "created_at": ds.created_at,
        "created_by": ds.created_by,
    }


def run_to_dict(run: EvaluationRun, include_results: bool = False) -> Dict[str, Any]:
    result = {
        "id": run.id,
        "dataset_id": run.dataset_id,
        "dataset_name": run.dataset_name,
        "status": run.status,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "workflow_id": run.workflow_id,
        "created_by": run.created_by,
        "error": run.error,
        "summary": run.summary,
        "result_count": len(run.results),
    }
    if include_results:
        result["results"] = [r.model_dump() for r in run.results]
    else:
        # 只返回前 5 个结果摘要（避免响应过大）
        result["results_preview"] = [
            {
                "query": r.query,
                "answer": r.answer[:200] if r.answer else "",
                "intent": r.intent,
                "needs_human": r.needs_human,
                "latency_ms": r.latency_ms,
                "error": r.error,
                "ragas": r.ragas,
            }
            for r in run.results[:5]
        ]
    return result
