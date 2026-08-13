"""tests for src.websocket.dispatcher

用 FakeSessionManager / FakeWS 覆盖转接分发、坐席分配、通知、坐席回复、
Copilot 建议、会话迁移与各类查询接口，不触网。
"""
import asyncio

import pytest

import src.websocket.dispatcher as disp
from src.websocket.dispatcher import TransferDispatcher


class FakeWS:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []
        self.closed = False

    async def send_json(self, payload):
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append(payload)


class FakeState:
    def __init__(self, ws=None):
        self._websocket_ref = ws
        self.mode = "ai"
        self.needs_human = False
        self.assigned_agent = None
        self.last_active = 0
        self.message_queue = asyncio.Queue()


class FakeSessionManager:
    def __init__(self):
        self.sessions = {}
        self.agents = {}
        self.online = []
        self.modes = {}

    def update_mode(self, sid, mode):
        self.modes[sid] = mode

    def list_online_agents(self):
        return list(self.online)

    def assign_agent_to_session(self, sid, agent_id):
        self.sessions.setdefault(sid, FakeState()).assigned_agent = agent_id

    def get_agent(self, agent_id):
        return self.agents.get(agent_id)

    def get_session(self, sid):
        return self.sessions.get(sid)


@pytest.fixture
def dispatcher(monkeypatch):
    fake = FakeSessionManager()
    monkeypatch.setattr(disp, "get_session_manager", lambda: fake)
    TransferDispatcher._instance = None
    d = TransferDispatcher()
    d._session_mgr = fake
    d._fake = fake
    yield d
    # 还原模块级单例，避免污染其它用到 dispatcher 的测试
    TransferDispatcher._instance = None


async def test_handle_escalation_assigns_agent(dispatcher):
    dispatcher._fake.online = ["agent1"]
    dispatcher._fake.agents["agent1"] = FakeWS()
    state = {
        "user_id": "u1",
        "intent": "refund",
        "quality_score": 0.2,
    }
    res = await dispatcher.handle_escalation("s1", state, [{"role": "user", "content": "退款"}])
    assert res["needs_human"] is True
    assert res["agent_assigned"] == "agent1"
    assert dispatcher._fake.modes["s1"].value == "waiting_human"
    # 通知已发给 agent
    assert dispatcher._fake.agents["agent1"].sent


async def test_handle_escalation_queues_when_no_agent(dispatcher):
    dispatcher._fake.online = []
    state = {"user_id": "u1"}
    res = await dispatcher.handle_escalation("s2", state, [])
    assert res["agent_assigned"] is None
    assert dispatcher.get_pending_count() == 1


async def test_handle_escalation_notify_failure_queues(dispatcher):
    dispatcher._fake.online = ["agentX"]
    dispatcher._fake.agents["agentX"] = FakeWS(fail=True)
    state = {"user_id": "u1"}
    res = await dispatcher.handle_escalation("s3", state, [])
    assert res["agent_assigned"] == "agentX"
    # 通知失败 -> 重新入队
    assert dispatcher.get_pending_count() == 1


async def test_agent_reply_direct(dispatcher):
    ws = FakeWS()
    st = FakeState(ws=ws)
    dispatcher._fake.sessions["s4"] = st
    ok = await dispatcher.agent_reply("agent1", "s4", "你好")
    assert ok is True
    assert ws.sent
    assert ws.sent[0]["type"] == "human_reply"


async def test_agent_reply_no_session(dispatcher):
    ok = await dispatcher.agent_reply("a", "missing", "hi")
    assert ok is False


async def test_agent_reply_no_ws_queues(dispatcher):
    st = FakeState(ws=None)
    dispatcher._fake.sessions["s5"] = st
    ok = await dispatcher.agent_reply("a", "s5", "hi")
    assert ok is False
    # 消息进了队列
    assert not st.message_queue.empty()


async def test_agent_reply_ws_send_failure(dispatcher):
    ws = FakeWS(fail=True)
    st = FakeState(ws=ws)
    dispatcher._fake.sessions["s6"] = st
    ok = await dispatcher.agent_reply("a", "s6", "hi")
    assert ok is False


async def test_copilot_suggestions_error_keyword(dispatcher):
    s = await dispatcher.get_copilot_suggestions("s", "报错了 error", [])
    assert len(s) >= 1
    assert "错误" in s[0] or "报错" in s[0]


async def test_copilot_suggestions_refund_keyword(dispatcher):
    s = await dispatcher.get_copilot_suggestions("s", "我要退款 refund", [])
    assert any("退款" in x for x in s)


async def test_copilot_suggestions_config_keyword(dispatcher):
    s = await dispatcher.get_copilot_suggestions("s", "如何配置 setup", [])
    assert len(s) >= 1


async def test_copilot_suggestions_login_keyword(dispatcher):
    s = await dispatcher.get_copilot_suggestions("s", "登录 login 密码", [])
    assert any("密码" in x or "登录" in x for x in s)


async def test_copilot_suggestions_fallback(dispatcher):
    s = await dispatcher.get_copilot_suggestions("s", "随便聊聊", [])
    assert len(s) == 2


async def test_push_copilot_suggestions_happy(dispatcher):
    ws = FakeWS()
    dispatcher._fake.agents["agent1"] = ws
    dispatcher._session_transfers["s7"] = "t1"
    from src.websocket.dispatcher import TransferRecord

    rec = TransferRecord(
        transfer_id="t1", session_id="s7", user_id="u1",
        context={}, urgency="normal", assigned_agent="agent1",
    )
    dispatcher._records["t1"] = rec
    await dispatcher.push_copilot_suggestions("s7", "报错", [])
    assert ws.sent and ws.sent[0]["type"] == "copilot_suggestion"


async def test_push_copilot_no_record(dispatcher):
    # 无转接记录 -> 直接返回
    await dispatcher.push_copilot_suggestions("sX", "hi", [])


async def test_push_copilot_no_assigned_agent(dispatcher):
    dispatcher._session_transfers["s8"] = "t2"
    from src.websocket.dispatcher import TransferRecord

    rec = TransferRecord(
        transfer_id="t2", session_id="s8", user_id="u1",
        context={}, urgency="normal", assigned_agent=None,
    )
    dispatcher._records["t2"] = rec
    await dispatcher.push_copilot_suggestions("s8", "hi", [])


def test_migrate_to_human(dispatcher):
    st = FakeState()
    dispatcher._fake.sessions["s9"] = st
    assert dispatcher.migrate_to_human("s9") is True
    assert st.mode.value == "human_chat"
    assert st.needs_human is True


def test_migrate_to_human_missing(dispatcher):
    assert dispatcher.migrate_to_human("missing") is False


def test_migrate_to_ai(dispatcher):
    st = FakeState()
    st.assigned_agent = "agent1"
    dispatcher._fake.sessions["s10"] = st
    assert dispatcher.migrate_to_ai("s10") is True
    assert st.mode.value == "ai_chat"
    assert st.needs_human is False
    assert st.assigned_agent is None


def test_migrate_to_ai_missing(dispatcher):
    assert dispatcher.migrate_to_ai("missing") is False


def test_get_transfer_record_and_session(dispatcher):
    from src.websocket.dispatcher import TransferRecord

    rec = TransferRecord(
        transfer_id="t3", session_id="s11", user_id="u1", context={}, urgency="normal",
    )
    dispatcher._records["t3"] = rec
    dispatcher._session_transfers["s11"] = "t3"
    assert dispatcher.get_transfer_record("t3") is rec
    assert dispatcher.get_session_transfer("s11") == "t3"
    assert dispatcher.get_transfer_record("nope") is None


def test_get_stats(dispatcher):
    from src.websocket.dispatcher import TransferRecord

    dispatcher._records["t4"] = TransferRecord(
        transfer_id="t4", session_id="s12", user_id="u1", context={},
        urgency="normal", assigned_agent="a", status="assigned",
    )
    dispatcher._queue.append(dispatcher._records["t4"])
    stats = dispatcher.get_stats()
    assert stats["total_transfers"] == 1
    assert stats["active_transfers"] == 1
    assert stats["pending_queue"] == 1
