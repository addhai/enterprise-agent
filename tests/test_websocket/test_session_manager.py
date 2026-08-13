"""WebSocketSessionManager 单元测试。

覆盖会话状态机、人工坐席注册/分配、消息推送、心跳清理与统计等全部分支。
不依赖任何外部服务，纯逻辑单测。
"""
from __future__ import annotations

import asyncio

import pytest

from src.websocket import session_manager as sm_mod
from src.websocket.session_manager import (
    SessionMode,
    WebSocketSessionManager,
    get_session_manager,
)


class FakeWS:
    """模拟人工坐席 WebSocket 连接。"""

    def __init__(self, fail: bool = False):
        self.sent: list = []
        self.fail = fail

    async def send_json(self, data):
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append(data)


@pytest.fixture
def sm():
    # 重置单例，保证每个测试拿到干净的实例
    WebSocketSessionManager._instance = None
    sm_mod._session_manager = None
    inst = WebSocketSessionManager()
    yield inst
    # 收尾：取消可能残留的清理任务
    task = inst._cleanup_task
    if task is not None and not task.done():
        task.cancel()
        try:
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
        except (asyncio.CancelledError, RuntimeError, ValueError):
            pass


# ----------------------------------------------------------------------
# 单例与构造
# ----------------------------------------------------------------------

def test_singleton_returns_same_instance():
    a = WebSocketSessionManager()
    b = WebSocketSessionManager()
    assert a is b
    # __init__ 的 _initialized 守卫：第二次构造不应重置状态
    assert a._initialized is True


def test_get_session_manager_lazy_singleton():
    WebSocketSessionManager._instance = None
    sm_mod._session_manager = None
    m1 = get_session_manager()
    m2 = get_session_manager()
    assert m1 is m2
    assert isinstance(m1, WebSocketSessionManager)


# ----------------------------------------------------------------------
# 会话管理
# ----------------------------------------------------------------------

def test_create_session_default_mode(sm):
    st = sm.create_session("s1", "u1", "t1")
    assert st.session_id == "s1"
    assert st.user_id == "u1"
    assert st.tenant_id == "t1"
    assert st.mode == SessionMode.AI_CHAT
    assert sm.get_session("s1") is st


def test_create_session_custom_mode(sm):
    st = sm.create_session("s2", "u2", "t2", mode=SessionMode.HUMAN_CHAT)
    assert st.mode == SessionMode.HUMAN_CHAT


def test_get_session_missing(sm):
    assert sm.get_session("nope") is None


def test_get_session_updates_last_active(sm):
    st = sm.create_session("s3", "u3")
    st.last_active = 0.0
    got = sm.get_session("s3")
    assert got is st
    assert got.last_active > 0.0


def test_update_mode_success(sm):
    st = sm.create_session("s4", "u4")
    assert sm.update_mode("s4", SessionMode.WAITING_HUMAN) is True
    assert st.mode == SessionMode.WAITING_HUMAN


def test_update_mode_missing(sm):
    assert sm.update_mode("ghost", SessionMode.HUMAN_CHAT) is False


def test_remove_session_success(sm):
    sm.create_session("s5", "u5")
    assert sm.remove_session("s5") is True
    assert sm.get_session("s5") is None


def test_remove_session_missing(sm):
    assert sm.remove_session("ghost") is False


# ----------------------------------------------------------------------
# 人工坐席管理
# ----------------------------------------------------------------------

def test_agent_register_unreg_get_list(sm):
    ws = FakeWS()
    sm.register_agent("a1", ws)
    assert sm.get_agent("a1") is ws
    assert sm.list_online_agents() == ["a1"]
    sm.unregister_agent("a1")
    assert sm.get_agent("a1") is None
    assert sm.list_online_agents() == []


def test_assign_agent_to_session_success(sm):
    st = sm.create_session("s6", "u6")
    ws = FakeWS()
    sm.register_agent("a1", ws)
    assert sm.assign_agent_to_session("s6", "a1") is True
    assert st.assigned_agent == "a1"
    assert st.mode == SessionMode.HUMAN_CHAT


def test_assign_agent_no_session(sm):
    ws = FakeWS()
    sm.register_agent("a1", ws)
    assert sm.assign_agent_to_session("ghost", "a1") is False


def test_assign_agent_not_registered(sm):
    st = sm.create_session("s7", "u7")
    assert sm.assign_agent_to_session("s7", "aX") is False


# ----------------------------------------------------------------------
# 消息推送（异步）
# ----------------------------------------------------------------------

async def test_push_to_session_success(sm):
    st = sm.create_session("s8", "u8")
    ok = await sm.push_to_session("s8", {"x": 1})
    assert ok is True
    assert st.message_queue.qsize() == 1


async def test_push_to_session_missing(sm):
    assert await sm.push_to_session("ghost", {"x": 1}) is False


async def test_push_to_agent_success(sm):
    ws = FakeWS()
    sm.register_agent("a1", ws)
    ok = await sm.push_to_agent("a1", {"hello": "world"})
    assert ok is True
    assert ws.sent == [{"hello": "world"}]


async def test_push_to_agent_no_ws(sm):
    # agent 未注册 -> ws 为 None 分支
    assert await sm.push_to_agent("ghost", {"x": 1}) is False


async def test_push_to_agent_exception(sm):
    ws = FakeWS(fail=True)
    sm.register_agent("a1", ws)
    assert await sm.push_to_agent("a1", {"x": 1}) is False


# ----------------------------------------------------------------------
# 心跳清理任务 start/stop
# ----------------------------------------------------------------------

async def test_start_creates_cleanup_task(sm):
    await sm.start()
    assert sm._cleanup_task is not None
    assert not sm._cleanup_task.done()
    await sm.stop()
    assert sm._cleanup_task.cancelled() or sm._cleanup_task.done()


async def test_stop_without_start_is_noop(sm):
    # 未启动 -> _cleanup_task 为 None，stop 不应抛错
    assert sm._cleanup_task is None
    await sm.stop()


async def test_start_existing_task_not_recreated(sm):
    await sm.start()
    t1 = sm._cleanup_task
    await sm.start()
    assert sm._cleanup_task is t1
    await sm.stop()


# ----------------------------------------------------------------------
# 统计
# ----------------------------------------------------------------------

def test_get_stats_empty(sm):
    stats = sm.get_stats()
    assert stats["total_sessions"] == 0
    assert stats["sessions_by_mode"] == {}
    assert stats["online_agents"] == 0
    assert stats["agent_ids"] == []


def test_get_stats_with_sessions_and_agents(sm):
    sm.create_session("s9", "u9", mode=SessionMode.AI_CHAT)
    sm.create_session("s10", "u10", mode=SessionMode.HUMAN_CHAT)
    sm.register_agent("a1", FakeWS())
    stats = sm.get_stats()
    assert stats["total_sessions"] == 2
    assert stats["sessions_by_mode"] == {"ai_chat": 1, "human_chat": 1}
    assert stats["online_agents"] == 1
    assert stats["agent_ids"] == ["a1"]
