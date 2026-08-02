"""工作流加载器 — 声明式 DAG → LangGraph StateGraph 运行时

将 WorkflowDefinition（JSON 声明式定义）编译为 LangGraph StateGraph，
使可视化编排的工作流可以实际运行。

核心流程：
    1. 解析 handler_ref / router_fn_ref 字符串 → Python 函数（动态导入）
    2. 按 bind_deps 绑定依赖（retriever / memory_manager）via partial
    3. 添加节点（add_node）
    4. 分组边：
       - 普通边（app-edge）→ add_edge(source, target)
       - 条件边（conditional-edge）→ 按 (source, router_fn_ref) 分组，
         组装 {branch_id: targetNodeId} 映射 → add_conditional_edges
    5. 终止节点（is_end）无出边时 → add_edge(node, END)
    6. 编译（compile）返回可运行 Runnable

与现有 create_workflow() 的关系：
    - create_workflow_from_definition(DEFAULT_WORKFLOW) 等价于 create_workflow()
    - 现有 create_workflow 保留不动，作为硬编码 fallback
    - 新 loader 优先用于自定义工作流（通过 API 创建的）
"""
from __future__ import annotations

import importlib
import logging
from collections import defaultdict
from functools import partial
from typing import Any, Callable, Dict, Optional, Tuple

from langgraph.graph import END, StateGraph

from src.graph.state import AgentState
from src.graph.workflow_dag import (
    DEFAULT_WORKFLOW,
    EdgeType,
    WorkflowDefinition,
    WorkflowValidationError,
    validate_workflow,
)

logger = logging.getLogger(__name__)


# ====================================================================
# 引用解析
# ====================================================================

def _resolve_ref(ref: str) -> Callable:
    """解析 'module.path:function_name' 字符串为可调用对象

    Args:
        ref: 如 'src.graph.nodes:entry_node'

    Returns:
        可调用对象

    Raises:
        WorkflowValidationError: 解析失败
    """
    if not ref or ":" not in ref:
        raise WorkflowValidationError(f"无效的引用格式（缺少冒号）: {ref!r}")

    module_path, func_name = ref.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise WorkflowValidationError(f"无法导入模块 {module_path!r}: {e}")

    fn = getattr(module, func_name, None)
    if fn is None:
        raise WorkflowValidationError(f"模块 {module_path!r} 中找不到 {func_name!r}")
    if not callable(fn):
        raise WorkflowValidationError(f"{ref!r} 不是可调用对象")

    return fn


# ====================================================================
# 依赖绑定
# ====================================================================

def _bind_dependencies(
    handler: Callable,
    bind_deps: Dict[str, bool],
    retriever: Optional[Any] = None,
    memory_manager: Optional[Any] = None,
) -> Callable:
    """根据 bind_deps 配置，用 partial 绑定依赖到 handler

    对齐现有 create_workflow 中的 partial(rag_node, retriever=..., memory_manager=...) 逻辑。
    """
    kwargs: Dict[str, Any] = {}
    if bind_deps.get("retriever") and retriever is not None:
        kwargs["retriever"] = retriever
    if bind_deps.get("memory_manager") and memory_manager is not None:
        kwargs["memory_manager"] = memory_manager

    if not kwargs:
        return handler
    return partial(handler, **kwargs)


# ====================================================================
# 边分组
# ====================================================================

def _group_conditional_edges(
    wf: WorkflowDefinition,
) -> Dict[str, list]:
    """按 sourceNodeId 分组条件边，同一 source 下再按 router_fn_ref 分组

    返回结构：
        {
            source_node_id: [
                {
                    "router_fn_ref": "...",
                    "router_fn": <callable>,
                    "branches": {branch_id: target_node_id, ...},
                },
                ...
            ]
        }
    """
    # source_id -> router_fn_ref -> {"fn": ..., "branches": {...}}
    grouped: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))

    for edge in wf.edges:
        if edge.type != EdgeType.CONDITIONAL_EDGE:
            continue

        source = edge.sourceNodeId
        ref = edge.router_fn_ref
        if not ref:
            logger.warning("条件边 %s 缺少 router_fn_ref，跳过", edge.id)
            continue

        if "fn" not in grouped[source][ref]:
            try:
                grouped[source][ref]["fn"] = _resolve_ref(ref)
            except WorkflowValidationError as e:
                logger.warning("解析 router_fn_ref 失败: %s", e)
                continue
            grouped[source][ref]["branches"] = {}

        # 分支映射：router_fn 返回值 → 目标节点
        branch_key = edge.branch_id or edge.targetNodeId
        target = edge.targetNodeId or edge.branch_id
        if branch_key and target:
            grouped[source][ref]["branches"][branch_key] = target

    # 展平为 list 结构（跳过 fn 解析失败的条目）
    result: Dict[str, list] = defaultdict(list)
    for source, refs in grouped.items():
        for ref, info in refs.items():
            if "fn" not in info:
                # router_fn 解析失败，跳过该条目
                continue
            result[source].append({
                "router_fn_ref": ref,
                "router_fn": info["fn"],
                "branches": info.get("branches", {}),
            })

    return result


def _get_direct_edges(wf: WorkflowDefinition) -> Dict[str, list]:
    """获取所有普通边，按 sourceNodeId 分组

    返回：{source_node_id: [target_node_id, ...]}
    """
    direct: Dict[str, list] = defaultdict(list)
    for edge in wf.edges:
        if edge.type == EdgeType.APP_EDGE and edge.targetNodeId:
            direct[edge.sourceNodeId].append(edge.targetNodeId)
    return direct


# ====================================================================
# 主编译函数
# ====================================================================

def create_workflow_from_definition(
    wf: WorkflowDefinition,
    retriever: Optional[Any] = None,
    memory_manager: Optional[Any] = None,
    checkpointer: Optional[Any] = None,
):
    """从声明式工作流定义编译 LangGraph StateGraph

    Args:
        wf: WorkflowDefinition（已校验）
        retriever: HybridRetriever 实例（rag-node 用）
        memory_manager: MemoryManager 实例（entry/rag/reply-node 用）
        checkpointer: LangGraph checkpointer（HITL 必需），None 则用 MemorySaver

    Returns:
        Compiled StateGraph (Runnable)

    Raises:
        WorkflowValidationError: 定义不合法或引用解析失败
    """
    # 1. 校验
    errors = validate_workflow(wf)
    if errors:
        raise WorkflowValidationError(f"工作流校验失败: {'; '.join(errors)}")

    # 2. 创建图
    workflow = StateGraph(AgentState)

    # 3. 添加节点（解析 handler_ref + 绑定依赖）
    for node in wf.nodes:
        if not node.handler_ref:
            logger.warning("节点 %s 缺少 handler_ref，跳过", node.id)
            continue
        try:
            handler = _resolve_ref(node.handler_ref)
        except WorkflowValidationError as e:
            raise WorkflowValidationError(f"节点 {node.id} 的 handler 解析失败: {e}")

        bound = _bind_dependencies(handler, node.bind_deps, retriever, memory_manager)
        workflow.add_node(node.id, bound)
        logger.debug("节点已添加: %s (type=%s)", node.id, node.type.value)

    # 4. 设置入口点
    workflow.set_entry_point(wf.entry_node_id)

    # 5. 分组边
    direct_edges = _get_direct_edges(wf)
    conditional_groups = _group_conditional_edges(wf)

    # 跟踪每个节点的出边数量（用于判断是否需要自动连 END）
    outgoing_counts: Dict[str, int] = defaultdict(int)

    # 6. 添加普通边
    for source, targets in direct_edges.items():
        for target in targets:
            workflow.add_edge(source, target)
            outgoing_counts[source] += 1

    # 7. 添加条件边
    for source, groups in conditional_groups.items():
        for group in groups:
            router_fn = group["router_fn"]
            branches = group["branches"]
            if not branches:
                logger.warning(
                    "节点 %s 的条件路由 %s 没有分支映射，跳过",
                    source, group["router_fn_ref"],
                )
                continue
            workflow.add_conditional_edges(source, router_fn, branches)
            outgoing_counts[source] += len(branches)

    # 8. 终止节点无出边时自动连 END
    end_node_ids = {
        n.id for n in wf.nodes
        if n.is_end or n.node_data.is_end
    }
    for node in wf.nodes:
        if node.id in end_node_ids and outgoing_counts[node.id] == 0:
            workflow.add_edge(node.id, END)
            logger.debug("终止节点自动连 END: %s", node.id)

    # 9. 编译
    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()

    app = workflow.compile(checkpointer=checkpointer)
    logger.info(
        "Workflow compiled from definition: id=%s nodes=%d edges=%d",
        wf.id, len(wf.nodes), len(wf.edges),
    )
    return app


# ====================================================================
# 便捷函数
# ====================================================================

def create_workflow_from_default(
    retriever: Optional[Any] = None,
    memory_manager: Optional[Any] = None,
    checkpointer: Optional[Any] = None,
):
    """从默认工作流定义编译 StateGraph

    等价于现有的 create_workflow()，但从声明式定义加载。
    用于验证 loader 正确性。
    """
    wf = DEFAULT_WORKFLOW.model_copy(deep=True)
    return create_workflow_from_definition(
        wf,
        retriever=retriever,
        memory_manager=memory_manager,
        checkpointer=checkpointer,
    )


def create_workflow_from_id(
    wf_id: str,
    tenant_id: str = "default",
    retriever: Optional[Any] = None,
    memory_manager: Optional[Any] = None,
    checkpointer: Optional[Any] = None,
):
    """从已保存的工作流 ID 编译 StateGraph

    优先使用已发布版本；若未发布则用最新版本。

    Raises:
        WorkflowValidationError: 工作流不存在或校验失败
    """
    from src.graph.workflow_dag import get_workflow

    wf = get_workflow(wf_id, tenant_id)
    if wf is None:
        if wf_id == DEFAULT_WORKFLOW.id:
            wf = DEFAULT_WORKFLOW.model_copy(deep=True)
        else:
            raise WorkflowValidationError(f"工作流不存在: {wf_id}")

    if not wf.is_publish:
        logger.warning("工作流 %s 未发布，使用最新版本编译", wf_id)

    return create_workflow_from_definition(
        wf,
        retriever=retriever,
        memory_manager=memory_manager,
        checkpointer=checkpointer,
    )
