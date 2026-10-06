"""工作流协作式取消：WS 断开与单轮硬超时

背景（2026-10-06 生产实测）：
    WS 处理器通过 ``asyncio.to_thread(app.invoke)`` 在线程池里跑同步
    langgraph。Python 无法强杀运行中的线程，客户端断开后接收循环又无人读
    套接字，检测不到断开，图会在 CPU 上跑到自然结束，实测单轮空跑 88 分钟。

修法：协作式取消。每次 LLM 调用前后检查取消信号（见
``src.agent.cancellable_llm.CancellableChatOpenAI``），信号到达后在下一次
调用边界抛 :class:`WorkflowCancelled`，图在节点边界快速收卷。浪费的 CPU
上限等于一次在途 LLM 请求，由 ``settings.llm_request_timeout`` 封顶。

两个取消来源：
    1. 客户端断开：WS 接收循环捕获 WebSocketDisconnect 后
       :func:`request_cancel`。
    2. 硬超时：注册时写入 deadline（应对客户端静默掉线、TCP 来不及通知）。

会话与取消信号的关联：
    键是 session_id，代际（gen）区分同一会话断线重连后新旧两轮。
    键与代际通过 contextvar 传递：``asyncio.to_thread`` 会复制当前 context，
    工作线程内所有 LLM（含模块级单例）读到的都是本轮的 (key, gen)。
    request_cancel 取消该会话所有代际（断开即停掉该会话全部在跑的轮次）。

生命周期：
    async 侧只负责 set/reset contextvar；注册表条目的删除权在工作线程
    （app.invoke 外层 finally 调 :func:`release_run`）。这样即使 async 任务
    先被 cancel，在途 LLM 返回后检查仍然能看到取消信号而收卷，不会因条目
    提前删除而漏判。begin 时顺手清理同键下早已过期的残留条目兜底。
"""

from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

#: 残留条目最长保留时间（秒）。正常路径由工作线程 release；
#: 只有线程异常死亡才会残留，begin 同键新轮次时按此值清扫。
_STALE_ENTRY_TTL = 3600.0


class WorkflowCancelled(Exception):
    """工作流被协作式取消（客户端断开或硬超时）"""

    def __init__(self, reason: str = "cancelled") -> None:
        self.reason = reason
        super().__init__(f"workflow cancelled: {reason}")


@dataclass
class _Entry:
    gen: int
    event: threading.Event = field(default_factory=threading.Event)
    deadline: float | None = None
    reason: str = ""
    created_at: float = field(default_factory=time.monotonic)


_lock = threading.Lock()
#: session_id -> {gen: entry}
_entries: dict[str, dict[int, _Entry]] = {}
_gen_seq = 0

#: 当前 context 绑定的运行代际 (session_id, gen)，to_thread 复制后透传进图
_current_run: contextvars.ContextVar[tuple[str, int] | None] = contextvars.ContextVar(
    "workflow_cancel_run",
    default=None,
)


def begin_run(key: str, hard_timeout: float | None = None) -> int:
    """注册一轮工作流运行，返回代际号 gen。

    工作线程必须在 app.invoke 的 finally 中调用 :func:`release_run` 释放。
    """
    global _gen_seq
    now = time.monotonic()
    with _lock:
        bucket = _entries.setdefault(key, {})
        # 清扫同键残留（线程异常死亡、无人 release 的过期条目）
        for old_gen, old in list(bucket.items()):
            expired_deadline = (
                old.deadline is not None and now - old.deadline > _STALE_ENTRY_TTL
            )
            expired_age = now - old.created_at > _STALE_ENTRY_TTL
            if expired_deadline or expired_age:
                bucket.pop(old_gen, None)

        _gen_seq += 1
        gen = _gen_seq
        deadline = now + hard_timeout if hard_timeout and hard_timeout > 0 else None
        bucket[gen] = _Entry(gen=gen, deadline=deadline)
        return gen


def release_run(key: str, gen: int) -> None:
    """工作线程侧：app.invoke 结束（正常/异常）后释放本轮条目。幂等。"""
    with _lock:
        bucket = _entries.get(key)
        if bucket is not None:
            bucket.pop(gen, None)
            if not bucket:
                _entries.pop(key, None)


def request_cancel(key: str, reason: str = "client_disconnect") -> None:
    """取消指定会话下所有在跑的轮次（断线重连前后两轮都会被停掉）。"""
    with _lock:
        for entry in _entries.get(key, {}).values():
            entry.reason = reason
            entry.event.set()


def check_cancelled() -> None:
    """LLM 调用边界检查。未绑定运行（离线脚本/测试）时为空操作。"""
    bound = _current_run.get()
    if bound is None:
        return
    key, gen = bound
    with _lock:
        entry = _entries.get(key, {}).get(gen)
        if entry is None:
            # 条目已被工作线程自己释放，或本轮根本未注册：不干预
            return
        fired = entry.event.is_set()
        reason = entry.reason or "client_disconnect"
        deadline = entry.deadline

    if fired:
        raise WorkflowCancelled(reason)
    if deadline is not None and time.monotonic() >= deadline:
        # 不在这里 set event：硬超时只针对本轮，断开取消才是会话级信号
        raise WorkflowCancelled("hard_timeout")


@contextmanager
def workflow_run(key: str, hard_timeout: float | None = None) -> Iterator[int]:
    """async 侧绑定本轮运行到当前 context（to_thread 会复制进工作线程）。

    用法::

        with workflow_run(session_id, 600.0) as gen:
            result = await asyncio.to_thread(_invoke_graph, app, state, cfg, key, gen)

    注意：本上下文管理器不负责删除注册表条目，释放权在工作线程的
    :func:`release_run`，避免 async 任务先被 cancel 时条目被提前清空、
    在途 LLM 返回后漏检取消信号。
    """
    gen = begin_run(key, hard_timeout)
    token = _current_run.set((key, gen))
    try:
        yield gen
    finally:
        _current_run.reset(token)
