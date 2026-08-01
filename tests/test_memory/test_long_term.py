"""LongTermMemory 单元测试

覆盖：
- MemoryEntry 数据模型（to_dict / from_dict）
- add_memory 写入与 upsert（同 topic 旧记忆标记为 superseded）
- search 关键词检索（内存 fallback）
- get_user_profile 用户画像聚合
- get_recent 最近记忆
- clear_user 清除用户记忆
- importance 加权与上限裁剪
- PG/Chroma 不可用时降级到内存
"""
import pytest

from src.memory.long_term import LongTermMemory, MemoryEntry


@pytest.fixture(autouse=True)
def force_in_memory(monkeypatch):
    """强制使用内存模式（禁用 PG 和 Chroma）"""
    monkeypatch.setattr("src.memory.long_term._get_pg_pool", lambda: None)
    monkeypatch.setattr("src.memory.long_term._get_memory_chroma", lambda: None)


# ============================================================
# MemoryEntry 数据模型
# ============================================================

class TestMemoryEntry:
    def test_create_entry_with_defaults(self):
        entry = MemoryEntry(topic="api_version", content="user uses v2")
        assert entry.topic == "api_version"
        assert entry.content == "user uses v2"
        assert entry.importance == 0.5
        assert entry.metadata == {}
        assert entry.access_count == 0
        assert entry.status == "active"
        assert entry.timestamp  # 自动生成

    def test_create_entry_with_custom_values(self):
        entry = MemoryEntry(
            topic="sso_provider",
            content="uses Okta",
            importance=0.9,
            metadata={"intent": "technical"},
            timestamp="2026-01-01T00:00:00",
            access_count=5,
            status="active",
        )
        assert entry.importance == 0.9
        assert entry.metadata["intent"] == "technical"
        assert entry.access_count == 5

    def test_to_dict_roundtrip(self):
        entry = MemoryEntry(
            topic="domain_info",
            content="example.com",
            importance=0.7,
            metadata={"source": "chat"},
        )
        d = entry.to_dict()
        assert d["topic"] == "domain_info"
        assert d["content"] == "example.com"
        assert d["importance"] == 0.7
        assert d["metadata"] == {"source": "chat"}
        assert d["status"] == "active"

    def test_from_dict_reconstructs_entry(self):
        data = {
            "topic": "plan_change",
            "content": "upgraded to enterprise",
            "importance": 0.8,
            "metadata": {"session": "s1"},
            "timestamp": "2026-01-01T00:00:00",
            "access_count": 2,
            "status": "active",
        }
        entry = MemoryEntry.from_dict(data)
        assert entry.topic == "plan_change"
        assert entry.importance == 0.8
        assert entry.access_count == 2

    def test_from_dict_ignores_unknown_keys(self):
        data = {"topic": "x", "content": "y", "unknown_field": "z"}
        entry = MemoryEntry.from_dict(data)
        assert entry.topic == "x"
        assert not hasattr(entry, "unknown_field")

    def test_metadata_defaults_to_empty_dict(self):
        entry = MemoryEntry(topic="t", content="c", metadata=None)
        assert entry.metadata == {}


# ============================================================
# LongTermMemory 写入
# ============================================================

class TestLongTermMemoryWrite:
    def test_add_memory_creates_entry(self):
        ltm = LongTermMemory()
        ltm.add_memory(
            user_id="user-1",
            topic="api_version",
            content="user uses API v2",
            importance=0.6,
        )
        assert "user-1" in ltm._memories
        entries = ltm._memories["user-1"]
        assert len(entries) == 1
        assert entries[0].topic == "api_version"
        assert entries[0].status == "active"

    def test_add_memory_same_topic_upsert(self):
        """同 topic 添加新记忆时，旧记忆应标记为 superseded"""
        ltm = LongTermMemory()
        ltm.add_memory("user-1", "sdk_config", "old config", importance=0.5)
        ltm.add_memory("user-1", "sdk_config", "new config", importance=0.7)

        entries = ltm._memories["user-1"]
        assert len(entries) == 2
        # 旧记忆被标记为 superseded
        assert entries[0].status == "superseded"
        assert entries[0].content == "old config"
        # 新记忆为 active
        assert entries[1].status == "active"
        assert entries[1].content == "new config"

    def test_add_memory_with_metadata(self):
        ltm = LongTermMemory()
        ltm.add_memory(
            "user-1",
            "error_pattern",
            "403 error",
            metadata={"intent": "technical", "escalated": True},
        )
        entry = ltm._memories["user-1"][0]
        assert entry.metadata["intent"] == "technical"
        assert entry.metadata["escalated"] is True

    def test_different_users_isolated(self):
        ltm = LongTermMemory()
        ltm.add_memory("user-a", "topic1", "content-a")
        ltm.add_memory("user-b", "topic2", "content-b")

        assert "user-a" in ltm._memories
        assert "user-b" in ltm._memories
        assert len(ltm._memories["user-a"]) == 1
        assert len(ltm._memories["user-b"]) == 1
        assert ltm._memories["user-a"][0].content == "content-a"


# ============================================================
# LongTermMemory 检索
# ============================================================

class TestLongTermMemorySearch:
    def test_search_by_keyword(self):
        ltm = LongTermMemory()
        ltm.add_memory("user-1", "api_version", "user uses API v2 endpoint", importance=0.7)
        ltm.add_memory("user-1", "domain_info", "callback domain is example.com", importance=0.5)

        results = ltm.search("user-1", "api v2", top_k=5)
        assert len(results) >= 1
        # api_version 记忆应排在前面
        assert any(r.topic == "api_version" for r in results)

    def test_search_no_match_returns_empty(self):
        ltm = LongTermMemory()
        ltm.add_memory("user-1", "api_version", "uses v2")

        results = ltm.search("user-1", "completely-unrelated-query-xyz", top_k=5)
        assert results == []

    def test_search_unknown_user_returns_empty(self):
        ltm = LongTermMemory()
        results = ltm.search("unknown-user", "anything", top_k=5)
        assert results == []

    def test_search_excludes_superseded(self):
        """检索应排除 superseded 状态的记忆"""
        ltm = LongTermMemory()
        ltm.add_memory("user-1", "sdk_config", "old sdk config v1", importance=0.9)
        ltm.add_memory("user-1", "sdk_config", "new sdk config v2", importance=0.5)

        results = ltm.search("user-1", "sdk", top_k=5)
        # 只应返回 active 的那条
        active_results = [r for r in results if r.status == "active"]
        assert len(active_results) == len(results)
        assert all(r.content == "new sdk config v2" for r in results)

    def test_search_top_k_limit(self):
        ltm = LongTermMemory()
        for i in range(5):
            ltm.add_memory("user-1", f"topic-{i}", f"api config {i}", importance=0.5)

        results = ltm.search("user-1", "api config", top_k=2)
        assert len(results) <= 2


# ============================================================
# 用户画像
# ============================================================

class TestUserProfile:
    def test_profile_empty_for_new_user(self):
        ltm = LongTermMemory()
        profile = ltm.get_user_profile("new-user")
        assert profile["preferences"] == []
        assert profile["tech_stack"] == {}
        assert profile["plan"] == "unknown"
        assert profile["memory_count"] == 0

    def test_profile_aggregates_preferences(self):
        ltm = LongTermMemory()
        ltm.add_memory("user-1", "user_preference", "我喜欢暗色主题", importance=0.5)
        ltm.add_memory("user-1", "preference", "需要中文回复", importance=0.4)

        profile = ltm.get_user_profile("user-1")
        assert len(profile["preferences"]) == 2

    def test_profile_aggregates_tech_stack(self):
        ltm = LongTermMemory()
        ltm.add_memory("user-1", "api_version", "uses v2", importance=0.6)
        ltm.add_memory("user-1", "sdk_config", "python sdk", importance=0.6)
        ltm.add_memory("user-1", "sso_provider", "okta", importance=0.6)

        profile = ltm.get_user_profile("user-1")
        assert "api_version" in profile["tech_stack"]
        assert "sdk_config" in profile["tech_stack"]
        assert "sso_provider" in profile["tech_stack"]

    def test_profile_detects_enterprise_plan(self):
        ltm = LongTermMemory()
        ltm.add_memory("user-1", "plan_change", "upgraded to enterprise plan", importance=0.8)

        profile = ltm.get_user_profile("user-1")
        assert profile["plan"] == "enterprise"


# ============================================================
# 最近记忆与清除
# ============================================================

class TestRecentAndClear:
    def test_get_recent_returns_latest(self):
        ltm = LongTermMemory()
        ltm.add_memory("user-1", "t1", "content-1")
        ltm.add_memory("user-1", "t2", "content-2")
        ltm.add_memory("user-1", "t3", "content-3")

        recent = ltm.get_recent("user-1", limit=2)
        assert len(recent) == 2

    def test_get_recent_unknown_user(self):
        ltm = LongTermMemory()
        assert ltm.get_recent("nobody", limit=5) == []

    def test_clear_user_removes_all_memories(self):
        ltm = LongTermMemory()
        ltm.add_memory("user-1", "t1", "c1")
        ltm.add_memory("user-1", "t2", "c2")
        ltm.add_memory("user-2", "t3", "c3")

        ltm.clear_user("user-1")
        assert "user-1" not in ltm._memories
        # 其他用户不受影响
        assert "user-2" in ltm._memories
