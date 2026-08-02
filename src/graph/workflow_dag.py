"""工作流 DAG 声明式定义 — 对齐 MaxKB / 阿里云百炼可视化编排

本模块提供声明式工作流定义（Pydantic 模型 + JSON 存储），
为未来的可视化编排打基础，同时保持与现有 LangGraph 七节点运行时兼容。

设计原则：
    1. 声明式 + 引用式混合
       - flow JSON 描述拓扑与参数
       - handler_ref / router_fn_ref / *_ref 字段映射到现有 src/graph/nodes.py 函数
       - 避免重写七节点逻辑，又能享受可视化编辑
    2. 默认工作流（DEFAULT_WORKFLOW）镜像当前 LangGraph 实现
       - entry → clarify → router → {faq | rag | human} → reflect → reply → END
       - 节点类型与 src/graph/nodes.py 一一对应
    3. 不替换 LangGraph 运行时
       - 本模块只提供"定义层"，运行时仍由 workflow.create_workflow() 编译
       - 未来可扩展一个 loader 把声明式 DAG 转换为 LangGraph StateGraph

参考：
    - MaxKB apps/application/flow/common.py (Node / Edge / Workflow)
    - MaxKB apps/application/flow/step_node/__init__.py (node_map)
    - MaxKB apps/application/flow/default_workflow_zh.json (默认 DAG 示例)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.mcp_tools.common import (
    TenantIsolatedStore,
    current_utc_time,
    generate_id,
)

logger = logging.getLogger(__name__)


# ====================================================================
# 枚举
# ====================================================================

class WorkflowMode(str, Enum):
    """工作流模式 — 对齐 MaxKB WorkflowMode（简化版）

    - APPLICATION: 主对话工作流（默认）
    - KNOWLEDGE:   知识库管理工作流（如文档抽取/写入）
    - TOOL:        工具型子工作流
    """
    APPLICATION = "application"
    KNOWLEDGE = "knowledge"
    TOOL = "tool"


class NodeType(str, Enum):
    """节点类型 — 对齐 MaxKB 节点注册表，兼容现有 LangGraph 七节点

    命名约定：
        - enterprise-agent 内部使用 `xxx-node` 形式
        - 注释中标出 MaxKB 对应类型
    """
    # === 现有 LangGraph 七节点 ===
    ENTRY_NODE = "entry-node"           # MaxKB: start-node
    CLARIFY_NODE = "clarify-node"       # MaxKB: question-node
    ROUTER_NODE = "router-node"         # MaxKB: intent-node
    FAQ_NODE = "faq-node"               # MaxKB: condition-node + reply-node 组合
    RAG_NODE = "rag-node"               # MaxKB: search-dataset-node + ai-chat-node
    HUMAN_NODE = "human-node"           # MaxKB: form-node（HITL 中断语义对齐）
    REFLECT_NODE = "reflect-node"       # MaxKB: 无直接对应（自研）
    REPLY_NODE = "reply-node"           # MaxKB: reply-node / ai-chat-node

    # === 通用扩展节点（未来用） ===
    CONDITION_NODE = "condition-node"   # MaxKB: condition-node（多分支 IF/ELSE）
    LLM_NODE = "llm-node"               # MaxKB: ai-chat-node
    SEARCH_NODE = "search-node"         # MaxKB: search-dataset-node/search-knowledge-node
    RERANKER_NODE = "reranker-node"     # MaxKB: reranker-node
    TOOL_NODE = "tool-node"             # MaxKB: tool-node / mcp-node
    LOOP_NODE = "loop-node"             # MaxKB: loop-node


class EdgeType(str, Enum):
    """边类型"""
    APP_EDGE = "app-edge"                  # 普通顺序边
    CONDITIONAL_EDGE = "conditional-edge"  # 条件边（由 router_fn 决定）


# 终止节点白名单 — 对齐 MaxKB end_nodes
END_NODES = {
    NodeType.REPLY_NODE,
    NodeType.HUMAN_NODE,
    NodeType.LLM_NODE,
    NodeType.TOOL_NODE,
}


# ====================================================================
# 节点与边定义
# ====================================================================

class NodeData(BaseModel):
    """节点业务参数 — 对齐 MaxKB node_data

    不同节点类型有不同字段，这里定义常用字段子集。
    扩展节点可使用 extra 字段存放自定义参数。
    """
    # 通用
    stepName: str = ""                # 节点显示名
    is_result: bool = False           # 是否产出最终答案
    is_end: bool = False              # 是否终止节点

    # entry-node
    inject_memory: bool = True
    guardrail: Dict[str, Any] = Field(
        default_factory=lambda: {"regex": True, "llm_jailbreak": False, "relevance": False}
    )

    # clarify / router / rag / reply 引用
    llm_ref: str = ""
    memory_ref: str = ""
    retriever_ref: str = ""

    # rag-node
    min_confidence: float = 0.5
    top_n: int = 3
    similarity: float = 0.6
    search_mode: str = "embedding"

    # router-node
    intents: List[str] = Field(default_factory=lambda: ["faq", "rag", "human"])

    # human-node (HITL)
    hitl: bool = False
    interrupt_key: str = "awaiting_human"

    # reply-node
    persist_memory: bool = True
    quality_score: bool = True

    # condition-node（对齐 MaxKB branch 结构）
    branch: List[Dict[str, Any]] = Field(default_factory=list)

    # 扩展字段（任意自定义参数）
    extra: Dict[str, Any] = Field(default_factory=dict)


class WorkflowNode(BaseModel):
    """工作流节点 — 对齐 MaxKB Node + 兼容现有 LangGraph 节点

    映射关系：
        - id 对应 LangGraph 节点名（如 "entry" / "clarify"）
        - type 用 NodeType 枚举值
        - handler_ref 指向 src/graph/nodes.py 中的函数（运行时映射）
        - node_data 存放业务参数
    """
    id: str = Field(..., description="节点 ID（对应 LangGraph 节点名）")
    type: NodeType = Field(..., description="节点类型")
    stepName: str = Field("", description="显示名")
    x: int = 0                          # 画布坐标（可视化用）
    y: int = 0
    handler_ref: str = Field(
        "",
        description="LangGraph 节点函数引用，如 'src.graph.nodes:entry_node'",
    )
    bind_deps: Dict[str, bool] = Field(
        default_factory=dict,
        description="需注入的依赖，如 {'retriever': true, 'memory_manager': true}",
    )
    node_data: NodeData = Field(default_factory=NodeData)
    is_end: bool = False                # 是否终止节点（覆盖 node_data.is_end）


class WorkflowEdge(BaseModel):
    """工作流边 — 对齐 MaxKB Edge + 兼容 LangGraph 条件边

    两种用法：
        1. 普通顺序边：type=APP_EDGE，sourceNodeId → targetNodeId
        2. 条件边：type=CONDITIONAL_EDGE，router_fn_ref 指向条件函数
           targetNodeId 可空，由 router_fn 返回值决定下一节点
    """
    id: str = Field(..., description="边 ID")
    type: EdgeType = Field(EdgeType.APP_EDGE, description="边类型")
    sourceNodeId: str = Field(..., description="源节点 ID")
    targetNodeId: str = Field("", description="目标节点 ID（条件边可空）")

    # 条件边专用
    router_fn_ref: str = Field(
        "",
        description="条件路由函数引用，如 'src.graph.workflow:_decide_route'",
    )
    branch_id: str = Field("", description="分支 ID（condition-node 多分支用）")
    condition: Dict[str, Any] = Field(
        default_factory=dict,
        description="条件表达式，对齐 MaxKB {field, value, compare}",
    )

    # 画布几何（可视化用，可空）
    sourceAnchorId: str = ""
    targetAnchorId: str = ""
    startPoint: Dict[str, float] = Field(default_factory=dict)
    endPoint: Dict[str, float] = Field(default_factory=dict)
    pointsList: List[Dict[str, float]] = Field(default_factory=list)

    properties: Dict[str, Any] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    """工作流定义 — 对齐 MaxKB Workflow / Application.work_flow

    持久化为 JSON，运行时由 loader 编译成 LangGraph StateGraph。
    """
    id: str = Field(..., description="工作流 ID")
    name: str = Field(..., description="工作流名称")
    description: str = ""
    workspace_id: str = "default"
    tenant_id: str = "default"
    workflow_mode: WorkflowMode = WorkflowMode.APPLICATION

    nodes: List[WorkflowNode] = Field(default_factory=list)
    edges: List[WorkflowEdge] = Field(default_factory=list)

    entry_node_id: str = "entry"
    is_publish: bool = False
    publish_time: Optional[str] = None
    version: int = 1
    checkpointer_config: Dict[str, Any] = Field(default_factory=dict)

    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


# ====================================================================
# 默认工作流（镜像当前 LangGraph 七节点实现）
# ====================================================================

DEFAULT_WORKFLOW = WorkflowDefinition(
    id="default-cs-workflow",
    name="默认客服工作流",
    description="七节点 DAG：entry → clarify → router → faq/rag/human → reflect → reply",
    workflow_mode=WorkflowMode.APPLICATION,
    entry_node_id="entry",
    is_publish=True,
    nodes=[
        WorkflowNode(
            id="entry",
            type=NodeType.ENTRY_NODE,
            stepName="入口",
            handler_ref="src.graph.nodes:entry_node",
            bind_deps={"memory_manager": True},
            node_data=NodeData(
                stepName="入口",
                inject_memory=True,
                guardrail={"regex": True, "llm_jailbreak": False, "relevance": False},
            ),
        ),
        WorkflowNode(
            id="clarify",
            type=NodeType.CLARIFY_NODE,
            stepName="意图澄清",
            handler_ref="src.graph.nodes:clarify_node",
            node_data=NodeData(stepName="意图澄清", llm_ref="src.graph.nodes:_get_clarify_llm"),
        ),
        WorkflowNode(
            id="router",
            type=NodeType.ROUTER_NODE,
            stepName="意图路由",
            handler_ref="src.graph.nodes:router_node",
            node_data=NodeData(
                stepName="意图路由",
                llm_ref="src.graph.nodes:_get_intent_llm",
                intents=["faq", "rag", "human"],
            ),
        ),
        WorkflowNode(
            id="faq",
            type=NodeType.FAQ_NODE,
            stepName="FAQ 匹配",
            handler_ref="src.graph.nodes:faq_node",
        ),
        WorkflowNode(
            id="rag",
            type=NodeType.RAG_NODE,
            stepName="RAG 检索",
            handler_ref="src.graph.nodes:rag_node",
            bind_deps={"retriever": True, "memory_manager": True},
            node_data=NodeData(
                stepName="RAG 检索",
                retriever_ref="src.rag.retriever:HybridRetriever",
                memory_ref="src.memory.manager:MemoryManager",
                min_confidence=0.5,
                top_n=3,
                similarity=0.6,
                search_mode="embedding",
            ),
        ),
        WorkflowNode(
            id="human",
            type=NodeType.HUMAN_NODE,
            stepName="转人工",
            handler_ref="src.graph.nodes:human_node",
            is_end=True,
            node_data=NodeData(
                stepName="转人工",
                hitl=True,
                interrupt_key="awaiting_human",
            ),
        ),
        WorkflowNode(
            id="reflect",
            type=NodeType.REFLECT_NODE,
            stepName="反思",
            handler_ref="src.graph.nodes:reflect_node",
        ),
        WorkflowNode(
            id="reply",
            type=NodeType.REPLY_NODE,
            stepName="回复",
            handler_ref="src.graph.nodes:reply_node",
            bind_deps={"memory_manager": True},
            is_end=True,
            node_data=NodeData(
                stepName="回复",
                memory_ref="src.memory.manager:MemoryManager",
                persist_memory=True,
                quality_score=True,
                is_result=True,
                is_end=True,
            ),
        ),
    ],
    edges=[
        # entry → clarify
        WorkflowEdge(
            id="e-entry-clarify",
            type=EdgeType.APP_EDGE,
            sourceNodeId="entry",
            targetNodeId="clarify",
        ),
        # clarify → (条件路由 _decide_clarity_route) → router / reply
        # 每个分支一条边，router_fn 返回值 = branch_id = targetNodeId
        WorkflowEdge(
            id="e-clarify-router",
            type=EdgeType.CONDITIONAL_EDGE,
            sourceNodeId="clarify",
            targetNodeId="router",
            branch_id="router",
            router_fn_ref="src.graph.workflow:_decide_clarity_route",
        ),
        WorkflowEdge(
            id="e-clarify-reply",
            type=EdgeType.CONDITIONAL_EDGE,
            sourceNodeId="clarify",
            targetNodeId="reply",
            branch_id="reply",
            router_fn_ref="src.graph.workflow:_decide_clarity_route",
        ),
        # router → (条件路由 _decide_route) → faq / rag / human
        WorkflowEdge(
            id="e-router-faq",
            type=EdgeType.CONDITIONAL_EDGE,
            sourceNodeId="router",
            targetNodeId="faq",
            branch_id="faq",
            router_fn_ref="src.graph.workflow:_decide_route",
        ),
        WorkflowEdge(
            id="e-router-rag",
            type=EdgeType.CONDITIONAL_EDGE,
            sourceNodeId="router",
            targetNodeId="rag",
            branch_id="rag",
            router_fn_ref="src.graph.workflow:_decide_route",
        ),
        WorkflowEdge(
            id="e-router-human",
            type=EdgeType.CONDITIONAL_EDGE,
            sourceNodeId="router",
            targetNodeId="human",
            branch_id="human",
            router_fn_ref="src.graph.workflow:_decide_route",
        ),
        # faq → (条件路由 _decide_after_faq) → reply / rag
        WorkflowEdge(
            id="e-faq-reply",
            type=EdgeType.CONDITIONAL_EDGE,
            sourceNodeId="faq",
            targetNodeId="reply",
            branch_id="reply",
            router_fn_ref="src.graph.workflow:_decide_after_faq",
        ),
        WorkflowEdge(
            id="e-faq-rag",
            type=EdgeType.CONDITIONAL_EDGE,
            sourceNodeId="faq",
            targetNodeId="rag",
            branch_id="rag",
            router_fn_ref="src.graph.workflow:_decide_after_faq",
        ),
        # rag → reflect
        WorkflowEdge(
            id="e-rag-reflect",
            type=EdgeType.APP_EDGE,
            sourceNodeId="rag",
            targetNodeId="reflect",
        ),
        # reflect → reply
        WorkflowEdge(
            id="e-reflect-reply",
            type=EdgeType.APP_EDGE,
            sourceNodeId="reflect",
            targetNodeId="reply",
        ),
        # human → reply
        WorkflowEdge(
            id="e-human-reply",
            type=EdgeType.APP_EDGE,
            sourceNodeId="human",
            targetNodeId="reply",
        ),
    ],
)


# ====================================================================
# 校验
# ====================================================================

class WorkflowValidationError(Exception):
    """工作流校验异常"""


def validate_workflow(wf: WorkflowDefinition) -> List[str]:
    """校验工作流 DAG 定义

    返回错误信息列表，空列表表示校验通过。
    校验项：
        1. 节点 ID 唯一
        2. 入口节点存在
        3. 边的 source/target 节点存在
        4. 至少有一个终止节点
        5. 条件边必须指定 router_fn_ref
        6. 普通边必须指定 targetNodeId
    """
    errors: List[str] = []

    # 1. 节点 ID 唯一
    node_ids = [n.id for n in wf.nodes]
    if len(node_ids) != len(set(node_ids)):
        dupes = [nid for nid in node_ids if node_ids.count(nid) > 1]
        errors.append(f"节点 ID 重复: {set(dupes)}")

    node_id_set = set(node_ids)

    # 2. 入口节点存在
    if wf.entry_node_id not in node_id_set:
        errors.append(f"入口节点不存在: {wf.entry_node_id}")

    # 3. 边的 source/target 节点存在
    for edge in wf.edges:
        if edge.sourceNodeId not in node_id_set:
            errors.append(f"边 {edge.id} 的 sourceNodeId 不存在: {edge.sourceNodeId}")
        if edge.type == EdgeType.APP_EDGE and edge.targetNodeId not in node_id_set:
            errors.append(f"边 {edge.id} 的 targetNodeId 不存在: {edge.targetNodeId}")

    # 4. 至少有一个终止节点
    end_nodes = [n for n in wf.nodes if n.is_end or n.node_data.is_end or n.type in END_NODES]
    if not end_nodes:
        errors.append("工作流必须至少有一个终止节点")

    # 5. 条件边必须指定 router_fn_ref
    for edge in wf.edges:
        if edge.type == EdgeType.CONDITIONAL_EDGE and not edge.router_fn_ref:
            errors.append(f"条件边 {edge.id} 必须指定 router_fn_ref")

    # 6. 普通边必须指定 targetNodeId
    for edge in wf.edges:
        if edge.type == EdgeType.APP_EDGE and not edge.targetNodeId:
            errors.append(f"普通边 {edge.id} 必须指定 targetNodeId")

    return errors


# ====================================================================
# 持久化存储
# ====================================================================

_workflow_store: TenantIsolatedStore[WorkflowDefinition] = TenantIsolatedStore(
    max_items_per_tenant=100, name="workflow"
)


def _utc_iso() -> str:
    return current_utc_time().isoformat()


def get_default_workflow() -> WorkflowDefinition:
    """获取默认工作流（七节点 DAG）"""
    return DEFAULT_WORKFLOW.model_copy(deep=True)


def save_workflow(wf: WorkflowDefinition, tenant_id: str = "default") -> WorkflowDefinition:
    """保存工作流定义（带校验）

    校验失败抛出 WorkflowValidationError。
    """
    errors = validate_workflow(wf)
    if errors:
        raise WorkflowValidationError("; ".join(errors))

    if not wf.created_at:
        wf.created_at = _utc_iso()
    wf.updated_at = _utc_iso()
    _workflow_store.save(tenant_id, wf.id, wf)
    logger.info("Workflow saved: id=%s name=%s tenant=%s", wf.id, wf.name, tenant_id)
    return wf


def get_workflow(wf_id: str, tenant_id: str = "default") -> Optional[WorkflowDefinition]:
    """获取工作流定义"""
    return _workflow_store.get(tenant_id, wf_id)


def list_workflows(tenant_id: str = "default", limit: int = 100) -> List[WorkflowDefinition]:
    """列出工作流"""
    return _workflow_store.list(tenant_id, limit)


def delete_workflow(wf_id: str, tenant_id: str = "default") -> bool:
    """删除工作流"""
    return _workflow_store.delete(tenant_id, wf_id)


def publish_workflow(wf_id: str, tenant_id: str = "default") -> Optional[WorkflowDefinition]:
    """发布工作流（标记 is_publish=True 并记录时间）"""
    wf = _workflow_store.get(tenant_id, wf_id)
    if wf is None:
        return None
    wf.is_publish = True
    wf.publish_time = _utc_iso()
    wf.version += 1
    wf.updated_at = _utc_iso()
    _workflow_store.save(tenant_id, wf_id, wf)
    logger.info("Workflow published: id=%s version=%d", wf_id, wf.version)
    return wf


def init_default_workflow(tenant_id: str = "default") -> WorkflowDefinition:
    """初始化默认工作流（若不存在则创建）

    应用启动时调用，确保系统至少有一个可用工作流。
    """
    existing = _workflow_store.get(tenant_id, DEFAULT_WORKFLOW.id)
    if existing is not None:
        return existing
    wf = DEFAULT_WORKFLOW.model_copy(deep=True)
    wf.tenant_id = tenant_id
    wf.workspace_id = tenant_id
    wf.created_at = _utc_iso()
    wf.updated_at = _utc_iso()
    _workflow_store.save(tenant_id, wf.id, wf)
    logger.info("Default workflow initialized: id=%s tenant=%s", wf.id, tenant_id)
    return wf


# ====================================================================
# 工作流转字典（用于 API 响应）
# ====================================================================

def workflow_to_dict(wf: WorkflowDefinition) -> Dict[str, Any]:
    """工作流转字典（用于 API 响应 / 持久化 JSON）"""
    return {
        "id": wf.id,
        "name": wf.name,
        "description": wf.description,
        "workspace_id": wf.workspace_id,
        "tenant_id": wf.tenant_id,
        "workflow_mode": wf.workflow_mode.value,
        "entry_node_id": wf.entry_node_id,
        "is_publish": wf.is_publish,
        "publish_time": wf.publish_time,
        "version": wf.version,
        "nodes": [n.model_dump(mode="json") for n in wf.nodes],
        "edges": [e.model_dump(mode="json") for e in wf.edges],
        "checkpointer_config": wf.checkpointer_config,
        "created_by": wf.created_by,
        "created_at": wf.created_at,
        "updated_at": wf.updated_at,
    }
