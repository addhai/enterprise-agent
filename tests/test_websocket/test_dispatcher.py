"""TransferDispatcher 单元测试

覆盖：
- handle_escalation 转接流程
- agent_reply 坐席回复
- get_copilot_suggestions Copilot 建议
- migrate_to_human / migrate_to_ai 会话迁移
- 查询接口（get_stats / get_pending_count / get_transfer_record）
- 无在线坐席时入队
"""
import pytest

from src.websocket.session_manager import (
    SessionMode,
    get_session_manager,
)
from src.websocket.dispatcher import (
    TransferDispatcher,
    TransferRecord,
    get_dispatcher,
)


# ============================================================
# handle_escalation 转接流程
# ============================================================

class TestHandleEscalation:
    @pytest.mark.asyncio
    async def test_escalation_creates_transfer_record(self):
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        state = {"user_id": "user-1", "intent": "technical"}
        result = await disp.handle_escalation("s1", state, [])

        assert result["needs_human"] is True
        assert "transfer_id" in result
        assert "transfer_notice" in result
        assert "handoff_context" in result

        # 转接记录应存在
        record = disp.get_transfer_record(result["transfer_id"])
        assert record is not None
        assert record.session_id == "s1"

    @pytest.mark.asyncio
    async def test_escalation_updates_session_mode_to_waiting(self):
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        await disp.handle_escalation("s1", {"user_id": "user-1"}, [])
        state = mgr.get_session("s1")
        assert state.mode == SessionMode.WAITING_HUMAN

    @pytest.mark.asyncio
    async def test_escalation_assigns_online_agent(self):
        """有在线坐席时应自动分配"""
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        class MockWS:
            def __init__(self):
                self.sent = []

            async def send_json(self, data):
                self.sent.append(data)

        mock_ws = MockWS()
        mgr.register_agent("agent-1", mock_ws)

        result = await disp.handle_escalation("s1", {"user_id": "user-1"}, [])
        assert result["agent_assigned"] == "agent-1"
        # 坐席应收到 new_transfer 通知
        assert len(mock_ws.sent) == 1
        assert mock_ws.sent[0]["type"] == "new_transfer"

    @pytest.mark.asyncio
    async def test_escalation_queues_when_no_agents(self):
        """无在线坐席时应入队"""
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        result = await disp.handle_escalation("s1", {"user_id": "user-1"}, [])
        assert result["agent_assigned"] is None
        assert disp.get_pending_count() == 1

    @pytest.mark.asyncio
    async def test_high_urgency_shorter_wait(self):
        """高紧急度转接的等待时间应更短"""
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        # enterprise + 投诉 → critical 紧急度
        state = {
            "user_id": "user-1",
            "intent": "general",
            "user_plan": "enterprise",
        }
        from langchain_core.messages import HumanMessage
        msgs = [HumanMessage(content="我要投诉退款")]

        result = await disp.handle_escalation("s1", state, msgs)
        notice = result["transfer_notice"]
        assert notice["estimated_wait_seconds"] == 30  # 高紧急度等待 30s


# ============================================================
# agent_reply 坐席回复
# ============================================================

class TestAgentReply:
    @pytest.mark.asyncio
    async def test_reply_via_websocket(self):
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        class MockWS:
            def __init__(self):
                self.sent = []

            async def send_json(self, data):
                self.sent.append(data)

        mock_ws = MockWS()
        state = mgr.get_session("s1")
        state._websocket_ref = mock_ws

        result = await disp.agent_reply("agent-1", "s1", "这是坐席回复")
        assert result is True
        assert mock_ws.sent[0]["text"] == "这是坐席回复"
        assert mock_ws.sent[0]["from_agent"] == "agent-1"

    @pytest.mark.asyncio
    async def test_reply_to_nonexistent_session_returns_false(self):
        disp = get_dispatcher()
        result = await disp.agent_reply("agent-1", "nope", "回复")
        assert result is False

    @pytest.mark.asyncio
    async def test_reply_without_websocket_enqueues(self):
        """无 WebSocket 引用时应放入消息队列"""
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        result = await disp.agent_reply("agent-1", "s1", "回复")
        assert result is False

        state = mgr.get_session("s1")
        msg = await state.message_queue.get()
        assert msg["text"] == "回复"
        assert msg["from_agent"] == "agent-1"


# ============================================================
# Copilot 建议
# ============================================================

class TestCopilotSuggestions:
    @pytest.mark.asyncio
    async def test_error_keyword_suggestions(self):
        disp = get_dispatcher()
        suggestions = await disp.get_copilot_suggestions(
            "s1", "我遇到了 error 报错", [],
        )
        assert len(suggestions) >= 1
        assert any("错误" in s or "error" in s.lower() for s in suggestions)

    @pytest.mark.asyncio
    async def test_refund_keyword_suggestions(self):
        disp = get_dispatcher()
        suggestions = await disp.get_copilot_suggestions(
            "s1", "我要退款 refund", [],
        )
        assert len(suggestions) >= 1
        assert any("退款" in s for s in suggestions)

    @pytest.mark.asyncio
    async def test_login_keyword_suggestions(self):
        disp = get_dispatcher()
        suggestions = await disp.get_copilot_suggestions(
            "s1", "我无法登录 password 忘了", [],
        )
        assert len(suggestions) >= 1

    @pytest.mark.asyncio
    async def test_generic_suggestions_when_no_match(self):
        disp = get_dispatcher()
        suggestions = await disp.get_copilot_suggestions(
            "s1", "一般的问候", [],
        )
        assert len(suggestions) >= 1

    @pytest.mark.asyncio
    async def test_max_three_suggestions(self):
        disp = get_dispatcher()
        suggestions = await disp.get_copilot_suggestions(
            "s1", "error refund password", [],
        )
        assert len(suggestions) <= 3


# ============================================================
# 会话迁移
# ============================================================

class TestSessionMigration:
    def test_migrate_to_human(self):
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        assert disp.migrate_to_human("s1") is True
        state = mgr.get_session("s1")
        assert state.mode == SessionMode.HUMAN_CHAT
        assert state.needs_human is True

    def test_migrate_to_human_nonexistent_returns_false(self):
        disp = get_dispatcher()
        assert disp.migrate_to_human("nope") is False

    def test_migrate_to_ai(self):
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")
        mgr.assign_agent_to_session("s1", "agent-1")  # 先转人工

        assert disp.migrate_to_ai("s1") is True
        state = mgr.get_session("s1")
        assert state.mode == SessionMode.AI_CHAT
        assert state.needs_human is False
        assert state.assigned_agent is None

    def test_migrate_to_ai_nonexistent_returns_false(self):
        disp = get_dispatcher()
        assert disp.migrate_to_ai("nope") is False


# ============================================================
# 查询接口与统计
# ============================================================

class TestDispatcherStats:
    @pytest.mark.asyncio
    async def test_get_stats_after_escalation(self):
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        await disp.handle_escalation("s1", {"user_id": "user-1"}, [])

        stats = disp.get_stats()
        assert stats["total_transfers"] == 1

    @pytest.mark.asyncio
    async def test_get_session_transfer(self):
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")

        result = await disp.handle_escalation("s1", {"user_id": "user-1"}, [])

        transfer_id = disp.get_session_transfer("s1")
        assert transfer_id == result["transfer_id"]

    def test_get_session_transfer_none(self):
        disp = get_dispatcher()
        assert disp.get_session_transfer("nope") is None

    def test_get_transfer_record_nonexistent(self):
        disp = get_dispatcher()
        assert disp.get_transfer_record("nope") is None

    @pytest.mark.asyncio
    async def test_pending_count_increments_without_agents(self):
        disp = get_dispatcher()
        mgr = get_session_manager()
        mgr.create_session("s1", "user-1")
        mgr.create_session("s2", "user-2")

        await disp.handle_escalation("s1", {"user_id": "user-1"}, [])
        await disp.handle_escalation("s2", {"user_id": "user-2"}, [])

        assert disp.get_pending_count() == 2

    @pytest.mark.asyncio
    async def test_singleton_returns_same_instance(self):
        assert get_dispatcher() is get_dispatcher()
