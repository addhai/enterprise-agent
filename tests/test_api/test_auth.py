"""Auth 认证模块单元测试

覆盖：
- 默认账号初始化（admin/agent/viewer）
- 登录接口（正确/错误凭证）
- token 校验机制
- /auth/me 接口
- /rbac/me/permissions 接口
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI 测试客户端"""
    from src.api.server import app
    # 默认账号（admin/agent/viewer）由 tests/conftest.py 的 _init_test_database
    # 在 session 级用内存 SQLite 完成建表 + seed，无需再手动初始化。
    return TestClient(app)


@pytest.fixture
def admin_token(client):
    """获取 admin token"""
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin123",
    })
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture
def agent_token(client):
    """获取 agent token"""
    resp = client.post("/api/v1/auth/login", json={
        "username": "agent",
        "password": "agent123",
    })
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture
def viewer_token(client):
    """获取 viewer token"""
    resp = client.post("/api/v1/auth/login", json={
        "username": "viewer",
        "password": "viewer123",
    })
    assert resp.status_code == 200
    return resp.json()["token"]


# ============================================================
# 默认账号测试
# ============================================================

class TestDefaultAccounts:
    """默认账号初始化测试"""

    def test_admin_account_exists(self, client):
        """admin 账号应存在并可登录"""
        resp = client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_agent_account_exists(self, client):
        """agent 账号应存在并可登录"""
        resp = client.post("/api/v1/auth/login", json={
            "username": "agent",
            "password": "agent123",
        })
        assert resp.status_code == 200

    def test_viewer_account_exists(self, client):
        """viewer 账号应存在并可登录"""
        resp = client.post("/api/v1/auth/login", json={
            "username": "viewer",
            "password": "viewer123",
        })
        assert resp.status_code == 200


# ============================================================
# 登录接口测试
# ============================================================

class TestLoginApi:
    """/auth/login 接口测试"""

    def test_login_success_returns_token(self, client):
        """登录成功应返回 token"""
        resp = client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert len(data["token"]) > 10

    def test_login_wrong_password(self, client):
        """错误密码应返回 401"""
        resp = client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "wrong-password",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        """不存在用户应返回 401"""
        resp = client.post("/api/v1/auth/login", json={
            "username": "nonexistent",
            "password": "whatever",
        })
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        """缺少字段应返回 422"""
        resp = client.post("/api/v1/auth/login", json={"username": "admin"})
        assert resp.status_code == 422


# ============================================================
# token 校验机制测试
# ============================================================

class TestTokenValidation:
    """token 校验机制测试"""

    def test_valid_token_works(self, client, admin_token):
        """有效 token 应能访问受保护接口"""
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

    def test_invalid_token_rejected(self, client):
        """无效 token 应返回 401"""
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token-xxx"},
        )
        assert resp.status_code == 401

    def test_missing_auth_header(self, client):
        """缺少 Authorization header 应返回 401"""
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_malformed_auth_header(self, client):
        """格式错误的 Authorization header 应返回 401"""
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "NotBearer xxx"},
        )
        assert resp.status_code == 401

    def test_different_users_get_different_tokens(self, client):
        """不同用户应获得不同 token"""
        admin_resp = client.post("/api/v1/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        viewer_resp = client.post("/api/v1/auth/login", json={
            "username": "viewer", "password": "viewer123",
        })
        assert admin_resp.json()["token"] != viewer_resp.json()["token"]


# ============================================================
# /auth/me 接口测试
# ============================================================

class TestAuthMeApi:
    """/auth/me 接口测试"""

    def test_admin_me(self, client, admin_token):
        """admin 用户信息应正确（默认 admin 账号角色为 super_admin）"""
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "super_admin"

    def test_viewer_me(self, client, viewer_token):
        """viewer 用户信息应正确"""
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "viewer"
        assert data["role"] == "viewer"


# ============================================================
# /rbac/me/permissions 接口测试
# ============================================================

class TestMyPermissionsApi:
    """/rbac/me/permissions 接口测试"""

    def test_admin_permissions(self, client, admin_token):
        """admin（实际角色 super_admin）应拥有全部权限，且包含 config:manage"""
        from src.api.rbac import Permission

        resp = client.get(
            "/api/v1/rbac/me/permissions",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "super_admin"
        perms = data["permissions"]
        # super_admin = 全量权限，与枚举同步而非硬编码数量
        assert len(perms) == len(Permission)
        assert "config:view" in perms
        assert "config:manage" in perms
        assert "evaluation:manage" in perms
        assert "workflow:manage" in perms

    def test_agent_permissions(self, client, agent_token):
        """agent 权限集合应与 ROLE_PERMISSIONS 一致，且不含任何 manage 类写权限。

        断言「集合 + 不变量」而非数量：数量会随业务扩展漂移，而「坐席不得拥有
        配置/评估/工作流的写权限」是恒定的安全契约，必须被精确守住。
        """
        from src.api.rbac import ROLE_PERMISSIONS, UserRole

        resp = client.get(
            "/api/v1/rbac/me/permissions",
            headers={"Authorization": f"Bearer {agent_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "agent"
        perms = set(data["permissions"])

        expected = {p.value for p in ROLE_PERMISSIONS[UserRole.AGENT]}
        assert perms == expected, f"agent 权限与配置不一致，差异: {perms ^ expected}"

        # 安全不变量：坐席只读新增模块
        assert "config:view" in perms
        for forbidden in ("config:manage", "evaluation:manage", "workflow:manage", "user:manage"):
            assert forbidden not in perms, f"agent 不应拥有 {forbidden}"

    def test_viewer_permissions(self, client, viewer_token):
        """viewer 应为纯只读角色：集合与配置一致，且不含任何 :manage 权限。"""
        from src.api.rbac import ROLE_PERMISSIONS, UserRole

        resp = client.get(
            "/api/v1/rbac/me/permissions",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "viewer"
        perms = set(data["permissions"])

        expected = {p.value for p in ROLE_PERMISSIONS[UserRole.VIEWER]}
        assert perms == expected, f"viewer 权限与配置不一致，差异: {perms ^ expected}"

        # 安全不变量：只读角色不得持有任何写权限
        writable = [p for p in perms if p.endswith(":manage") or p.endswith(":assign")]
        assert not writable, f"viewer 不应拥有写权限: {writable}"

    def test_permissions_endpoint_requires_auth(self, client):
        """/rbac/me/permissions 应需要认证"""
        resp = client.get("/api/v1/rbac/me/permissions")
        assert resp.status_code == 401
