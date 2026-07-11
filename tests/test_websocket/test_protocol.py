"""WebSocket 协议测试"""
import pytest
from src.websocket.protocol import (
    build_client_message,
    build_server_message,
    build_streaming_chunk,
    build_typing_indicator,
    build_transfer_notice,
    build_handoff_context,
    build_error,
    build_new_transfer,
    build_session_update,
    build_copilot_suggestion,
    TYPE_STREAMING_CHUNK,
    TYPE_TYPING_INDICATOR,
    TYPE_TRANSFER_NOTICE,
    TYPE_HANDOFF_CONTEXT,
    TYPE_SESSION_UPDATE,
    TYPE_ERROR,
    TYPE_NEW_TRANSFER,
    TYPE_COPILOT_SUGGESTION,
)


def test_build_client_message():
    msg = build_client_message("chat_message", message="hello")
    assert msg["type"] == "chat_message"
    assert msg["message"] == "hello"
    assert "timestamp" in msg


def test_build_server_message():
    msg = build_server_message(TYPE_STREAMING_CHUNK, session_id="s1", text="hi")
    assert msg["type"] == TYPE_STREAMING_CHUNK
    assert msg["session_id"] == "s1"
    assert msg["text"] == "hi"


def test_build_streaming_chunk():
    msg = build_streaming_chunk("s1", "你好世界", done=False, delta="你好")
    assert msg["type"] == TYPE_STREAMING_CHUNK
    assert msg["session_id"] == "s1"
    assert msg["text"] == "你好世界"
    assert msg["delta"] == "你好"
    assert msg["done"] is False


def test_build_typing_indicator():
    msg = build_typing_indicator("s1", is_typing=True)
    assert msg["type"] == TYPE_TYPING_INDICATOR
    assert msg["is_typing"] is True

    msg2 = build_typing_indicator("s1", is_typing=False)
    assert msg2["is_typing"] is False


def test_build_transfer_notice():
    msg = build_transfer_notice("s1", reason="低置信度", estimated_wait=30)
    assert msg["type"] == TYPE_TRANSFER_NOTICE
    assert msg["reason"] == "低置信度"
    assert msg["estimated_wait_seconds"] == 30


def test_build_handoff_context():
    msg = build_handoff_context(
        session_id="s1",
        summary="用户问题：同步失败",
        conversation=[{"role": "user", "content": "sync broken"}],
        user_profile={"plan": "pro"},
        attempted_solutions=["RAG 检索"],
        quality_score=0.2,
    )
    assert msg["type"] == TYPE_HANDOFF_CONTEXT
    assert msg["summary"] == "用户问题：同步失败"
    assert msg["quality_score"] == 0.2


def test_build_error():
    msg = build_error("s1", "CHAT_ERROR", "Internal error")
    assert msg["type"] == TYPE_ERROR
    assert msg["error_code"] == "CHAT_ERROR"
    assert msg["error_message"] == "Internal error"


def test_build_new_transfer():
    msg = build_new_transfer(
        transfer_id="t1",
        session_id="s1",
        user_id="u1",
        summary="用户需要帮助",
        conversation=[],
        user_profile={},
        urgency="high",
    )
    assert msg["type"] == TYPE_NEW_TRANSFER
    assert msg["urgency"] == "high"
    assert msg["transfer_id"] == "t1"


def test_build_session_update():
    msg = build_session_update("s1", mode="human_chat", assigned_agent="agent-1")
    assert msg["type"] == TYPE_SESSION_UPDATE
    assert msg["mode"] == "human_chat"
    assert msg["assigned_agent"] == "agent-1"


def test_build_copilot_suggestion():
    msg = build_copilot_suggestion("s1", ["建议1", "建议2"], [0.9, 0.7])
    assert msg["type"] == TYPE_COPILOT_SUGGESTION
    assert len(msg["suggestions"]) == 2
    assert msg["confidence"][0] == 0.9
