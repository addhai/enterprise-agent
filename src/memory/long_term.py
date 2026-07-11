"""长期记忆管理：跨对话的向量化记忆存储 + 用户画像

存储策略：
    PG 优先（user_id 分区，支持 upsert + 时间衰减）
    向量检索优先 Chroma（语义匹配），降级为关键词 + 时间衰减
    无 PG/Chroma 时自动降级为进程内存字典

每条记忆包含：topic, content, importance(0-1), metadata, timestamp, access_count
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

class MemoryEntry:
    """单条长期记忆"""
    __slots__ = ("topic", "content", "importance", "metadata",
                 "timestamp", "access_count", "status")

    def __init__(
        self,
        topic: str,
        content: str,
        importance: float = 0.5,
        metadata: Optional[dict] = None,
        timestamp: Optional[str] = None,
        access_count: int = 0,
        status: str = "active",
    ):
        self.topic = topic
        self.content = content
        self.importance = importance
        self.metadata = metadata or {}
        self.timestamp = timestamp or datetime.now().isoformat()
        self.access_count = access_count
        self.status = status

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "content": self.content,
            "importance": self.importance,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "access_count": self.access_count,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        return cls(**{k: d.get(k) for k in [
            "topic", "content", "importance", "metadata",
            "timestamp", "access_count", "status"
        ] if k in d})


# ---------------------------------------------------------------------------
# PG 适配层
# ---------------------------------------------------------------------------

_pg_pool = None


def _get_pg_pool():
    """延迟初始化 PG 连接池，不可用时返回 None"""
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool

    try:
        import psycopg2.pool as _pgpool
        url = settings.database_url
        _pg_pool = _pgpool.ThreadedConnectionPool(
            minconn=1, maxconn=5, dsn=url,
        )
        # 确保表存在
        conn = _pg_pool.getconn()
        try:
            conn.cursor().execute("""
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    topic VARCHAR(512) NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    timestamp TIMESTAMPTZ DEFAULT NOW(),
                    access_count INT DEFAULT 0,
                    status VARCHAR(32) DEFAULT 'active'
                );
                CREATE INDEX IF NOT EXISTS idx_ltm_user
                    ON long_term_memory(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_ltm_user_topic
                    ON long_term_memory(user_id, topic);
                CREATE INDEX IF NOT EXISTS idx_ltm_timestamp
                    ON long_term_memory(user_id, timestamp DESC);
            """)
            conn.commit()
        finally:
            _pg_pool.putconn(conn)

        logger.info("LongTermMemory: PG connected (%s)", url)
        return _pg_pool
    except Exception:
        logger.info("LongTermMemory: PG unavailable, using in-memory fallback")
        return None


# ---------------------------------------------------------------------------
# Chroma 向量检索适配层
# ---------------------------------------------------------------------------

_chroma_memory_store = None


def _get_memory_chroma():
    """获取长期记忆专用的 Chroma 集合（与知识库 Chroma 隔离）"""
    global _chroma_memory_store
    if _chroma_memory_store is not None:
        return _chroma_memory_store

    try:
        from langchain_chroma import Chroma
        from src.rag.embedder import Embedder

        _chroma_memory_store = Chroma(
            collection_name="long_term_memory",
            embedding_function=Embedder(),
            persist_directory=settings.chroma_persist_dir,
        )
        logger.info("LongTermMemory: Chroma vector store ready")
        return _chroma_memory_store
    except Exception as e:
        logger.info("LongTermMemory: Chroma unavailable (%s), using keyword fallback", e)
        return None


def _make_memory_text(entry: MemoryEntry) -> str:
    """将记忆条目转为 Chroma 可索引的文本块"""
    parts = [f"Topic: {entry.topic}", f"Content: {entry.content}"]
    if entry.metadata:
        parts.append(f"Metadata: {json.dumps(entry.metadata, ensure_ascii=False)}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# LongTermMemory
# ---------------------------------------------------------------------------

class LongTermMemory:
    """管理跨对话的长期记忆 + 用户画像

    核心能力：
    - 按 user_id 隔离
    - 同 topic upsert（新版本 supersede 旧版本）
    - 向量语义检索（Chroma）→ 关键词 fallback（TF + 时间衰减）
    - 重要性 + 访问频次加权召回
    - 用户画像自动聚合
    """

    def __init__(self):
        self._memories: dict[str, List[MemoryEntry]] = {}  # 内存 fallback

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def add_memory(
        self,
        user_id: str,
        topic: str,
        content: str,
        importance: float = 0.5,
        metadata: Optional[dict] = None,
    ) -> None:
        """添加一条长期记忆（同 topic upsert）

        importance 建议：
            0.1 — 用户随口提了一句偏好
            0.5 — 用户明确表述的需求/配置
            0.9 — 用户多次强调的关键信息（如企业定制方案）
        """
        entry = MemoryEntry(
            topic=topic,
            content=content,
            importance=importance,
            metadata=metadata,
        )

        # PG 写入
        pool = _get_pg_pool()
        if pool:
            try:
                conn = pool.getconn()
                try:
                    cur = conn.cursor()
                    # 将同 topic 的旧记忆标记为 superseded
                    cur.execute(
                        "UPDATE long_term_memory SET status='superseded' "
                        "WHERE user_id=%s AND topic=%s AND status='active'",
                        (user_id, topic),
                    )
                    # 插入新记忆
                    cur.execute(
                        "INSERT INTO long_term_memory "
                        "(user_id, topic, content, importance, metadata, timestamp) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (user_id, topic, content, importance,
                         json.dumps(metadata or {}, ensure_ascii=False),
                         entry.timestamp),
                    )
                    conn.commit()
                finally:
                    pool.putconn(conn)
            except Exception as e:
                logger.warning("LongTermMemory PG write failed: %s", e)

        # Chroma 写入
        chroma = _get_memory_chroma()
        if chroma:
            try:
                from langchain_core.documents import Document
                doc = Document(
                    page_content=_make_memory_text(entry),
                    metadata={"user_id": user_id, "topic": topic,
                              "importance": importance, "timestamp": entry.timestamp},
                )
                chroma.add_documents([doc])
            except Exception as e:
                logger.warning("LongTermMemory Chroma write failed: %s", e)

        # 写入内存 fallback
        if user_id not in self._memories:
            self._memories[user_id] = []
        for old in self._memories[user_id]:
            if old.topic == topic and old.status == "active":
                old.status = "superseded"
        self._memories[user_id].append(entry)

        # 每个用户控制上限
        active = [m for m in self._memories[user_id] if m.status == "active"]
        if len(active) > settings.long_term_max_per_user:
            active.sort(key=lambda m: (m.importance, len(m.content)), reverse=True)
            for m in active[settings.long_term_max_per_user:]:
                m.status = "pruned"

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
    ) -> List[MemoryEntry]:
        """检索最相关的长期记忆

        策略：Chroma 向量检索 → 关键词 + 时间衰减 fallback
        """
        # 优先 Chroma 语义检索
        chroma = _get_memory_chroma()
        if chroma:
            try:
                from langchain_chroma import Chroma
                results = chroma.similarity_search_with_relevance_scores(
                    query, k=top_k,
                    filter={"user_id": user_id},
                )
                entries: List[MemoryEntry] = []
                for doc, score in results:
                    entry = MemoryEntry(
                        topic=doc.metadata.get("topic", ""),
                        content=doc.page_content,
                        importance=doc.metadata.get("importance", 0.5),
                        metadata=doc.metadata,
                    )
                    entries.append(entry)
                if entries:
                    return self._rerank(entries, query)[:top_k]
            except Exception as e:
                logger.debug("Chroma search failed, falling back: %s", e)

        # Fallback: 关键词 + 时间衰减
        return self._keyword_search(user_id, query, top_k)

    def _keyword_search(
        self, user_id: str, query: str, top_k: int
    ) -> List[MemoryEntry]:
        """关键词 + 重要性 + 时间衰减 排序"""
        pool = _get_pg_pool()
        if pool:
            return self._pg_search(user_id, query, top_k)

        # 纯内存搜索
        if user_id not in self._memories:
            return []

        active = [m for m in self._memories[user_id] if m.status == "active"]
        scored = self._score_entries(active, query)
        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:top_k]]

    def _pg_search(self, user_id: str, query: str, top_k: int) -> List[MemoryEntry]:
        """PG ILIKE 搜索 + 重要性排序"""
        pool = _get_pg_pool()
        if not pool:
            return []

        try:
            conn = pool.getconn()
            try:
                words = [w.strip() for w in query.split() if len(w.strip()) > 1]
                if not words:
                    words = [query.strip()]

                # 构建 ILIKE 条件
                conditions = " OR ".join(
                    ["(topic ILIKE %s OR content ILIKE %s)"] * len(words)
                )
                params = []
                for w in words:
                    params.extend([f"%{w}%", f"%{w}%"])

                cur = conn.cursor()
                cur.execute(
                    f"SELECT topic, content, importance, metadata, timestamp, access_count "
                    f"FROM long_term_memory "
                    f"WHERE user_id=%s AND status='active' AND ({conditions}) "
                    f"ORDER BY importance DESC, timestamp DESC "
                    f"LIMIT %s",
                    (user_id, *params, top_k * 2),
                )
                rows = cur.fetchall()

                entries = [MemoryEntry(
                    topic=r[0], content=r[1], importance=r[2],
                    metadata=r[3], timestamp=str(r[4]), access_count=r[5],
                ) for r in rows]

                # 更新访问计数
                if entries:
                    topics = [e.topic for e in entries]
                    cur.execute(
                        "UPDATE long_term_memory SET access_count = access_count + 1 "
                        "WHERE user_id=%s AND topic = ANY(%s)",
                        (user_id, topics),
                    )
                    conn.commit()

                return entries
            finally:
                pool.putconn(conn)
        except Exception as e:
            logger.warning("PG search failed: %s", e)
            return []

    def _score_entries(
        self, entries: List[MemoryEntry], query: str
    ) -> List[tuple]:
        """对记忆条目打分（关键词 + 时间衰减 + 重要性）"""
        query_lower = query.lower()
        scored: List[tuple] = []
        for entry in entries:
            score = 0.0
            combined = (entry.topic + " " + entry.content + " " +
                        json.dumps(entry.metadata, ensure_ascii=False)).lower()

            # TF-like: 查询词在combined中出现
            for word in query_lower.split():
                count = combined.count(word)
                if count > 0:
                    score += 1.0 + min(count - 1, 3) * 0.3  # 平滑 term frequency

            # 重要性加权
            score *= (0.5 + entry.importance)

            # 时间衰减 (90 天半衰)
            try:
                mem_date = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00").split("+")[0])
                days_ago = max(0, (datetime.now() - mem_date.replace(tzinfo=None)).total_seconds() / 86400)
                decay = 0.5 ** (days_ago / 90)
                score *= max(0.1, decay)
            except Exception:
                pass

            if score > 0:
                scored.append((entry, score))

        return scored

    def _rerank(
        self, entries: List[MemoryEntry], query: str
    ) -> List[MemoryEntry]:
        """对检索结果二次排序（重要性 + 时间衰减）"""
        scored = self._score_entries(entries, query)
        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored]

    # ------------------------------------------------------------------
    # 用户画像
    # ------------------------------------------------------------------

    def get_user_profile(self, user_id: str) -> dict:
        """聚合用户长期记忆生成用户画像

        Returns:
            {
                "preferences": [...],
                "tech_stack": {...},
                "recent_issues": [...],
                "plan": "...",
                "memory_count": N,
            }
        """
        recent = self.get_recent(user_id, limit=50)

        # 按 topic 分类
        preferences: List[str] = []
        tech_info: dict = {}
        issues: List[str] = []

        for entry in recent:
            if "preference" in entry.topic.lower() or "prefer" in entry.topic.lower():
                preferences.append(entry.content[:200])
            elif any(kw in entry.topic.lower() for kw in
                     ["api", "sdk", "version", "config", "sso", "domain"]):
                tech_info[entry.topic] = entry.content[:200]
            elif any(kw in entry.topic.lower() for kw in
                     ["error", "issue", "bug", "problem", "stuck", "fail"]):
                issues.append(entry.content[:200])

        # 推断 plan
        plan = "unknown"
        for entry in recent:
            combined = (entry.topic + " " + entry.content).lower()
            if "enterprise" in combined or "enterprise" in (entry.metadata or {}).get("plan", ""):
                plan = "enterprise"
                break
            elif "pro" in combined and "plan" in combined:
                plan = "pro"
                break
            elif "free" in combined and "plan" in combined:
                plan = "free"
                break

        return {
            "preferences": preferences[:5],
            "tech_stack": tech_info,
            "recent_issues": issues[:5],
            "plan": plan,
            "memory_count": len([m for m in recent if m.status == "active"]),
        }

    def get_recent(self, user_id: str, limit: int = 5) -> List[MemoryEntry]:
        """获取用户最近的记忆（先尝试 PG，再内存）"""
        pool = _get_pg_pool()
        if pool:
            try:
                conn = pool.getconn()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT topic, content, importance, metadata, timestamp, "
                        "access_count, status "
                        "FROM long_term_memory "
                        "WHERE user_id=%s AND status='active' "
                        "ORDER BY timestamp DESC LIMIT %s",
                        (user_id, limit),
                    )
                    rows = cur.fetchall()
                    return [MemoryEntry(
                        topic=r[0], content=r[1], importance=r[2],
                        metadata=r[3], timestamp=str(r[4]), access_count=r[5],
                        status=r[6],
                    ) for r in rows]
                finally:
                    pool.putconn(conn)
            except Exception as e:
                logger.warning("PG get_recent failed: %s", e)

        # 内存 fallback
        if user_id not in self._memories:
            return []
        active = [m for m in self._memories[user_id] if m.status == "active"]
        active.sort(key=lambda m: m.timestamp, reverse=True)
        return active[:limit]

    def clear_user(self, user_id: str) -> None:
        """删除某用户全部长期记忆"""
        pool = _get_pg_pool()
        if pool:
            try:
                conn = pool.getconn()
                try:
                    conn.cursor().execute(
                        "DELETE FROM long_term_memory WHERE user_id=%s",
                        (user_id,),
                    )
                    conn.commit()
                finally:
                    pool.putconn(conn)
            except Exception as e:
                logger.warning("PG clear_user failed: %s", e)

        self._memories.pop(user_id, None)
