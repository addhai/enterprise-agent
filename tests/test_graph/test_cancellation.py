"""协作式取消原语与可取消 LLM 包装的单元测试

覆盖 2026-10-06「WS 断开后 CPU 空跑」修复的核心机制：
- 取消信号在 contextvar 绑定下生效，未绑定时空操作
- 硬超时到期抛 hard_timeout
- asyncio.to_thread 复制 context，工作线程内可收到主线程的取消信号
- 代际隔离与工作线程侧释放
- CancellableChatOpenAI 在请求前检查，取消时不触网
"""

import asyncio
import time

import pytest
from src.graph.cancellation import (
    WorkflowCancelled,
    _entries,
    begin_run,
    check_cancelled,
    release_run,
    request_cancel,
    workflow_run,
)


def test_check_noop_without_guard():
    """离线脚本/测试等未绑定运行的场景，检查必须是空操作"""
    check_cancelled()


def test_request_cancel_raises_in_guarded_run():
    with workflow_run("sess-cancel-1") as gen:
        request_cancel("sess-cancel-1", reason="client_disconnect")
        with pytest.raises(WorkflowCancelled) as exc:
            check_cancelled()
        assert exc.value.reason == "client_disconnect"
    # 上下文退出只解绑 contextvar；工作线程未 release 前条目仍在
    # （模拟 worker 尚未结束），手动释放清理
    release_run("sess-cancel-1", gen)
    assert "sess-cancel-1" not in _entries


def test_hard_timeout_raises_after_deadline():
    with workflow_run("sess-timeout-1", hard_timeout=0.05):
        time.sleep(0.12)
        with pytest.raises(WorkflowCancelled) as exc:
            check_cancelled()
        assert exc.value.reason == "hard_timeout"


def test_worker_release_makes_check_noop():
    """工作线程结束释放后，残留 context 再检查不应误报"""
    with workflow_run("sess-release-1") as gen:
        release_run("sess-release-1", gen)
        check_cancelled()  # 不抛


def test_generations_are_isolated():
    """同一会话新旧两轮：旧代际看不到新轮次的取消状态"""
    gen1 = begin_run("sess-gen-1")
    release_run("sess-gen-1", gen1)
    with workflow_run("sess-gen-1") as gen2:
        # 新轮次未取消
        check_cancelled()
        # 会话级取消会停掉当前轮次
        request_cancel("sess-gen-1")
        with pytest.raises(WorkflowCancelled):
            check_cancelled()
        assert gen2 != gen1


def test_cancel_propagates_through_to_thread():
    """工作线程内 check 抛出的取消异常能穿过 to_thread 被 async 侧捕获"""

    async def runner():
        key = "sess-thread-3"

        def blocking_worker():
            for _ in range(100):
                check_cancelled()
                time.sleep(0.02)

        with workflow_run(key):
            task = asyncio.create_task(asyncio.to_thread(blocking_worker))
            await asyncio.sleep(0.05)
            request_cancel(key)
            with pytest.raises(WorkflowCancelled):
                await task

    asyncio.run(runner())


# ---- CancellableChatOpenai 包装 -------------------------------------------


def test_model_raises_before_request_when_cancelled():
    """取消信号到达后，模型在发出 HTTP 请求前就抛异常（不触网）"""
    from src.agent.cancellable_llm import make_chat_model

    llm = make_chat_model(
        model="not-a-real-model",
        api_key="test-key",
        base_url="http://127.0.0.1:1",
    )
    # 默认补了单次请求超时（新版 langchain-openai 字段名为 request_timeout）
    assert llm.request_timeout is not None

    with workflow_run("sess-model-1"):
        request_cancel("sess-model-1")
        with pytest.raises(WorkflowCancelled):
            llm.invoke("hi")


def test_direct_synthesis_does_not_swallow_cancel(monkeypatch):
    """直答旁路的「任何异常都回落 ReAct」兜底不得吞掉取消信号，
    否则断线后会白走一遍 Agent 构建（生产实测曾出现该回落日志）"""
    from src.graph import nodes

    class _CancelModel:
        def invoke(self, messages):
            raise WorkflowCancelled(reason="client_disconnect")

    monkeypatch.setattr(nodes, "_get_intent_llm", lambda: _CancelModel())
    with pytest.raises(WorkflowCancelled):
        nodes._direct_synthesize_with_docs(
            "F02 怎么处理",
            history=[],
            docs=[],
            mode="always",
            retrieval_decided_by="always",
            retrieval_count=1,
        )
