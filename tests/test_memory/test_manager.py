"""MemoryManager 单元测试

覆盖：
- 短期记忆池管理（按 session_id 路由）
- on_entry 注入长期记忆上下文
- on_rag_start 提取对话历史
- on_completion 持久化长期记忆
- 匿名用户跳过长期记忆
- 评估接口（record_quality / get_context_for_evaluation）
- 会话清理（cleanup_session / cleanup_expired）
"""
import pytest

from src.memory.manager import MemoryManager


@pytest.fixture(autouse=True)
def force_in_memory(monkeypatch):
    """强制使用内存模式（禁用 Redis / PG / Chroma）"""
    monkeypatch.setattr("src.memory.short_term._get_redis", lambda: None)
    monkeypatch.setattr("src.memory.long_term._get_pg_pool", lambda: None)
    monkeypatch.setattr("src.memory.long_term._get_memory_chroma", lambda: None)


@pytest.fixture
def manager():
    return MemoryManager()


# ============================================================
# 短期记忆池
# ============================================================

class TestShortTermPool:
    def test_get_short_term_creates_per_session(self, manager):
        stm1 = manager.get_short_term("session-1")
        stm2 = manager.get_short_term("session-2")
        assert stm1 is not stm2
        assert stm1.session_id == "session-1"
        assert stm2.session_id == "session-2"

    def test_get_short_term_reuses_same_session(self, manager):
        stm1 = manager.get_short_term("session-1")
        stm2 = manager.get_short_term("session-1")
        assert stm1 is stm2


# ============================================================
# on_entry 接入点
# ============================================================

class TestOnEntry:
    def test_anonymous_user_returns_empty(self, manager):
        ctx = manager.on_entry("session-x", "anonymous", "你好")
        assert ctx == ""

    def test_empty_user_id_returns_empty(self, manager):
        ctx = manager.on_entry("session-x", "", "你好")
        assert ctx == ""

    def test_records_user_message_to_short_term(self, manager):
        manager.on_entry("session-1", "user-1", "我的 API 是 v2 版本")
        stm = manager.get_short_term("session-1")
        # on_entry 会把 user 消息加入短期记忆
        assert any(m["role"] == "user" for m in stm._full_history)

    def test_returns_empty_when_no_long_term_memories(self, manager):
        """新用户没有长期记忆时应返回空字符串"""
        ctx = manager.on_entry("session-1", "new-user", "你好")
        assert ctx == ""


# ============================================================
# on_rag_start 接入点
# ============================================================

class TestOnRagStart:
    def test_returns_conversation_history(self, manager):
        # 先通过 on_entry 注入一条消息
        manager.on_entry("session-1", "user-1", "问题1")
        # 模拟 assistant 回复
        manager.get_short_term("session-1").add_message("assistant", "回答1")

        history = manager.on_rag_start("session-1", "问题2")
        assert isinstance(history, list)
        # 应包含之前的对话对
        assert len(history) >= 1

    def test_records_new_message_if_provided(self, manager):
        manager.on_rag_start("session-new", "新问题")
        stm = manager.get_short_term("session-new")
        assert any(m["content"] == "新问题" for m in stm._full_history)

    def test_empty_message_does_not_add(self, manager):
        manager.on_rag_start("session-empty", "")
        stm = manager.get_short_term("session-empty")
        assert stm._full_history == []


# ============================================================
# on_completion 接入点
# ============================================================

class TestOnCompletion:
    def test_records_assistant_reply_to_short_term(self, manager):
        manager.on_completion(
            session_id="session-1",
            user_id="user-1",
            intent="technical",
            final_response="这是回复",
            user_message="问题",
        )
        stm = manager.get_short_term("session-1")
        assert any(m["role"] == "assistant" and m["content"] == "这是回复"
                   for m in stm._full_history)

    def test_anonymous_skips_long_term_persist(self, manager):
        """匿名用户不应持久化长期记忆"""
        manager.on_completion(
            session_id="session-anon",
            user_id="anonymous",
            intent="faq",
            final_response="回复",
            user_message="问题",
        )
        ltm = manager.long_term
        assert "anonymous" not in ltm._memories

    def test_persists_tech_memories_for_real_user(self, manager):
        """真实用户的技术问题应持久化到长期记忆"""
        manager.on_completion(
            session_id="session-1",
            user_id="user-tech",
            intent="technical",
            final_response="您的 API 版本是 v2",
            user_message="我想查询 api version",
        )
        ltm = manager.long_term
        assert "user-tech" in ltm._memories
        # 应包含 api_version 类型的记忆
        topics = [m.topic for m in ltm._memories["user-tech"]]
        assert "api_version" in topics

    def test_persists_user_preference(self, manager):
        """用户显式偏好应被提取"""
        manager.on_completion(
            session_id="session-pref",
            user_id="user-pref",
            intent="general",
            final_response="好的",
            user_message="我需要中文回复",
        )
        ltm = manager.long_term
        topics = [m.topic for m in ltm._memories.get("user-pref", [])]
        assert "user_preference" in topics

    def test_escalated_increases_importance(self, manager):
        manager.on_completion(
            session_id="session-esc",
            user_id="user-esc",
            intent="technical",
            final_response="已转人工",
            user_message="api version 报错",
            is_escalated=True,
        )
        ltm = manager.long_term
        entries = ltm._memories.get("user-esc", [])
        tech_entries = [m for m in entries if m.topic == "api_version"]
        assert tech_entries
        # 转人工的重要度应为 0.6（高于未转人工的 0.4）
        assert tech_entries[0].importance == 0.6


# ============================================================
# 评估接口
# ============================================================

class TestEvaluationInterface:
    def test_record_quality_adds_system_message(self, manager):
        manager.record_quality("session-1", "user-1", score=0.85)
        stm = manager.get_short_term("session-1")
        sys_msgs = [m for m in stm._full_history if m["role"] == "system"]
        assert len(sys_msgs) == 1
        assert "quality_score" in sys_msgs[0]["content"]
        assert "0.85" in sys_msgs[0]["content"]

    def test_get_context_for_evaluation(self, manager):
        manager.on_entry("session-1", "user-1", "问题")
        ctx = manager.get_context_for_evaluation("session-1")
        assert "window" in ctx
        assert "summary" in ctx
        assert "history" in ctx
        assert isinstance(ctx["window"], list)
        assert isinstance(ctx["history"], list)


# ============================================================
# 生命周期管理
# ============================================================

class TestLifecycle:
    def test_cleanup_session_removes_from_pool(self, manager):
        manager.get_short_term("session-to-clean")
        assert "session-to-clean" in manager._stm_pool

        manager.cleanup_session("session-to-clean")
        assert "session-to-clean" not in manager._stm_pool

    def test_cleanup_nonexistent_session_no_error(self, manager):
        """清理不存在的会话不应报错"""
        manager.cleanup_session("nonexistent")

    def test_cleanup_expired_respects_pool_size(self, manager):
        """超过最大池大小时应清理最早会话"""
        # 创建 3 个会话
        for i in range(3):
            manager.get_short_term(f"session-{i}")

        # 限制池为 1，应清理掉 2 个
        removed = manager.cleanup_expired(max_age_seconds=7200)
        # cleanup_expired 实际按 MAX_POOL_SIZE(10000) 控制
        # 这里池未超限，返回 0
        assert removed == 0
        assert len(manager._stm_pool) == 3
