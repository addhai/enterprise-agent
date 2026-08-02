"""评估管理 API — 数据集管理 + 触发评估 + 查看报告

提供 HTTP 接口管理 RAG 评估流水线：
    - 数据集 CRUD：上传 / 列表 / 详情 / 删除
    - 触发评估：对指定数据集运行评估（同步返回结果）
    - 评估历史：列表 / 详情（含聚合报告）

权限：admin / agent 可读，仅 admin 可创建/删除/触发。
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from src.api.rbac import Role, require_roles
from src.evaluation.pipeline import (
    EvaluationDataset,
    EvaluationSample,
    RunStatus,
    dataset_to_dict,
    delete_dataset,
    delete_run,
    get_dataset,
    get_pipeline,
    get_run,
    list_datasets,
    list_runs,
    run_to_dict,
    save_dataset,
)
from src.mcp_tools.common import generate_id

logger = logging.getLogger(__name__)
router = APIRouter(tags=["evaluation"])

_DEFAULT_TENANT = "default"


def _get_tenant_id(current_user: Dict[str, Any]) -> str:
    return current_user.get("tenant_id") or _DEFAULT_TENANT


# ====================================================================
# 请求模型
# ====================================================================

class SampleRequest(BaseModel):
    """测试样本请求"""
    query: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    ground_truth: Optional[str] = Field(None, description="标准答案")
    expected_intent: Optional[str] = Field(None, description="期望意图")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DatasetCreateRequest(BaseModel):
    """创建数据集请求"""
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=512)
    samples: List[SampleRequest] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class DatasetUpdateRequest(BaseModel):
    """更新数据集请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    samples: Optional[List[SampleRequest]] = None
    tags: Optional[List[str]] = None


class EvaluationRunRequest(BaseModel):
    """触发评估请求"""
    dataset_id: str = Field(..., description="数据集 ID")
    workflow_id: str = Field("", description="工作流 ID（空=默认工作流）")


# ====================================================================
# 数据集 CRUD
# ====================================================================

@router.post("/admin/evaluation/datasets")
async def create_dataset(
    req: DatasetCreateRequest,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """创建评估数据集（仅 admin）

    样本格式对齐 RAGAS：query（必填）+ ground_truth（可选）
    """
    tenant_id = _get_tenant_id(current_user)

    samples = [
        EvaluationSample(
            query=s.query,
            ground_truth=s.ground_truth,
            expected_intent=s.expected_intent,
            metadata=s.metadata,
        )
        for s in req.samples
    ]

    ds = EvaluationDataset(
        id=generate_id("DS"),
        tenant_id=tenant_id,
        name=req.name,
        description=req.description,
        samples=samples,
        tags=req.tags,
        created_at="",
        created_by=current_user.get("user_id", ""),
    )
    from src.mcp_tools.common import current_utc_time
    ds.created_at = current_utc_time().isoformat()

    save_dataset(ds, tenant_id)
    logger.info(
        "Dataset created: id=%s name=%s samples=%d by=%s",
        ds.id, ds.name, len(samples), current_user.get("user_id"),
    )
    return {"success": True, "dataset": dataset_to_dict(ds)}


@router.get("/admin/evaluation/datasets")
async def list_user_datasets(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """列出所有评估数据集"""
    tenant_id = _get_tenant_id(current_user)
    dss = list_datasets(tenant_id, 100)
    return {
        "total": len(dss),
        "datasets": [dataset_to_dict(d) for d in dss],
    }


@router.get("/admin/evaluation/datasets/{dataset_id}")
async def get_dataset_detail(
    dataset_id: str = Path(..., description="数据集 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取数据集详情（含完整样本列表）"""
    tenant_id = _get_tenant_id(current_user)
    ds = get_dataset(dataset_id, tenant_id)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}")
    return {
        "dataset": {
            **dataset_to_dict(ds),
            "samples": [s.model_dump() for s in ds.samples],
        }
    }


@router.put("/admin/evaluation/datasets/{dataset_id}")
async def update_dataset(
    req: DatasetUpdateRequest,
    dataset_id: str = Path(..., description="数据集 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """更新数据集（仅 admin）"""
    tenant_id = _get_tenant_id(current_user)
    ds = get_dataset(dataset_id, tenant_id)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}")

    if req.name is not None:
        ds.name = req.name
    if req.description is not None:
        ds.description = req.description
    if req.samples is not None:
        ds.samples = [
            EvaluationSample(
                query=s.query,
                ground_truth=s.ground_truth,
                expected_intent=s.expected_intent,
                metadata=s.metadata,
            )
            for s in req.samples
        ]
    if req.tags is not None:
        ds.tags = req.tags

    save_dataset(ds, tenant_id)
    logger.info("Dataset updated: id=%s by=%s", dataset_id, current_user.get("user_id"))
    return {"success": True, "dataset": dataset_to_dict(ds)}


@router.delete("/admin/evaluation/datasets/{dataset_id}")
async def delete_dataset_endpoint(
    dataset_id: str = Path(..., description="数据集 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """删除数据集（仅 admin）"""
    tenant_id = _get_tenant_id(current_user)
    ds = get_dataset(dataset_id, tenant_id)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}")
    delete_dataset(dataset_id, tenant_id)
    logger.info("Dataset deleted: id=%s by=%s", dataset_id, current_user.get("user_id"))
    return {"success": True, "message": f"数据集 {dataset_id} 已删除"}


# ====================================================================
# 触发评估
# ====================================================================

@router.post("/admin/evaluation/runs")
async def create_evaluation_run(
    req: EvaluationRunRequest,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """触发评估运行（仅 admin）

    对指定数据集运行评估流水线，同步返回结果。
    注意：评估可能耗时较长（每个样本需要调用 LLM），建议数据集不超过 20 个样本。

    Args:
        dataset_id: 数据集 ID
        workflow_id: 工作流 ID（空=使用默认工作流）
    """
    tenant_id = _get_tenant_id(current_user)
    ds = get_dataset(req.dataset_id, tenant_id)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"数据集不存在: {req.dataset_id}")

    if not ds.samples:
        raise HTTPException(status_code=400, detail="数据集为空，无法评估")

    # 获取工作流
    try:
        from src.api.dependencies import get_workflow
        workflow_app = get_workflow()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"工作流未就绪: {e}")

    # 如果指定了 workflow_id，尝试从声明式定义加载
    if req.workflow_id:
        try:
            from src.api.dependencies import get_retriever, get_memory_manager
            from src.graph.workflow_loader import create_workflow_from_id
            workflow_app = create_workflow_from_id(
                req.workflow_id,
                tenant_id=tenant_id,
                retriever=get_retriever(),
                memory_manager=get_memory_manager(),
            )
        except Exception as e:
            logger.warning("从 workflow_id 加载失败，回退到默认工作流: %s", e)

    # 运行评估
    pipeline = get_pipeline()
    try:
        run = pipeline.run(
            dataset=ds,
            workflow_app=workflow_app,
            workflow_id=req.workflow_id,
            created_by=current_user.get("user_id", ""),
            tenant_id=tenant_id,
        )
    except Exception as e:
        logger.exception("评估运行失败: %s", e)
        raise HTTPException(status_code=500, detail=f"评估失败: {e}")

    logger.info(
        "Evaluation run completed: id=%s status=%s by=%s",
        run.id, run.status, current_user.get("user_id"),
    )
    return {"success": True, "run": run_to_dict(run, include_results=False)}


@router.get("/admin/evaluation/runs")
async def list_user_runs(
    status: str = Query("", description="按状态筛选"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """列出评估运行历史"""
    tenant_id = _get_tenant_id(current_user)
    runs = list_runs(tenant_id, 100)
    if status:
        runs = [r for r in runs if r.status == status]
    return {
        "total": len(runs),
        "runs": [run_to_dict(r, include_results=False) for r in runs],
    }


@router.get("/admin/evaluation/runs/{run_id}")
async def get_run_detail(
    run_id: str = Path(..., description="运行 ID"),
    include_results: bool = Query(True, description="是否包含完整结果列表"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取评估运行详情（含聚合报告与样本结果）"""
    tenant_id = _get_tenant_id(current_user)
    run = get_run(run_id, tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"评估运行不存在: {run_id}")
    return {"run": run_to_dict(run, include_results=include_results)}


@router.delete("/admin/evaluation/runs/{run_id}")
async def delete_run_endpoint(
    run_id: str = Path(..., description="运行 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """删除评估运行记录（仅 admin）"""
    tenant_id = _get_tenant_id(current_user)
    run = get_run(run_id, tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"评估运行不存在: {run_id}")
    delete_run(run_id, tenant_id)
    logger.info("Run deleted: id=%s by=%s", run_id, current_user.get("user_id"))
    return {"success": True, "message": f"评估运行 {run_id} 已删除"}


# ====================================================================
# 评估指标说明（元数据）
# ====================================================================

@router.get("/admin/evaluation/meta/metrics")
async def get_metrics_info(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取评估指标说明

    供前端渲染指标面板与诊断建议。
    """
    return {
        "metrics": [
            {
                "name": "faithfulness",
                "label": "忠实度",
                "description": "生成内容是否忠于检索上下文（幻觉检测）",
                "threshold": 0.7,
                "improve_hint": "降低 LLM 温度、增强 grounding、加入事实核查",
            },
            {
                "name": "context_recall",
                "label": "上下文召回",
                "description": "检索是否覆盖答案所需关键信息",
                "threshold": 0.7,
                "improve_hint": "增大 top_k、降低相似度阈值、优化切片",
            },
            {
                "name": "context_precision",
                "label": "上下文精确度",
                "description": "检索上下文的信噪比",
                "threshold": 0.7,
                "improve_hint": "提高相似度阈值、加入重排序、优化查询改写",
            },
            {
                "name": "answer_relevancy",
                "label": "答案相关性",
                "description": "回答是否切题",
                "threshold": 0.7,
                "improve_hint": "优化系统提示词、检查意图识别、多轮上下文截断",
            },
            {
                "name": "answer_correctness",
                "label": "答案准确性",
                "description": "回答是否正确（需 ground_truth）",
                "threshold": 0.7,
                "improve_hint": "检查知识库内容准确性、更新过时文档、调整多知识库权重",
            },
        ],
        "summary_fields": [
            {"name": "overall_score", "label": "综合评分", "description": "各指标几何平均"},
            {"name": "pass_rate", "label": "通过率", "description": "综合分 >= 0.7 的样本占比"},
            {"name": "avg_latency_ms", "label": "平均延迟", "description": "单样本平均耗时（毫秒）"},
            {"name": "needs_human_rate", "label": "转人工率", "description": "触发转人工的样本占比"},
            {"name": "intent_accuracy", "label": "路由准确率", "description": "意图识别正确率"},
        ],
        "statuses": [
            {"value": RunStatus.PENDING, "label": "等待中"},
            {"value": RunStatus.RUNNING, "label": "运行中"},
            {"value": RunStatus.COMPLETED, "label": "已完成"},
            {"value": RunStatus.FAILED, "label": "失败"},
        ],
    }
