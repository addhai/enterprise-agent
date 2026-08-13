"""websocket/routes.py chat 端点未覆盖分支（用 FakeSessionManager 驱动）

覆盖：
    - human_escalation 幂等（会话已在转接/人工态 → 仅提示，不再触发转接）
    - 用户在 WAITING_HUMAN 态发消息 → 提示稍候
    - 用户在 HUMAN_CHAT 态发消息 → 转发给坐席 WebSocket
    - resume_session 从 DB 恢复历史时异常 → 非致命降级

这些分支需要控制会话 mode，真实 session_manager 无法从外部设定，故用 Fake 注入。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
import src.websocket.routes as rt
from src.websocket.session_manager import SessionMode


class FakeWSRef:
    def __init__(self):
        self.sent = []

    async def send_json(self, d):
        self.sent.append(d)


class FakeSession:
    def __init__(self, sid, mode, user_id="u1", tenant_id="t1"):
        self.session_id = sid
        self.mode = mode
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.conversation_history = []
        self._websocket_ref = None
        self.assigned_agent = None
        self.last_active = 0


class FakeSM:
    def __init__(self, preset_mode=None):
        self.sessions = {}
        self.agents = {}
        self.preset_mode = preset_mode

    def create_session(self, session_id, user_id, tenant_id, mode=None):
        m = self.preset_mode if self.preset_mode is not None else (mode or SessionMode.AI_CHAT)
        s = FakeSession(session_id, m, user_id, tenant_id)
        self.sessions[session_id] = s
        return s

    def get_session(self, sid):
        return self.sessions.get(sid)

    def update_mode(self, sid, mode):
        if sid in self.sessions:
            self.sessions[sid].mode = mode

    def remove_session(self, sid):
        self.sessions.pop(sid, None)

    def get_agent(self, aid):
        return self.agents.get(aid)


class FakeDispatcher:
    def __init__(self, transfer_id=None, record=None):
        self.transfer_id = transfer_id
        self.record = record
        self.escalations = []

    async def handle_escalation(self, sid, result, messages):
        self.escalations.append(sid)

    def get_session_transfer(self, sid):
        return self.transfer_id

    def get_transfer_record(self, tid):
        return self.record


def _client():
    return TestClient(app)


@pytest.fixture
def patch_globals(monkeypatch):
    monkeypatch.setattr("src.api.metrics.gauge_inc", lambda *a, **k: None)
    monkeypatch.setattr("src.api.metrics.gauge_dec", lambda *a, **k: None)


def test_human_escalation_idempotent(monkeypatch, patch_globals):
    sm = FakeSM(preset_mode=SessionMode.WAITING_HUMAN)
    disp = FakeDispatcher()
    monkeypatch.setattr(rt, "get_session_manager", lambda: sm)
    monkeypatch.setattr(rt, "get_dispatcher", lambda: disp)
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        sid = ready["session_id"]
        ws.send_text(
            '{"type": "human_escalation", "session_id": "%s", "reason": "x"}' % sid
        )
        info = ws.receive_json()
        assert info["type"] == "info"
        # 已在转接队列 → 幂等，不再触发转接
        assert disp.escalations == []


def test_chat_while_waiting_human(monkeypatch, patch_globals):
    sm = FakeSM(preset_mode=SessionMode.WAITING_HUMAN)
    disp = FakeDispatcher()
    monkeypatch.setattr(rt, "get_session_manager", lambda: sm)
    monkeypatch.setattr(rt, "get_dispatcher", lambda: disp)
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text('{"type": "chat", "message": "还在吗"}')
        info = ws.receive_json()
        assert info["type"] == "info"
        assert "转接" in (info.get("text") or "")


def test_chat_while_human_chat_forward(monkeypatch, patch_globals):
    agent_ws = FakeWSRef()
    sm = FakeSM(preset_mode=SessionMode.HUMAN_CHAT)
    sm.agents["agent-9"] = agent_ws
    record = SimpleNamespace(assigned_agent="agent-9")
    disp = FakeDispatcher(transfer_id="t-1", record=record)
    monkeypatch.setattr(rt, "get_session_manager", lambda: sm)
    monkeypatch.setattr(rt, "get_dispatcher", lambda: disp)
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        sid = ready["session_id"]
        ws.send_text('{"type": "chat", "message": "我的问题还没解决"}')
        resp = ws.receive_json()
        assert resp["type"] == "message_received"
        assert resp.get("status") == "forwarded_to_agent"
        # 坐席端收到用户消息
        assert any(
            m.get("type") == "agent_chat_message" for m in agent_ws.sent
        )


def test_resume_session_db_error(monkeypatch, patch_globals):
    def _boom(*a, **k):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("src.db.repositories.message_list", _boom)
    monkeypatch.setattr(rt, "get_session_manager", lambda: FakeSM())
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text('{"type": "resume_session", "session_id": "old-sess-xyz"}')
        resp = ws.receive_json()
        assert resp["type"] == "session_resumed"
        # DB 异常被捕获，降级为沿用，restored_count=0
        assert resp["restored_count"] == 0
