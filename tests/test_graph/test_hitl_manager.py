"""HITLManager 单元测试

覆盖：
- add_pending / list_pending / get_task
- assign（认领 + 防止重复认领）
- complete（完成任务）
- cleanup_expired（清理超时任务）
- Redis 不可用时降级为纯内存
- get_hitl_manager 单例
"""
import time

import pytest

from src.graph.hitl_manager import HITLManager, get_hitl_manager


@pytest.fixture
def manager():
    """每个测试用新的 HITLManager 实例（Redis 已在 conftest 中禁用）"""
    return HITLManager()


# ============================================================
# add_pending / list_pending / get_task
# ============================================================

class TestAddAndList:
    @pytest.mark.asyncio
    async def test_add_pending_creates_task(self, manager):
        await manager.add_pending(
            thread_id="thread-1",
            interrupt_value={"type": "human_review", "data": "xxx"},
            session_id="session-1",
            user_id="user-1",
        )
        task = await manager.get_task("thread-1")
        assert task is not None
        assert task["thread_id"] == "thread-1"
        assert task["session_id"] == "session-1"
        assert task["user_id"] == "user-1"
        assert task["status"] == "pending"
        assert task["assigned_to"] is None
        assert task["interrupt_value"]["type"] == "human_review"
        assert "created_at" in task

    @pytest.mark.asyncio
    async def test_add_pending_uses_thread_id_as_session_default(self, manager):
        await manager.add_pending(
            thread_id="thread-2",
            interrupt_value={"type": "review"},
        )
        task = await manager.get_task("thread-2")
        assert task["session_id"] == "thread-2"

    @pytest.mark.asyncio
    async def test_list_pending_returns_all(self, manager):
        await manager.add_pending("t1", {"type": "a"})
        await manager.add_pending("t2", {"type": "b"})
        await manager.add_pending("t3", {"type": "c"})
        tasks = await manager.list_pending()
        assert len(tasks) == 3
        thread_ids = {t["thread_id"] for t in tasks}
        assert thread_ids == {"t1", "t2", "t3"}

    @pytest.mark.asyncio
    async def test_list_pending_empty_returns_empty_list(self, manager):
        tasks = await manager.list_pending()
        assert tasks == []

    @pytest.mark.asyncio
    async def test_get_task_nonexistent_returns_none(self, manager):
        task = await manager.get_task("nonexistent")
        assert task is None

    @pytest.mark.asyncio
    async def test_add_pending_overwrites_same_thread(self, manager):
        """同 thread_id 重复添加应覆盖"""
        await manager.add_pending("t1", {"type": "first"})
        await manager.add_pending("t1", {"type": "second"})
        task = await manager.get_task("t1")
        assert task["interrupt_value"]["type"] == "second"
        tasks = await manager.list_pending()
        assert len(tasks) == 1


# ============================================================
# assign
# ============================================================

class TestAssign:
    @pytest.mark.asyncio
    async def test_assign_succeeds_for_pending_task(self, manager):
        await manager.add_pending("t1", {"type": "review"})
        result = await manager.assign("t1", "agent-1")
        assert result is True
        task = await manager.get_task("t1")
        assert task["assigned_to"] == "agent-1"
        assert task["status"] == "assigned"

    @pytest.mark.asyncio
    async def test_assign_fails_for_nonexistent_task(self, manager):
        result = await manager.assign("nonexistent", "agent-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_assign_fails_if_already_assigned_to_other(self, manager):
        await manager.add_pending("t1", {"type": "review"})
        ok1 = await manager.assign("t1", "agent-1")
        ok2 = await manager.assign("t1", "agent-2")
        assert ok1 is True
        assert ok2 is False
        task = await manager.get_task("t1")
        assert task["assigned_to"] == "agent-1"

    @pytest.mark.asyncio
    async def test_assign_same_agent_reassigns(self, manager):
        """同一 agent 重复认领应成功（幂等）"""
        await manager.add_pending("t1", {"type": "review"})
        ok1 = await manager.assign("t1", "agent-1")
        ok2 = await manager.assign("t1", "agent-1")
        assert ok1 is True
        assert ok2 is True


# ============================================================
# complete
# ============================================================

class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_removes_task(self, manager):
        await manager.add_pending("t1", {"type": "review"})
        await manager.complete("t1")
        task = await manager.get_task("t1")
        assert task is None
        tasks = await manager.list_pending()
        assert len(tasks) == 0

    @pytest.mark.asyncio
    async def test_complete_nonexistent_does_not_raise(self, manager):
        """完成不存在的任务不应抛异常"""
        await manager.complete("nonexistent")

    @pytest.mark.asyncio
    async def test_complete_only_removes_specified_task(self, manager):
        await manager.add_pending("t1", {"type": "a"})
        await manager.add_pending("t2", {"type": "b"})
        await manager.complete("t1")
        tasks = await manager.list_pending()
        assert len(tasks) == 1
        assert tasks[0]["thread_id"] == "t2"


# ============================================================
# cleanup_expired
# ============================================================

class TestCleanupExpired:
    @pytest.mark.asyncio
    async def test_cleanup_removes_expired_tasks(self, manager):
        await manager.add_pending("t1", {"type": "a"})
        # 手动将 created_at 改为 1 小时前
        task = await manager.get_task("t1")
        task["created_at"] = time.time() - 3600
        await manager.add_pending("t2", {"type": "b"})  # 这个是新的

        removed = await manager.cleanup_expired(max_age_seconds=1800)
        assert removed == 1
        tasks = await manager.list_pending()
        assert len(tasks) == 1
        assert tasks[0]["thread_id"] == "t2"

    @pytest.mark.asyncio
    async def test_cleanup_keeps_fresh_tasks(self, manager):
        await manager.add_pending("t1", {"type": "a"})
        await manager.add_pending("t2", {"type": "b"})
        removed = await manager.cleanup_expired(max_age_seconds=1800)
        assert removed == 0
        tasks = await manager.list_pending()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_cleanup_empty_returns_zero(self, manager):
        removed = await manager.cleanup_expired(max_age_seconds=1800)
        assert removed == 0

    @pytest.mark.asyncio
    async def test_cleanup_default_max_age(self, manager):
        """默认 30 分钟超时"""
        await manager.add_pending("t1", {"type": "a"})
        task = await manager.get_task("t1")
        task["created_at"] = time.time() - 2000  # 超过 30 分钟
        removed = await manager.cleanup_expired()
        assert removed == 1


# ============================================================
# 单例
# ============================================================

class TestSingleton:
    def test_get_hitl_manager_returns_same_instance(self):
        m1 = get_hitl_manager()
        m2 = get_hitl_manager()
        assert m1 is m2

    def test_get_hitl_manager_returns_hitl_manager_instance(self):
        m = get_hitl_manager()
        assert isinstance(m, HITLManager)


# ============================================================
# Redis 降级（conftest 已禁用 Redis）
# ============================================================

class TestRedisFallback:
    @pytest.mark.asyncio
    async def test_works_without_redis(self, manager):
        """Redis 不可用时应正常工作（纯内存）"""
        await manager.add_pending("t1", {"type": "review"})
        task = await manager.get_task("t1")
        assert task is not None
        assert task["thread_id"] == "t1"

    @pytest.mark.asyncio
    async def test_assign_works_without_redis(self, manager):
        await manager.add_pending("t1", {"type": "review"})
        result = await manager.assign("t1", "agent-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_complete_works_without_redis(self, manager):
        await manager.add_pending("t1", {"type": "review"})
        await manager.complete("t1")
        assert await manager.get_task("t1") is None
