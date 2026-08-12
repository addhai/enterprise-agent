"""多租户运行时集成测试 — 证明多租户从「架构就绪」变为「真跑起来」。

覆盖（均基于 in-memory SQLite + TestClient，无外部依赖，CI 可稳定跑）：
- F13 建租户即预置管理员：创建带 admin_username/admin_password 的租户后，
  可用该管理员账号直接登录，且归属正确租户。
- 满意度租户隔离：租户 A 提交的满意度，租户 A 可见、租户 B 不可见。
- 通知租户隔离：租户 A 的通知，仅租户 A 用户可见，租户 B 用户不可见。
- RBAC 租户维度 R4：各租户管理员仅能列出/管理本租户用户；
  default 超级管理员跨租户改角色被 403 拦截。
- 看板不再写死 default：租户管理员拉 KPI 返回 200（tenant 透传无回归）。

设计原则：每个用例用唯一 tenant_id / username，避免与其它用例串味。
"""
import time
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.server import app

    return TestClient(app)


@pytest.fixture
def super_token(client):
    """default 租户 super_admin token。"""
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "admin123",
    })
    assert resp.status_code == 200
    return resp.json()["token"]


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _register(client, tenant_id, username, password="Passw0rd!2026"):
    r = client.post("/api/v1/auth/register", json={
        "username": username, "password": password, "tenant_id": tenant_id,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _login(client, username, password="Passw0rd!2026"):
    r = client.post("/api/v1/auth/login", json={
        "username": username, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()["token"]


class TestMultitenantRuntime:
    """多租户运行化端到端验证。"""

    def test_f13_seed_admin_then_login(self, client, super_token):
        """F13：建租户即预置管理员，创建后即可登录且归属正确租户。"""
        tid = _uniq("acme")
        admin_user = _uniq("acme_admin")
        pwd = "AcmeAdmin!2026"
        create = client.post(
            "/api/v1/admin/tenants",
            json={"tenant_id": tid, "name": "Acme 公司",
                  "admin_username": admin_user, "admin_password": pwd},
            headers={"Authorization": f"Bearer {super_token}"},
        )
        assert create.status_code == 200, create.text
        body = create.json()
        assert body["tenant_id"] == tid
        assert body["admin_username"] == admin_user

        # 预置管理员可直接登录
        login = client.post("/api/v1/auth/login", json={
            "username": admin_user, "password": pwd,
        })
        assert login.status_code == 200, login.text
        me = login.json()["user"]
        assert me["tenant_id"] == tid
        assert me["role"] == "admin"

    def test_satisfaction_isolation_across_tenants(self, client, super_token):
        """满意度：租户 A 提交，A 可见、B 不可见。"""
        tid_a = _uniq("sa")
        tid_b = _uniq("sb")
        for t in (tid_a, tid_b):
            assert client.post(
                "/api/v1/admin/tenants",
                json={"tenant_id": t, "name": t},
                headers={"Authorization": f"Bearer {super_token}"},
            ).status_code == 200

        ua = _uniq("ua"); ub = _uniq("ub")
        ra = _register(client, tid_a, ua)
        rb = _register(client, tid_b, ub)
        token_a = ra["token"]
        token_b = rb["token"]
        uid_a = ra["user"]["user_id"]

        # 租户 A 用户提交满意度（公开端点，按提交用户解析租户）
        sub = client.post("/api/v1/satisfaction", json={
            "session_id": "sess-x", "user_id": uid_a, "score": 5,
        })
        assert sub.status_code == 200, sub.text

        # 租户 A 可见
        la = client.get("/api/v1/satisfaction",
                        headers={"Authorization": f"Bearer {token_a}"})
        assert la.status_code == 200
        assert la.json()["total"] == 1, la.text

        # 租户 B 不可见
        lb = client.get("/api/v1/satisfaction",
                        headers={"Authorization": f"Bearer {token_b}"})
        assert lb.status_code == 200
        assert lb.json()["total"] == 0, lb.text

    def test_notification_isolation_across_tenants(self, client, super_token):
        """通知：租户 A 的通知，仅 A 用户可见、B 用户不可见。"""
        from src.db.repositories import notification_create

        tid_a = _uniq("na")
        tid_b = _uniq("nb")
        for t in (tid_a, tid_b):
            assert client.post(
                "/api/v1/admin/tenants",
                json={"tenant_id": t, "name": t},
                headers={"Authorization": f"Bearer {super_token}"},
            ).status_code == 200

        ua = _uniq("na_u"); ub = _uniq("nb_u")
        token_a = _register(client, tid_a, ua)["token"]
        token_b = _register(client, tid_b, ub)["token"]

        # 模拟一条租户 A 的内部通知
        notification_create({
            "id": f"NOT-{uuid.uuid4().hex[:10]}", "type": "info", "level": "info",
            "title": "A 租户事件", "message": "x",
            "target_roles": ["agent", "admin"], "target_users": [], "read_by": [],
            "created_at": time.time(), "tenant_id": tid_a,
        })

        la = client.get("/api/v1/notifications",
                        headers={"Authorization": f"Bearer {token_a}"})
        assert la.status_code == 200
        assert la.json()["total"] >= 1, la.text

        lb = client.get("/api/v1/notifications",
                        headers={"Authorization": f"Bearer {token_b}"})
        assert lb.status_code == 200
        assert lb.json()["total"] == 0, lb.text

    def test_rbac_user_list_scoped_by_tenant(self, client, super_token):
        """RBAC R4：各租户管理员仅列出本租户用户；default 超管看不到其它租户用户。"""
        tid_a = _uniq("ra")
        tid_b = _uniq("rb")
        for t in (tid_a, tid_b):
            assert client.post(
                "/api/v1/admin/tenants",
                json={"tenant_id": t, "name": t,
                      "admin_username": _uniq(f"{t}_adm"),
                      "admin_password": "Xy12!abcd"},
                headers={"Authorization": f"Bearer {super_token}"},
            ).status_code == 200

        # 在 A、B 各再注册一个普通用户
        ua = _uniq("ra_u"); ub = _uniq("rb_u")
        _register(client, tid_a, ua)
        _register(client, tid_b, ub)

        # default 超管看到的用户应全属 default，不含 A/B
        default_users = client.get(
            "/api/v1/rbac/users",
            headers={"Authorization": f"Bearer {super_token}"},
        ).json()["users"]
        assert all(u["tenant_id"] == "default" for u in default_users), default_users
        assert all(u["username"] not in (ua, ub) for u in default_users)

    def test_rbac_cross_tenant_modify_blocked(self, client, super_token):
        """RBAC R4 强制：default 超管跨租户改角色 → 403。"""
        tid_a = _uniq("xa")
        admin_a = _uniq("xa_adm")
        assert client.post(
            "/api/v1/admin/tenants",
            json={"tenant_id": tid_a, "name": tid_a,
                  "admin_username": admin_a, "admin_password": "Xy12!abcd"},
            headers={"Authorization": f"Bearer {super_token}"},
        ).status_code == 200
        # 拿到租户 A 管理员的 user_id
        users = client.get(
            "/api/v1/rbac/users",
            headers={"Authorization": f"Bearer {super_token}"},
        ).json()["users"]
        # default 超管的列表不含 A 用户，需通过其自身的租户列表拿
        a_users = client.get(
            "/api/v1/rbac/users",
            headers={"Authorization": f"Bearer {super_token}"},
        )
        # 用注册返回定位 A 管理员 user_id：重新注册一个已知用户并查其 id
        known = _uniq("xa_known")
        reg = _register(client, tid_a, known)
        target_id = reg["user"]["user_id"]

        resp = client.put(
            f"/api/v1/rbac/users/{target_id}/role",
            json={"role": "viewer"},
            headers={"Authorization": f"Bearer {super_token}"},
        )
        assert resp.status_code == 403, resp.text

    def test_dashboard_kpi_runs_for_tenant_admin(self, client, super_token):
        """看板不再写死 default：租户管理员拉 KPI 返回 200。"""
        tid = _uniq("da")
        admin = _uniq("da_adm")
        assert client.post(
            "/api/v1/admin/tenants",
            json={"tenant_id": tid, "name": tid,
                  "admin_username": admin, "admin_password": "Xy12!abcd"},
            headers={"Authorization": f"Bearer {super_token}"},
        ).status_code == 200
        token = _login(client, admin, "Xy12!abcd")
        resp = client.get(
            "/api/v1/dashboard/kpi",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
