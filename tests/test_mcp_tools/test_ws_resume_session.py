"""WebSocket /ws/chat 的 resume_session 握手集成测试

锁定：
  - 客户端连接后发送 `resume_session` 消息可显式续接会话
  - 内存有会话 → 复用，返回 source=memory + 当前历史条数
  - 内存无会话但 DB 有历史 → 重建会话并从 DB 恢复，返回 source=database
  - 未携带 session_id → 沿用本连接已建会话，restored_count=0
"""
from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

from src.api.server import app
from src.db.repositories import conversation_ensure, message_save
from src.websocket.session_manager import get_session_manager


def _client():
    return TestClient(app)


def _cleanup_session(session_id: str):
    """清理内存会话，避免跨测试污染。"""
    try:
        get_session_manager().remove_session(session_id)
    except Exception:
        pass


def test_resume_session_reuses_memory_session():
    """内存有该会话 → source=memory，restored_count 反映内存历史条数。"""
    client = _client()
    sid = f"WS-RES-MEM-{uuid.uuid4().hex[:8]}"

    # 先在内存里建一个会话，并塞入历史
    session_mgr = get_session_manager()
    from src.websocket.session_manager import SessionMode
    session_mgr.create_session(
        session_id=sid, user_id="u1", tenant_id="t1", mode=SessionMode.AI_CHAT
    )
    s = session_mgr.get_session(sid)
    s.conversation_history = [
        {"role": "user", "content": "在内存里的问题"},
        {"role": "assistant", "content": "在内存里的回答"},
    ]

    try:
        with client.websocket_connect("/ws/chat") as ws:
            # 收到 session_ready
            ready = ws.receive_json()
            assert ready["type"] == "session_ready"

            ws.send_text(json.dumps({
                "type": "resume_session",
                "session_id": sid,
                "user_id": "u1",
            }))
            resumed = ws.receive_json()
            assert resumed["type"] == "session_resumed"
            assert resumed["session_id"] == sid
            assert resumed["source"] == "memory"
            assert resumed["restored_count"] == 2
    finally:
        _cleanup_session(sid)


def test_resume_session_rebuilds_from_db_when_memory_misses():
    """内存无该会话但 DB 有历史 → 重建会话并从 DB 恢复，source=database。"""
    client = _client()
    sid = f"WS-RES-DB-{uuid.uuid4().hex[:8]}"
    _cleanup_session(sid)

    # 往 DB 塞历史（不通过 WebSocket，直接走仓储层）
    conversation_ensure(sid, "default", "u1", channel="web")
    message_save(sid, "default", "u1", "user", "DB 历史问题")
    message_save(sid, "default", "u1", "assistant", "DB 历史回答")

    try:
        with client.websocket_connect("/ws/chat") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "session_ready"

            ws.send_text(json.dumps({
                "type": "resume_session",
                "session_id": sid,
                "user_id": "u1",
            }))
            resumed = ws.receive_json()
            assert resumed["type"] == "session_resumed"
            assert resumed["session_id"] == sid
            assert resumed["source"] == "database"
            assert resumed["restored_count"] == 2

            # 在 WS 仍在连接状态下验证内存会话已建立且历史已恢复
            # （WS 断开后 server 会 remove_session 清理，因此必须在 with 块内断言）
            s = get_session_manager().get_session(sid)
            assert s is not None
            assert len(s.conversation_history) == 2
            assert s.conversation_history[0]["content"] == "DB 历史问题"
    finally:
        _cleanup_session(sid)


def test_resume_session_without_session_id_keeps_current():
    """客户端未携带 session_id → 沿用连接建立时分配的会话，restored_count=0。"""
    client = _client()

    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "session_ready"
        auto_sid = ready["session_id"]

        ws.send_text(json.dumps({"type": "resume_session"}))
        resumed = ws.receive_json()
        assert resumed["type"] == "session_resumed"
        assert resumed["session_id"] == auto_sid
        assert resumed["restored_count"] == 0

    _cleanup_session(auto_sid)


def test_resume_session_rebuilds_with_zero_history_when_db_empty():
    """内存无会话且 DB 也无历史 → 重建空会话，source=database，restored_count=0。"""
    client = _client()
    sid = f"WS-RES-EMPTY-{uuid.uuid4().hex[:8]}"
    _cleanup_session(sid)

    try:
        with client.websocket_connect("/ws/chat") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "session_ready"

            ws.send_text(json.dumps({
                "type": "resume_session",
                "session_id": sid,
                "user_id": "u-new",
            }))
            resumed = ws.receive_json()
            assert resumed["type"] == "session_resumed"
            assert resumed["session_id"] == sid
            assert resumed["source"] == "database"
            assert resumed["restored_count"] == 0

            # 在 WS 仍在连接状态下验证内存会话已建立且历史为空
            s = get_session_manager().get_session(sid)
            assert s is not None
            assert s.conversation_history == []
    finally:
        _cleanup_session(sid)
