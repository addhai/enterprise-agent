"""MCP 工具公共基础 — 内存存储基类、工具注册辅助函数、通用响应格式化"""
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Generic, List, Optional, TypeVar

from src.agent.tools import PermissionChecker

logger = logging.getLogger(__name__)

T = TypeVar("T")

MEMORY_STATS: Dict[str, int] = {}
_STATS_LOCK = threading.RLock()


class MemoryStoreWithTTL(Generic[T]):
    """带 TTL 和容量限制的内存存储 — 线程安全，自动清理过期数据

    Args:
        max_items: 最大容量（超过后按时间淘汰最早的），默认 10000
        ttl_hours: 数据过期时间（小时），默认 0 表示永不过期
        name: 存储名称（用于监控）
    """

    def __init__(self, max_items: int = 10000, ttl_hours: int = 0, name: str = ""):
        self._items: Dict[str, T] = {}
        self._timestamps: Dict[str, datetime] = {}  # item_id -> created_at
        self._max_items = max_items
        self._ttl = timedelta(hours=ttl_hours) if ttl_hours > 0 else None
        self._name = name
        self._lock = threading.RLock()
        self._update_stats()

    def _update_stats(self):
        with _STATS_LOCK:
            MEMORY_STATS[self._name] = len(self._items)

    def _cleanup(self):
        """清理过期数据和超出容量的数据"""
        now = datetime.now(timezone.utc)
        expired_keys = []

        # TTL 过期清理
        if self._ttl:
            for item_id, created_at in self._timestamps.items():
                if now - created_at > self._ttl:
                    expired_keys.append(item_id)

        # 容量溢出清理（按时间淘汰最早的）
        overflow_count = len(self._items) - self._max_items
        if overflow_count > 0:
            oldest = sorted(
                self._timestamps.items(), key=lambda x: x[1]
            )[:overflow_count]
            expired_keys.extend([k for k, _ in oldest])

        if expired_keys:
            for item_id in expired_keys:
                del self._items[item_id]
                del self._timestamps[item_id]
            logger.info(
                "Cleanup %s: removed %d items (TTL=%s, max=%d)",
                self._name, len(expired_keys), self._ttl, self._max_items,
            )
            self._update_stats()

    def get(self, item_id: str) -> Optional[T]:
        with self._lock:
            self._cleanup()
            return self._items.get(item_id)

    def save(self, item_id: str, item: T):
        with self._lock:
            self._items[item_id] = item
            self._timestamps[item_id] = datetime.now(timezone.utc)
            self._cleanup()
            self._update_stats()
            logger.debug("Saved item: %s", item_id)

    def delete(self, item_id: str) -> bool:
        with self._lock:
            if item_id in self._items:
                del self._items[item_id]
                del self._timestamps[item_id]
                self._update_stats()
                logger.debug("Deleted item: %s", item_id)
                return True
            return False

    def list(self, limit: int = 100) -> List[T]:
        with self._lock:
            self._cleanup()
            return list(self._items.values())[:limit]

    def count(self) -> int:
        with self._lock:
            return len(self._items)


class TenantIsolatedStore(Generic[T]):
    """多租户隔离存储基类 — tenant_id 作为第一层索引，带 TTL 和容量限制"""

    def __init__(self, max_items_per_tenant: int = 10000, ttl_hours: int = 0, name: str = ""):
        self._store: Dict[str, Dict[str, T]] = {}
        self._timestamps: Dict[str, Dict[str, datetime]] = {}
        self._max_items = max_items_per_tenant
        self._ttl = timedelta(hours=ttl_hours) if ttl_hours > 0 else None
        self._name = name
        self._lock = threading.RLock()
        self._update_stats()

    def _update_stats(self):
        with _STATS_LOCK:
            total = sum(len(items) for items in self._store.values())
            MEMORY_STATS[self._name] = total

    def _cleanup_tenant(self, tenant_id: str):
        """清理单个租户的过期/溢出数据"""
        now = datetime.now(timezone.utc)
        tenant_items = self._store.get(tenant_id)
        tenant_timestamps = self._timestamps.get(tenant_id)
        if not tenant_items or not tenant_timestamps:
            return

        expired_keys = []

        if self._ttl:
            for item_id, created_at in tenant_timestamps.items():
                if now - created_at > self._ttl:
                    expired_keys.append(item_id)

        overflow_count = len(tenant_items) - self._max_items
        if overflow_count > 0:
            oldest = sorted(
                tenant_timestamps.items(), key=lambda x: x[1]
            )[:overflow_count]
            expired_keys.extend([k for k, _ in oldest])

        if expired_keys:
            for item_id in expired_keys:
                del tenant_items[item_id]
                del tenant_timestamps[item_id]
            logger.info(
                "Cleanup %s tenant=%s: removed %d items",
                self._name, tenant_id, len(expired_keys),
            )
            self._update_stats()

    def get(self, tenant_id: str, item_id: str) -> Optional[T]:
        with self._lock:
            self._cleanup_tenant(tenant_id)
            tenant_store = self._store.get(tenant_id)
            if tenant_store is None:
                return None
            return tenant_store.get(item_id)

    def save(self, tenant_id: str, item_id: str, item: T):
        with self._lock:
            if tenant_id not in self._store:
                self._store[tenant_id] = {}
            if tenant_id not in self._timestamps:
                self._timestamps[tenant_id] = {}

            self._store[tenant_id][item_id] = item
            self._timestamps[tenant_id][item_id] = datetime.now(timezone.utc)
            self._cleanup_tenant(tenant_id)
            self._update_stats()
            logger.debug("Saved item %s for tenant %s", item_id, tenant_id)

    def delete(self, tenant_id: str, item_id: str) -> bool:
        with self._lock:
            tenant_store = self._store.get(tenant_id)
            if tenant_store is None or item_id not in tenant_store:
                return False

            del tenant_store[item_id]
            del self._timestamps[tenant_id][item_id]
            self._update_stats()
            logger.debug("Deleted item %s from tenant %s", item_id, tenant_id)
            return True

    def list(self, tenant_id: str, limit: int = 100) -> List[T]:
        with self._lock:
            self._cleanup_tenant(tenant_id)
            tenant_store = self._store.get(tenant_id, {})
            return list(tenant_store.values())[:limit]

    def count(self, tenant_id: str = None) -> int:
        with self._lock:
            if tenant_id:
                return len(self._store.get(tenant_id, {}))
            return sum(len(items) for items in self._store.values())


class InMemoryStore(Generic[T]):
    """通用内存存储基类 — 线程安全，适合 MCP 单机部署"""

    def __init__(self):
        self._items: Dict[str, T] = {}
        self._lock = threading.RLock()

    def get(self, item_id: str) -> Optional[T]:
        with self._lock:
            return self._items.get(item_id)

    def save(self, item_id: str, item: T):
        with self._lock:
            self._items[item_id] = item
            logger.debug("Saved item: %s", item_id)

    def delete(self, item_id: str) -> bool:
        with self._lock:
            if item_id in self._items:
                del self._items[item_id]
                logger.debug("Deleted item: %s", item_id)
                return True
            return False

    def list(self, limit: int = 100) -> List[T]:
        with self._lock:
            return list(self._items.values())[:limit]


def get_memory_stats() -> dict:
    """获取所有存储的内存使用统计"""
    with _STATS_LOCK:
        total = sum(MEMORY_STATS.values())
        return {
            "total_records": total,
            "stores": dict(MEMORY_STATS),
            "estimated_memory_mb": total * 0.0005,
        }


def format_result(status: str, message: str, data: dict = None) -> str:
    """格式化工具返回结果 — 统一格式便于 LLM 解析"""
    from enum import Enum

    lines = [f"[{status}] {message}"]
    if data:
        for key, value in data.items():
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, Enum):
                value = value.value
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def require_role(checker: PermissionChecker, required_roles: List[str], tool_name: str) -> bool:
    """检查是否具备必需角色，不具备时记录审计日志"""
    if not any(r in checker.roles for r in required_roles):
        checker._audit(
            "ROLE_DENIED", tool_name,
            f"required roles: {required_roles}, actual roles: {checker.roles}",
        )
        return False
    return True


def require_admin(checker: PermissionChecker, tool_name: str) -> bool:
    """快捷函数：要求 admin 角色"""
    return require_role(checker, ["admin"], tool_name)


def require_admin_or_manager(checker: PermissionChecker, tool_name: str) -> bool:
    """快捷函数：要求 admin 或 *_manager 角色"""
    return require_role(checker, ["admin", "billing_manager", "user_manager"], tool_name)


def current_utc_time() -> datetime:
    """获取当前 UTC 时间（统一使用）"""
    return datetime.now(timezone.utc)


def generate_id(prefix: str = "") -> str:
    """生成短 ID，如 BIL-ABC123、USR-XYZ456"""
    from uuid import uuid4

    return f"{prefix}-{uuid4().hex[:6].upper()}" if prefix else uuid4().hex[:8].upper()
