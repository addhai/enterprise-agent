"""WebSocketSessionManager 单元测试

覆盖：
- 会话创建 / 获取 / 更新模式 / 移除
- 人工坐席注册 / 注销 / 列表 / 分配
- 消息推送（session / agent）
- 统计信息
- 单例模式
"""
import asyncio
import pytest

from src.websocket.session_manager import (
    SessionMode,
    SessionState,
    WebSocketSessionManager,
    get_session_manager,
)


# ============================================================
# 会话管理
# ============================================================

class TestSessionManagement:
    def test_create_session(self):
        mgr = get_session_manager()
        state = mgr.create_session("s1", "user-1", tenant_id="t1")

        assert state.session_id == "s1"
        assert state.user_id == "user-1"
        assert state.tenant_id == "t1"
        assert state.mode == SessionMode.AI_CHAT
        assert state.turn_count == 0

    def test_create_session_with_custom_mode(self):
        mgr = get_session_manager()
        state = mgr.create_session("s1", "user-1", mode=SessionMode.WAITING_HUMAN)
        assert state.mode == SessionMode.WAITING_HUMAN

    def test_get_session_updates_last_active(self):
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")
        state = mgr.get_session("s1")
        old_active = state.last_active

        import time
        time.sleep(0.01)
        state2 = mgr.get_session("s1")
        assert state2.last_active >= old_active

    def test_get_nonexistent_session_returns_none(self):
        mgr = get_session_manager()
        assert mgr.get_session("nope") is None

    def test_update_mode(self):
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        assert mgr.update_mode("s1", SessionMode.HUMAN_CHAT) is True
        assert mgr.get_session("s1").mode == SessionMode.HUMAN_CHAT

    def test_update_mode_nonexistent_returns_false(self):
        mgr = get_session_manager()
        assert mgr.update_mode("nope", SessionMode.CLOSED) is False

    def test_remove_session(self):
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        assert mgr.remove_session("s1") is True
        assert mgr.get_session("s1") is None

    def test_remove_nonexistent_returns_false(self):
        mgr = get_session_manager()
        assert mgr.remove_session("nope") is False


# ============================================================
# 人工坐席管理
# ============================================================

class TestAgentManagement:
    def test_register_and_get_agent(self):
        mgr = get_session_manager()
        mock_ws = object()
        mgr.register_agent("agent-1", mock_ws)

        assert mgr.get_agent("agent-1") is mock_ws

    def test_unregister_agent(self):
        mgr = get_session_manager()
        mgr.register_agent("agent-1", object())
        mgr.unregister_agent("agent-1")

        assert mgr.get_agent("agent-1") is None

    def test_list_online_agents(self):
        mgr = get_session_manager()
        mgr.register_agent("agent-1", object())
        mgr.register_agent("agent-2", object())

        online = mgr.list_online_agents()
        assert "agent-1" in online
        assert "agent-2" in online
        assert len(online) == 2

    def test_assign_agent_to_session(self):
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")
        mgr.register_agent("agent-1", object())

        assert mgr.assign_agent_to_session("s1", "agent-1") is True
        state = mgr.get_session("s1")
        assert state.assigned_agent == "agent-1"
        assert state.mode == SessionMode.HUMAN_CHAT

    def test_assign_nonexistent_agent_returns_false(self):
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")
        assert mgr.assign_agent_to_session("s1", "ghost-agent") is False

    def test_assign_to_nonexistent_session_returns_false(self):
        mgr = get_session_manager()
        mgr.register_agent("agent-1", object())
        assert mgr.assign_agent_to_session("nope", "agent-1") is False


# ============================================================
# 消息推送
# ============================================================

class TestMessagePush:
    @pytest.mark.asyncio
    async def test_push_to_session_enqueues_message(self):
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        result = await mgr.push_to_session("s1", {"type": "test"})
        assert result is True

        state = mgr.get_session("s1")
        msg = await state.message_queue.get()
        assert msg == {"type": "test"}

    @pytest.mark.asyncio
    async def test_push_to_nonexistent_session_returns_false(self):
        mgr = get_session_manager()
        result = await mgr.push_to_session("nope", {"type": "test"})
        assert result is False

    @pytest.mark.asyncio
    async def test_push_to_agent_sends_json(self):
        mgr = get_session_manager()

        class MockWS:
            def __init__(self):
                self.sent = []

            async def send_json(self, data):
                self.sent.append(data)

        mock_ws = MockWS()
        mgr.register_agent("agent-1", mock_ws)

        result = await mgr.push_to_agent("agent-1", {"type": "test"})
        assert result is True
        assert mock_ws.sent == [{"type": "test"}]

    @pytest.mark.asyncio
    async def test_push_to_nonexistent_agent_returns_false(self):
        mgr = get_session_manager()
        result = await mgr.push_to_agent("ghost", {"type": "test"})
        assert result is False

    @pytest.mark.asyncio
    async def test_push_to_agent_handles_send_failure(self):
        mgr = get_session_manager()

        class FailingWS:
            async def send_json(self, data):
                raise ConnectionError("断开")

        mgr.register_agent("agent-1", FailingWS())
        result = await mgr.push_to_agent("agent-1", {"type": "test"})
        assert result is False


# ============================================================
# 统计与单例
# ============================================================

class TestStatsAndSingleton:
    def test_get_stats(self):
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1", mode=SessionMode.AI_CHAT)
        mgr.create_session("s2", "user-2", mode=SessionMode.HUMAN_CHAT)
        mgr.register_agent("agent-1", object())

        stats = mgr.get_stats()
        assert stats["total_sessions"] == 2
        assert stats["sessions_by_mode"]["ai_chat"] == 1
        assert stats["sessions_by_mode"]["human_chat"] == 1
        assert stats["online_agents"] == 1
        assert "agent-1" in stats["agent_ids"]

    def test_singleton_returns_same_instance(self):
        assert get_session_manager() is get_session_manager()

    def test_session_state_dataclass_defaults(self):
        state = SessionState(session_id="s1", user_id="u1", tenant_id="t1")
        assert state.mode == SessionMode.AI_CHAT
        assert state.turn_count == 0
        assert state.needs_human is False
        assert state.assigned_agent is None
        assert state.conversation_history == []
        assert state.failed_attempts == 0
        assert state.suggest_human is False
