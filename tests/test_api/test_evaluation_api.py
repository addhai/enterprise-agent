"""评估模块 API 测试（内存 SQLite + 登录 token）"""
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


DS_PAYLOAD = {
    "name": "测试数据集",
    "description": "P2-5 覆盖率测试",
    "samples": [
        {"query": "如何重置密码", "ground_truth": "在设置页点击重置密码"},
        {"query": "退款流程", "expected_intent": "refund"},
    ],
    "tags": ["smoke"],
}


class TestEvaluationApi:
    def test_create_dataset(self, client, admin_token):
        r = client.post(
            "/api/v1/admin/evaluation/datasets",
            json=DS_PAYLOAD,
            headers=_auth(admin_token),
        )
        assert r.status_code == 200
        assert "id" in r.json()["dataset"]

    def test_create_requires_auth(self, client):
        r = client.post("/api/v1/admin/evaluation/datasets", json=DS_PAYLOAD)
        assert r.status_code == 401

    def test_crud_flow(self, client, admin_token):
        h = _auth(admin_token)
        ds_id = (
            client.post(
                "/api/v1/admin/evaluation/datasets", json=DS_PAYLOAD, headers=h
            )
            .json()["dataset"]["id"]
        )

        lst = client.get("/api/v1/admin/evaluation/datasets", headers=h)
        assert lst.status_code == 200
        assert lst.json()["total"] >= 1

        got = client.get(f"/api/v1/admin/evaluation/datasets/{ds_id}", headers=h)
        assert got.status_code == 200
        assert got.json()["dataset"]["id"] == ds_id

        upd = client.put(
            f"/api/v1/admin/evaluation/datasets/{ds_id}",
            json={"name": "改名数据集", "tags": ["regression"]},
            headers=h,
        )
        assert upd.status_code == 200

        dele = client.delete(
            f"/api/v1/admin/evaluation/datasets/{ds_id}", headers=h
        )
        assert dele.status_code == 200

    def test_runs_list(self, client, admin_token):
        r = client.get("/api/v1/admin/evaluation/runs", headers=_auth(admin_token))
        assert r.status_code == 200

    def test_create_run_missing_dataset_404(self, client, admin_token):
        # 确定性分支：数据集不存在 → 404（不触发真实 LLM 评估）
        r = client.post(
            "/api/v1/admin/evaluation/runs",
            json={"dataset_id": "DS_NOT_EXIST"},
            headers=_auth(admin_token),
        )
        assert r.status_code == 404

    def test_meta_metrics(self, client, admin_token):
        r = client.get(
            "/api/v1/admin/evaluation/meta/metrics", headers=_auth(admin_token)
        )
        assert r.status_code == 200
