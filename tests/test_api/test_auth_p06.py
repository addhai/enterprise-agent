"""P0-6 认证收口测试（2026-10）

三块内容：
1. LoginGuard 登录失败锁定纯逻辑（阈值、锁定时长、成功清零、窗口过期）
2. /auth/login 爆破锁定 HTTP 行为（429 + Retry-After、锁定期正确密码也拒绝）
3. 默认密码治理：登录响应标志、/auth/change-password、强制改密拦截与白名单
4. 生产环境 JWT_SECRET 缺失拒启动
"""

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.server import app

    return TestClient(app)


@pytest.fixture
def admin_token(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["token"]


# ============================================================
# LoginGuard 纯逻辑
# ============================================================


class TestLoginGuard:
    def test_locks_after_threshold(self):
        from src.api.login_guard import LoginGuard

        guard = LoginGuard(max_failures=5, lockout_seconds=900)
        for _ in range(4):
            assert guard.record_failure("u") < 5
            assert not guard.is_locked("u")
        assert guard.record_failure("u") == 5
        assert guard.is_locked("u")
        assert guard.locked_seconds("u") > 800

    def test_success_resets_counter(self):
        from src.api.login_guard import LoginGuard

        guard = LoginGuard(max_failures=3, lockout_seconds=900)
        guard.record_failure("u")
        guard.record_failure("u")
        guard.record_success("u")
        assert not guard.is_locked("u")
        # 清零后再失败两次不应触发锁定
        guard.record_failure("u")
        guard.record_failure("u")
        assert not guard.is_locked("u")

    def test_window_expiry_unlocks(self):
        from src.api.login_guard import LoginGuard

        guard = LoginGuard(max_failures=2, lockout_seconds=10)
        # 手工注入已过期的失败记录（monotonic 时间戳）
        now = time.monotonic()
        guard._failures["u"] = [now - 11, now - 10.5]
        # 查询时旧记录应被剔除，表现为未锁定
        assert not guard.is_locked("u")

    def test_keys_isolated(self):
        from src.api.login_guard import LoginGuard

        guard = LoginGuard(max_failures=2, lockout_seconds=900)
        guard.record_failure("a")
        guard.record_failure("a")
        assert guard.is_locked("a")
        assert not guard.is_locked("b")

    def test_reset_clears_all(self):
        from src.api.login_guard import LoginGuard

        guard = LoginGuard(max_failures=1, lockout_seconds=900)
        guard.record_failure("a")
        guard.reset()
        assert not guard.is_locked("a")


# ============================================================
# /auth/login 爆破锁定
# ============================================================


class TestLoginLockoutApi:
    def test_five_failures_then_429_even_with_correct_password(self, client):
        """连续 5 次错密后第 6 次即使密码正确也返回 429。"""
        for _ in range(5):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "viewer", "password": "wrong"},
            )
            assert resp.status_code == 401
        # 正确密码也被拒
        locked = client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "viewer123"},
        )
        assert locked.status_code == 429
        assert int(locked.headers["Retry-After"]) > 0

    def test_successful_login_resets_failures(self, client):
        """失败未达阈值时一次成功登录应清零计数。"""
        client.post(
            "/api/v1/auth/login",
            json={"username": "agent", "password": "wrong"},
        )
        client.post(
            "/api/v1/auth/login",
            json={"username": "agent", "password": "wrong"},
        )
        ok = client.post(
            "/api/v1/auth/login",
            json={"username": "agent", "password": "agent123"},
        )
        assert ok.status_code == 200
        # 再错 4 次（阈值 5）不应被锁，证明计数已重置
        for _ in range(4):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "agent", "password": "wrong"},
            )
            assert resp.status_code == 401
        still_ok = client.post(
            "/api/v1/auth/login",
            json={"username": "agent", "password": "agent123"},
        )
        assert still_ok.status_code == 200

    def test_nonexistent_user_also_counts_but_returns_401(self, client):
        """不存在用户名连续失败同样计数，但锁定前响应仍是统一的 401。"""
        for _ in range(4):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "ghost-user", "password": "x"},
            )
            assert resp.status_code == 401
        fifth = client.post(
            "/api/v1/auth/login",
            json={"username": "ghost-user", "password": "x"},
        )
        # 第 5 次本身仍先返回 401（计数发生在拒绝时），第 6 次才 429
        assert fifth.status_code == 401
        sixth = client.post(
            "/api/v1/auth/login",
            json={"username": "ghost-user", "password": "x"},
        )
        assert sixth.status_code == 429


# ============================================================
# 默认密码标志与改密
# ============================================================


class TestDefaultPasswordFlag:
    def test_login_response_flags_seed_account(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["must_change_password"] is True

    def test_me_flags_seed_account(self, client, admin_token):
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.json()["must_change_password"] is True

    def test_flag_clears_after_password_change(self, client):
        """admin 走完改密后标志变 False；用例结束恢复出厂密码避免污染会话库。"""
        from src.api.auth import hash_password
        from src.db.repositories import user_get_by_username, user_update

        token = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        ).json()["token"]
        try:
            resp = client.post(
                "/api/v1/auth/change-password",
                json={"old_password": "admin123", "new_password": "Adm!n-2026-Rotated"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200

            # 旧密码登录失败，新密码登录成功且标志消失
            old = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "admin123"},
            )
            assert old.status_code == 401
            relogin = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "Adm!n-2026-Rotated"},
            )
            assert relogin.status_code == 200
            assert relogin.json()["user"]["must_change_password"] is False
        finally:
            # 恢复出厂密码，保证同 session 内存库后续用例的 admin fixture 可用
            admin = user_get_by_username("admin")
            user_update(admin["user_id"], {"password_hash": hash_password("admin123")})


class TestChangePasswordValidation:
    def test_wrong_old_password_rejected(self, client, admin_token):
        resp = client.post(
            "/api/v1/auth/change-password",
            json={"old_password": "totally-wrong", "new_password": "NewPass!2026"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    def test_new_password_same_as_old_rejected(self, client, admin_token):
        resp = client.post(
            "/api/v1/auth/change-password",
            json={"old_password": "admin123", "new_password": "admin123"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    def test_new_password_equal_other_seed_default_rejected(self, client, admin_token):
        """不能改成别的出厂密码（viewer123 / agent123）。"""
        resp = client.post(
            "/api/v1/auth/change-password",
            json={"old_password": "admin123", "new_password": "viewer123"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    def test_weak_new_password_rejected_by_schema(self, client, admin_token):
        """短于 8 位由 pydantic 校验，返回 422。"""
        resp = client.post(
            "/api/v1/auth/change-password",
            json={"old_password": "admin123", "new_password": "Ab1!"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    def test_change_password_requires_auth(self, client):
        resp = client.post(
            "/api/v1/auth/change-password",
            json={"old_password": "admin123", "new_password": "NewPass!2026"},
        )
        assert resp.status_code == 401


# ============================================================
# 强制改密拦截
# ============================================================


class TestEnforceDefaultPasswordChange:
    def test_business_endpoint_blocked_when_enabled(self, client, monkeypatch):
        """开关开启时，默认密码 token 访问业务接口返回 403 + 专用错误码。"""
        from src.config import settings

        monkeypatch.setattr(settings, "require_default_password_change", True)
        resp = client.post(
            "/api/v1/chat",
            json={"message": "你好"},
            headers={"Authorization": "Bearer admin-token-placeholder"},
        )
        # 先确认占位 token 会因无效被 401，因此下面用真实 token 重测
        assert resp.status_code == 401

        token = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        ).json()["token"]
        blocked = client.post(
            "/api/v1/chat",
            json={"message": "你好"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    def test_whitelisted_endpoints_remain_open(self, client, monkeypatch):
        """拦截开启时，/auth/me 与 /auth/change-password 仍可访问。"""
        from src.config import settings

        monkeypatch.setattr(settings, "require_default_password_change", True)
        token = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        ).json()["token"]

        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 200

        # change-password 走到旧密码校验，证明依赖层已放行
        cp = client.post(
            "/api/v1/auth/change-password",
            json={"old_password": "wrong-old", "new_password": "NewPass!2026"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cp.status_code == 400

    def test_disabled_switch_allows_business_access(
        self, client, admin_token, monkeypatch
    ):
        """开关关闭（现网灰度豁免）时默认密码账号可正常访问业务接口。"""
        from src.config import settings

        monkeypatch.setattr(settings, "require_default_password_change", False)
        resp = client.post(
            "/api/v1/chat",
            json={"message": "你好"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    def test_optional_auth_route_also_blocked(self, client, monkeypatch):
        """可选鉴权链路（/sessions）不得绕过强制改密：默认密码 token 同样 403。"""
        from src.config import settings

        monkeypatch.setattr(settings, "require_default_password_change", True)
        token = client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "viewer123"},
        ).json()["token"]
        resp = client.get(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    def test_suspended_user_blocked_on_optional_route(self, client):
        """停用账号 token 在可选鉴权链路上也必须 403（P0-1 收口一致性）。"""
        from src.db.repositories import user_get_by_username, user_update

        viewer = user_get_by_username("viewer")
        token = client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "viewer123"},
        ).json()["token"]
        user_update(viewer["user_id"], {"status": "suspended"})
        try:
            resp = client.get(
                "/api/v1/sessions",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403
        finally:
            user_update(viewer["user_id"], {"status": "active"})


# ============================================================
# 生产 JWT_SECRET 强校验
# ============================================================


class TestProductionJwtSecret:
    def test_production_with_placeholder_secret_rejected(self):
        from src.config import Settings

        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            Settings(
                app_env="production",
                jwt_secret="enterprise-agent-dev-secret-please-change-in-prod",
            )

    def test_production_with_empty_secret_rejected(self):
        from src.config import Settings

        with pytest.raises(RuntimeError):
            Settings(app_env="production", jwt_secret="   ")

    def test_production_with_real_secret_ok(self):
        from src.config import Settings

        s = Settings(app_env="production", jwt_secret="a" * 64)
        assert s.jwt_secret == "a" * 64

    def test_development_placeholder_falls_back_to_dev_secret(self):
        from src.config import Settings

        s = Settings(app_env="development", jwt_secret="")
        # dev 模式走随机/持久化兜底，最终拿到非空且非占位密钥
        assert s.jwt_secret
        assert s.jwt_secret != "enterprise-agent-dev-secret-please-change-in-prod"

    def test_environment_env_var_triggers_production_guard(self, monkeypatch):
        """ENVIRONMENT=production 经环境变量映射后，缺密钥同样拒启动。"""
        from src.config import Settings

        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(RuntimeError):
            Settings()
