"""工作流 DAG 声明式定义单元测试

覆盖：
- 枚举（WorkflowMode / NodeType / EdgeType / END_NODES）
- 模型（NodeData / WorkflowNode / WorkflowEdge / WorkflowDefinition）
- 默认工作流（DEFAULT_WORKFLOW 结构完整性）
- validate_workflow 校验规则
- 持久化（save / get / list / delete / publish / init_default）
- workflow_to_dict 序列化
"""
import pytest

from src.graph.workflow_dag import (
    DEFAULT_WORKFLOW,
    END_NODES,
    EdgeType,
    NodeData,
    NodeType,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowMode,
    WorkflowValidationError,
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


# ============================================================
# 枚举
# ============================================================

class TestEnums:
    def test_workflow_mode_values(self):
        assert WorkflowMode.APPLICATION == "application"
        assert WorkflowMode.KNOWLEDGE == "knowledge"
        assert WorkflowMode.TOOL == "tool"

    def test_node_type_core_nodes(self):
        assert NodeType.ENTRY_NODE == "entry-node"
        assert NodeType.CLARIFY_NODE == "clarify-node"
        assert NodeType.ROUTER_NODE == "router-node"
        assert NodeType.FAQ_NODE == "faq-node"
        assert NodeType.RAG_NODE == "rag-node"
        assert NodeType.HUMAN_NODE == "human-node"
        assert NodeType.REFLECT_NODE == "reflect-node"
        assert NodeType.REPLY_NODE == "reply-node"

    def test_edge_type_values(self):
        assert EdgeType.APP_EDGE == "app-edge"
        assert EdgeType.CONDITIONAL_EDGE == "conditional-edge"

    def test_end_nodes_contains_reply_and_human(self):
        assert NodeType.REPLY_NODE in END_NODES
        assert NodeType.HUMAN_NODE in END_NODES
        assert NodeType.LLM_NODE in END_NODES
        assert NodeType.TOOL_NODE in END_NODES


# ============================================================
# 模型
# ============================================================

class TestNodeData:
    def test_default_node_data(self):
        nd = NodeData()
        assert nd.stepName == ""
        assert nd.is_result is False
        assert nd.is_end is False
        assert nd.inject_memory is True
        assert nd.min_confidence == 0.5
        assert nd.top_n == 3
        assert nd.similarity == 0.6
        assert nd.search_mode == "embedding"
        assert nd.intents == ["faq", "rag", "human"]
        assert nd.hitl is False
        assert nd.persist_memory is True
        assert nd.quality_score is True

    def test_guardrail_default(self):
        nd = NodeData()
        assert nd.guardrail == {"regex": True, "llm_jailbreak": False, "relevance": False}


class TestWorkflowNode:
    def test_minimal_node(self):
        n = WorkflowNode(id="entry", type=NodeType.ENTRY_NODE)
        assert n.id == "entry"
        assert n.type == NodeType.ENTRY_NODE
        assert n.handler_ref == ""
        assert n.bind_deps == {}
        assert n.is_end is False
        assert isinstance(n.node_data, NodeData)

    def test_node_with_full_config(self):
        n = WorkflowNode(
            id="rag",
            type=NodeType.RAG_NODE,
            stepName="RAG",
            handler_ref="src.graph.nodes:rag_node",
            bind_deps={"retriever": True, "memory_manager": True},
            is_end=False,
            node_data=NodeData(stepName="RAG", min_confidence=0.7, top_n=5),
        )
        assert n.stepName == "RAG"
        assert n.handler_ref == "src.graph.nodes:rag_node"
        assert n.bind_deps == {"retriever": True, "memory_manager": True}
        assert n.node_data.min_confidence == 0.7
        assert n.node_data.top_n == 5


class TestWorkflowEdge:
    def test_app_edge(self):
        e = WorkflowEdge(id="e1", sourceNodeId="a", targetNodeId="b")
        assert e.type == EdgeType.APP_EDGE
        assert e.sourceNodeId == "a"
        assert e.targetNodeId == "b"
        assert e.router_fn_ref == ""

    def test_conditional_edge(self):
        e = WorkflowEdge(
            id="e1",
            type=EdgeType.CONDITIONAL_EDGE,
            sourceNodeId="router",
            targetNodeId="faq",
            branch_id="faq",
            router_fn_ref="src.graph.workflow:_decide_route",
        )
        assert e.type == EdgeType.CONDITIONAL_EDGE
        assert e.branch_id == "faq"
        assert e.router_fn_ref == "src.graph.workflow:_decide_route"


# ============================================================
# 默认工作流
# ============================================================

class TestDefaultWorkflow:
    def test_default_workflow_metadata(self):
        assert DEFAULT_WORKFLOW.id == "default-cs-workflow"
        assert DEFAULT_WORKFLOW.name == "默认客服工作流"
        assert DEFAULT_WORKFLOW.entry_node_id == "entry"
        assert DEFAULT_WORKFLOW.is_publish is True
        assert DEFAULT_WORKFLOW.workflow_mode == WorkflowMode.APPLICATION

    def test_default_workflow_has_seven_nodes(self):
        node_ids = [n.id for n in DEFAULT_WORKFLOW.nodes]
        assert node_ids == ["entry", "clarify", "router", "faq", "rag", "human", "reflect", "reply"]

    def test_default_workflow_node_types(self):
        type_map = {n.id: n.type for n in DEFAULT_WORKFLOW.nodes}
        assert type_map["entry"] == NodeType.ENTRY_NODE
        assert type_map["clarify"] == NodeType.CLARIFY_NODE
        assert type_map["router"] == NodeType.ROUTER_NODE
        assert type_map["faq"] == NodeType.FAQ_NODE
        assert type_map["rag"] == NodeType.RAG_NODE
        assert type_map["human"] == NodeType.HUMAN_NODE
        assert type_map["reflect"] == NodeType.REFLECT_NODE
        assert type_map["reply"] == NodeType.REPLY_NODE

    def test_default_workflow_end_nodes(self):
        end_nodes = [n.id for n in DEFAULT_WORKFLOW.nodes if n.is_end]
        assert "human" in end_nodes
        assert "reply" in end_nodes

    def test_default_workflow_has_handler_refs(self):
        for n in DEFAULT_WORKFLOW.nodes:
            assert n.handler_ref.startswith("src.graph.nodes:")

    def test_default_workflow_edges_exist(self):
        edge_ids = {e.id for e in DEFAULT_WORKFLOW.edges}
        assert "e-entry-clarify" in edge_ids
        assert "e-router-faq" in edge_ids
        assert "e-router-rag" in edge_ids
        assert "e-router-human" in edge_ids
        assert "e-rag-reflect" in edge_ids
        assert "e-reflect-reply" in edge_ids

    def test_default_workflow_conditional_edges_have_router(self):
        for e in DEFAULT_WORKFLOW.edges:
            if e.type == EdgeType.CONDITIONAL_EDGE:
                assert e.router_fn_ref != ""
                assert e.branch_id != ""

    def test_get_default_workflow_returns_copy(self):
        wf1 = get_default_workflow()
        wf2 = get_default_workflow()
        assert wf1 is not wf2
        assert wf1.id == wf2.id

    def test_default_workflow_passes_validation(self):
        errors = validate_workflow(DEFAULT_WORKFLOW)
        assert errors == []


# ============================================================
# validate_workflow
# ============================================================

def _make_valid_workflow() -> WorkflowDefinition:
    """构造一个最小合法工作流"""
    return WorkflowDefinition(
        id="test-wf",
        name="测试工作流",
        entry_node_id="start",
        nodes=[
            WorkflowNode(id="start", type=NodeType.ENTRY_NODE, handler_ref="src.graph.nodes:entry_node"),
            WorkflowNode(id="end", type=NodeType.REPLY_NODE, handler_ref="src.graph.nodes:reply_node", is_end=True),
        ],
        edges=[
            WorkflowEdge(id="e1", sourceNodeId="start", targetNodeId="end"),
        ],
    )


class TestValidateWorkflow:
    def test_valid_workflow_no_errors(self):
        wf = _make_valid_workflow()
        assert validate_workflow(wf) == []

    def test_duplicate_node_ids(self):
        wf = _make_valid_workflow()
        wf.nodes.append(
            WorkflowNode(id="start", type=NodeType.ENTRY_NODE, handler_ref="x:y"),
        )
        errors = validate_workflow(wf)
        assert any("重复" in e for e in errors)

    def test_missing_entry_node(self):
        wf = _make_valid_workflow()
        wf.entry_node_id = "nonexistent"
        errors = validate_workflow(wf)
        assert any("入口节点不存在" in e for e in errors)

    def test_edge_source_not_exist(self):
        wf = _make_valid_workflow()
        wf.edges.append(
            WorkflowEdge(id="bad", sourceNodeId="ghost", targetNodeId="end"),
        )
        errors = validate_workflow(wf)
        assert any("sourceNodeId 不存在" in e for e in errors)

    def test_app_edge_target_not_exist(self):
        wf = _make_valid_workflow()
        wf.edges.append(
            WorkflowEdge(id="bad", sourceNodeId="start", targetNodeId="ghost"),
        )
        errors = validate_workflow(wf)
        assert any("targetNodeId 不存在" in e for e in errors)

    def test_no_end_nodes(self):
        wf = WorkflowDefinition(
            id="no-end",
            name="无终止",
            entry_node_id="start",
            nodes=[
                WorkflowNode(id="start", type=NodeType.ENTRY_NODE, handler_ref="x:y"),
                WorkflowNode(id="mid", type=NodeType.CLARIFY_NODE, handler_ref="x:y", is_end=False),
            ],
            edges=[
                WorkflowEdge(id="e1", sourceNodeId="start", targetNodeId="mid"),
            ],
        )
        errors = validate_workflow(wf)
        assert any("终止节点" in e for e in errors)

    def test_conditional_edge_without_router_fn(self):
        wf = _make_valid_workflow()
        wf.nodes.append(WorkflowNode(id="router", type=NodeType.ROUTER_NODE, handler_ref="x:y"))
        wf.edges.append(
            WorkflowEdge(
                id="bad",
                type=EdgeType.CONDITIONAL_EDGE,
                sourceNodeId="router",
                targetNodeId="end",
                router_fn_ref="",  # 缺失
            ),
        )
        errors = validate_workflow(wf)
        assert any("router_fn_ref" in e for e in errors)

    def test_app_edge_without_target(self):
        wf = _make_valid_workflow()
        wf.edges.append(
            WorkflowEdge(id="bad", sourceNodeId="start", targetNodeId=""),
        )
        errors = validate_workflow(wf)
        assert any("targetNodeId" in e for e in errors)

    def test_end_node_type_in_end_nodes_whitelist(self):
        """NodeType 在 END_NODES 白名单中即使 is_end=False 也算终止节点"""
        wf = WorkflowDefinition(
            id="whitelist",
            name="白名单终止",
            entry_node_id="start",
            nodes=[
                WorkflowNode(id="start", type=NodeType.ENTRY_NODE, handler_ref="x:y"),
                # REPLY_NODE 在 END_NODES 中
                WorkflowNode(id="end", type=NodeType.REPLY_NODE, handler_ref="x:y", is_end=False),
            ],
            edges=[
                WorkflowEdge(id="e1", sourceNodeId="start", targetNodeId="end"),
            ],
        )
        errors = validate_workflow(wf)
        assert errors == []


# ============================================================
# 持久化
# ============================================================

class TestPersistence:
    def test_save_and_get_workflow(self):
        wf = _make_valid_workflow()
        saved = save_workflow(wf, tenant_id="t1")
        assert saved.created_at != ""
        assert saved.updated_at != ""

        fetched = get_workflow(wf.id, tenant_id="t1")
        assert fetched is not None
        assert fetched.id == wf.id
        assert fetched.name == wf.name

    def test_get_nonexistent_returns_none(self):
        assert get_workflow("nonexistent", tenant_id="t1") is None

    def test_save_invalid_workflow_raises(self):
        wf = _make_valid_workflow()
        wf.entry_node_id = "ghost"
        with pytest.raises(WorkflowValidationError):
            save_workflow(wf, tenant_id="t1")

    def test_list_workflows(self):
        wf1 = _make_valid_workflow()
        wf1.id = "wf-1"
        wf2 = _make_valid_workflow()
        wf2.id = "wf-2"
        save_workflow(wf1, tenant_id="t1")
        save_workflow(wf2, tenant_id="t1")
        result = list_workflows(tenant_id="t1")
        assert len(result) == 2

    def test_list_workflows_tenant_isolation(self):
        wf = _make_valid_workflow()
        save_workflow(wf, tenant_id="t1")
        save_workflow(wf, tenant_id="t2")
        t1_list = list_workflows(tenant_id="t1")
        t2_list = list_workflows(tenant_id="t2")
        assert len(t1_list) == 1
        assert len(t2_list) == 1
        assert t1_list[0].tenant_id == "t1" or t1_list[0].tenant_id == "default"

    def test_delete_workflow(self):
        wf = _make_valid_workflow()
        save_workflow(wf, tenant_id="t1")
        assert delete_workflow(wf.id, tenant_id="t1") is True
        assert get_workflow(wf.id, tenant_id="t1") is None

    def test_delete_nonexistent_returns_false(self):
        assert delete_workflow("nonexistent", tenant_id="t1") is False

    def test_publish_workflow(self):
        wf = _make_valid_workflow()
        wf.is_publish = False
        save_workflow(wf, tenant_id="t1")
        original_version = get_workflow(wf.id, tenant_id="t1").version

        published = publish_workflow(wf.id, tenant_id="t1")
        assert published is not None
        assert published.is_publish is True
        assert published.publish_time is not None
        assert published.version == original_version + 1

    def test_publish_nonexistent_returns_none(self):
        assert publish_workflow("nonexistent", tenant_id="t1") is None

    def test_save_updates_updated_at(self):
        wf = _make_valid_workflow()
        save_workflow(wf, tenant_id="t1")
        first_updated = get_workflow(wf.id, tenant_id="t1").updated_at

        # 再次保存
        wf.name = "更新后的名字"
        save_workflow(wf, tenant_id="t1")
        second_updated = get_workflow(wf.id, tenant_id="t1").updated_at

        assert second_updated >= first_updated


class TestInitDefaultWorkflow:
    def test_init_creates_when_not_exists(self):
        wf = init_default_workflow(tenant_id="fresh-tenant")
        assert wf.id == DEFAULT_WORKFLOW.id
        assert wf.tenant_id == "fresh-tenant"
        assert wf.created_at != ""

    def test_init_returns_existing_when_already_exists(self):
        wf1 = init_default_workflow(tenant_id="t-init")
        wf2 = init_default_workflow(tenant_id="t-init")
        assert wf1.created_at == wf2.created_at


# ============================================================
# 序列化
# ============================================================

class TestWorkflowToDict:
    def test_to_dict_contains_all_fields(self):
        wf = _make_valid_workflow()
        d = workflow_to_dict(wf)
        assert d["id"] == wf.id
        assert d["name"] == wf.name
        assert d["entry_node_id"] == wf.entry_node_id
        assert d["workflow_mode"] == "application"
        assert isinstance(d["nodes"], list)
        assert isinstance(d["edges"], list)
        assert len(d["nodes"]) == 2
        assert len(d["edges"]) == 1

    def test_to_dict_nodes_are_serializable(self):
        wf = _make_valid_workflow()
        d = workflow_to_dict(wf)
        import json
        # 应可 JSON 序列化
        json.dumps(d, ensure_ascii=False, default=str)

    def test_to_dict_default_workflow(self):
        d = workflow_to_dict(DEFAULT_WORKFLOW)
        assert d["id"] == "default-cs-workflow"
        assert len(d["nodes"]) == 8
        assert d["is_publish"] is True
