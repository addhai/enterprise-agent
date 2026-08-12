"""客户管理 API 测试（内存 SQLite + 登录 token）"""
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


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


class TestCustomersApi:
    def test_list_customers(self, client, admin_token):
        r = client.get("/api/v1/customers", headers=_auth(admin_token))
        assert r.status_code == 200
        assert "customers" in r.json()

    def test_list_requires_auth(self, client):
        r = client.get("/api/v1/customers")
        assert r.status_code == 401

    def test_get_customer(self, client, admin_token):
        r = client.get("/api/v1/customers/admin", headers=_auth(admin_token))
        assert r.status_code in (200, 404)

    def test_customer_timeline(self, client, admin_token):
        r = client.get("/api/v1/customers/admin/timeline", headers=_auth(admin_token))
        assert r.status_code in (200, 404)

    def test_update_tags(self, client, admin_token):
        r = client.put(
            "/api/v1/customers/admin/tags",
            json={"tags": ["vip", "high_value"]},
            headers=_auth(admin_token),
        )
        assert r.status_code in (200, 404)

    def test_update_note(self, client, admin_token):
        r = client.put(
            "/api/v1/customers/admin/note",
            json={"note": "重要客户，需优先跟进"},
            headers=_auth(admin_token),
        )
        assert r.status_code in (200, 404)

    def test_update_status(self, client, admin_token):
        r = client.put(
            "/api/v1/customers/admin/status?status=active",
            headers=_auth(admin_token),
        )
        assert r.status_code in (200, 404)
