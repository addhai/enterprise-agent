"""WebSocket /ws/chat 多租户隔离与越权防护集成测试

锁定（对应 src/websocket/routes.py:_resolve_ws_identity）：
  - 匿名连接：每个连接按「连接粒度」隔离租户（anon-<session_id>），不同匿名会话互不串台
  - 登录连接：携带有效 JWT → 解码 sub → 查库取真实 tenant_id，租户以服务端解析为准
  - 越权防护：客户端无法通过 URL / 消息体注入 tenant_id（服务端一律以 token 查库结果为准）
  - 伪造 token：签名校验失败 → 降级为匿名隔离会话，无法冒充他人

这些断言直接证明后端在 WS 层实现了多租户 RBAC 隔离，可随 CI 长期复跑。
"""
from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

from src.api.jwt_utils import create_access_token
from src.api.server import app
from src.config import settings
from src.websocket.session_manager import get_session_manager


def _client() -> TestClient:
    return TestClient(app)


def _admin_token(client: TestClient) -> str:
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _ensure_tenant(client: TestClient, tenant_id: str):
    """注册用户前必须先有租户（auth 校验 tenant_exists）。已存在则忽略 409。"""
    token = _admin_token(client)
    r = client.post(
        "/api/v1/admin/tenants",
        json={"tenant_id": tenant_id, "name": tenant_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code in (200, 409), r.text
    return tenant_id


def _register(client: TestClient, tenant_id: str):
    """注册一个属于指定租户的用户，返回 (token, user_id)。"""
    _ensure_tenant(client, tenant_id)
    username = f"tiso_{uuid.uuid4().hex[:10]}"
    r = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "pass123456", "tenant_id": tenant_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["token"], body["user"]["user_id"]


def _cleanup_session(session_id: str):
    try:
        get_session_manager().remove_session(session_id)
    except Exception:
        pass


def test_anonymous_ws_gets_per_connection_isolated_tenant():
    """两个匿名连接 → 各自独立 tenant 命名空间，互不串台。"""
    client = _client()
    sids: list[str] = []
    tenants: list[str] = []
    try:
        # 连接 1
        with client.websocket_connect("/ws/chat") as ws1:
            ready1 = ws1.receive_json()
            assert ready1["type"] == "session_ready"
            sid1 = ready1["session_id"]
            s1 = get_session_manager().get_session(sid1)
            assert s1.tenant_id.startswith("anon-"), s1.tenant_id
            assert s1.user_id == "anonymous"
            sids.append(sid1)
            tenants.append(s1.tenant_id)

        # 连接 2（全新连接）
        with client.websocket_connect("/ws/chat") as ws2:
            ready2 = ws2.receive_json()
            assert ready2["type"] == "session_ready"
            sid2 = ready2["session_id"]
            s2 = get_session_manager().get_session(sid2)
            assert s2.tenant_id.startswith("anon-"), s2.tenant_id
            sids.append(sid2)
            tenants.append(s2.tenant_id)

        # 两个匿名会话的 tenant 命名空间必须不同（隔离）
        assert tenants[0] != tenants[1], "两个匿名连接的租户命名空间不应相同"
        # 命名空间与各自 session 绑定
        assert tenants[0] == f"anon-{sids[0]}"
        assert tenants[1] == f"anon-{sids[1]}"
    finally:
        for s in sids:
            _cleanup_session(s)


def test_authenticated_ws_derives_real_tenant_from_token():
    """登录用户带 JWT 连接 → 服务端查库取真实 tenant_id，而非客户端声明。"""
    client = _client()
    tenant = f"acme_iso_{uuid.uuid4().hex[:8]}"
    token, user_id = _register(client, tenant)

    try:
        with client.websocket_connect(f"/ws/chat?token={token}") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "session_ready"
            sid = ready["session_id"]
            s = get_session_manager().get_session(sid)
            # 关键断言：租户来自 token 对应的 DB 用户记录，而非客户端任意声明
            assert s.tenant_id == tenant, (s.tenant_id, tenant)
            assert s.user_id == user_id
    finally:
        _cleanup_session(sid)


def test_ws_ignores_client_supplied_tenant_for_privilege_escalation():
    """越权防护：即使客户端在消息体伪造 tenant_id，服务端会话 tenant 仍由 token 决定。"""
    client = _client()
    tenant = f"acme_safe_{uuid.uuid4().hex[:8]}"
    token, _ = _register(client, tenant)

    try:
        with client.websocket_connect(f"/ws/chat?token={token}") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "session_ready"
            sid = ready["session_id"]
            s = get_session_manager().get_session(sid)
            assert s.tenant_id == tenant  # 连接建立时即来自 token

            # 客户端在 resume_session 消息体里伪造一个其它租户
            ws.send_text(json.dumps({
                "type": "resume_session",
                "session_id": sid,
                "tenant_id": "evil_tenant_should_be_ignored",
            }))
            resumed = ws.receive_json()
            assert resumed["type"] == "session_resumed"
            # 服务端会话 tenant 不变，仍以 token 查库结果为准（防越权串租户）
            assert s.tenant_id == tenant
            assert s.tenant_id != "evil_tenant_should_be_ignored"
    finally:
        _cleanup_session(sid)


def test_forged_token_downgrades_to_anonymous_isolation():
    """伪造 token（错误签名 secret）→ 校验失败，降级为匿名隔离，无法冒充。"""
    client = _client()
    # 用错误 secret 签发，后端用正确 secret 解码会失败
    forged = create_access_token(
        "victim_user", secret="wrong-secret-not-the-real-one",
        extra_claims={"tenant_id": "victim_tenant"},
    )
    assert forged != ""
    try:
        with client.websocket_connect(f"/ws/chat?token={forged}") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "session_ready"
            sid = ready["session_id"]
            s = get_session_manager().get_session(sid)
            # 伪造 token 无效 → 降级匿名，无法冒充 victim 的租户/身份
            assert s.user_id == "anonymous"
            assert s.tenant_id.startswith("anon-"), s.tenant_id
            assert s.tenant_id != "victim_tenant"
    finally:
        _cleanup_session(sid)
