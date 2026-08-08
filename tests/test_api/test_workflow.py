"""Workflow API 集成测试

覆盖：
- GET /admin/workflows（列表）
- GET /admin/workflows/default（默认工作流）
- GET /admin/workflows/{wf_id}（详情）
- POST /admin/workflows（创建）
- PUT /admin/workflows/{wf_id}（更新）
- DELETE /admin/workflows/{wf_id}（删除）
- POST /admin/workflows/{wf_id}/publish（发布）
- POST /admin/workflows/{wf_id}/validate（校验）
- POST /admin/workflows/validate（校验草稿）
- POST /admin/workflows/{wf_id}/clone（克隆）
- GET /admin/workflows/meta/node-types（节点类型参考）
- 权限控制（agent 可读不可写，viewer 无权）
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.server import app
    # 默认账号由 tests/conftest.py 的 _init_test_database 在 session 级 seed
    return TestClient(app)


@pytest.fixture
def admin_token(client):
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "admin123",
    })
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture
def agent_token(client):
    resp = client.post("/api/v1/auth/login", json={
        "username": "agent", "password": "agent123",
    })
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture
def viewer_token(client):
    resp = client.post("/api/v1/auth/login", json={
        "username": "viewer", "password": "viewer123",
    })
    assert resp.status_code == 200
    return resp.json()["token"]


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# 列表
# ============================================================

class TestListWorkflows:
    def test_admin_can_list_workflows(self, client, admin_token):
        resp = client.get("/api/v1/admin/workflows", headers=_auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "workflows" in data

    def test_agent_can_list_workflows(self, client, agent_token):
        resp = client.get("/api/v1/admin/workflows", headers=_auth_header(agent_token))
        assert resp.status_code == 200

    def test_viewer_cannot_list_workflows(self, client, viewer_token):
        resp = client.get("/api/v1/admin/workflows", headers=_auth_header(viewer_token))
        assert resp.status_code == 403

    def test_list_includes_default_workflow(self, client, admin_token):
        resp = client.get("/api/v1/admin/workflows", headers=_auth_header(admin_token))
        data = resp.json()
        wf_ids = [w["id"] for w in data["workflows"]]
        assert "default-cs-workflow" in wf_ids


# ============================================================
# 默认工作流
# ============================================================

class TestDefaultWorkflow:
    def test_get_default_workflow(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/workflows/default",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "workflow" in data
        assert data["workflow"]["id"] == "default-cs-workflow"
        assert len(data["workflow"]["nodes"]) == 8


# ============================================================
# 详情
# ============================================================

class TestGetWorkflowDetail:
    def test_get_default_workflow_detail(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/workflows/default-cs-workflow",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["workflow"]["id"] == "default-cs-workflow"

    def test_get_nonexistent_workflow_returns_404(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/workflows/nonexistent",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404


# ============================================================
# 创建
# ============================================================

class TestCreateWorkflow:
    def test_admin_can_create_workflow(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/workflows",
            json={
                "name": "测试工作流",
                "description": "通过 API 创建的测试工作流",
                "entry_node_id": "start",
                "nodes": [
                    {"id": "start", "type": "entry-node", "handler_ref": "src.graph.nodes:entry_node"},
                    {"id": "end", "type": "reply-node", "handler_ref": "src.graph.nodes:reply_node", "is_end": True},
                ],
                "edges": [
                    {"id": "e1", "sourceNodeId": "start", "targetNodeId": "end"},
                ],
            },
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["workflow"]["name"] == "测试工作流"

    def test_agent_cannot_create_workflow(self, client, agent_token):
        resp = client.post(
            "/api/v1/admin/workflows",
            json={
                "name": "agent不可创建",
                "entry_node_id": "start",
                "nodes": [
                    {"id": "start", "type": "entry-node", "handler_ref": "x:y"},
                    {"id": "end", "type": "reply-node", "handler_ref": "x:y", "is_end": True},
                ],
                "edges": [],
            },
            headers=_auth_header(agent_token),
        )
        assert resp.status_code == 403

    def test_create_invalid_workflow_returns_400(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/workflows",
            json={
                "name": "非法工作流",
                "entry_node_id": "ghost",
                "nodes": [
                    {"id": "start", "type": "entry-node", "handler_ref": "x:y"},
                ],
                "edges": [],
            },
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_create_empty_nodes_workflow_returns_400(self, client, admin_token):
        """无节点的工作流应校验失败"""
        resp = client.post(
            "/api/v1/admin/workflows",
            json={
                "name": "空工作流",
                "entry_node_id": "entry",
                "nodes": [],
                "edges": [],
            },
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 400


# ============================================================
# 更新
# ============================================================

class TestUpdateWorkflow:
    def test_admin_can_update_workflow(self, client, admin_token):
        # 先创建
        create_resp = client.post(
            "/api/v1/admin/workflows",
            json={
                "name": "待更新",
                "entry_node_id": "start",
                "nodes": [
                    {"id": "start", "type": "entry-node", "handler_ref": "src.graph.nodes:entry_node"},
                    {"id": "end", "type": "reply-node", "handler_ref": "src.graph.nodes:reply_node", "is_end": True},
                ],
                "edges": [
                    {"id": "e1", "sourceNodeId": "start", "targetNodeId": "end"},
                ],
            },
            headers=_auth_header(admin_token),
        )
        wf_id = create_resp.json()["workflow"]["id"]

        # 更新名称
        resp = client.put(
            f"/api/v1/admin/workflows/{wf_id}",
            json={"name": "已更新名称"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["workflow"]["name"] == "已更新名称"

    def test_update_nonexistent_returns_404(self, client, admin_token):
        resp = client.put(
            "/api/v1/admin/workflows/nonexistent",
            json={"name": "x"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404


# ============================================================
# 删除
# ============================================================

class TestDeleteWorkflow:
    def test_admin_can_delete_workflow(self, client, admin_token):
        # 创建
        create_resp = client.post(
            "/api/v1/admin/workflows",
            json={
                "name": "待删除",
                "entry_node_id": "start",
                "nodes": [
                    {"id": "start", "type": "entry-node", "handler_ref": "src.graph.nodes:entry_node"},
                    {"id": "end", "type": "reply-node", "handler_ref": "src.graph.nodes:reply_node", "is_end": True},
                ],
                "edges": [
                    {"id": "e1", "sourceNodeId": "start", "targetNodeId": "end"},
                ],
            },
            headers=_auth_header(admin_token),
        )
        wf_id = create_resp.json()["workflow"]["id"]

        # 删除
        resp = client.delete(
            f"/api/v1/admin/workflows/{wf_id}",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200

        # 确认已删除
        resp = client.get(
            f"/api/v1/admin/workflows/{wf_id}",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_cannot_delete_default_workflow(self, client, admin_token):
        resp = client.delete(
            "/api/v1/admin/workflows/default-cs-workflow",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_delete_nonexistent_returns_404(self, client, admin_token):
        resp = client.delete(
            "/api/v1/admin/workflows/nonexistent",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404


# ============================================================
# 发布
# ============================================================

class TestPublishWorkflow:
    def test_publish_workflow(self, client, admin_token):
        # 创建一个工作流
        create_resp = client.post(
            "/api/v1/admin/workflows",
            json={
                "name": "待发布",
                "entry_node_id": "start",
                "nodes": [
                    {"id": "start", "type": "entry-node", "handler_ref": "src.graph.nodes:entry_node"},
                    {"id": "end", "type": "reply-node", "handler_ref": "src.graph.nodes:reply_node", "is_end": True},
                ],
                "edges": [
                    {"id": "e1", "sourceNodeId": "start", "targetNodeId": "end"},
                ],
            },
            headers=_auth_header(admin_token),
        )
        wf_id = create_resp.json()["workflow"]["id"]

        # 发布
        resp = client.post(
            f"/api/v1/admin/workflows/{wf_id}/publish",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow"]["is_publish"] is True

    def test_publish_nonexistent_returns_404(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/workflows/nonexistent/publish",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404


# ============================================================
# 校验
# ============================================================

class TestValidateWorkflow:
    def test_validate_valid_workflow(self, client, admin_token):
        # 使用默认工作流校验
        resp = client.post(
            "/api/v1/admin/workflows/default-cs-workflow/validate",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["node_count"] == 8

    def test_validate_draft_valid(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/workflows/validate",
            json={
                "name": "草稿校验",
                "entry_node_id": "start",
                "nodes": [
                    {"id": "start", "type": "entry-node", "handler_ref": "src.graph.nodes:entry_node"},
                    {"id": "end", "type": "reply-node", "handler_ref": "src.graph.nodes:reply_node", "is_end": True},
                ],
                "edges": [
                    {"id": "e1", "sourceNodeId": "start", "targetNodeId": "end"},
                ],
            },
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_validate_draft_invalid(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/workflows/validate",
            json={
                "name": "非法草稿",
                "entry_node_id": "ghost",
                "nodes": [
                    {"id": "start", "type": "entry-node", "handler_ref": "x:y"},
                ],
                "edges": [],
            },
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_validate_nonexistent_returns_404(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/workflows/nonexistent/validate",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404


# ============================================================
# 克隆
# ============================================================

class TestCloneWorkflow:
    def test_clone_default_workflow(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/workflows/default-cs-workflow/clone",
            json={"new_name": "克隆版默认工作流"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["workflow"]["name"] == "克隆版默认工作流"
        assert data["workflow"]["is_publish"] is False

    def test_clone_nonexistent_returns_404(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/workflows/nonexistent/clone",
            json={"new_name": "x"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404


# ============================================================
# 节点类型参考
# ============================================================

class TestNodeTypes:
    def test_get_node_types(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/workflows/meta/node-types",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        assert "node_types" in data
        assert "edge_types" in data
        assert "workflow_modes" in data

    def test_agent_can_get_node_types(self, client, agent_token):
        resp = client.get(
            "/api/v1/admin/workflows/meta/node-types",
            headers=_auth_header(agent_token),
        )
        assert resp.status_code == 200
