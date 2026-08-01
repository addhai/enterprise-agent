"""WebSocket 消息协议单元测试

覆盖 protocol.py 中所有消息构建函数：
- build_client_message / build_server_message
- build_streaming_chunk
- build_typing_indicator
- build_transfer_notice
- build_handoff_context
- build_error
- build_new_transfer
- build_session_update
- build_copilot_suggestion
"""
import pytest

from src.websocket.protocol import (
    TYPE_CLIENT_CHAT,
    TYPE_STREAMING_CHUNK,
    TYPE_TYPING_INDICATOR,
    TYPE_TRANSFER_NOTICE,
    TYPE_HANDOFF_CONTEXT,
    TYPE_ERROR,
    TYPE_HEARTBEAT_ACK,
    TYPE_NEW_TRANSFER,
    TYPE_SESSION_UPDATE,
    TYPE_COPILOT_SUGGESTION,
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
)


# ============================================================
# 基础消息构建
# ============================================================

class TestBuildClientMessage:
    def test_includes_type_and_timestamp(self):
        msg = build_client_message(TYPE_CLIENT_CHAT, content="hello")
        assert msg["type"] == TYPE_CLIENT_CHAT
        assert "timestamp" in msg
        assert msg["content"] == "hello"

    def test_extra_kwargs_merged(self):
        msg = build_client_message(TYPE_CLIENT_CHAT, content="hi", session_id="s1")
        assert msg["session_id"] == "s1"
        assert msg["content"] == "hi"


class TestBuildServerMessage:
    def test_includes_type_session_and_timestamp(self):
        msg = build_server_message(TYPE_HEARTBEAT_ACK, session_id="s1")
        assert msg["type"] == TYPE_HEARTBEAT_ACK
        assert msg["session_id"] == "s1"
        assert "timestamp" in msg

    def test_empty_session_id(self):
        msg = build_server_message(TYPE_HEARTBEAT_ACK)
        assert msg["session_id"] == ""

    def test_extra_kwargs_merged(self):
        msg = build_server_message(TYPE_ERROR, session_id="s1", code="500")
        assert msg["code"] == "500"


# ============================================================
# 流式消息
# ============================================================

class TestStreamingChunk:
    def test_basic_chunk(self):
        msg = build_streaming_chunk("s1", text="你好")
        assert msg["type"] == TYPE_STREAMING_CHUNK
        assert msg["session_id"] == "s1"
        assert msg["text"] == "你好"
        assert msg["done"] is False
        assert msg["delta"] == "你好"  # delta 默认等于 text
        assert msg["suggest_human"] is False

    def test_done_chunk(self):
        msg = build_streaming_chunk("s1", text="", done=True)
        assert msg["done"] is True
        assert msg["text"] == ""

    def test_custom_delta(self):
        msg = build_streaming_chunk("s1", text="完整文本", delta="增量")
        assert msg["delta"] == "增量"

    def test_suggest_human_flag(self):
        msg = build_streaming_chunk("s1", text="建议转人工", suggest_human=True)
        assert msg["suggest_human"] is True


# ============================================================
# 打字指示器
# ============================================================

class TestTypingIndicator:
    def test_typing_on(self):
        msg = build_typing_indicator("s1", is_typing=True)
        assert msg["type"] == TYPE_TYPING_INDICATOR
        assert msg["is_typing"] is True
        assert "status" not in msg

    def test_typing_off(self):
        msg = build_typing_indicator("s1", is_typing=False)
        assert msg["is_typing"] is False

    def test_with_status(self):
        msg = build_typing_indicator("s1", is_typing=True, status="正在搜索文档...")
        assert msg["status"] == "正在搜索文档..."

    def test_default_is_typing_true(self):
        msg = build_typing_indicator("s1")
        assert msg["is_typing"] is True


# ============================================================
# 转接通知
# ============================================================

class TestTransferNotice:
    def test_basic_notice(self):
        msg = build_transfer_notice("s1", reason="用户要求", estimated_wait=60)
        assert msg["type"] == TYPE_TRANSFER_NOTICE
        assert msg["session_id"] == "s1"
        assert msg["reason"] == "用户要求"
        assert msg["estimated_wait_seconds"] == 60
        assert "正在为您转接" in msg["message"]

    def test_default_wait_time(self):
        msg = build_transfer_notice("s1")
        assert msg["estimated_wait_seconds"] == 30


# ============================================================
# 转接上下文
# ============================================================

class TestHandoffContext:
    def test_full_context(self):
        msg = build_handoff_context(
            session_id="s1",
            summary="用户遇到 403 错误",
            conversation=[{"role": "user", "content": "报错"}],
            user_profile={"plan": "enterprise"},
            attempted_solutions=["检查了权限配置"],
            quality_score=0.25,
        )
        assert msg["type"] == TYPE_HANDOFF_CONTEXT
        assert msg["summary"] == "用户遇到 403 错误"
        assert msg["quality_score"] == 0.25
        assert len(msg["conversation"]) == 1
        assert msg["user_profile"]["plan"] == "enterprise"

    def test_null_quality_score(self):
        msg = build_handoff_context(
            session_id="s1",
            summary="摘要",
            conversation=[],
            user_profile={},
            attempted_solutions=[],
            quality_score=None,
        )
        assert msg["quality_score"] is None


# ============================================================
# 错误消息
# ============================================================

class TestError:
    def test_error_message(self):
        msg = build_error("s1", code="INTERNAL_ERROR", message="服务器内部错误")
        assert msg["type"] == TYPE_ERROR
        assert msg["session_id"] == "s1"
        assert msg["error_code"] == "INTERNAL_ERROR"
        assert msg["error_message"] == "服务器内部错误"


# ============================================================
# 新转接通知（发给坐席）
# ============================================================

class TestNewTransfer:
    def test_full_transfer(self):
        msg = build_new_transfer(
            transfer_id="t1",
            session_id="s1",
            user_id="u1",
            summary="退款问题",
            conversation=[{"role": "user", "content": "我要退款"}],
            user_profile={"plan": "pro"},
            urgency="high",
        )
        assert msg["type"] == TYPE_NEW_TRANSFER
        assert msg["transfer_id"] == "t1"
        assert msg["user_id"] == "u1"
        assert msg["urgency"] == "high"
        assert "timestamp" in msg

    def test_default_urgency(self):
        msg = build_new_transfer(
            transfer_id="t1", session_id="s1", user_id="u1",
            summary="", conversation=[], user_profile={},
        )
        assert msg["urgency"] == "normal"


# ============================================================
# 会话状态更新
# ============================================================

class TestSessionUpdate:
    def test_basic_update(self):
        msg = build_session_update("s1", mode="human_chat")
        assert msg["type"] == TYPE_SESSION_UPDATE
        assert msg["session_id"] == "s1"
        assert msg["mode"] == "human_chat"
        assert msg["assigned_agent"] is None

    def test_with_assigned_agent(self):
        msg = build_session_update("s1", mode="human_chat", assigned_agent="agent-1")
        assert msg["assigned_agent"] == "agent-1"

    def test_extra_fields(self):
        msg = build_session_update("s1", mode="ai_chat", extra_info="hello")
        assert msg["extra_info"] == "hello"


# ============================================================
# Copilot 建议
# ============================================================

class TestCopilotSuggestion:
    def test_basic_suggestion(self):
        msg = build_copilot_suggestion("s1", suggestions=["回复1", "回复2"])
        assert msg["type"] == TYPE_COPILOT_SUGGESTION
        assert msg["session_id"] == "s1"
        assert len(msg["suggestions"]) == 2
        # 默认 confidence 为 0.8 × 数量
        assert len(msg["confidence"]) == 2
        assert msg["confidence"][0] == 0.8

    def test_custom_confidence(self):
        msg = build_copilot_suggestion(
            "s1", suggestions=["回复1"], confidence_scores=[0.95],
        )
        assert msg["confidence"][0] == 0.95
