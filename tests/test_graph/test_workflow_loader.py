"""工作流加载器单元测试

覆盖：
- _resolve_ref: 引用解析（合法/非法格式/模块不存在/函数不存在/非可调用）
- _bind_dependencies: 依赖绑定（无依赖/retriever/memory_manager/混合）
- _get_direct_edges: 普通边分组
- _group_conditional_edges: 条件边分组（含 router_fn 解析失败容错）
- create_workflow_from_definition: 完整编译（默认工作流/校验失败/依赖绑定）
- create_workflow_from_default / create_workflow_from_id
"""
import pytest

from src.graph.workflow_dag import (
    DEFAULT_WORKFLOW,
    EdgeType,
    NodeData,
    NodeType,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowValidationError,
    save_workflow,
)
from src.graph.workflow_loader import (
    _bind_dependencies,
    _get_direct_edges,
    _group_conditional_edges,
    _resolve_ref,
    create_workflow_from_default,
    create_workflow_from_definition,
    create_workflow_from_id,
)


# ============================================================
# _resolve_ref
# ============================================================

class TestResolveRef:
    def test_resolves_valid_function_ref(self):
        fn = _resolve_ref("src.graph.workflow:_decide_route")
        assert callable(fn)

    def test_resolves_entry_node(self):
        fn = _resolve_ref("src.graph.nodes:entry_node")
        assert callable(fn)

    def test_invalid_format_no_colon_raises(self):
        with pytest.raises(WorkflowValidationError) as exc:
            _resolve_ref("src.graph.nodes.entry_node")
        assert "冒号" in str(exc.value) or "格式" in str(exc.value)

    def test_empty_ref_raises(self):
        with pytest.raises(WorkflowValidationError):
            _resolve_ref("")

    def test_nonexistent_module_raises(self):
        with pytest.raises(WorkflowValidationError) as exc:
            _resolve_ref("src.nonexistent.module:func")
        assert "无法导入" in str(exc.value) or "模块" in str(exc.value)

    def test_nonexistent_function_raises(self):
        with pytest.raises(WorkflowValidationError) as exc:
            _resolve_ref("src.graph.nodes:nonexistent_function")
        assert "找不到" in str(exc.value)

    def test_non_callable_attribute_raises(self):
        # 模块级变量不是可调用对象
        with pytest.raises(WorkflowValidationError) as exc:
            _resolve_ref("src.graph.nodes:__name__")
        assert "可调用" in str(exc.value) or "callable" in str(exc.value).lower()


# ============================================================
# _bind_dependencies
# ============================================================

def _dummy_handler(state, retriever=None, memory_manager=None):
    return state


class TestBindDependencies:
    def test_no_deps_returns_handler_unchanged(self):
        bound = _bind_dependencies(_dummy_handler, {})
        assert bound is _dummy_handler

    def test_empty_deps_returns_handler_unchanged(self):
        bound = _bind_dependencies(_dummy_handler, {"retriever": False, "memory_manager": False})
        assert bound is _dummy_handler

    def test_bind_retriever_only(self):
        retriever = object()
        bound = _bind_dependencies(_dummy_handler, {"retriever": True}, retriever=retriever)
        assert bound is not _dummy_handler
        # partial 应注入 retriever
        import inspect
        sig = inspect.signature(bound)
        assert "retriever" not in sig.parameters or sig.parameters["retriever"].default is not inspect.Parameter.empty

    def test_bind_memory_manager_only(self):
        mm = object()
        bound = _bind_dependencies(_dummy_handler, {"memory_manager": True}, memory_manager=mm)
        assert bound is not _dummy_handler

    def test_bind_both_deps(self):
        retriever = object()
        mm = object()
        bound = _bind_dependencies(
            _dummy_handler,
            {"retriever": True, "memory_manager": True},
            retriever=retriever,
            memory_manager=mm,
        )
        assert bound is not _dummy_handler

    def test_bind_dep_requested_but_dependency_none_returns_handler(self):
        """请求绑定但依赖实例为 None 时返回原 handler"""
        bound = _bind_dependencies(_dummy_handler, {"retriever": True}, retriever=None)
        assert bound is _dummy_handler


# ============================================================
# _get_direct_edges
# ============================================================

class TestGetDirectEdges:
    def test_groups_app_edges_by_source(self):
        wf = WorkflowDefinition(
            id="test",
            name="test",
            entry_node_id="a",
            nodes=[
                WorkflowNode(id="a", type=NodeType.ENTRY_NODE),
                WorkflowNode(id="b", type=NodeType.REPLY_NODE, is_end=True),
                WorkflowNode(id="c", type=NodeType.REPLY_NODE, is_end=True),
            ],
            edges=[
                WorkflowEdge(id="e1", type=EdgeType.APP_EDGE, sourceNodeId="a", targetNodeId="b"),
                WorkflowEdge(id="e2", type=EdgeType.APP_EDGE, sourceNodeId="a", targetNodeId="c"),
                WorkflowEdge(id="e3", type=EdgeType.APP_EDGE, sourceNodeId="b", targetNodeId="c"),
            ],
        )
        direct = _get_direct_edges(wf)
        assert direct["a"] == ["b", "c"]
        assert direct["b"] == ["c"]

    def test_excludes_conditional_edges(self):
        wf = WorkflowDefinition(
            id="test",
            name="test",
            entry_node_id="a",
            nodes=[
                WorkflowNode(id="a", type=NodeType.ENTRY_NODE),
                WorkflowNode(id="b", type=NodeType.REPLY_NODE, is_end=True),
            ],
            edges=[
                WorkflowEdge(
                    id="e1",
                    type=EdgeType.CONDITIONAL_EDGE,
                    sourceNodeId="a",
                    targetNodeId="b",
                    router_fn_ref="src.graph.workflow:_decide_route",
                ),
            ],
        )
        direct = _get_direct_edges(wf)
        assert "a" not in direct or direct.get("a", []) == []

    def test_empty_workflow_returns_empty(self):
        wf = WorkflowDefinition(id="test", name="test", entry_node_id="a")
        direct = _get_direct_edges(wf)
        assert len(direct) == 0


# ============================================================
# _group_conditional_edges
# ============================================================

class TestGroupConditionalEdges:
    def test_groups_by_source_and_router(self):
        wf = DEFAULT_WORKFLOW.model_copy(deep=True)
        grouped = _group_conditional_edges(wf)
        # 默认工作流有 clarify / router / faq 三个条件边源
        assert "clarify" in grouped
        assert "router" in grouped
        assert "faq" in grouped

    def test_router_has_three_branches(self):
        wf = DEFAULT_WORKFLOW.model_copy(deep=True)
        grouped = _group_conditional_edges(wf)
        router_groups = grouped["router"]
        assert len(router_groups) == 1
        branches = router_groups[0]["branches"]
        assert set(branches.keys()) == {"faq", "rag", "human"}
        assert branches["faq"] == "faq"
        assert branches["rag"] == "rag"
        assert branches["human"] == "human"

    def test_router_fn_is_callable(self):
        wf = DEFAULT_WORKFLOW.model_copy(deep=True)
        grouped = _group_conditional_edges(wf)
        assert callable(grouped["router"][0]["router_fn"])

    def test_conditional_edge_without_router_ref_skipped(self):
        """缺少 router_fn_ref 的条件边应被跳过"""
        wf = WorkflowDefinition(
            id="test",
            name="test",
            entry_node_id="a",
            nodes=[
                WorkflowNode(id="a", type=NodeType.ENTRY_NODE),
                WorkflowNode(id="b", type=NodeType.REPLY_NODE, is_end=True),
            ],
            edges=[
                WorkflowEdge(
                    id="e1",
                    type=EdgeType.CONDITIONAL_EDGE,
                    sourceNodeId="a",
                    targetNodeId="b",
                    router_fn_ref="",  # 缺失
                ),
            ],
        )
        grouped = _group_conditional_edges(wf)
        # 应为空（跳过了无效边）
        assert len(grouped) == 0 or "a" not in grouped

    def test_invalid_router_ref_skipped(self):
        """router_fn_ref 解析失败时应跳过该组"""
        wf = WorkflowDefinition(
            id="test",
            name="test",
            entry_node_id="a",
            nodes=[
                WorkflowNode(id="a", type=NodeType.ENTRY_NODE),
                WorkflowNode(id="b", type=NodeType.REPLY_NODE, is_end=True),
            ],
            edges=[
                WorkflowEdge(
                    id="e1",
                    type=EdgeType.CONDITIONAL_EDGE,
                    sourceNodeId="a",
                    targetNodeId="b",
                    router_fn_ref="src.nonexistent:bad_fn",
                ),
            ],
        )
        grouped = _group_conditional_edges(wf)
        # 解析失败应跳过，不抛异常
        assert "a" not in grouped or len(grouped["a"]) == 0


# ============================================================
# create_workflow_from_definition
# ============================================================

class TestCreateWorkflowFromDefinition:
    def test_compiles_default_workflow(self):
        """默认工作流应能成功编译为 LangGraph Runnable"""
        wf = DEFAULT_WORKFLOW.model_copy(deep=True)
        app = create_workflow_from_definition(wf)
        assert app is not None
        # 编译后的对象应有 invoke 方法
        assert hasattr(app, "invoke")

    def test_compiles_with_retriever_and_memory(self):
        wf = DEFAULT_WORKFLOW.model_copy(deep=True)
        retriever = object()
        mm = object()
        app = create_workflow_from_definition(
            wf, retriever=retriever, memory_manager=mm,
        )
        assert app is not None

    def test_invalid_workflow_raises(self):
        wf = WorkflowDefinition(
            id="bad",
            name="非法",
            entry_node_id="nonexistent",
            nodes=[
                WorkflowNode(id="a", type=NodeType.ENTRY_NODE, handler_ref="src.graph.nodes:entry_node"),
                WorkflowNode(id="b", type=NodeType.REPLY_NODE, handler_ref="src.graph.nodes:reply_node", is_end=True),
            ],
            edges=[
                WorkflowEdge(id="e1", sourceNodeId="a", targetNodeId="b"),
            ],
        )
        with pytest.raises(WorkflowValidationError) as exc:
            create_workflow_from_definition(wf)
        assert "校验失败" in str(exc.value)

    def test_node_with_invalid_handler_raises(self):
        wf = WorkflowDefinition(
            id="bad-handler",
            name="handler 非法",
            entry_node_id="a",
            nodes=[
                WorkflowNode(
                    id="a",
                    type=NodeType.ENTRY_NODE,
                    handler_ref="src.nonexistent:bad_fn",
                ),
                WorkflowNode(id="b", type=NodeType.REPLY_NODE, handler_ref="src.graph.nodes:reply_node", is_end=True),
            ],
            edges=[
                WorkflowEdge(id="e1", sourceNodeId="a", targetNodeId="b"),
            ],
        )
        with pytest.raises(WorkflowValidationError) as exc:
            create_workflow_from_definition(wf)
        assert "handler 解析失败" in str(exc.value)

    def test_node_without_handler_ref_skipped(self):
        """缺少 handler_ref 的节点应被跳过（不抛异常）"""
        wf = WorkflowDefinition(
            id="skip-node",
            name="跳过节点",
            entry_node_id="a",
            nodes=[
                WorkflowNode(id="a", type=NodeType.ENTRY_NODE, handler_ref="src.graph.nodes:entry_node"),
                # 这个节点无 handler_ref，应跳过
                WorkflowNode(id="skip", type=NodeType.LLM_NODE, handler_ref=""),
                WorkflowNode(id="b", type=NodeType.REPLY_NODE, handler_ref="src.graph.nodes:reply_node", is_end=True),
            ],
            edges=[
                WorkflowEdge(id="e1", sourceNodeId="a", targetNodeId="b"),
            ],
        )
        app = create_workflow_from_definition(wf)
        assert app is not None

    def test_end_node_auto_connected_to_end(self):
        """终止节点无出边时应自动连接到 END"""
        wf = WorkflowDefinition(
            id="auto-end",
            name="自动连 END",
            entry_node_id="a",
            nodes=[
                WorkflowNode(id="a", type=NodeType.ENTRY_NODE, handler_ref="src.graph.nodes:entry_node"),
                WorkflowNode(id="b", type=NodeType.REPLY_NODE, handler_ref="src.graph.nodes:reply_node", is_end=True),
            ],
            edges=[
                WorkflowEdge(id="e1", sourceNodeId="a", targetNodeId="b"),
                # b 没有出边，应自动连 END
            ],
        )
        app = create_workflow_from_definition(wf)
        assert app is not None

    def test_custom_checkpointer_used(self):
        """传入自定义 checkpointer 应被使用"""
        from langgraph.checkpoint.memory import MemorySaver
        custom_cp = MemorySaver()
        wf = DEFAULT_WORKFLOW.model_copy(deep=True)
        app = create_workflow_from_definition(wf, checkpointer=custom_cp)
        assert app is not None


# ============================================================
# create_workflow_from_default
# ============================================================

class TestCreateWorkflowFromDefault:
    def test_returns_compiled_workflow(self):
        app = create_workflow_from_default()
        assert app is not None
        assert hasattr(app, "invoke")

    def test_with_dependencies(self):
        retriever = object()
        mm = object()
        app = create_workflow_from_default(retriever=retriever, memory_manager=mm)
        assert app is not None


# ============================================================
# create_workflow_from_id
# ============================================================

class TestCreateWorkflowFromId:
    def test_loads_default_workflow_by_id(self):
        """默认工作流 ID 即使未保存也能从 DEFAULT_WORKFLOW 加载"""
        app = create_workflow_from_id(DEFAULT_WORKFLOW.id)
        assert app is not None
        assert hasattr(app, "invoke")

    def test_loads_saved_workflow(self):
        """加载已保存的自定义工作流"""
        wf = DEFAULT_WORKFLOW.model_copy(deep=True)
        wf.id = "custom-test-wf"
        wf.name = "自定义测试工作流"
        save_workflow(wf, tenant_id="default")

        app = create_workflow_from_id("custom-test-wf", tenant_id="default")
        assert app is not None

    def test_nonexistent_workflow_raises(self):
        with pytest.raises(WorkflowValidationError) as exc:
            create_workflow_from_id("nonexistent-wf-id")
        assert "不存在" in str(exc.value)

    def test_unpublished_workflow_compiles_with_warning(self):
        """未发布的工作流应仍能编译（仅警告）"""
        wf = DEFAULT_WORKFLOW.model_copy(deep=True)
        wf.id = "unpublished-wf"
        wf.is_publish = False
        save_workflow(wf, tenant_id="default")

        app = create_workflow_from_id("unpublished-wf", tenant_id="default")
        assert app is not None
