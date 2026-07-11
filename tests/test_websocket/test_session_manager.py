"""WebSocket 会话管理器测试"""
import asyncio
import time
import pytest
from src.websocket.session_manager import (
    WebSocketSessionManager,
    SessionMode,
    SessionState,
    get_session_manager,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """每次测试前重置单例"""
    global _session_manager
    import src.websocket.session_manager as sm
    sm._session_manager = None
    yield
    # 清理
    sm._session_manager = None


def test_singleton():
    """测试单例模式"""
    mgr1 = get_session_manager()
    mgr2 = get_session_manager()
    assert mgr1 is mgr2


def test_create_session():
    """测试创建会话"""
    mgr = get_session_manager()
    state = mgr.create_session(
        session_id="test-1",
        user_id="user-123",
        tenant_id="tenant-a",
        mode=SessionMode.AI_CHAT,
    )
    assert state.session_id == "test-1"
    assert state.user_id == "user-123"
    assert state.mode == SessionMode.AI_CHAT
    assert state.created_at <= time.time()


def test_get_session():
    """测试获取会话"""
    mgr = get_session_manager()
    mgr.create_session("s1", "u1")
    state = mgr.get_session("s1")
    assert state is not None
    assert state.session_id == "s1"
    # 不存在的会话
    assert mgr.get_session("nonexistent") is None


def test_update_mode():
    """测试更新会话模式"""
    mgr = get_session_manager()
    mgr.create_session("s1", "u1")
    assert mgr.update_mode("s1", SessionMode.WAITING_HUMAN)
    state = mgr.get_session("s1")
    assert state.mode == SessionMode.WAITING_HUMAN
    # 不存在的会话
    assert not mgr.update_mode("nope", SessionMode.AI_CHAT)


def test_remove_session():
    """测试移除会话"""
    mgr = get_session_manager()
    mgr.create_session("s1", "u1")
    assert mgr.remove_session("s1")
    assert mgr.get_session("s1") is None
    assert not mgr.remove_session("nope")


def test_agent_register_unregister():
    """测试坐席注册/注销"""
    mgr = get_session_manager()
    mock_ws = {"connected": True}
    mgr.register_agent("agent-1", mock_ws)
    assert mgr.get_agent("agent-1") is mock_ws
    assert "agent-1" in mgr.list_online_agents()
    mgr.unregister_agent("agent-1")
    assert mgr.get_agent("agent-1") is None
    assert len(mgr.list_online_agents()) == 0


def test_assign_agent_to_session():
    """测试会话分配给坐席"""
    mgr = get_session_manager()
    mgr.create_session("s1", "u1")
    mock_ws = {"connected": True}
    mgr.register_agent("agent-1", mock_ws)
    assert mgr.assign_agent_to_session("s1", "agent-1")
    state = mgr.get_session("s1")
    assert state.assigned_agent == "agent-1"
    assert state.mode == SessionMode.HUMAN_CHAT


def test_push_to_session():
    """测试向会话推送消息"""
    mgr = get_session_manager()
    mgr.create_session("s1", "u1")
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            mgr.push_to_session("s1", {"type": "test", "data": 123})
        )
        assert result is True
        # 不存在的会话
        result = loop.run_until_complete(
            mgr.push_to_session("nope", {})
        )
        assert result is False
    finally:
        loop.close()


def test_stats():
    """测试统计信息"""
    mgr = get_session_manager()
    # 清理之前的测试数据
    mgr._sessions.clear()
    mgr.create_session("s1", "u1", mode=SessionMode.AI_CHAT)
    mgr.create_session("s2", "u2", mode=SessionMode.WAITING_HUMAN)
    stats = mgr.get_stats()
    assert stats["total_sessions"] == 2
    assert stats["sessions_by_mode"]["ai_chat"] == 1
    assert stats["sessions_by_mode"]["waiting_human"] == 1
