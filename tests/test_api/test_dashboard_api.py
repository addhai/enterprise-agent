"""运营看板 API 测试（内存 SQLite + 登录 token）"""
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


class TestDashboardApi:
    def test_kpi(self, client, admin_token):
        r = client.get("/api/v1/dashboard/kpi", headers=_auth(admin_token))
        assert r.status_code == 200

    def test_realtime(self, client, admin_token):
        r = client.get("/api/v1/dashboard/realtime", headers=_auth(admin_token))
        assert r.status_code == 200

    def test_agent_performance(self, client, admin_token):
        r = client.get(
            "/api/v1/dashboard/agent-performance", headers=_auth(admin_token)
        )
        assert r.status_code == 200

    def test_intent_distribution(self, client, admin_token):
        r = client.get(
            "/api/v1/dashboard/intent-distribution", headers=_auth(admin_token)
        )
        assert r.status_code == 200

    def test_kpi_requires_auth(self, client):
        r = client.get("/api/v1/dashboard/kpi")
        assert r.status_code == 401
