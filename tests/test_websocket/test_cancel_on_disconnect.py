"""WS 断开即取消工作流的端到端测试（2026-10-06 CPU 空跑修复）

背景：旧实现里接收循环直接 await _handle_ai_chat，图在 to_thread 里跑时
无人读套接字，客户端断开检测不到，Python 又无法杀线程，CPU 空跑最长
88 分钟。本测试用 TestClient + 阻塞式假工作流验证：
1. 连接关闭后，工作线程在下一次检查边界收到取消信号并收卷
2. 注册表条目随工作线程结束被释放
3. 上一轮还在跑时第二条消息收到 BUSY，保证串行语义
"""

import json
import threading
import time

from fastapi.testclient import TestClient
from src.api.server import app
from src.graph import cancellation


class BlockingFakeApp:
    """在检查循环里阻塞、直到被协作式取消的假 langgraph app"""

    def __init__(self, stop_after: float = 30.0):
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.got_cancel = False
        self._stop_after = stop_after

    def invoke(self, state, config):
        self.started.set()
        deadline = time.monotonic() + self._stop_after
        try:
            while time.monotonic() < deadline:
                cancellation.check_cancelled()
                time.sleep(0.02)
        except cancellation.WorkflowCancelled:
            self.got_cancel = True
            raise
        finally:
            self.stopped.set()
        return {"final_response": "不应走到这里", "messages": []}

    def get_state(self, config):
        return None


def _patch_deps(monkeypatch, fake_app):
    monkeypatch.setattr("src.api.dependencies.get_workflow", lambda: fake_app)
    monkeypatch.setattr("src.db.repositories.conversation_ensure", lambda *a, **k: None)
    monkeypatch.setattr("src.db.repositories.message_save", lambda *a, **k: None)
    monkeypatch.setattr("src.db.repositories.message_list", lambda *a, **k: [])
    monkeypatch.setattr(
        "src.websocket.multimodal.process_multimodal_message",
        lambda m, **k: (m, m),
    )
    monkeypatch.setattr("src.api.metrics.gauge_inc", lambda *a, **k: None)
    monkeypatch.setattr("src.api.metrics.gauge_dec", lambda *a, **k: None)


def test_disconnect_cancels_running_workflow(monkeypatch):
    fake_app = BlockingFakeApp()
    _patch_deps(monkeypatch, fake_app)

    client = TestClient(app)
    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "session_ready"
        sid = ready["session_id"]

        ws.send_text(json.dumps({"type": "chat_message", "message": "一个很慢的问题"}))
        # 等待工作线程真正跑起来
        assert fake_app.started.wait(timeout=3)

    # with 退出即关闭连接：服务端接收循环应检测到断开并 request_cancel
    assert fake_app.stopped.wait(timeout=5), "工作线程未在断开后收卷"
    assert fake_app.got_cancel, "工作线程未收到取消信号"

    # 工作线程 finally 释放注册条目，注册表不应残留
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if sid not in cancellation._entries:
            break
        time.sleep(0.02)
    assert sid not in cancellation._entries


def test_hard_timeout_returns_workflow_error_while_connected(monkeypatch):
    """客户端没断开但图跑过墙钟硬超时：async 侧仍存活，应收到超时错误帧"""
    import src.websocket.routes as rt

    fake_app = BlockingFakeApp()
    _patch_deps(monkeypatch, fake_app)
    monkeypatch.setattr(rt._ws_settings, "ws_workflow_hard_timeout", 0.2)

    client = TestClient(app)
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text(json.dumps({"type": "chat_message", "message": "一个卡住的问题"}))
        assert fake_app.started.wait(timeout=3)

        got_timeout = False
        for _ in range(10):
            frame = ws.receive_json()
            if (
                frame.get("type") == "error"
                and frame.get("error_code") == "WORKFLOW_TIMEOUT"
            ):
                got_timeout = True
                break
        assert got_timeout, "硬超时后未收到 WORKFLOW_TIMEOUT 错误帧"

    assert fake_app.stopped.wait(timeout=5)
    assert fake_app.got_cancel


def test_second_message_while_busy_gets_busy_error(monkeypatch):
    fake_app = BlockingFakeApp()
    _patch_deps(monkeypatch, fake_app)

    client = TestClient(app)
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()  # session_ready
        ws.send_text(json.dumps({"type": "chat_message", "message": "慢问题一"}))
        assert fake_app.started.wait(timeout=3)

        ws.send_text(json.dumps({"type": "chat_message", "message": "慢问题二"}))

        # 收到的可能先有 typing_indicator，循环取到 BUSY 错误为止
        frames = []
        for _ in range(5):
            frame = ws.receive_json()
            frames.append(frame)
            if frame.get("type") == "error" and frame.get("error_code") == "BUSY":
                break
        assert any(
            f.get("type") == "error" and f.get("error_code") == "BUSY" for f in frames
        ), frames
