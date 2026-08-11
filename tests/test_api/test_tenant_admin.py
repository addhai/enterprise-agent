"""多租户管理端点（F13）测试 — 钉死「已实现」状态。

覆盖：
- super_admin 可创建租户（POST /api/v1/admin/tenants）
- super_admin 可列出租户（GET /api/v1/admin/tenants），返回的列表包含新建租户
- 未带 token 访问 → 401
- 非 super_admin（agent）访问 → 403
- 重复 tenant_id → 409

默认 admin 账号角色为 super_admin，因此用 admin/admin123 登录即可拿到
满足 require_user_manage 的 token。测试库为 session 级内存 SQLite，
每个用例用唯一 tenant_id 避免 409 互相干扰。
"""
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI 测试客户端（默认账号由 conftest 在内存 SQLite 建表 + seed）。"""
    from src.api.server import app

    return TestClient(app)


@pytest.fixture
def admin_token(client):
    """super_admin token（默认 admin 账号角色为 super_admin）。"""
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin123",
    })
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture
def agent_token(client):
    """普通 agent token（非 super_admin，用于 403 负向用例）。"""
    resp = client.post("/api/v1/auth/login", json={
        "username": "agent",
        "password": "agent123",
    })
    assert resp.status_code == 200
    return resp.json()["token"]


def _unique_tenant_id() -> str:
    """生成全局唯一的租户标识，避免与 seeded `default` 或其他用例冲突。"""
    return "t_" + uuid.uuid4().hex[:12]


class TestTenantAdminEndpoint:
    """F13 多租户管理端点（仅 super_admin）。"""

    def test_create_tenant_requires_auth(self, client):
        """未带 token → 401。"""
        resp = client.post("/api/v1/admin/tenants", json={
            "tenant_id": _unique_tenant_id(),
            "name": "未授权租户",
        })
        assert resp.status_code == 401

    def test_create_tenant_forbidden_for_agent(self, client, agent_token):
        """非 super_admin（agent）创建租户 → 403。"""
        resp = client.post(
            "/api/v1/admin/tenants",
            json={"tenant_id": _unique_tenant_id(), "name": "越权租户"},
            headers={"Authorization": f"Bearer {agent_token}"},
        )
        assert resp.status_code == 403

    def test_create_and_list_tenant_as_super_admin(self, client, admin_token):
        """super_admin 创建租户，并能从列表查询到。"""
        tid = _unique_tenant_id()
        create = client.post(
            "/api/v1/admin/tenants",
            json={"tenant_id": tid, "name": "演示租户A", "plan": "standard"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert create.status_code == 200, create.text
        body = create.json()
        assert body["tenant_id"] == tid
        assert body["name"] == "演示租户A"
        assert body["plan"] == "standard"
        assert body["status"] == "active"

        listing = client.get(
            "/api/v1/admin/tenants",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert listing.status_code == 200, listing.text
        tids = {t["tenant_id"] for t in listing.json()}
        assert tid in tids, "新建租户未出现在租户列表中"

    def test_create_duplicate_tenant_conflict(self, client, admin_token):
        """重复 tenant_id → 409。"""
        tid = _unique_tenant_id()
        first = client.post(
            "/api/v1/admin/tenants",
            json={"tenant_id": tid, "name": "冲突租户-1"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/api/v1/admin/tenants",
            json={"tenant_id": tid, "name": "冲突租户-2"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert second.status_code == 409, second.text

    def test_list_requires_auth(self, client):
        """未带 token 列出租户 → 401。"""
        resp = client.get("/api/v1/admin/tenants")
        assert resp.status_code == 401
