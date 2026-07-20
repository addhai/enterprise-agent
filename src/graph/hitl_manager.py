"""HITL (Human-in-the-loop) 任务管理器

追踪所有因 interrupt() 暂停、等待人工介入的会话。
供 admin API 查询待处理任务列表 + 人工恢复工作流。

设计：
    - Redis 持久化（重启不丢任务） + 内存缓存（保证读取性能）
    - Redis 不可用时自动降级为纯内存
    - 线程安全（asyncio.Lock）
    - 记录 thread_id、上下文、创建时间、状态

存储结构：
    Redis Key: ea:hitl:pending  (Hash)
      Field: thread_id
      Value: JSON(task_info)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from src.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Redis 适配层（延迟初始化，连接失败自动降级为内存模式）
# ---------------------------------------------------------------------------

_redis_client: Optional[object] = None


def _get_redis():
    """延迟初始化 Redis 客户端（连接不可用时返回 None）"""
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except Exception:
            logger.warning("HITLManager: Redis ping failed, falling back to in-memory")
            return None

    try:
        import redis as _redis_mod
        # protocol=2 兼容 Redis 3.x（旧版 Windows Redis 不支持 HELLO/RESP3）
        _redis_client = _redis_mod.from_url(
            settings.redis_url, decode_responses=True, protocol=2,
        )
        _redis_client.ping()
        logger.info("HITLManager: Redis connected (%s)", settings.redis_url)
        return _redis_client
    except Exception:
        logger.info("HITLManager: Redis unavailable, using in-memory only")
        return None


# Redis key 常量
REDIS_KEY_HITL_PENDING = "ea:hitl:pending"  # Hash: field=thread_id, value=JSON(task_info)


class HITLManager:
    """管理所有等待人工介入的任务

    Redis 优先 + 内存缓存（write-through）：
    - 写入：先写内存，再写 Redis
    - 读取：直接读内存（启动时从 Redis 加载）
    - 启动：load_from_redis() 恢复之前未完成的任务
    - 降级：Redis 不可用时退化为纯内存
    """

    def __init__(self) -> None:
        # thread_id -> task_info（内存缓存）
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        # 启动时从 Redis 恢复
        self._load_from_redis()

    # ---- Redis 持久化辅助方法 ----

    def _persist_to_redis(self, thread_id: str, task: Dict[str, Any]) -> None:
        """写入单条任务到 Redis"""
        r = _get_redis()
        if r is None:
            return
        try:
            r.hset(
                REDIS_KEY_HITL_PENDING,
                thread_id,
                json.dumps(task, ensure_ascii=False, default=str),
            )
        except Exception as e:
            logger.warning("HITLManager: persist to Redis failed (%s): %s", thread_id, e)

    def _remove_from_redis(self, thread_id: str) -> None:
        """从 Redis 删除单条任务"""
        r = _get_redis()
        if r is None:
            return
        try:
            r.hdel(REDIS_KEY_HITL_PENDING, thread_id)
        except Exception as e:
            logger.warning("HITLManager: remove from Redis failed (%s): %s", thread_id, e)

    def _load_from_redis(self) -> int:
        """启动时从 Redis 加载所有未完成任务到内存

        Returns: 恢复的任务数量
        """
        r = _get_redis()
        if r is None:
            return 0
        try:
            all_data = r.hgetall(REDIS_KEY_HITL_PENDING)
            if not all_data:
                return 0
            count = 0
            for thread_id, json_str in all_data.items():
                try:
                    task = json.loads(json_str)
                    self._pending[thread_id] = task
                    count += 1
                except Exception as e:
                    logger.warning(
                        "HITLManager: failed to restore task %s from Redis: %s",
                        thread_id, e,
                    )
            if count > 0:
                logger.info("HITLManager: restored %d pending tasks from Redis", count)
            return count
        except Exception as e:
            logger.warning("HITLManager: load from Redis failed: %s", e)
            return 0

    # ---- 业务方法 ----

    async def add_pending(
        self,
        thread_id: str,
        interrupt_value: Dict[str, Any],
        session_id: str = "",
        user_id: str = "",
    ) -> None:
        """记录一个新的待处理任务"""
        async with self._lock:
            task = {
                "thread_id": thread_id,
                "session_id": session_id or thread_id,
                "user_id": user_id,
                "interrupt_value": interrupt_value,
                "created_at": time.time(),
                "status": "pending",
                "assigned_to": None,  # 哪个人工客服认领了
            }
            self._pending[thread_id] = task
            # write-through：同步写入 Redis
            self._persist_to_redis(thread_id, task)
            logger.info(
                "HITL 任务已加入: thread=%s, user=%s, type=%s",
                thread_id, user_id, interrupt_value.get("type"),
            )

    async def list_pending(self) -> List[Dict[str, Any]]:
        """列出所有待处理任务"""
        async with self._lock:
            return list(self._pending.values())

    async def get_task(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """获取单个任务"""
        async with self._lock:
            return self._pending.get(thread_id)

    async def assign(self, thread_id: str, agent_id: str) -> bool:
        """人工客服认领任务（防止多人同时处理）"""
        async with self._lock:
            task = self._pending.get(thread_id)
            if not task:
                return False
            if task.get("assigned_to") and task["assigned_to"] != agent_id:
                return False  # 已被其他人认领
            task["assigned_to"] = agent_id
            task["status"] = "assigned"
            # 同步到 Redis
            self._persist_to_redis(thread_id, task)
            return True

    async def complete(self, thread_id: str) -> None:
        """任务完成，从待处理列表移除"""
        async with self._lock:
            self._pending.pop(thread_id, None)
            # 同步从 Redis 删除
            self._remove_from_redis(thread_id)
            logger.info("HITL 任务已完成: thread=%s", thread_id)

    async def cleanup_expired(self, max_age_seconds: int = 1800) -> int:
        """清理超时任务（默认 30 分钟）"""
        now = time.time()
        expired_ids = []
        async with self._lock:
            for tid, task in self._pending.items():
                if now - task["created_at"] > max_age_seconds:
                    expired_ids.append(tid)
            for tid in expired_ids:
                self._pending.pop(tid, None)
                # 同步从 Redis 删除
                self._remove_from_redis(tid)
        if expired_ids:
            logger.warning("清理 %d 个超时 HITL 任务", len(expired_ids))
        return len(expired_ids)


# 全局单例
_hitl_manager: Optional[HITLManager] = None


def get_hitl_manager() -> HITLManager:
    """获取全局 HITLManager 单例"""
    global _hitl_manager
    if _hitl_manager is None:
        _hitl_manager = HITLManager()
    return _hitl_manager
