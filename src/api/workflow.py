"""工作流管理 API — 对齐 MaxKB application API

提供 HTTP 接口管理工作流 DAG 定义：
    - 工作流 CRUD：创建 / 列表 / 详情 / 更新 / 删除
    - 发布：标记为已发布，记录版本
    - 校验：验证 DAG 拓扑合法性
    - 默认工作流：获取系统内置七节点 DAG

权限：admin / agent 可读，仅 admin 可写。
存储：复用 src.graph.workflow_dag._workflow_store（TenantIsolatedStore）。
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from src.api.rbac import Role, require_roles
from src.graph.workflow_dag import (
    DEFAULT_WORKFLOW,
    EdgeType,
    NodeType,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowMode,
    WorkflowNode,
    WorkflowValidationError,
    NodeData,
    delete_workflow,
    get_default_workflow,
    get_workflow,
    init_default_workflow,
    list_workflows,
    publish_workflow,
    save_workflow,
    validate_workflow,
    workflow_to_dict,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["workflow"])

_DEFAULT_TENANT = "default"


def _get_tenant_id(current_user: Dict[str, Any]) -> str:
    return current_user.get("tenant_id") or _DEFAULT_TENANT


# ====================================================================
# 请求模型
# ====================================================================

class WorkflowNodeRequest(BaseModel):
    """节点定义请求"""
    id: str = Field(..., description="节点 ID")
    type: str = Field(..., description="节点类型，如 entry-node / rag-node")
    stepName: str = Field("", description="显示名")
    x: int = 0
    y: int = 0
    handler_ref: str = Field("", description="LangGraph 节点函数引用")
    bind_deps: Dict[str, bool] = Field(default_factory=dict)
    is_end: bool = False
    node_data: Dict[str, Any] = Field(default_factory=dict, description="节点业务参数")


class WorkflowEdgeRequest(BaseModel):
    """边定义请求"""
    id: str = Field(..., description="边 ID")
    type: str = Field("app-edge", description="边类型：app-edge / conditional-edge")
    sourceNodeId: str = Field(..., description="源节点 ID")
    targetNodeId: str = Field("", description="目标节点 ID（条件边可空）")
    router_fn_ref: str = Field("", description="条件路由函数引用")
    branch_id: str = ""
    condition: Dict[str, Any] = Field(default_factory=dict)
    sourceAnchorId: str = ""
    targetAnchorId: str = ""


class WorkflowCreateRequest(BaseModel):
    """创建工作流请求"""
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=512)
    workflow_mode: str = Field("application", description="application / knowledge / tool")
    entry_node_id: str = Field("entry", description="入口节点 ID")
    nodes: List[WorkflowNodeRequest] = Field(default_factory=list)
    edges: List[WorkflowEdgeRequest] = Field(default_factory=list)
    checkpointer_config: Dict[str, Any] = Field(default_factory=dict)


class WorkflowUpdateRequest(BaseModel):
    """更新工作流请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    entry_node_id: Optional[str] = None
    nodes: Optional[List[WorkflowNodeRequest]] = None
    edges: Optional[List[WorkflowEdgeRequest]] = None
    checkpointer_config: Optional[Dict[str, Any]] = None


class WorkflowCloneRequest(BaseModel):
    """克隆工作流请求"""
    new_name: str = Field(..., min_length=1, max_length=128)
    new_description: str = Field("")


# ====================================================================
# 辅助：请求 → 模型
# ====================================================================

def _node_request_to_model(req: WorkflowNodeRequest) -> WorkflowNode:
    try:
        node_type = NodeType(req.type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"未知节点类型 '{req.type}': {e}")
    return WorkflowNode(
        id=req.id,
        type=node_type,
        stepName=req.stepName,
        x=req.x,
        y=req.y,
        handler_ref=req.handler_ref,
        bind_deps=req.bind_deps,
        is_end=req.is_end,
        node_data=NodeData(**req.node_data) if req.node_data else NodeData(),
    )


def _edge_request_to_model(req: WorkflowEdgeRequest) -> WorkflowEdge:
    try:
        edge_type = EdgeType(req.type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"未知边类型 '{req.type}': {e}")
    return WorkflowEdge(
        id=req.id,
        type=edge_type,
        sourceNodeId=req.sourceNodeId,
        targetNodeId=req.targetNodeId,
        router_fn_ref=req.router_fn_ref,
        branch_id=req.branch_id,
        condition=req.condition,
        sourceAnchorId=req.sourceAnchorId,
        targetAnchorId=req.targetAnchorId,
    )


def _build_definition(
    wf_id: str,
    tenant_id: str,
    req: WorkflowCreateRequest,
    created_by: str = "",
) -> WorkflowDefinition:
    """从请求构造 WorkflowDefinition"""
    try:
        mode = WorkflowMode(req.workflow_mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"未知工作流模式 '{req.workflow_mode}': {e}")

    nodes = [_node_request_to_model(n) for n in req.nodes]
    edges = [_edge_request_to_model(e) for e in req.edges]

    return WorkflowDefinition(
        id=wf_id,
        name=req.name,
        description=req.description,
        workspace_id=tenant_id,
        tenant_id=tenant_id,
        workflow_mode=mode,
        entry_node_id=req.entry_node_id,
        nodes=nodes,
        edges=edges,
        checkpointer_config=req.checkpointer_config,
        created_by=created_by,
    )


# ====================================================================
# 工作流 CRUD
# ====================================================================

@router.get("/admin/workflows")
async def list_user_workflows(
    workflow_mode: str = Query("", description="按模式筛选"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """列出所有工作流

    需要 admin / agent 角色。默认工作流也会包含在列表中。
    """
    tenant_id = _get_tenant_id(current_user)
    # 确保默认工作流已初始化
    init_default_workflow(tenant_id)

    wfs = list_workflows(tenant_id, 100)
    if workflow_mode:
        wfs = [w for w in wfs if w.workflow_mode == workflow_mode]

    return {
        "total": len(wfs),
        "workflows": [workflow_to_dict(w) for w in wfs],
    }


@router.get("/admin/workflows/default")
async def get_default_workflow_endpoint(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取系统默认工作流（七节点 DAG）

    返回默认工作流的深拷贝，可用于新建工作流的模板。
    """
    wf = get_default_workflow()
    return {"workflow": workflow_to_dict(wf)}


@router.get("/admin/workflows/{wf_id}")
async def get_workflow_detail(
    wf_id: str = Path(..., description="工作流 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取工作流详情"""
    tenant_id = _get_tenant_id(current_user)
    wf = get_workflow(wf_id, tenant_id)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"工作流不存在: {wf_id}")
    return {"workflow": workflow_to_dict(wf)}


@router.post("/admin/workflows")
async def create_workflow_endpoint(
    req: WorkflowCreateRequest,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """创建工作流（仅 admin）

    自动校验 DAG 拓扑合法性，校验失败返回 400。
    """
    from src.mcp_tools.common import generate_id

    tenant_id = _get_tenant_id(current_user)
    wf_id = generate_id("WF")
    wf = _build_definition(wf_id, tenant_id, req, created_by=current_user.get("user_id", ""))

    try:
        saved = save_workflow(wf, tenant_id)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=400, detail=f"工作流校验失败: {e}")

    logger.info("Workflow created: id=%s name=%s by=%s", wf_id, req.name, current_user.get("user_id"))
    return {"success": True, "workflow": workflow_to_dict(saved)}


@router.put("/admin/workflows/{wf_id}")
async def update_workflow_endpoint(
    req: WorkflowUpdateRequest,
    wf_id: str = Path(..., description="工作流 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """更新工作流（仅 admin）

    可更新：名称、描述、入口节点、节点列表、边列表、checkpointer 配置。
    未提供的字段保持不变。
    """
    tenant_id = _get_tenant_id(current_user)
    wf = get_workflow(wf_id, tenant_id)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"工作流不存在: {wf_id}")

    if req.name is not None:
        wf.name = req.name
    if req.description is not None:
        wf.description = req.description
    if req.entry_node_id is not None:
        wf.entry_node_id = req.entry_node_id
    if req.nodes is not None:
        wf.nodes = [_node_request_to_model(n) for n in req.nodes]
    if req.edges is not None:
        wf.edges = [_edge_request_to_model(e) for e in req.edges]
    if req.checkpointer_config is not None:
        wf.checkpointer_config = req.checkpointer_config

    try:
        saved = save_workflow(wf, tenant_id)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=400, detail=f"工作流校验失败: {e}")

    logger.info("Workflow updated: id=%s by=%s", wf_id, current_user.get("user_id"))
    return {"success": True, "workflow": workflow_to_dict(saved)}


@router.delete("/admin/workflows/{wf_id}")
async def delete_workflow_endpoint(
    wf_id: str = Path(..., description="工作流 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """删除工作流（仅 admin）

    注意：默认工作流（id=default-cs-workflow）不可删除。
    """
    tenant_id = _get_tenant_id(current_user)
    if wf_id == DEFAULT_WORKFLOW.id:
        raise HTTPException(status_code=400, detail="默认工作流不可删除")

    wf = get_workflow(wf_id, tenant_id)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"工作流不存在: {wf_id}")

    delete_workflow(wf_id, tenant_id)
    logger.info("Workflow deleted: id=%s by=%s", wf_id, current_user.get("user_id"))
    return {"success": True, "message": f"工作流 {wf_id} 已删除"}


# ====================================================================
# 发布与校验
# ====================================================================

@router.post("/admin/workflows/{wf_id}/publish")
async def publish_workflow_endpoint(
    wf_id: str = Path(..., description="工作流 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """发布工作流（仅 admin）

    发布前会重新校验拓扑合法性。发布后 is_publish=True，version+1。
    """
    tenant_id = _get_tenant_id(current_user)
    wf = get_workflow(wf_id, tenant_id)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"工作流不存在: {wf_id}")

    errors = validate_workflow(wf)
    if errors:
        raise HTTPException(status_code=400, detail=f"校验失败: {'; '.join(errors)}")

    published = publish_workflow(wf_id, tenant_id)
    if published is None:
        raise HTTPException(status_code=500, detail="发布失败")

    logger.info("Workflow published: id=%s version=%d by=%s", wf_id, published.version, current_user.get("user_id"))
    return {"success": True, "workflow": workflow_to_dict(published)}


@router.post("/admin/workflows/{wf_id}/validate")
async def validate_workflow_endpoint(
    wf_id: str = Path(..., description="工作流 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """校验工作流 DAG 拓扑合法性

    返回校验结果与错误列表（若有）。
    """
    tenant_id = _get_tenant_id(current_user)
    wf = get_workflow(wf_id, tenant_id)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"工作流不存在: {wf_id}")

    errors = validate_workflow(wf)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "node_count": len(wf.nodes),
        "edge_count": len(wf.edges),
    }


@router.post("/admin/workflows/validate")
async def validate_workflow_draft(
    req: WorkflowCreateRequest,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """校验工作流草稿（未保存的工作流定义）

    用于可视化编辑器实时校验。
    """
    tenant_id = _get_tenant_id(current_user)
    wf = _build_definition("draft", tenant_id, req)

    errors = validate_workflow(wf)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "node_count": len(wf.nodes),
        "edge_count": len(wf.edges),
    }


# ====================================================================
# 克隆
# ====================================================================

@router.post("/admin/workflows/{wf_id}/clone")
async def clone_workflow_endpoint(
    req: WorkflowCloneRequest,
    wf_id: str = Path(..., description="源工作流 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """克隆工作流（仅 admin）

    基于现有工作流创建副本，新工作流 is_publish=False。
    常用于基于默认工作流创建自定义工作流。
    """
    from src.mcp_tools.common import generate_id

    tenant_id = _get_tenant_id(current_user)
    src_wf = get_workflow(wf_id, tenant_id)
    if src_wf is None:
        # 如果是默认工作流 ID，从默认模板获取
        if wf_id == DEFAULT_WORKFLOW.id:
            src_wf = get_default_workflow()
        else:
            raise HTTPException(status_code=404, detail=f"源工作流不存在: {wf_id}")

    new_id = generate_id("WF")
    new_wf = src_wf.model_copy(deep=True)
    new_wf.id = new_id
    new_wf.name = req.new_name
    new_wf.description = req.new_description
    new_wf.tenant_id = tenant_id
    new_wf.workspace_id = tenant_id
    new_wf.is_publish = False
    new_wf.publish_time = None
    new_wf.version = 1
    new_wf.created_by = current_user.get("user_id", "")
    new_wf.created_at = ""
    new_wf.updated_at = ""

    try:
        saved = save_workflow(new_wf, tenant_id)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=400, detail=f"工作流校验失败: {e}")

    logger.info(
        "Workflow cloned: src=%s new=%s by=%s",
        wf_id, new_id, current_user.get("user_id"),
    )
    return {"success": True, "workflow": workflow_to_dict(saved)}


# ====================================================================
# 节点类型参考
# ====================================================================

@router.get("/admin/workflows/meta/node-types")
async def get_node_types(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取可用节点类型清单

    供可视化编辑器渲染节点面板使用。
    """
    node_types = []
    for nt in NodeType:
        # 根据 enum 值推断分类
        if nt in (NodeType.ENTRY_NODE, NodeType.REPLY_NODE, NodeType.HUMAN_NODE):
            category = "control"
        elif nt in (NodeType.CLARIFY_NODE, NodeType.ROUTER_NODE, NodeType.CONDITION_NODE, NodeType.REFLECT_NODE):
            category = "logic"
        elif nt in (NodeType.FAQ_NODE, NodeType.RAG_NODE, NodeType.SEARCH_NODE, NodeType.RERANKER_NODE):
            category = "retrieval"
        elif nt in (NodeType.LLM_NODE, NodeType.TOOL_NODE, NodeType.LOOP_NODE):
            category = "execution"
        else:
            category = "other"

        node_types.append({
            "type": nt.value,
            "category": category,
            "is_end": nt in {NodeType.REPLY_NODE, NodeType.HUMAN_NODE, NodeType.LLM_NODE, NodeType.TOOL_NODE},
        })

    return {
        "total": len(node_types),
        "node_types": node_types,
        "edge_types": [e.value for e in EdgeType],
        "workflow_modes": [w.value for w in WorkflowMode],
    }
