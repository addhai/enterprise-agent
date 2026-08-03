"""对话持久化往返测试（离线 sqlite）

锁定阶段三的核心保证：
  - conversation_ensure 创建会话行（id == session_id）
  - message_save 落库用户 / 助手消息
  - message_list 按时间正序返回，role 正确（WebSocket 重启恢复历史即依赖此）
  - conversation_list 聚合 message_count 与 last_message
"""
from __future__ import annotations

from src.db.repositories import (
    conversation_ensure,
    conversation_list,
    message_list,
    message_save,
)


def _reset():
    from src.db.repositories import db_session
    from src.db.models import Conversation, Message

    with db_session() as s:
        s.query(Message).delete()
        s.query(Conversation).delete()


def test_conversation_ensure_returns_session_id():
    _reset()
    sid = "SES-PERSIST-1"
    got = conversation_ensure(sid, "default", "u1", channel="web")
    assert got == sid
    # 重复调用幂等（不报错，更新 updated_at）
    conversation_ensure(sid, "default", "u1", channel="web")


def test_message_roundtrip_preserves_order_and_roles():
    _reset()
    sid = "SES-PERSIST-2"
    conversation_ensure(sid, "default", "u1", channel="web")
    message_save(sid, "default", "u1", "user", "你好，怎么退款？")
    message_save(sid, "default", "u1", "assistant", "7天内可申请无理由退款。")
    message_save(sid, "default", "u1", "user", "那发票呢？")

    rows = message_list(sid, limit=200)
    assert [r["role"] for r in rows] == ["user", "assistant", "user"]
    assert rows[0]["content"] == "你好，怎么退款？"
    assert rows[2]["content"] == "那发票呢？"
    # 默认按时间正序
    assert rows[0]["created_at"] <= rows[2]["created_at"]


def test_conversation_list_aggregates_count_and_last():
    _reset()
    sid = "SES-PERSIST-3"
    conversation_ensure(sid, "default", "u1", channel="web")
    message_save(sid, "default", "u1", "user", "第一轮问题")
    message_save(sid, "default", "u1", "assistant", "第一轮回答内容较长一二三")

    convs = conversation_list("default", "u1", limit=50)
    assert len(convs) == 1
    c = convs[0]
    assert c["session_id"] == sid
    assert c["message_count"] == 2
    # last_message 截断到 200 字符，前缀应为助手回复
    assert c["last_message"].startswith("第一轮回答内容")


def test_isolation_by_session_id():
    """不同 session 的消息互不串（与知识库 kb_id 隔离同一思想）。"""
    _reset()
    a, b = "SES-A", "SES-B"
    conversation_ensure(a, "default", "u1", channel="web")
    conversation_ensure(b, "default", "u2", channel="web")
    message_save(a, "default", "u1", "user", "A的独有内容")
    message_save(b, "default", "u2", "user", "B的独有内容")

    rows_a = message_list(a, limit=200)
    rows_b = message_list(b, limit=200)
    assert [r["content"] for r in rows_a] == ["A的独有内容"]
    assert [r["content"] for r in rows_b] == ["B的独有内容"]
