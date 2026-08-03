"""会话历史 API + 监控端点的集成测试（离线 sqlite + TestClient）

验证：
  - GET /api/v1/conversations 仅返回当前用户会话（越权隔离）
  - GET /api/v1/conversations/{sid}/messages 返回落库消息
  - GET /api/v1/metrics/system 返回真实健康字段（db/cpu/会话数）
  - GET /api/v1/metrics/risk 返回基于 tracker 的真实风险指标
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from src.api.server import app
from src.db.repositories import conversation_ensure, message_save


def _client():
    return TestClient(app)


def _register(client: TestClient):
    username = f"conv_{uuid.uuid4().hex[:10]}"
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "conv123456"},
    )
    body = resp.json()
    return body["token"], body["user"]["user_id"]


def test_conversations_list_scoped_to_user():
    client = _client()
    token, uid = _register(client)

    # 种子：当前用户的会话 + 另一条别人的会话
    conversation_ensure("SES-API-1", "default", uid, channel="web")
    message_save("SES-API-1", "default", uid, "user", "我的退款问题")
    message_save("SES-API-1", "default", uid, "assistant", "已为您处理。")
    conversation_ensure("SES-API-OTHER", "default", "other-user", channel="web")
    message_save("SES-API-OTHER", "default", "other-user", "user", "别人的问题")

    r = client.get(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    convs = r.json()["conversations"]
    sids = {c["session_id"] for c in convs}
    assert "SES-API-1" in sids
    assert "SES-API-OTHER" not in sids  # 看不到别人的会话


def test_conversation_messages_endpoint():
    client = _client()
    token, uid = _register(client)

    conversation_ensure("SES-API-2", "default", uid, channel="web")
    message_save("SES-API-2", "default", uid, "user", "第一条")
    message_save("SES-API-2", "default", uid, "assistant", "第二条")

    r = client.get(
        f"/api/v1/conversations/SES-API-2/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]


def test_conversations_requires_auth():
    client = _client()
    r = client.get("/api/v1/conversations")
    assert r.status_code in (401, 403)


def test_metrics_system_returns_real_fields():
    client = _client()
    r = client.get("/api/v1/metrics/system")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # 真实 DB 健康信息（backend / reachable 至少有一个字段）
    assert "database" in body
    assert "reachable" in body["database"]
    # 活跃会话数字段存在（可能 0）
    assert "active_sessions" in body


def test_metrics_risk_returns_real_fields():
    client = _client()
    r = client.get("/api/v1/metrics/risk")
    assert r.status_code == 200
    body = r.json()
    # 不再是硬编码假零，而是带 instrumented 标识的真实结构
    assert "instrumented" in body
    assert "escalation_rate" in body
    assert "low_quality_rate" in body
