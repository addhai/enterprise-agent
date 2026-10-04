"""
AgentWorker 消息处理路由的单测（无 RabbitMQ / 无 LLM 依赖）。

覆盖关键链路：
  - 正常任务           → basic_ack
  - 非法 JSON 消息     → basic_reject（不重试）
  - 处理过程抛异常     → basic_nack（由消息 TTL + DLX 决定进 DLQ）
即「消费一条任务消息」的核心 ACK / REJECT / NACK 语义，是 worker 最不该出错的路径。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from src.worker.consumer import AgentWorker


class _FakeChannel:
    """记录 ACK / REJECT / NACK 调用的轻量替身，无需真实 RabbitMQ。"""

    def __init__(self) -> None:
        self.acks: list = []
        self.rejects: list = []
        self.nacks: list = []

    def basic_ack(self, delivery_tag: int, **_kw) -> None:
        self.acks.append(delivery_tag)

    def basic_reject(self, delivery_tag: int, **_kw) -> None:
        self.rejects.append(delivery_tag)

    def basic_nack(self, delivery_tag: int, **_kw) -> None:
        self.nacks.append(delivery_tag)


def _method(delivery_tag: int = 1) -> MagicMock:
    m = MagicMock()
    m.delivery_tag = delivery_tag
    return m


def _props() -> MagicMock:
    return MagicMock()


def _worker() -> AgentWorker:
    return AgentWorker(rabbitmq_url="amqp://guest:guest@localhost:5672")


def test_handle_message_acks_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _worker()
    ch = _FakeChannel()
    body = json.dumps(
        {"task_id": "t1", "user_id": "u1", "session_id": "s1", "message": "hi"}
    ).encode()

    # 跳过真实 LangGraph 编排，直接返回结果
    monkeypatch.setattr(
        worker,
        "_process_task",
        lambda task: {
            "intent": "faq",
            "final_response": "ok",
            "needs_human": False,
            "quality_score": 0.9,
        },
    )

    worker._handle_message(ch, _method(), _props(), body)

    assert ch.acks == [1]
    assert ch.rejects == [] and ch.nacks == []


def test_handle_message_rejects_on_invalid_json() -> None:
    worker = _worker()
    ch = _FakeChannel()

    worker._handle_message(ch, _method(), _props(), b"{not valid json")

    assert ch.rejects == [1]
    assert ch.acks == [] and ch.nacks == []


def test_handle_message_nacks_on_process_error(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _worker()
    ch = _FakeChannel()
    body = json.dumps({"task_id": "t2", "message": "hi"}).encode()

    def _boom(_task):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(worker, "_process_task", _boom)

    worker._handle_message(ch, _method(), _props(), body)

    assert ch.nacks == [1]
    assert ch.acks == [] and ch.rejects == []
