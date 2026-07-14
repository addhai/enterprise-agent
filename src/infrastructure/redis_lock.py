"""
Redis 分布式锁 — 用于知识库索引更新、记忆去重、租户配额扣减

使用方式:
    from src.infrastructure.redis_lock import RedisLock

    lock = RedisLock("lock:index:kb_001", ttl=60)
    if lock.acquire():
        try:
            # ... 临界区操作 ...
        finally:
            lock.release()

    # 或上下文管理器:
    with RedisLock("lock:memory:session_123:round_5", ttl=30) as acquired:
        if acquired:
            # ... 执行去重操作 ...
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

import redis

from src.config import settings

logger = logging.getLogger(__name__)

# 锁 Key 前缀常量
LOCK_PREFIX = "lock:"
LOCK_INDEX = f"{LOCK_PREFIX}index:"           # 知识库索引更新锁
LOCK_MEMORY = f"{LOCK_PREFIX}memory:"          # 长期记忆去重锁
LOCK_QUOTA = f"{LOCK_PREFIX}quota:"            # 租户配额锁
LOCK_RATE = f"{LOCK_PREFIX}rate:"             # 分布式限流锁

# 默认 TTL（秒）
DEFAULT_TTL = 30


class RedisLock:
    """基于 Redis SET NX EX 的轻量级分布式锁

    特性:
        - 自动续期（renew_interval 秒刷新一次）
        - 锁持有者标识（防止误释放）
        - 上下文管理器支持
        - 非阻塞模式（acquire=False 时立即返回）
        - 重试模式（retry_times + retry_delay）

    不适用于:
        - 严格 CP 场景（Redis 是 AP）— 用 PG advisory lock
        - 长时间持锁（TTL 默认 30s）
    """

    def __init__(
        self,
        lock_key: str,
        ttl: int = DEFAULT_TTL,
        redis_url: str = "",
        auto_renew: bool = True,
        renew_interval: float = 0.7,  # TTL * 0.7 秒续期
    ):
        self.lock_key = lock_key
        self.ttl = ttl
        self.auto_renew = auto_renew
        self.renew_interval = max(renew_interval * ttl, 1.0)

        self._owner_id = f"{uuid.uuid4().hex[:12]}-{int(time.time())}"
        self._client: Optional[redis.Redis] = None
        self._redis_url = redis_url or settings.redis_url
        self._acquired = False

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            try:
                self._client = redis.Redis.from_url(
                    self._redis_url,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                    decode_responses=True,
                )
                self._client.ping()
            except Exception as e:
                logger.warning("Redis unavailable for lock '%s': %s", self.lock_key, e)
                raise
        return self._client

    # ------------------------------------------------------------------
    # 获取 / 释放
    # ------------------------------------------------------------------

    def acquire(
        self,
        blocking: bool = False,
        retry_times: int = 3,
        retry_delay: float = 0.1,
    ) -> bool:
        """获取分布式锁

        Args:
            blocking: True=阻塞等待直到获取锁, False=未获取立即返回
            retry_times: 最大重试次数
            retry_delay: 重试间隔 (秒)

        Returns:
            True=获取成功, False=锁被他人持有
        """
        if self._acquired:
            return True

        for attempt in range(retry_times):
            try:
                acquired = self.client.set(
                    self.lock_key,
                    self._owner_id,
                    nx=True,     # 仅当 key 不存在时设置
                    ex=self.ttl,  # 过期时间
                )
                if acquired:
                    self._acquired = True
                    logger.debug("Lock acquired: %s (owner=%s, ttl=%ds)",
                                 self.lock_key, self._owner_id, self.ttl)
                    return True

                if not blocking:
                    logger.debug("Lock not acquired (held by another): %s", self.lock_key)
                    return False

                time.sleep(retry_delay)

            except (redis.ConnectionError, redis.TimeoutError) as e:
                logger.warning("Redis error acquiring lock '%s' (attempt %d/%d): %s",
                               self.lock_key, attempt + 1, retry_times, e)
                if attempt == retry_times - 1:
                    return False
                time.sleep(retry_delay)

        logger.debug("Lock not acquired after %d attempts: %s", retry_times, self.lock_key)
        return False

    def release(self) -> bool:
        """释放分布式锁（Lua 脚本保证原子性）

        只释放自己持有的锁（通过 owner_id 校验）
        """
        if not self._acquired:
            return True

        # Lua 脚本: 原子性检查 owner + 删除
        lua_release = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """

        try:
            result = self.client.eval(lua_release, 1, self.lock_key, self._owner_id)
            self._acquired = False

            if result:
                logger.debug("Lock released: %s", self.lock_key)
                return True
            else:
                logger.warning("Lock release failed (not our lock or expired): %s", self.lock_key)
                return False
        except redis.RedisError as e:
            logger.warning("Redis error releasing lock '%s': %s", self.lock_key, e)
            self._acquired = False
            return False

    def extend(self, additional_ttl: int = None) -> bool:
        """续期（延长锁的 TTL）

        在长时间操作中定期调用，防止锁过期。
        """
        new_ttl = additional_ttl or self.ttl
        lua_extend = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        try:
            result = self.client.eval(lua_extend, 1, self.lock_key, self._owner_id, new_ttl)
            if result:
                logger.debug("Lock extended: %s (+%ds)", self.lock_key, new_ttl)
                return True
            else:
                logger.warning("Lock extend failed (not our lock): %s", self.lock_key)
                self._acquired = False
                return False
        except redis.RedisError:
            return False

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------

    def __enter__(self):
        self.acquire(blocking=True, retry_times=5, retry_delay=0.2)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False  # 不吞异常

    def __del__(self):
        if self._acquired:
            try:
                self.release()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 静态工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def is_locked(lock_key: str, redis_url: str = "") -> bool:
        """检查锁是否被持有（不阻塞）"""
        try:
            r = redis.Redis.from_url(
                redis_url or settings.redis_url,
                socket_connect_timeout=1,
                decode_responses=True,
            )
            return bool(r.exists(lock_key))
        except redis.RedisError:
            return False

    @staticmethod
    def force_release(lock_key: str, redis_url: str = "") -> bool:
        """强制释放锁（管理员操作，危险！）"""
        try:
            r = redis.Redis.from_url(
                redis_url or settings.redis_url,
                socket_connect_timeout=1,
                decode_responses=True,
            )
            return bool(r.delete(lock_key))
        except redis.RedisError:
            return False


# =========================================================================
# 预定义锁工厂
# =========================================================================

def index_update_lock(kb_id: str, ttl: int = 120) -> RedisLock:
    """知识库索引更新锁 — 防止并发写入冲突"""
    return RedisLock(f"{LOCK_INDEX}{kb_id}", ttl=ttl, auto_renew=True)


def memory_dedup_lock(session_id: str, round_num: int = 0, ttl: int = 30) -> RedisLock:
    """长期记忆去重锁 — 防止同一对话被多次持久化"""
    return RedisLock(f"{LOCK_MEMORY}{session_id}:round_{round_num}", ttl=ttl)


def quota_lock(tenant_id: str, resource: str, ttl: int = 10) -> RedisLock:
    """租户配额扣减锁 — 防止并发配额超扣"""
    return RedisLock(f"{LOCK_QUOTA}{tenant_id}:{resource}", ttl=ttl)
