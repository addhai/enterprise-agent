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
    # 真实安全计数已暴露（注入拦截 / 安全违规 / 事件明细）
    assert "prompt_injections_blocked" in body
    assert "safety_violations" in body
    assert "safety_events" in body
    assert isinstance(body["prompt_injections_blocked"], int)
    assert isinstance(body["safety_events"], dict)


def test_metrics_risk_exposes_hallucination_fields():
    """/metrics/risk 应暴露 hallucinations_detected / hallucinations_blocked 真实计数。"""
    from src.evaluation.tracker import get_evaluation_tracker

    tracker = get_evaluation_tracker()
    before_detected = tracker.stats().get("hallucinations_detected", 0)
    before_blocked = tracker.stats().get("hallucinations_blocked", 0)
    tracker.record_safety_event("hallucination_detected")
    tracker.record_safety_event("hallucination_blocked")

    client = _client()
    r = client.get("/api/v1/metrics/risk")
    assert r.status_code == 200
    body = r.json()
    assert body["hallucinations_detected"] == before_detected + 1
    assert body["hallucinations_blocked"] == before_blocked + 1
    # safety_events 明细也要包含原始 key
    assert body["safety_events"].get("hallucination_detected") == before_detected + 1
    assert body["safety_events"].get("hallucination_blocked") == before_blocked + 1


def test_tracker_records_real_safety_events():
    """EvaluationTracker 真实累计安全事件（供 /metrics/risk 暴露）。"""
    from src.evaluation.tracker import get_evaluation_tracker

    tracker = get_evaluation_tracker()
    before = tracker.stats().get("prompt_injections_blocked", 0)
    tracker.record_safety_event("prompt_injection_blocked")
    tracker.record_safety_event("safety_violation")
    after = tracker.stats()
    assert after["prompt_injections_blocked"] == before + 1
    assert after["safety_violations"] == 1
    assert after["safety_events"].get("safety_violation") == 1


def test_delete_conversation_removes_messages():
    client = _client()
    token, uid = _register(client)
    conversation_ensure("SES-DEL-1", "default", uid, channel="web")
    message_save("SES-DEL-1", "default", uid, "user", "待删除")
    message_save("SES-DEL-1", "default", uid, "assistant", "也会被删")

    r = client.delete(
        "/api/v1/conversations/SES-DEL-1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["success"] is True

    # 删除后再查消息 → 404（会话与消息均已从 DB 删除）
    m = client.get(
        "/api/v1/conversations/SES-DEL-1/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert m.status_code == 404


def test_delete_nonexistent_returns_404():
    client = _client()
    token, _ = _register(client)
    r = client.delete(
        "/api/v1/conversations/NOPE-XYZ",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_admin_sessions_merges_persisted_db_sessions():
    """管理员会话列表/详情应合并持久化 DB 的历史会话（重启后可见）。"""
    client = _client()
    token, _ = _register(client)

    # 直接往 DB 写一条不在内存的会话
    conversation_ensure("SES-DB-ADM", "default", "user_db", channel="web")
    message_save("SES-DB-ADM", "default", "user_db", "user", "你好")
    message_save("SES-DB-ADM", "default", "user_db", "assistant", "您好，有什么可以帮您？")

    r = client.get("/api/v1/admin/sessions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    sids = {s["session_id"] for s in r.json()["sessions"]}
    assert "SES-DB-ADM" in sids

    d = client.get(
        "/api/v1/admin/sessions/SES-DB-ADM",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert d.status_code == 200
    body = d.json()
    assert body["session_id"] == "SES-DB-ADM"
    assert len(body["conversation_history"]) == 2


def test_user_sessions_merges_persisted_db_sessions_scoped():
    """普通用户会话列表应合并自己的持久化会话，且看不到别人的。"""
    client = _client()
    token, uid = _register(client)

    conversation_ensure("SES-DB-USR", "default", uid, channel="web")
    message_save("SES-DB-USR", "default", uid, "user", "我的订单")
    conversation_ensure("SES-DB-OTHER2", "default", "stranger", channel="web")
    message_save("SES-DB-OTHER2", "default", "stranger", "user", "别人的订单")

    r = client.get("/api/v1/sessions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    sids = {s["session_id"] for s in r.json()["sessions"]}
    assert "SES-DB-USR" in sids
    assert "SES-DB-OTHER2" not in sids


# ============================================================
# 统一会话 API（共享 service 层）—— 5 个新增测试
# ============================================================

def test_user_session_detail_returns_own_history():
    """普通用户 GET /sessions/{sid} 返回自己的会话详情（DB 历史回退）。"""
    client = _client()
    token, uid = _register(client)

    conversation_ensure("SES-USR-DET", "default", uid, channel="web")
    message_save("SES-USR-DET", "default", uid, "user", "你好")
    message_save("SES-USR-DET", "default", uid, "assistant", "您好，请问需要什么帮助？")

    r = client.get(
        "/api/v1/sessions/SES-USR-DET",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "SES-USR-DET"
    # DB 回退路径会填充 conversation_history
    assert len(body["conversation_history"]) == 2
    assert body["conversation_history"][0]["role"] == "user"


def test_user_session_detail_403_for_other_users():
    """普通用户访问别人的会话详情应返回 403（统一 service 层归属校验）。"""
    client = _client()
    token_a, _ = _register(client)
    # 直接往 DB 写一条属于 other-user 的会话
    conversation_ensure("SES-OTHER-DET", "default", "other-user", channel="web")
    message_save("SES-OTHER-DET", "default", "other-user", "user", "别人的会话")

    r = client.get(
        "/api/v1/sessions/SES-OTHER-DET",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 403


def test_conversation_messages_403_for_viewer_role_users():
    """viewer 角色用户访问别人会话的 /conversations/{sid}/messages 应返回 403。

    注册默认创建 role=agent 用户（被 service 层视为管理员，可跨用户访问），
    因此要测试跨用户 403 必须显式构造一个 role=viewer 的低权限用户。
    """
    import time as _time
    import uuid as _uuid
    from src.db.repositories import user_create
    from src.api.jwt_utils import create_access_token
    from src.config import settings  # JWT secret

    client = _client()
    # 直接往 DB 写一条属于 other-user 的会话
    conversation_ensure("SES-CONV-OTHER", "default", "other-user", channel="web")
    message_save("SES-CONV-OTHER", "default", "other-user", "user", "别人的会话")

    # 构造一个 viewer 角色用户
    viewer_id = str(_uuid.uuid4())
    user_create({
        "user_id": viewer_id,
        "username": f"viewer_{_uuid.uuid4().hex[:8]}",
        "password_hash": "dummy",
        "avatar": "V",
        "created_at": _time.time(),
        "is_admin": False,
        "role": "viewer",
        "status": "active",
        "email": "viewer@test.local",
        "department": "test",
    })
    # 用 JWT 生成 viewer 的 access token（替代旧的 _tokens 内存字典）
    token = create_access_token(viewer_id, settings.jwt_secret)

    r = client.get(
        "/api/v1/conversations/SES-CONV-OTHER/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_user_deletes_own_session_from_memory_and_db():
    """普通用户 DELETE /sessions/{sid} 同时从内存与 DB 删除。"""
    client = _client()
    token, uid = _register(client)
    conversation_ensure("SES-USR-DEL", "default", uid, channel="web")
    message_save("SES-USR-DEL", "default", uid, "user", "待删除")

    r = client.delete(
        "/api/v1/sessions/SES-USR-DEL",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["success"] is True

    # 删除后再查详情 → 404（DB 也已删除）
    r2 = client.get(
        "/api/v1/sessions/SES-USR-DEL",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 404


def test_admin_delete_any_session():
    """管理员 DELETE /admin/sessions/{sid} 可删除任意用户的会话。"""
    client = _client()
    token, _ = _register(client)  # 默认 role=agent（满足 ADMIN/AGENT 校验）
    # 写一条属于 third-user 的会话
    conversation_ensure("SES-ADM-DEL", "default", "third-user", channel="web")
    message_save("SES-ADM-DEL", "default", "third-user", "user", "待管理员删除")

    r = client.delete(
        "/api/v1/admin/sessions/SES-ADM-DEL",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["success"] is True

    # 删除后再查 → 404
    r2 = client.get(
        "/api/v1/admin/sessions/SES-ADM-DEL",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 404
