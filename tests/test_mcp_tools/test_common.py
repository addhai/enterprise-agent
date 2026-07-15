"""内存存储 TTL 和容量限制测试 — 验证自动清理机制"""
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.mcp_tools.common import (
    MemoryStoreWithTTL,
    TenantIsolatedStore,
    get_memory_stats,
    MEMORY_STATS,
    _STATS_LOCK,
)


@pytest.fixture(autouse=True)
def reset_stats():
    with _STATS_LOCK:
        MEMORY_STATS.clear()
    yield
    with _STATS_LOCK:
        MEMORY_STATS.clear()


# ---------------------------------------------------------------------------
# TenantIsolatedStore 容量限制
# ---------------------------------------------------------------------------

def test_tenant_store_capacity_limit():
    """超出容量应淘汰最早的数据"""
    store = TenantIsolatedStore(max_items_per_tenant=3, name="test_capacity")
    store.save("t1", "item1", "data1")
    store.save("t1", "item2", "data2")
    store.save("t1", "item3", "data3")
    assert store.count("t1") == 3

    # 第 4 条应触发淘汰
    store.save("t1", "item4", "data4")
    assert store.count("t1") == 3

    # 最早的 item1 应被淘汰
    assert store.get("t1", "item1") is None
    assert store.get("t1", "item4") == "data4"


def test_tenant_store_multi_tenant_capacity():
    """每个租户独立计算容量"""
    store = TenantIsolatedStore(max_items_per_tenant=2, name="test_multi")
    store.save("tA", "a1", "data_a1")
    store.save("tA", "a2", "data_a2")
    store.save("tB", "b1", "data_b1")
    store.save("tB", "b2", "data_b2")

    assert store.count("tA") == 2
    assert store.count("tB") == 2

    # tA 添加第 3 条，应只淘汰 tA 的
    store.save("tA", "a3", "data_a3")
    assert store.count("tA") == 2
    assert store.count("tB") == 2
    assert store.get("tA", "a1") is None
    assert store.get("tB", "b1") == "data_b1"


# ---------------------------------------------------------------------------
# TenantIsolatedStore TTL 过期
# ---------------------------------------------------------------------------

def test_tenant_store_ttl_expiry():
    """TTL 过期后数据应被清理"""
    store = TenantIsolatedStore(max_items_per_tenant=100, ttl_hours=1, name="test_ttl")

    # 保存数据
    store.save("t1", "item1", "data1")

    # 模拟时间过去 30 分钟（未过期）
    with patch("src.mcp_tools.common.datetime") as mock_dt:
        future_time = datetime.now(timezone.utc) + timedelta(minutes=30)
        mock_dt.now.return_value = future_time
        assert store.get("t1", "item1") == "data1"

    # 模拟时间过去 2 小时（已过期）
    with patch("src.mcp_tools.common.datetime") as mock_dt:
        future_time = datetime.now(timezone.utc) + timedelta(hours=2)
        mock_dt.now.return_value = future_time
        result = store.get("t1", "item1")
        assert result is None


def test_tenant_store_no_ttl_never_expires():
    """TTL=0 表示永不过期"""
    store = TenantIsolatedStore(max_items_per_tenant=100, ttl_hours=0, name="test_no_ttl")
    store.save("t1", "item1", "data1")

    # 即使时间很久也不会过期
    with patch("src.mcp_tools.common.datetime") as mock_dt:
        future_time = datetime.now(timezone.utc) + timedelta(days=365)
        mock_dt.now.return_value = future_time
        assert store.get("t1", "item1") == "data1"


# ---------------------------------------------------------------------------
# MemoryStoreWithTTL
# ---------------------------------------------------------------------------

def test_memory_store_with_ttl_capacity():
    """MemoryStoreWithTTL 容量限制"""
    store = MemoryStoreWithTTL(max_items=2, name="test_simple_capacity")
    store.save("k1", "v1")
    store.save("k2", "v2")
    store.save("k3", "v3")

    assert store.count() == 2
    assert store.get("k1") is None  # 最早的被淘汰
    assert store.get("k3") == "v3"


def test_memory_store_with_ttl_expiry():
    """MemoryStoreWithTTL TTL 过期"""
    store = MemoryStoreWithTTL(max_items=100, ttl_hours=1, name="test_simple_ttl")
    store.save("k1", "v1")

    # 模拟时间过去 2 小时
    with patch("src.mcp_tools.common.datetime") as mock_dt:
        future_time = datetime.now(timezone.utc) + timedelta(hours=2)
        mock_dt.now.return_value = future_time
        assert store.get("k1") is None


def test_memory_store_delete():
    """删除数据"""
    store = MemoryStoreWithTTL(max_items=10, name="test_delete")
    store.save("k1", "v1")
    assert store.delete("k1") is True
    assert store.get("k1") is None
    assert store.delete("nonexistent") is False


# ---------------------------------------------------------------------------
# 内存监控
# ---------------------------------------------------------------------------

def test_get_memory_stats():
    """获取内存统计"""
    store1 = TenantIsolatedStore(max_items_per_tenant=100, name="stats_test_1")
    store1.save("t1", "a", "data")
    store1.save("t1", "b", "data")

    store2 = TenantIsolatedStore(max_items_per_tenant=100, name="stats_test_2")
    store2.save("t1", "x", "data")

    stats = get_memory_stats()
    assert stats["total_records"] >= 3
    assert stats["stores"]["stats_test_1"] == 2
    assert stats["stores"]["stats_test_2"] == 1
    assert stats["estimated_memory_mb"] > 0


def test_stats_update_on_save_and_delete():
    """统计应在 save/delete 时更新"""
    store = TenantIsolatedStore(max_items_per_tenant=100, name="stats_update_test")
    assert get_memory_stats()["stores"].get("stats_update_test", 0) == 0

    store.save("t1", "a", "data")
    assert get_memory_stats()["stores"]["stats_update_test"] == 1

    store.delete("t1", "a")
    assert get_memory_stats()["stores"]["stats_update_test"] == 0


# ---------------------------------------------------------------------------
# 并发安全
# ---------------------------------------------------------------------------

def test_concurrent_access():
    """并发读写应线程安全"""
    import threading

    store = TenantIsolatedStore(max_items_per_tenant=1000, name="concurrent_test")
    errors = []

    def writer():
        try:
            for i in range(100):
                store.save("t1", f"key_{i}", f"value_{i}")
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for i in range(100):
                store.get("t1", f"key_{i}")
                store.list("t1", 10)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(3)]
    threads += [threading.Thread(target=reader) for _ in range(2)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"并发错误: {errors}"
    assert store.count("t1") <= 1000  # 容量限制
