"""知识库管理 API 测试（使用内存 SQLite + 登录 token，确定性不触网）"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.server import app

    return TestClient(app)


@pytest.fixture
def admin_token(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture
def viewer_token(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "viewer", "password": "viewer123"}
    )
    assert resp.status_code == 200
    return resp.json()["token"]


KB_PAYLOAD = {
    "name": "测试知识库",
    "description": "P2-5 覆盖率测试用",
    "kb_version": "standard",
    "kb_type": "document",
    "similarity_threshold": 0.75,
    "weight": 1.0,
}


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


class TestKnowledgeCrud:
    def test_create_kb(self, client, admin_token):
        r = client.post(
            "/api/v1/admin/knowledge", json=KB_PAYLOAD, headers=_auth(admin_token)
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "id" in data["kb"]

    def test_create_kb_requires_auth(self, client):
        r = client.post("/api/v1/admin/knowledge", json=KB_PAYLOAD)
        assert r.status_code == 401

    def test_create_kb_forbidden_for_viewer(self, client, viewer_token):
        r = client.post(
            "/api/v1/admin/knowledge", json=KB_PAYLOAD, headers=_auth(viewer_token)
        )
        assert r.status_code == 403

    def test_create_kb_bad_enum(self, client, admin_token):
        bad = dict(KB_PAYLOAD, kb_type="not_a_type")
        r = client.post(
            "/api/v1/admin/knowledge", json=bad, headers=_auth(admin_token)
        )
        assert r.status_code == 400

    def test_crud_flow(self, client, admin_token):
        h = _auth(admin_token)
        created = client.post(
            "/api/v1/admin/knowledge", json=KB_PAYLOAD, headers=h
        ).json()["kb"]
        kb_id = created["id"]

        # list
        lst = client.get("/api/v1/admin/knowledge", headers=h)
        assert lst.status_code == 200
        assert lst.json()["total"] >= 1

        # get
        got = client.get(f"/api/v1/admin/knowledge/{kb_id}", headers=h)
        assert got.status_code == 200
        assert got.json()["kb"]["id"] == kb_id

        # get nonexistent
        miss = client.get("/api/v1/admin/knowledge/NOPE", headers=h)
        assert miss.status_code == 404

        # update
        upd = client.put(
            f"/api/v1/admin/knowledge/{kb_id}",
            json={"name": "改名后的知识库"},
            headers=h,
        )
        assert upd.status_code == 200
        assert upd.json()["kb"]["name"] == "改名后的知识库"

        # reindex
        rei = client.post(
            f"/api/v1/admin/knowledge/{kb_id}/reindex", headers=h
        )
        assert rei.status_code == 200

        # delete
        dele = client.delete(f"/api/v1/admin/knowledge/{kb_id}", headers=h)
        assert dele.status_code == 200
        assert "已删除" in dele.json()["message"]
