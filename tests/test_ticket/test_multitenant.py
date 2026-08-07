"""多租户运行时隔离（P1）端到端测试

验证：
  - 两租户用户各自建工单后，互不可见（列表与按 ID 直取均隔离）
  - 租户管理端点可用（super_admin 创建 / 列出）
  - 注册到不存在的租户被拒绝（隔离空间有效性兜底）
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from src.api.server import app


def _client() -> TestClient:
    return TestClient(app)


def _admin_token(client: TestClient) -> str:
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _register(client: TestClient, tenant_id: str):
    username = f"mt_{uuid.uuid4().hex[:10]}"
    r = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "pass123456", "tenant_id": tenant_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["token"], body["user"]["user_id"]


def test_multitenant_ticket_isolation():
    client = _client()
    admin_token = _admin_token(client)
    h_admin = {"Authorization": f"Bearer {admin_token}"}

    # 创建第二个租户（唯一 id 防重跑 409）
    tenant_b = f"acme_{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/v1/admin/tenants",
        json={"tenant_id": tenant_b, "name": "Acme Corp"},
        headers=h_admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == tenant_b

    # 两租户各注册一个用户（默认角色 agent）
    token_a, _ = _register(client, "default")
    token_b, _ = _register(client, tenant_b)
    h_a = {"Authorization": f"Bearer {token_a}"}
    h_b = {"Authorization": f"Bearer {token_b}"}

    # 各建一张工单
    ta = client.post(
        "/api/v1/tickets",
        json={"user_id": "custA", "title": "Default租户的问题"},
        headers=h_a,
    )
    tb = client.post(
        "/api/v1/tickets",
        json={"user_id": "custB", "title": "Acme租户的问题"},
        headers=h_b,
    )
    assert ta.status_code == 200 and tb.status_code == 200, (ta.text, tb.text)
    id_b = tb.json()["ticket"]["id"]

    # A 看自己的列表：含 default 单，不含 acme 单
    list_a = client.get("/api/v1/tickets", headers=h_a).json()
    titles_a = {t["title"] for t in list_a["tickets"]}
    assert "Default租户的问题" in titles_a
    assert "Acme租户的问题" not in titles_a

    # B 看自己的列表：含 acme 单，不含 default 单
    list_b = client.get("/api/v1/tickets", headers=h_b).json()
    titles_b = {t["title"] for t in list_b["tickets"]}
    assert "Acme租户的问题" in titles_b
    assert "Default租户的问题" not in titles_b

    # A 按 ID 直接取 B 的工单 → 404（隔离兜底）
    cross = client.get(f"/api/v1/tickets/{id_b}", headers=h_a)
    assert cross.status_code == 404

    # 管理员可见两个租户
    tenants = client.get("/api/v1/admin/tenants", headers=h_admin).json()
    ids = {t["tenant_id"] for t in tenants}
    assert "default" in ids and tenant_b in ids


def test_register_rejects_unknown_tenant():
    client = _client()
    username = f"mt_{uuid.uuid4().hex[:10]}"
    r = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "pass123456", "tenant_id": "no-such-tenant"},
    )
    assert r.status_code == 400
    assert "租户不存在" in r.json()["detail"]
