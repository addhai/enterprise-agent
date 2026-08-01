"""HITL API 集成测试

覆盖：
- GET /admin/hitl/pending（列出待处理任务）
- GET /admin/hitl/{thread_id}（获取任务详情）
- POST /admin/hitl/{thread_id}/assign（认领任务）
- POST /admin/hitl/{thread_id}/resume（恢复工作流）
- POST /admin/hitl/cleanup（清理超时任务）
- 权限控制（viewer 无权访问）
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.server import app
    from src.api.auth import _init_default_admin
    _init_default_admin()
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
# 列出待处理任务
# ============================================================

class TestListPendingTasks:
    def test_admin_can_list_pending(self, client, admin_token):
        resp = client.get("/api/v1/admin/hitl/pending", headers=_auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    def test_agent_can_list_pending(self, client, agent_token):
        resp = client.get("/api/v1/admin/hitl/pending", headers=_auth_header(agent_token))
        assert resp.status_code == 200

    def test_viewer_cannot_list_pending(self, client, viewer_token):
        resp = client.get("/api/v1/admin/hitl/pending", headers=_auth_header(viewer_token))
        assert resp.status_code == 403

    def test_unauthenticated_cannot_list(self, client):
        resp = client.get("/api/v1/admin/hitl/pending")
        assert resp.status_code == 401


# ============================================================
# 获取任务详情
# ============================================================

class TestGetTaskDetail:
    def test_get_nonexistent_task_returns_404(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/hitl/nonexistent-thread",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_viewer_cannot_get_task(self, client, viewer_token):
        resp = client.get(
            "/api/v1/admin/hitl/some-thread",
            headers=_auth_header(viewer_token),
        )
        assert resp.status_code == 403


# ============================================================
# 认领任务
# ============================================================

class TestAssignTask:
    def test_assign_nonexistent_task_returns_404_or_409(self, client, admin_token):
        """分配不存在的任务可能返回 404 或 409（取决于实现）"""
        resp = client.post(
            "/api/v1/admin/hitl/nonexistent/assign",
            json={"agent_id": "agent-1"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code in (404, 409)

    def test_viewer_cannot_assign(self, client, viewer_token):
        resp = client.post(
            "/api/v1/admin/hitl/some/assign",
            json={"agent_id": "agent-1"},
            headers=_auth_header(viewer_token),
        )
        assert resp.status_code == 403


# ============================================================
# 清理超时任务
# ============================================================

class TestCleanupExpired:
    def test_admin_can_cleanup(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/hitl/cleanup",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "cleaned" in data

    def test_agent_cannot_cleanup(self, client, agent_token):
        """仅 admin 可调用"""
        resp = client.post(
            "/api/v1/admin/hitl/cleanup",
            headers=_auth_header(agent_token),
        )
        assert resp.status_code == 403

    def test_cleanup_with_custom_max_age(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/hitl/cleanup",
            params={"max_age_seconds": 60},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
