"""
/chat 在线韧性 P0 测试（2026-11）

覆盖三项在线 P0 修复，全部直接 await 路由协程，无需起 ASGI 容器、不触网：
- P0-A 同步 app.invoke 经 asyncio.to_thread 卸载到工作线程，事件循环不被阻塞
- P0-B 全局并发闸门满员时 503 快速失败，异常路径保证槽位不泄漏
- P0-C 工作流异常细节只进服务端日志，对外仅返回通用 500 文案

conftest.py 的 autouse fixture 已把 get_workflow 打成 FakeWorkflow，
本文件各用例再用 monkeypatch 覆盖为带行为探针的自定义假实现。
"""

import asyncio
import threading

import pytest
from fastapi import HTTPException
from src.api import routes
from src.api.routes import ChatRequest, ChatResponse
from src.config import Settings, settings

# 与 test_routes.py 中 token 用户同构的服务端身份字典，直接喂给路由协程。
_CURRENT_USER = {
    "user_id": "u-resilience",
    "tenant_id": "t-resilience",
    "role": "admin",
}


def _ok_result():
    """构造 routes.chat 会读取的完整工作流返回字段。"""
    return {
        "final_response": "ok",
        "needs_human": False,
        "suggest_human": False,
        "access_filtered": 0,
        "intent": "faq",
        "turn_count": 1,
        "quality_score": 0.9,
    }


@pytest.fixture
def clean_gate():
    """每个用例前后清空信号量缓存，杜绝跨用例的闸门状态污染。"""
    routes._chat_semaphores.clear()
    yield
    routes._chat_semaphores.clear()


class _ThreadProbeWorkflow:
    """记录 invoke 实际执行线程，用于证明 to_thread 卸载生效。"""

    def __init__(self):
        self.worker_ident = None

    def invoke(self, state, config=None):
        self.worker_ident = threading.get_ident()
        return _ok_result()


class _BlockingWorkflow:
    """进入 invoke 后阻塞，直到测试放开，用于占住并发槽位。"""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def invoke(self, state, config=None):
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("_BlockingWorkflow 等待释放超时")
        return _ok_result()


class _BoomWorkflow:
    """调用即抛异常，验证异常文案收敛与槽位释放。"""

    def __init__(self, secret_marker):
        self.secret_marker = secret_marker

    def invoke(self, state, config=None):
        raise RuntimeError(self.secret_marker)


# ============================================================
# P0-A：事件循环 offload
# ============================================================


@pytest.mark.asyncio
async def test_chat_invoke_runs_in_worker_thread(monkeypatch, clean_gate):
    """app.invoke 必须在工作线程执行，与事件循环线程不同。

    旧实现裸调同步 invoke 时两者线程相同，本用例对旧代码会确定性失败。
    """
    workflow = _ThreadProbeWorkflow()
    monkeypatch.setattr(routes, "get_workflow", lambda: workflow)

    loop_thread_ident = threading.get_ident()
    response = await routes.chat(
        ChatRequest(message="你好"), current_user=_CURRENT_USER
    )

    assert isinstance(response, ChatResponse)
    assert workflow.worker_ident is not None
    assert workflow.worker_ident != loop_thread_ident


# ============================================================
# P0-B：全局并发闸门
# ============================================================


@pytest.mark.asyncio
async def test_chat_over_limit_returns_503(monkeypatch, clean_gate):
    """容量为 1 时，第二个在途请求必须立即 503，并带 Retry-After。"""
    monkeypatch.setattr(settings, "chat_max_concurrent", 1)
    workflow = _BlockingWorkflow()
    monkeypatch.setattr(routes, "get_workflow", lambda: workflow)

    first_task = asyncio.create_task(
        routes.chat(ChatRequest(message="first"), current_user=_CURRENT_USER)
    )
    # 让出事件循环，等工作线程真正进入 invoke，此时槽位已被占用。
    assert await asyncio.to_thread(workflow.entered.wait, 5)

    with pytest.raises(HTTPException) as exc_info:
        await routes.chat(ChatRequest(message="second"), current_user=_CURRENT_USER)
    assert exc_info.value.status_code == 503
    assert exc_info.value.headers["Retry-After"] == "30"

    workflow.release.set()
    first_response = await first_task
    assert isinstance(first_response, ChatResponse)


@pytest.mark.asyncio
async def test_chat_gate_released_after_exception(monkeypatch, clean_gate):
    """工作流异常走 finally 释放槽位后，后续请求仍能拿到额度正常执行。"""
    monkeypatch.setattr(settings, "chat_max_concurrent", 1)
    monkeypatch.setattr(routes, "get_workflow", lambda: _BoomWorkflow("boom-once"))

    with pytest.raises(HTTPException) as first_exc:
        await routes.chat(ChatRequest(message="first"), current_user=_CURRENT_USER)
    assert first_exc.value.status_code == 500

    # 若异常路径漏释放，容量 1 的闸门此处会直接 503。
    monkeypatch.setattr(routes, "get_workflow", lambda: _ThreadProbeWorkflow())
    second_response = await routes.chat(
        ChatRequest(message="second"), current_user=_CURRENT_USER
    )
    assert isinstance(second_response, ChatResponse)


# ============================================================
# P0-C：异常细节不泄漏
# ============================================================


@pytest.mark.asyncio
async def test_internal_exception_detail_not_leaked(monkeypatch, clean_gate):
    """500 响应只含通用文案，原始异常串不得出现在对外 detail 中。"""
    secret_marker = "SECRET-INTERNAL-DETAIL-XYZ"
    monkeypatch.setattr(routes, "get_workflow", lambda: _BoomWorkflow(secret_marker))

    with pytest.raises(HTTPException) as exc_info:
        await routes.chat(ChatRequest(message="hi"), current_user=_CURRENT_USER)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Internal server error"
    assert secret_marker not in str(exc_info.value.detail)


# ============================================================
# 配置契约：闸门默认关闭，保护生产既有行为
# ============================================================


def test_chat_gate_disabled_by_default():
    """代码级默认值必须为 0（关闭），启用需显式 env CHAT_MAX_CONCURRENT。"""
    field = Settings.model_fields["chat_max_concurrent"]
    assert field.default == 0
