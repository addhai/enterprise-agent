"""ShortTermMemory 单元测试

覆盖：
- 消息添加与滑动窗口
- 窗口超限触发摘要（关键词降级）
- 对话历史配对提取（context_rounds 截断）
- get_context_for_llm 上下文构建
- clear 清空
- Redis 不可用时降级到内存
"""
import pytest

from src.memory.short_term import ShortTermMemory


@pytest.fixture(autouse=True)
def force_in_memory(monkeypatch):
    """强制使用内存模式（禁用 Redis，避免测试依赖外部服务）"""
    monkeypatch.setattr("src.memory.short_term._get_redis", lambda: None)


# ============================================================
# 基础消息管理
# ============================================================

class TestShortTermMemoryBasic:
    def test_add_message_appends_to_history(self):
        stm = ShortTermMemory(session_id="test-basic")
        stm.add_message("user", "你好")
        stm.add_message("assistant", "您好，有什么可以帮您？")

        assert len(stm._full_history) == 2
        assert stm._full_history[0]["role"] == "user"
        assert stm._full_history[0]["content"] == "你好"
        assert stm._full_history[1]["role"] == "assistant"

    def test_default_session_id(self):
        stm = ShortTermMemory()
        assert stm.session_id == "default"

    def test_custom_session_id(self):
        stm = ShortTermMemory(session_id="sess-123")
        assert stm.session_id == "sess-123"

    def test_max_window_size_from_settings(self):
        """未指定 max_window_size 时应使用 settings.short_term_max_window"""
        from src.config import settings
        stm = ShortTermMemory(session_id="test-settings")
        assert stm.max_window_size == settings.short_term_max_window

    def test_custom_max_window_size(self):
        stm = ShortTermMemory(session_id="test-custom", max_window_size=5)
        assert stm.max_window_size == 5


# ============================================================
# 滑动窗口
# ============================================================

class TestSlidingWindow:
    def test_get_window_returns_recent_messages(self):
        stm = ShortTermMemory(session_id="test-window", max_window_size=3)
        for i in range(5):
            stm.add_message("user", f"msg-{i}")

        window = stm.get_window()
        assert len(window) == 3
        # 应保留最后 3 条
        assert window[0]["content"] == "msg-2"
        assert window[-1]["content"] == "msg-4"

    def test_window_within_limit_returns_all(self):
        stm = ShortTermMemory(session_id="test-window-small", max_window_size=10)
        stm.add_message("user", "a")
        stm.add_message("assistant", "b")

        window = stm.get_window()
        assert len(window) == 2

    def test_window_empty(self):
        stm = ShortTermMemory(session_id="test-window-empty")
        assert stm.get_window() == []


# ============================================================
# 摘要生成（超窗触发）
# ============================================================

class TestSummaryGeneration:
    def test_summary_generated_when_exceeding_window(self):
        """超窗消息包含关键词时应生成摘要"""
        stm = ShortTermMemory(session_id="test-summary", max_window_size=2)
        # 第一条消息含关键词 "password"，会被挤出窗口并触发摘要
        stm.add_message("user", "I forgot my password, need reset")
        stm.add_message("assistant", "Please use the reset link")
        stm.add_message("user", "Thanks")  # 触发超窗

        summary = stm.get_summary()
        assert isinstance(summary, str)
        # 关键词摘要应包含 password 相关信息
        assert "password" in summary.lower() or "reset" in summary.lower()

    def test_summary_empty_when_no_keywords(self):
        """超窗消息不含关键词时摘要可能为空"""
        stm = ShortTermMemory(session_id="test-no-keyword", max_window_size=2)
        stm.add_message("user", "hi")
        stm.add_message("assistant", "hello")
        stm.add_message("user", "bye")  # 触发超窗

        summary = stm.get_summary()
        assert isinstance(summary, str)

    def test_summary_empty_when_within_window(self):
        stm = ShortTermMemory(session_id="test-no-summary", max_window_size=10)
        stm.add_message("user", "hello")
        assert stm.get_summary() == ""


# ============================================================
# 对话历史配对
# ============================================================

class TestConversationHistory:
    def test_pairs_user_and_assistant(self):
        stm = ShortTermMemory(session_id="test-pairs")
        stm.add_message("user", "问题1")
        stm.add_message("assistant", "回答1")
        stm.add_message("user", "问题2")
        stm.add_message("assistant", "回答2")

        history = stm.get_conversation_history()
        assert len(history) == 2
        assert history[0] == ("问题1", "回答1")
        assert history[1] == ("问题2", "回答2")

    def test_unpaired_user_message_excluded(self):
        """没有 assistant 回复的 user 消息应被排除"""
        stm = ShortTermMemory(session_id="test-unpaired")
        stm.add_message("user", "孤立的提问")
        stm.add_message("user", "另一个提问")
        stm.add_message("assistant", "回复")

        history = stm.get_conversation_history()
        # 只有最后一个 user 与 assistant 配对
        assert len(history) == 1
        assert history[0] == ("另一个提问", "回复")

    def test_max_rounds_truncation(self):
        """max_rounds 应截断历史轮数"""
        stm = ShortTermMemory(session_id="test-rounds")
        for i in range(5):
            stm.add_message("user", f"q{i}")
            stm.add_message("assistant", f"a{i}")

        # 只取最近 2 轮
        history = stm.get_conversation_history(max_rounds=2)
        assert len(history) == 2
        assert history[0] == ("q3", "a3")
        assert history[1] == ("q4", "a4")

    def test_max_rounds_zero_means_no_limit(self):
        stm = ShortTermMemory(session_id="test-rounds-zero")
        for i in range(3):
            stm.add_message("user", f"q{i}")
            stm.add_message("assistant", f"a{i}")

        history = stm.get_conversation_history(max_rounds=0)
        assert len(history) == 3


# ============================================================
# LLM 上下文构建
# ============================================================

class TestContextForLlm:
    def test_context_without_summary(self):
        stm = ShortTermMemory(session_id="test-ctx-no-sum", max_window_size=10)
        stm.add_message("user", "你好")
        stm.add_message("assistant", "您好")

        ctx = stm.get_context_for_llm()
        assert len(ctx) == 2
        assert ctx[0]["role"] == "user"
        assert ctx[1]["role"] == "assistant"

    def test_context_includes_summary_as_system(self):
        """有摘要时应作为 system 消息前置"""
        stm = ShortTermMemory(session_id="test-ctx-sum", max_window_size=2)
        stm.add_message("user", "I need a password reset")
        stm.add_message("assistant", "ok")
        stm.add_message("user", "thanks")  # 触发摘要

        ctx = stm.get_context_for_llm()
        # 第一条应为 system 摘要
        assert ctx[0]["role"] == "system"
        assert "摘要" in ctx[0]["content"]
        # 后面跟窗口消息
        assert len(ctx) > 1


# ============================================================
# 清空操作
# ============================================================

class TestClear:
    def test_clear_empties_history(self):
        stm = ShortTermMemory(session_id="test-clear")
        stm.add_message("user", "a")
        stm.add_message("assistant", "b")

        stm.clear()
        assert stm._full_history == []
        assert stm._summary == ""
        assert stm.get_window() == []
        assert stm.get_summary() == ""
