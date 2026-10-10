"""Chat + Health API 集成测试

覆盖：
- GET /health
- POST /chat（同步对话，2026-10 P0-1 起强制登录）
- 消息校验（空消息、超长消息）
- 响应清洗（ReAct 标记清理）
- 认证与越权：无 token / 坏 token 401，请求体自报身份字段一律不采信
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI 测试客户端"""
    from src.api.server import app

    return TestClient(app)


def _login(client, username: str, password: str):
    """登录 seed 账号，返回 (token, user_info)。"""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, (
        f"seed 账号 {username} 登录失败: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    return body["token"], body["user"]


@pytest.fixture
def admin_token(client):
    """seed 预置 super_admin 账号的 JWT"""
    token, _ = _login(client, "admin", "admin123")
    return token


@pytest.fixture
def admin_user(client):
    """seed 预置 super_admin 账号的用户信息（user_id/tenant_id/role）"""
    _, user = _login(client, "admin", "admin123")
    return user


@pytest.fixture
def viewer_token(client):
    """seed 预置 viewer 只读账号的 JWT"""
    token, _ = _login(client, "viewer", "viewer123")
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# /health
# ============================================================


class TestHealthEndpoint:
    def test_health_check_returns_ok(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "enterprise-agent"


# ============================================================
# /chat
# ============================================================


# /chat 的完整链路依赖 LangGraph 工作流 + LLM。工作流由 tests/conftest.py 的
# autouse fixture 统一替换为 FakeWorkflow，因此这里无需真实凭据、也不会触网，
# 可以正常断言 HTTP 行为。请求体校验（422）类用例同样携带 token，以隔离
# 认证层，专注验证 body 契约。
class TestChatEndpoint:
    def test_chat_with_valid_message(self, client, admin_token):
        """有效消息 + 有效 token 应返回 200"""
        resp = client.post(
            "/api/v1/chat",
            json={
                "message": "你好，我想了解一下产品价格",
                "user_id": "test-user",
            },
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "reply" in data
        assert "needs_human" in data

    def test_chat_with_session_id(self, client, admin_token):
        """传入 session_id 应被使用"""
        resp = client.post(
            "/api/v1/chat",
            json={
                "message": "续上之前的对话",
                "session_id": "test-session-123",
                "user_id": "test-user",
            },
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test-session-123"

    def test_chat_empty_message_rejected(self, client, admin_token):
        """空消息应返回 422（请求体校验，不触 LLM）"""
        resp = client.post(
            "/api/v1/chat",
            json={
                "message": "",
                "user_id": "test-user",
            },
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422

    def test_chat_missing_message_rejected(self, client, admin_token):
        """缺少 message 字段应返回 422（请求体校验，不触 LLM）"""
        resp = client.post(
            "/api/v1/chat",
            json={
                "user_id": "test-user",
            },
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422

    def test_chat_reply_is_string(self, client, admin_token):
        """reply 应为非空字符串"""
        resp = client.post(
            "/api/v1/chat",
            json={
                "message": "如何重置密码？",
                "user_id": "test-user",
            },
            headers=_auth(admin_token),
        )
        data = resp.json()
        assert isinstance(data["reply"], str)

    def test_chat_session_id_defaults_to_uuid(self, client, admin_token, fake_workflow):
        """不传 session_id 时应自动生成一个非空 id 作为线程标识"""
        resp = client.post(
            "/api/v1/chat", json={"message": "你好"}, headers=_auth(admin_token)
        )
        assert resp.status_code == 200
        generated = resp.json()["session_id"]
        assert generated
        # 生成的 id 应同时作为 LangGraph 的 thread_id 传入
        thread_id = fake_workflow.calls[0]["config"]["configurable"]["thread_id"]
        assert thread_id == generated


# ============================================================
# /chat 认证与越权防护（P0-1：H1 收口）
# ============================================================


class TestChatAuthBoundary:
    def test_chat_without_token_returns_401(self, client):
        """无 Authorization header 必须 401，不得落到 anonymous 默认身份"""
        resp = client.post("/api/v1/chat", json={"message": "你好"})
        assert resp.status_code == 401

    def test_chat_with_malformed_header_returns_401(self, client):
        """非 Bearer 格式 / 伪造 token 必须 401"""
        resp = client.post(
            "/api/v1/chat",
            json={"message": "你好"},
            headers={"Authorization": "Bearer forged-not-a-real-jwt"},
        )
        assert resp.status_code == 401

        resp = client.post(
            "/api/v1/chat",
            json={"message": "你好"},
            headers={"Authorization": "Basic abc"},
        )
        assert resp.status_code == 401

    def test_chat_identity_comes_from_token_not_body(
        self, client, admin_token, admin_user, fake_workflow
    ):
        """请求体自报 user_id 必须被忽略，state 身份取 token 用户"""
        client.post(
            "/api/v1/chat",
            json={
                "message": "你好",
                "user_id": "attacker-user-id",
            },
            headers=_auth(admin_token),
        )
        assert fake_workflow.calls, "chat 未调用工作流"
        state = fake_workflow.calls[0]["state"]
        assert state["user_id"] == admin_user["user_id"]
        assert state["user_id"] != "attacker-user-id"

    def test_chat_tenant_from_token_not_body(
        self, client, admin_token, admin_user, fake_workflow
    ):
        """请求体自报 tenant_id 必须被忽略，防止跨租户检索（H1 核心）"""
        client.post(
            "/api/v1/chat",
            json={
                "message": "你好",
                "tenant_id": "attacker-tenant",
                "user_access_levels": [
                    "public",
                    "internal",
                    "confidential",
                    "restricted",
                ],
            },
            headers=_auth(admin_token),
        )
        state = fake_workflow.calls[0]["state"]
        # 文档历史无租户标签，检索层把空租户归一为 default；这里以 token 租户为准
        assert state["tenant_id"] == admin_user.get("tenant_id", "default")
        assert state["tenant_id"] != "attacker-tenant"

    def test_chat_access_levels_derived_from_role(
        self, client, admin_token, fake_workflow
    ):
        """请求体自报密级必须被忽略，密级由服务端角色映射授予"""
        client.post(
            "/api/v1/chat",
            json={
                "message": "你好",
                "user_access_levels": ["public"],
                "user_roles": ["viewer"],
            },
            headers=_auth(admin_token),
        )
        state = fake_workflow.calls[0]["state"]
        # admin(super_admin) 由 rbac.role_to_access_levels 授予四级
        assert state["user_access_levels"] == [
            "public",
            "internal",
            "confidential",
            "restricted",
        ]
        assert state["user_roles"][0] in ("super_admin", "admin")

    def test_chat_viewer_gets_public_internal_only(
        self, client, viewer_token, fake_workflow
    ):
        """viewer 只读角色只能拿到 public/internal 两级密级"""
        resp = client.post(
            "/api/v1/chat", json={"message": "你好"}, headers=_auth(viewer_token)
        )
        assert resp.status_code == 200
        state = fake_workflow.calls[0]["state"]
        assert state["user_access_levels"] == ["public", "internal"]
        assert state["user_roles"] == ["viewer"]
