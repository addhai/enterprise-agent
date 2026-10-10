"""websocket/routes.py 单元测试与轻量集成测试

覆盖：
    - ``_build_citations``：纯函数，多文档形态（含空/缺字段/非字符串内容）
    - ``_resolve_ws_identity``：匿名隔离 / JWT 鉴权 / 过期与用户缺失降级
    - ``/ws/chat`` 与 ``/ws/agent/{agent_id}`` 端点：用 TestClient 驱动真实 handler，
      覆盖 connect 握手、心跳、非法 JSON、resume_session、human_escalation、
      坐席回复 / 登出等分支（重活儿 LangGraph 工作流通过 monkeypatch 替换为 Fake）。
    - ``_handle_ai_chat``：直接调用，覆盖 主路径流式 / needs_human 转接 /
      异常兜底 / HITL 中断 / 权限过滤 等核心分支。

不需要真实 LLM / 向量库 / 数据库：依赖项在测试内被 monkeypatch 成 Fake。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from src.api.server import app
from src.websocket.routes import (
    _build_citations,
    _handle_ai_chat,
    _resolve_ws_identity,
)
from src.websocket.session_manager import SessionMode, get_session_manager

try:
    from src.api.jwt_utils import JWTInvalid as _WS_JWTInvalid
except Exception:  # pragma: no cover
    _WS_JWTInvalid = Exception


# ===========================================================================
# Fake 构建块
# ===========================================================================


class FakeWebSocket:
    """记录 send_json 调用、可注入 query_params 的假 WebSocket。

    用于直接调用 handler。
    """

    def __init__(self, token: str | None = None):
        self.sent: list = []
        self._token = token

    @property
    def query_params(self):
        return SimpleNamespace(get=lambda k, d=None: self._token)

    async def accept(self):
        return None

    async def send_json(self, data):
        self.sent.append(data)


class FakeApp:
    """替代 LangGraph 工作流的假 app：invoke 同步返回、get_state 可控"""

    def __init__(self, result: dict, state_next=None, state_tasks=None):
        self.result = result
        self._state_next = state_next
        self._state_tasks = state_tasks or []

    def invoke(self, state, config):
        return self.result

    def get_state(self, config):
        return SimpleNamespace(next=self._state_next, tasks=self._state_tasks)


class FakeTracker:
    def __init__(self):
        self.chat_calls = []
        self.safety_events = []

    def record_chat(self, **kwargs):
        self.chat_calls.append(kwargs)

    def record_safety_event(self, name):
        self.safety_events.append(name)


class FakeHITL:
    def __init__(self):
        self.pending = []

    async def add_pending(self, **kwargs):
        self.pending.append(kwargs)


class FakeDispatcher:
    def __init__(self):
        self.escalations = []
        self.replies = []
        self.session_transfer: str | None = None
        self.transfer_record = None

    async def handle_escalation(self, session_id, result, messages):
        self.escalations.append(session_id)

    async def agent_reply(self, agent_id, session_id, text):
        self.replies.append((agent_id, session_id, text))
        return True

    def get_session_transfer(self, session_id):
        return self.session_transfer

    def get_transfer_record(self, session_id):
        return self.transfer_record


def _dispatch_result(
    final_response: str = "这是回复。第二句。",
    needs_human: bool = False,
    intent: str = "qa",
    quality_score: float = 0.8,
    suggest_human: bool = False,
    failed_attempts: int = 0,
    retrieved_docs=None,
    access_filtered: int = 0,
):
    return {
        "messages": [HumanMessage(content="hi"), AIMessage(content="ok")],
        "final_response": final_response,
        "needs_human": needs_human,
        "intent": intent,
        "quality_score": quality_score,
        "suggest_human": suggest_human,
        "failed_attempts": failed_attempts,
        "retrieved_docs": retrieved_docs or [],
        "access_filtered": access_filtered,
    }


def _patch_chat_deps(monkeypatch, fake_app, fake_tracker, fake_dispatcher, fake_hitl):
    """把 _handle_ai_chat 内的重依赖替换为 Fake"""
    monkeypatch.setattr("src.api.dependencies.get_workflow", lambda: fake_app)
    monkeypatch.setattr("src.db.repositories.conversation_ensure", lambda *a, **k: None)
    monkeypatch.setattr("src.db.repositories.message_save", lambda *a, **k: None)
    monkeypatch.setattr("src.db.repositories.message_list", lambda *a, **k: [])
    monkeypatch.setattr(
        "src.websocket.multimodal.process_multimodal_message",
        lambda m, **k: (m, m),
    )
    monkeypatch.setattr(
        "src.evaluation.tracker.get_evaluation_tracker", lambda: fake_tracker
    )
    monkeypatch.setattr("src.websocket.routes.get_dispatcher", lambda: fake_dispatcher)
    monkeypatch.setattr("src.graph.hitl_manager.get_hitl_manager", lambda: fake_hitl)
    monkeypatch.setattr(
        "src.api.notifications.add_handoff_notification", lambda *a, **k: None
    )


# ===========================================================================
# _build_citations
# ===========================================================================


def test_build_citations_empty():
    assert _build_citations([]) == []
    assert _build_citations(None) == []


def test_build_citations_basic():
    docs = [
        Document(
            page_content="内容A",
            metadata={
                "source": "s1",
                "doc_id": "d1",
                "title": "标题A",
                "kb_id": "kb1",
                "score": 0.9,
            },
        )
    ]
    cites = _build_citations(docs)
    assert len(cites) == 1
    c = cites[0]
    assert c["title"] == "标题A"
    assert c["content"] == "内容A"
    assert c["source"] == "s1"
    assert c["doc_id"] == "d1"
    assert c["kb_id"] == "kb1"
    assert abs(c["score"] - 0.9) < 1e-6


def test_build_citations_no_metadata():
    docs = [Document(page_content="x")]
    cites = _build_citations(docs)
    assert cites[0]["title"] == "未知文档"
    assert cites[0]["source"] == ""
    assert cites[0]["score"] == 0.0


def test_build_citations_rrf_score_fallback():
    docs = [Document(page_content="y", metadata={"rrf_score": 0.42, "source": "s2"})]
    cites = _build_citations(docs)
    assert abs(cites[0]["score"] - 0.42) < 1e-6
    assert cites[0]["source"] == "s2"


class _FakeDoc:
    """模拟非 langchain Document 的检索结果（_build_citations 用 getattr 容错）"""

    def __init__(self, content, metadata):
        self.page_content = content
        self.metadata = metadata


def test_build_citations_non_str_content():
    # page_content 非字符串：函数应降级为 str(content)
    docs = [_FakeDoc(content=12345, metadata={"title": "t"})]
    cites = _build_citations(docs)
    assert cites[0]["content"] == "12345"[:500]
    assert cites[0]["title"] == "t"


def test_build_citations_none_doc_and_non_dict_meta():
    # None 被跳过；metadata 非 dict 退化为 {}；第三条正常 Document
    docs = [
        None,
        _FakeDoc(content="z", metadata="not-a-dict"),
        Document(page_content="w", metadata={"title": "ok"}),
    ]
    cites = _build_citations(docs)
    assert len(cites) == 2
    assert cites[0]["title"] == "未知文档"
    assert cites[1]["title"] == "ok"


def test_build_citations_page_passthrough():
    # Q3：PDF chunk 的 page 戳原样透出（int），非 PDF 缺省为 None
    docs = [
        Document(page_content="a", metadata={"title": "手册", "page": 42}),
        Document(page_content="b", metadata={"title": "md文档"}),
    ]
    cites = _build_citations(docs)
    assert cites[0]["page"] == 42
    assert cites[1]["page"] is None


def test_build_citations_bad_page_coerces_none():
    # page 脏值（字符串数字可转；无法转换时降级 None，不抛异常）
    docs = [
        Document(page_content="a", metadata={"page": "7"}),
        Document(page_content="b", metadata={"page": "not-int"}),
    ]
    cites = _build_citations(docs)
    assert cites[0]["page"] == 7
    assert cites[1]["page"] is None


def test_build_citations_chapter_path_passthrough():
    # 6.4：outline 写入的 chapter_path 原样透出，老块/无章节语料降级 None
    docs = [
        Document(
            page_content="a",
            metadata={"title": "手册", "chapter_path": "1. 概述 / 2.1 认证方式"},
        ),
        Document(page_content="b", metadata={"title": "md文档"}),
    ]
    cites = _build_citations(docs)
    assert cites[0]["chapter_path"] == "1. 概述 / 2.1 认证方式"
    assert cites[1]["chapter_path"] is None


def test_build_citations_blank_chapter_path_is_none():
    # 空白章节路径与非字符串脏值安全降级为 None，不向前端吐空串
    docs = [
        Document(page_content="a", metadata={"chapter_path": "   "}),
        Document(page_content="b", metadata={"chapter_path": 123}),
    ]
    cites = _build_citations(docs)
    assert cites[0]["chapter_path"] is None
    assert cites[1]["chapter_path"] == "123"


# ===========================================================================
# _resolve_ws_identity
# ===========================================================================


def test_resolve_identity_anonymous():
    ws = FakeWebSocket(token=None)
    uid, tid, plan, role, authed = _resolve_ws_identity(ws, "sess-1")
    assert uid == "anonymous"
    assert tid == "anon-sess-1"
    assert plan == "free"
    assert role == ""
    assert authed is False


def test_resolve_identity_authed(monkeypatch):
    ws = FakeWebSocket(token="valid.jwt.token")

    monkeypatch.setattr(
        "src.websocket.routes._ws_decode_token",
        lambda token, secret: {"sub": "u1"},
    )
    monkeypatch.setattr(
        "src.db.repositories.user_get_by_id",
        lambda uid: {"user_id": "u1", "tenant_id": "t1", "role": "admin"},
    )
    uid, tid, plan, role, authed = _resolve_ws_identity(ws, "sess-2")
    assert uid == "u1"
    assert tid == "t1"
    assert plan == "free"
    assert role == "admin"
    assert authed is True


def test_resolve_identity_token_expired_falls_anonymous(monkeypatch):
    ws = FakeWebSocket(token="expired.token")

    def _boom(token, secret):
        raise _WS_JWTInvalid("expired")

    monkeypatch.setattr("src.websocket.routes._ws_decode_token", _boom)
    uid, tid, plan, role, authed = _resolve_ws_identity(ws, "sess-3")
    assert uid == "anonymous"
    assert authed is False


def test_resolve_identity_user_not_found_falls_anonymous(monkeypatch):
    ws = FakeWebSocket(token="valid.jwt.token")
    monkeypatch.setattr(
        "src.websocket.routes._ws_decode_token",
        lambda token, secret: {"sub": "ghost"},
    )
    monkeypatch.setattr("src.db.repositories.user_get_by_id", lambda uid: None)
    uid, tid, plan, role, authed = _resolve_ws_identity(ws, "sess-4")
    assert uid == "anonymous"
    assert authed is False


# ===========================================================================
# /ws/chat 轻量集成测试（TestClient）
# ===========================================================================


def _client() -> TestClient:
    return TestClient(app)


def _patch_route_globals(monkeypatch, fake_dispatcher=None, fake_app=None):
    if fake_dispatcher is not None:
        monkeypatch.setattr(
            "src.websocket.routes.get_dispatcher", lambda: fake_dispatcher
        )
    if fake_app is not None:
        monkeypatch.setattr("src.api.dependencies.get_workflow", lambda: fake_app)
    # 指标打点不应影响测试
    monkeypatch.setattr("src.api.metrics.gauge_inc", lambda *a, **k: None)
    monkeypatch.setattr("src.api.metrics.gauge_dec", lambda *a, **k: None)


def test_chat_connect_session_ready(monkeypatch):
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "session_ready"
        assert "session_id" in ready


def test_chat_heartbeat(monkeypatch):
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text('{"type": "heartbeat"}')
        ack = ws.receive_json()
        assert ack["type"] == "heartbeat_ack"


def test_chat_invalid_json(monkeypatch):
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text("this is not json")
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["error_code"] == "INVALID_JSON"


def _patch_authed(monkeypatch):
    # 让连接以已认证身份建立，绕过匿名守卫（这些用例测的是 resume/handoff 本身）
    monkeypatch.setattr(
        "src.websocket.routes._resolve_ws_identity",
        lambda ws, sid: ("u-test", "t-test", "free", "agent", True),
    )


def test_chat_resume_no_session_id(monkeypatch):
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    _patch_authed(monkeypatch)
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text('{"type": "resume_session"}')
        resp = ws.receive_json()
        assert resp["type"] == "session_resumed"
        assert resp["restored_count"] == 0
        assert "沿用" in (resp.get("message") or "")


def test_chat_resume_new_session_from_db(monkeypatch):
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    _patch_authed(monkeypatch)
    # 模拟从 DB 恢复历史（P0-3 起 message_list 带租户参数）
    monkeypatch.setattr(
        "src.db.repositories.message_list",
        lambda sid, n, tenant_id=None: [
            {"role": "user", "content": "之前问过什么"},
            {"role": "assistant", "content": "之前的回答"},
        ],
    )
    # DB 无会话记录 → 全新 id 允许重建并恢复
    monkeypatch.setattr("src.db.repositories.conversation_get", lambda sid: None)
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text('{"type": "resume_session", "session_id": "old-sess-xyz"}')
        resp = ws.receive_json()
        assert resp["type"] == "session_resumed"
        assert resp["source"] == "database"
        assert resp["session_id"] == "old-sess-xyz"
        assert resp["restored_count"] == 2


def test_chat_resume_memory_other_user_forbidden(monkeypatch):
    """P0-3：内存中属于他人的会话不得续接（H3 IDOR）"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    _patch_authed(monkeypatch)  # 当前身份 u-test / t-test
    mgr = get_session_manager()
    victim_sid = "idor-memory-victim-001"
    mgr.create_session(
        session_id=victim_sid,
        user_id="user-victim",
        tenant_id="t-test",
        mode=SessionMode.AI_CHAT,
    )
    try:
        client = _client()
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()  # session_ready
            ws.send_text(f'{{"type": "resume_session", "session_id": "{victim_sid}"}}')
            frame = ws.receive_json()
            assert frame["type"] == "session_forbidden"
            assert frame["error_code"] == "SESSION_FORBIDDEN"
            # 受害者会话的 ws 引用不得被攻击者连接顶替
            assert mgr.get_session(victim_sid)._websocket_ref is None
    finally:
        mgr.remove_session(victim_sid)


def test_chat_resume_db_other_user_forbidden(monkeypatch):
    """P0-3：DB 中属于他人的会话历史不得恢复，且不得调用 message_list"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    _patch_authed(monkeypatch)  # u-test / t-test
    monkeypatch.setattr(
        "src.db.repositories.conversation_get",
        lambda sid: {
            "id": sid,
            "session_id": sid,
            "user_id": "user-victim",
            "tenant_id": "t-test",
            "status": "active",
        },
    )
    called = {"n": 0}

    def _message_list(sid, n, tenant_id=None):
        called["n"] += 1
        return [{"role": "user", "content": "受害者密语"}]

    monkeypatch.setattr("src.db.repositories.message_list", _message_list)
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()
        ws.send_text('{"type": "resume_session", "session_id": "idor-db-victim-001"}')
        frame = ws.receive_json()
        assert frame["type"] == "session_forbidden"
        assert called["n"] == 0  # 历史拉取必须被挡在校验之前


def test_chat_resume_db_other_tenant_forbidden(monkeypatch):
    """P0-3：同 user_id 跨租户同样拒绝（租户隔离维度）"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    _patch_authed(monkeypatch)  # u-test / t-test
    monkeypatch.setattr(
        "src.db.repositories.conversation_get",
        lambda sid: {
            "id": sid,
            "session_id": sid,
            "user_id": "u-test",
            "tenant_id": "tenant-other",
            "status": "active",
        },
    )
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()
        ws.send_text('{"type": "resume_session", "session_id": "idor-tenant-001"}')
        frame = ws.receive_json()
        assert frame["type"] == "session_forbidden"


def test_chat_resume_own_db_session_restored(monkeypatch):
    """P0-3：归属一致时 DB 历史正常恢复（正向不回归）"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    _patch_authed(monkeypatch)  # u-test / t-test
    monkeypatch.setattr(
        "src.db.repositories.conversation_get",
        lambda sid: {
            "id": sid,
            "session_id": sid,
            "user_id": "u-test",
            "tenant_id": "t-test",
            "status": "active",
        },
    )
    monkeypatch.setattr(
        "src.db.repositories.message_list",
        lambda sid, n, tenant_id=None: (
            [{"role": "user", "content": "我的历史"}] if tenant_id == "t-test" else []
        ),
    )
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()
        ws.send_text('{"type": "resume_session", "session_id": "own-db-session-001"}')
        frame = ws.receive_json()
        assert frame["type"] == "session_resumed"
        assert frame["restored_count"] == 1


def test_chat_human_escalation(monkeypatch):
    disp = FakeDispatcher()
    _patch_route_globals(monkeypatch, fake_dispatcher=disp)
    _patch_authed(monkeypatch)
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        sid = ready["session_id"]
        ws.send_text(
            f'{{"type": "human_escalation", "session_id": "{sid}", '
            '"reason": "user_requested"}'
        )
        # 顺序：transfer_notice + handoff_context
        f1 = ws.receive_json()
        f2 = ws.receive_json()
        types = {f1.get("type"), f2.get("type")}
        assert "transfer_notice" in types
        assert "handoff_context" in types
        assert disp.escalations == [sid]


# ===========================================================================
# /ws/agent/{agent_id} 集成测试
# ===========================================================================


def _patch_agent_auth(monkeypatch, agent_id="agent-007"):
    """让坐席 WS 以指定身份通过强鉴权（P0-2）"""
    monkeypatch.setattr(
        "src.websocket.routes._authenticate_agent_ws",
        lambda ws, aid: (
            {
                "user_id": agent_id,
                "role": "agent",
                "tenant_id": "default",
                "status": "active",
            }
            if aid == agent_id
            else None
        ),
    )


def test_agent_connect_heartbeat_reply_logout(monkeypatch):
    disp = FakeDispatcher()
    _patch_route_globals(monkeypatch, fake_dispatcher=disp)
    _patch_agent_auth(monkeypatch)
    client = _client()
    with client.websocket_connect("/ws/agent/agent-007") as ws:
        # 心跳
        ws.send_text('{"type": "heartbeat"}')
        ack = ws.receive_json()
        assert ack["type"] == "heartbeat_ack"
        # 坐席回复用户
        ws.send_text(
            '{"type": "agent_send_reply", "session_id": "s1", '
            '"text": "您好，马上为您处理"}'
        )
        resp = ws.receive_json()
        assert resp["type"] == "agent_reply_ack"
        assert resp["sent"] is True
        assert disp.replies == [("agent-007", "s1", "您好，马上为您处理")]
        # 登出
        ws.send_text('{"type": "agent_logout"}')


def _expect_ws_rejected(client, url: str):
    """握手应被服务端以 1008 policy violation 拒绝，且连接无法建立。"""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        client.websocket_connect(url).__enter__()
    assert exc_info.value.code == 1008


def test_agent_ws_rejected_without_token(monkeypatch):
    """无 token 连接坐席台必须在握手阶段被 1008 拒绝（H2 核心）"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    client = _client()
    _expect_ws_rejected(client, "/ws/agent/agent-007")


def test_agent_ws_rejected_with_bad_token(monkeypatch):
    """伪造 token 必须被拒"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    client = _client()
    _expect_ws_rejected(client, "/ws/agent/agent-007?token=forged.token.value")


def test_agent_ws_rejected_for_viewer_role(monkeypatch):
    """viewer 只读角色不得接入坐席台"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    monkeypatch.setattr(
        "src.websocket.routes._ws_decode_token",
        lambda token, secret: {"sub": "u-viewer"},
    )
    monkeypatch.setattr(
        "src.db.repositories.user_get_by_id",
        lambda uid: {
            "user_id": "u-viewer",
            "tenant_id": "default",
            "role": "viewer",
            "status": "active",
        },
    )
    client = _client()
    _expect_ws_rejected(client, "/ws/agent/u-viewer?token=valid-looking")


def test_agent_ws_rejected_for_identity_mismatch(monkeypatch):
    """token 身份与路径 agent_id 不一致（抢坐席 id）必须被拒"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    monkeypatch.setattr(
        "src.websocket.routes._ws_decode_token",
        lambda token, secret: {"sub": "agent-A"},
    )
    monkeypatch.setattr(
        "src.db.repositories.user_get_by_id",
        lambda uid: {
            "user_id": "agent-A",
            "tenant_id": "default",
            "role": "agent",
            "status": "active",
        },
    )
    client = _client()
    # A 持自己的 token 想注册成 agent-B
    _expect_ws_rejected(client, "/ws/agent/agent-B?token=valid-looking")


def test_agent_ws_rejected_for_suspended_user(monkeypatch):
    """停用账号即便 token 未过期也必须被拒"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    monkeypatch.setattr(
        "src.websocket.routes._ws_decode_token",
        lambda token, secret: {"sub": "agent-s"},
    )
    monkeypatch.setattr(
        "src.db.repositories.user_get_by_id",
        lambda uid: {
            "user_id": "agent-s",
            "tenant_id": "default",
            "role": "agent",
            "status": "suspended",
        },
    )
    client = _client()
    _expect_ws_rejected(client, "/ws/agent/agent-s?token=valid-looking")


def _patch_seed_agent_token(monkeypatch):
    """模拟 seed agent 账号（密码哈希能验通出厂密码 agent123）的合法 token。"""
    from src.api.auth import hash_password

    monkeypatch.setattr(
        "src.websocket.routes._ws_decode_token",
        lambda token, secret: {"sub": "agent-default"},
    )
    monkeypatch.setattr(
        "src.db.repositories.user_get_by_id",
        lambda uid: {
            "user_id": "agent-default",
            "username": "agent",
            "tenant_id": "default",
            "role": "agent",
            "status": "active",
            "password_hash": hash_password("agent123"),
        },
    )


def test_agent_ws_rejected_for_default_password(monkeypatch):
    """出厂默认密码未改（开关开启）时坐席 WS 必须 1008 拒绝（P0-6）"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    monkeypatch.setattr(
        "src.websocket.routes._ws_settings.require_default_password_change", True
    )
    _patch_seed_agent_token(monkeypatch)
    client = _client()
    _expect_ws_rejected(client, "/ws/agent/agent-default?token=valid-looking")


def test_agent_ws_default_password_allowed_when_switch_off(monkeypatch):
    """现网灰度豁免（开关关闭）时默认密码账号仍可接入并收到心跳响应"""
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    monkeypatch.setattr(
        "src.websocket.routes._ws_settings.require_default_password_change", False
    )
    _patch_seed_agent_token(monkeypatch)
    client = _client()
    with client.websocket_connect("/ws/agent/agent-default?token=valid-looking") as ws:
        ws.send_text('{"type": "heartbeat"}')
        ack = ws.receive_json()
        assert ack["type"] == "heartbeat_ack"


# ===========================================================================
# _handle_ai_chat 直接调用（核心分支）
# ===========================================================================


async def test_handle_ai_chat_happy_path(monkeypatch):
    mgr = get_session_manager()
    sid = "ai-happy-1"
    mgr.create_session(
        session_id=sid, user_id="u1", tenant_id="t1", mode=SessionMode.AI_CHAT
    )
    fake_app = FakeApp(_dispatch_result())
    fake_tracker = FakeTracker()
    fake_disp = FakeDispatcher()
    fake_hitl = FakeHITL()
    _patch_chat_deps(monkeypatch, fake_app, fake_tracker, fake_disp, fake_hitl)

    ws = FakeWebSocket()
    await _handle_ai_chat(ws, sid, "你好", "u1", "t1", "free", mgr)

    types = [f.get("type") for f in ws.sent]
    # 必有：思考中 -> 思考完毕 -> 流式片段 -> 完成标记
    assert "typing_indicator" in types
    assert "streaming_chunk" in types
    done = [f for f in ws.sent if f.get("type") == "streaming_chunk" and f.get("done")]
    assert done, "缺少 done 流式结束标记"
    # 至少一段非空正文
    chunks = [
        f.get("text", "")
        for f in ws.sent
        if f.get("type") == "streaming_chunk" and f.get("text")
    ]
    assert any(chunks), "未推送任何正文片段"
    # 历史已落库到会话状态
    sess = mgr.get_session(sid)
    assert sess is not None
    assert any(m["role"] == "user" for m in sess.conversation_history)
    assert any(m["role"] == "assistant" for m in sess.conversation_history)
    # 业务指标已记录
    assert fake_tracker.chat_calls, "未记录 chat 指标"
    # 不应触发转人工
    assert fake_disp.escalations == []


async def test_handle_ai_chat_needs_human(monkeypatch):
    mgr = get_session_manager()
    sid = "ai-needs-human-1"
    mgr.create_session(
        session_id=sid, user_id="u1", tenant_id="t1", mode=SessionMode.AI_CHAT
    )
    fake_app = FakeApp(_dispatch_result(needs_human=True, intent="complaint"))
    fake_tracker = FakeTracker()
    fake_disp = FakeDispatcher()
    fake_hitl = FakeHITL()
    _patch_chat_deps(monkeypatch, fake_app, fake_tracker, fake_disp, fake_hitl)

    ws = FakeWebSocket()
    await _handle_ai_chat(ws, sid, "我要投诉", "u1", "t1", "free", mgr)

    types = [f.get("type") for f in ws.sent]
    assert "transfer_notice" in types
    assert "handoff_context" in types
    assert fake_disp.escalations == [sid]
    # 会话模式切换为等待人工
    assert mgr.get_session(sid).mode == SessionMode.WAITING_HUMAN
    # 安全计数：escalation 事件被记录
    assert "escalation" in fake_tracker.safety_events


async def test_handle_ai_chat_error_path(monkeypatch):
    mgr = get_session_manager()
    sid = "ai-error-1"
    mgr.create_session(
        session_id=sid, user_id="u1", tenant_id="t1", mode=SessionMode.AI_CHAT
    )

    class BoomApp(FakeApp):
        def invoke(self, state, config):
            raise RuntimeError("simulated pipeline failure")

    fake_app = BoomApp(_dispatch_result())
    fake_tracker = FakeTracker()
    fake_disp = FakeDispatcher()
    fake_hitl = FakeHITL()
    _patch_chat_deps(monkeypatch, fake_app, fake_tracker, fake_disp, fake_hitl)

    ws = FakeWebSocket()
    await _handle_ai_chat(ws, sid, "触发异常", "u1", "t1", "free", mgr)

    errs = [f for f in ws.sent if f.get("type") == "error"]
    assert errs, "异常路径应推送 error 帧"
    assert errs[0]["error_code"] == "CHAT_ERROR"
    # 出错也尝试转人工
    assert fake_disp.escalations == [sid]


async def test_handle_ai_chat_hitl_interrupt(monkeypatch):
    mgr = get_session_manager()
    sid = "ai-hitl-1"
    mgr.create_session(
        session_id=sid, user_id="u1", tenant_id="t1", mode=SessionMode.AI_CHAT
    )

    interrupt = SimpleNamespace(value={"tool": "mcp_xxx", "args": {}})
    task = SimpleNamespace(interrupts=[interrupt])
    fake_app = FakeApp(
        _dispatch_result(), state_next=("__interrupt__",), state_tasks=[task]
    )
    fake_tracker = FakeTracker()
    fake_disp = FakeDispatcher()
    fake_hitl = FakeHITL()
    _patch_chat_deps(monkeypatch, fake_app, fake_tracker, fake_disp, fake_hitl)

    ws = FakeWebSocket()
    await _handle_ai_chat(ws, sid, "敏感操作", "u1", "t1", "free", mgr)

    # 应有 HITL 等待帧
    hitl_frames = [
        f
        for f in ws.sent
        if f.get("type") == "streaming_chunk"
        and (f.get("awaiting_human") or f.get("needs_human"))
    ]
    assert hitl_frames, "HITL 中断应推送等待人工帧"
    assert fake_hitl.pending, "HITL 应登记 pending"
    assert mgr.get_session(sid).mode == SessionMode.WAITING_HUMAN


async def test_handle_ai_chat_access_filtered(monkeypatch):
    mgr = get_session_manager()
    sid = "ai-filtered-1"
    mgr.create_session(
        session_id=sid, user_id="u1", tenant_id="t1", mode=SessionMode.AI_CHAT
    )
    fake_app = FakeApp(_dispatch_result(access_filtered=3))
    fake_tracker = FakeTracker()
    fake_disp = FakeDispatcher()
    fake_hitl = FakeHITL()
    _patch_chat_deps(monkeypatch, fake_app, fake_tracker, fake_disp, fake_hitl)

    ws = FakeWebSocket()
    await _handle_ai_chat(ws, sid, "查内部资料", "u1", "t1", "free", mgr)

    infos = [f for f in ws.sent if f.get("type") == "info"]
    assert infos, "权限过滤应推送 info 提示"
    assert "3" in (infos[0].get("text") or "")


async def test_handle_ai_chat_multimodal_display(monkeypatch):
    mgr = get_session_manager()
    sid = "ai-mm-1"
    mgr.create_session(
        session_id=sid, user_id="u1", tenant_id="t1", mode=SessionMode.AI_CHAT
    )
    fake_app = FakeApp(_dispatch_result())
    fake_tracker = FakeTracker()
    fake_disp = FakeDispatcher()
    fake_hitl = FakeHITL()
    _patch_chat_deps(monkeypatch, fake_app, fake_tracker, fake_disp, fake_hitl)
    # 多模态引擎返回与原文不同的展示文本
    monkeypatch.setattr(
        "src.websocket.multimodal.process_multimodal_message",
        lambda m, **k: ("🖼️ 图片识别结果：一只猫", "[用户发送了一张图片]"),
    )
    ws = FakeWebSocket()
    await _handle_ai_chat(
        ws,
        sid,
        "看这张图",
        "u1",
        "t1",
        "free",
        mgr,
        image_base64="data:image/png;base64,AAAA",
    )
    # 先推送多模态识别结果展示块
    assert any("图片识别结果" in (f.get("text") or "") for f in ws.sent)
    # 主回复仍完成
    assert any(f.get("type") == "streaming_chunk" and f.get("done") for f in ws.sent)


async def test_handle_ai_chat_persistence_failure(monkeypatch):
    mgr = get_session_manager()
    sid = "ai-persist-1"
    mgr.create_session(
        session_id=sid, user_id="u1", tenant_id="t1", mode=SessionMode.AI_CHAT
    )
    fake_app = FakeApp(_dispatch_result())
    fake_tracker = FakeTracker()
    fake_disp = FakeDispatcher()
    fake_hitl = FakeHITL()
    _patch_chat_deps(monkeypatch, fake_app, fake_tracker, fake_disp, fake_hitl)

    # 落库失败应是非致命的：主流程仍走完
    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("src.db.repositories.message_save", _boom)
    monkeypatch.setattr("src.db.repositories.conversation_ensure", _boom)

    ws = FakeWebSocket()
    await _handle_ai_chat(ws, sid, "你好", "u1", "t1", "free", mgr)
    assert any(f.get("type") == "streaming_chunk" and f.get("done") for f in ws.sent)


def test_chat_message_too_long(monkeypatch):
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    _patch_authed(monkeypatch)
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text('{"type": "chat_message", "message": "%s"}' % ("x" * 2001))
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["error_code"] == "MESSAGE_TOO_LONG"


# ===========================================================================
# 匿名访问策略（产品方向 B：匿名引导登录，CURRENT 待办 #2 已决议）
#
# 无 token 连接仍可建立（session_ready 正常），身份固定 anonymous、租户按
# 连接粒度隔离为 anon-<session_id>；但除心跳外的业务动作（问答 / 转人工 /
# 历史续接）一律被身份守卫挡回 need_login(AUTH_REQUIRED)，不触碰数据链路。
# ===========================================================================


def test_anonymous_connection_identity_baseline(monkeypatch):
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        sid = ready["session_id"]
        sess = get_session_manager().get_session(sid)

        # 匿名身份固定，租户按连接粒度隔离，不与任何真实租户共享
        assert sess.user_id == "anonymous"
        assert sess.tenant_id == f"anon-{sid}"


def test_anonymous_heartbeat_still_allowed(monkeypatch):
    # 心跳不涉及数据，匿名连接仍可保活
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text('{"type": "heartbeat"}')
        ack = ws.receive_json()
        assert ack["type"] == "heartbeat_ack"


def test_anonymous_chat_message_blocked_with_need_login(monkeypatch):
    fake_app = FakeApp(_dispatch_result())
    _patch_chat_deps(monkeypatch, fake_app, FakeTracker(), FakeDispatcher(), FakeHITL())
    # 在会话落库最早一环打点：被身份守卫拦截时根本到不了这里
    ensure_calls: list = []
    monkeypatch.setattr(
        "src.db.repositories.conversation_ensure",
        lambda *a, **k: ensure_calls.append(1),
    )

    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text('{"type": "chat_message", "message": "测温设备量程是多少"}')
        frame = ws.receive_json()

        assert frame["type"] == "need_login"
        assert frame["error_code"] == "AUTH_REQUIRED"
        assert "登录" in frame["message"]
        assert ensure_calls == [], "匿名问答不得触发会话落库"


def test_anonymous_human_escalation_blocked(monkeypatch):
    disp = FakeDispatcher()
    _patch_route_globals(monkeypatch, fake_dispatcher=disp)
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        sid = ready["session_id"]
        ws.send_text(
            f'{{"type": "human_escalation", "session_id": "{sid}", '
            '"reason": "user_requested"}'
        )
        frame = ws.receive_json()

        assert frame["type"] == "need_login"
        assert frame["error_code"] == "AUTH_REQUIRED"
        assert disp.escalations == [], "匿名不得进入转人工链路"


def test_anonymous_resume_session_blocked(monkeypatch):
    # 历史续接同样需要身份，匿名态不允许借 session_id 拉取任何会话数据
    _patch_route_globals(monkeypatch, fake_dispatcher=FakeDispatcher())
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text('{"type": "resume_session", "session_id": "someone-else-session"}')
        frame = ws.receive_json()

        assert frame["type"] == "need_login"
        assert frame["error_code"] == "AUTH_REQUIRED"
