"""A2A Agent Card + HTTP Client 缓存

解决的问题：
    delegate_to_expert() 每次委托都会做两件事——
      1) 通过 A2ACardResolver.get_agent_card() 拉取远端 Agent Card
         （一次 HTTP 往返 + 反序列化）
      2) 新建一个 httpx.AsyncClient（连接池从头建）
    Agent Card 属于「服务发现元数据」，极少变化，却在每个 RAG 工具循环里被反复拉取，
    造成冗余的 HTTP 流量与对象分配，拖慢 Agent 间通信。

方案：
    进程级 TTL 缓存，按 agent URL 缓存 (card, client)：
      - card 命中且未过期 → 直接复用，跳过 HTTP 拉取
      - client 命中且未过期 → 复用同一个连接池（httpx.AsyncClient 支持并发复用）
      - 未命中 → 新建持久化 client + 拉 card，写入缓存

设计要点：
    - 缓存的 client 为「长生命周期」对象，正常运行期间不关闭（仅在进程退出时可选 close）
    - 带 asyncio.Lock，避免并发请求同时穿透去拉同一张 card（缓存击穿）
    - TTL 默认 60s，可通过 src.config.settings.a2a_card_cache_ttl 覆盖
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class AgentCardCache:
    """进程级、TTL 驱动的 A2A Agent Card + HTTP 客户端缓存。

    条目结构：(card, client, expires_at)，expires_at 为 monotonic 时间戳。
    """

    def __init__(self, default_ttl: float = 60.0):
        self._default_ttl = default_ttl
        # url -> (card, client, expires_at)
        self._store: dict[str, tuple[object, object, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, url: str) -> tuple[object | None, object | None]:
        """命中且未过期返回 (card, client)，否则返回 (None, None)。"""
        async with self._lock:
            entry = self._store.get(url)
            if entry is None:
                return (None, None)
            card, client, expires_at = entry
            if expires_at <= time.monotonic():
                # 过期即剔除，由调用方重新拉取
                del self._store[url]
                return (None, None)
            return (card, client)

    async def set(
        self,
        url: str,
        card,
        client,
        ttl: float | None = None,
    ) -> None:
        """写入缓存，ttl 为秒；为空则用默认 TTL。"""
        async with self._lock:
            self._store[url] = (
                card,
                client,
                time.monotonic() + (ttl if ttl is not None else self._default_ttl),
            )

    async def expire(self, url: str) -> None:
        """主动使某个 URL 的缓存失效（如 agent 掉线后强制下次重发现）。"""
        async with self._lock:
            self._store.pop(url, None)

    async def clear(self) -> None:
        """清空全部缓存（测试或热重启时使用）。"""
        async with self._lock:
            self._store.clear()

    def size(self) -> int:
        """当前缓存条目数（测试/可观测用）。"""
        return len(self._store)


# ---------------------------------------------------------------------------
# 模块级单例：每个 worker 进程一个缓存
# ---------------------------------------------------------------------------

_default_cache: AgentCardCache | None = None


def get_agent_card_cache() -> AgentCardCache:
    """获取（懒初始化）进程级 Agent Card 缓存单例。"""
    global _default_cache
    if _default_cache is None:
        try:
            from src.config import settings

            ttl = float(getattr(settings, "a2a_card_cache_ttl", 60.0))
        except Exception:  # pragma: no cover - 配置缺失时退化为默认
            ttl = 60.0
        _default_cache = AgentCardCache(default_ttl=ttl)
    return _default_cache


async def reset_agent_card_cache() -> None:
    """测试辅助：清空并重置单例（避免用例间状态串扰）。"""
    global _default_cache
    if _default_cache is not None:
        await _default_cache.clear()
    _default_cache = None
