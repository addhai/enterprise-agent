"""短期记忆管理：滑动窗口 + 对话摘要

存储策略：Redis 优先（按 session_id 隔离，支持 TTL 过期）
         无 Redis 时自动降级为进程内存

摘要生成：LLM 提取（保留用户意图、关键事实、已完成操作）
         无 LLM 时降级为关键词提取
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis 适配层
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
            logger.warning("Redis ping failed, falling back to in-memory")
            return None

    try:
        import redis as _redis_mod
        _redis_client = _redis_mod.from_url(settings.redis_url, decode_responses=True)
        _redis_client.ping()
        logger.info("ShortTermMemory: Redis connected (%s)", settings.redis_url)
        return _redis_client
    except Exception:
        logger.info("ShortTermMemory: Redis unavailable, using in-memory fallback")
        return None


# ---------------------------------------------------------------------------
# ShortTermMemory
# ---------------------------------------------------------------------------

class ShortTermMemory:
    """管理单次对话的短期记忆

    三层架构：
    1. 滑动窗口 — 最近 N 条消息保留原文
    2. 对话摘要 — 早期消息由 LLM 压缩为结构化摘要
    3. 关键信息提取 — 从摘要中提取用户意图/偏好/事实
    """

    def __init__(
        self,
        session_id: str = "",
        max_window_size: int | None = None,
    ):
        self.session_id = session_id or "default"
        self.max_window_size = max_window_size or settings.short_term_max_window
        self._full_history: List[dict] = []
        self._summary: str = ""

        # 尝试从 Redis 恢复
        self._load_from_redis()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def add_message(self, role: str, content: str) -> None:
        """添加一条消息到短期记忆"""
        self._full_history.append({"role": role, "content": content})

        # 超窗时触发摘要更新
        if len(self._full_history) > self.max_window_size:
            self._update_summary()

        # 持久化到 Redis
        self._save_to_redis()

    def get_window(self) -> List[dict]:
        """返回滑动窗口内的最近消息（保留原文）"""
        return self._full_history[-self.max_window_size:]

    def get_summary(self) -> str:
        """返回早期对话的摘要"""
        if not self._summary and len(self._full_history) > self.max_window_size:
            self._update_summary()
        return self._summary

    def get_context_for_llm(self) -> List[dict]:
        """构建注入 LLM 的完整上下文：摘要块 + 窗口消息

        与 LangChain Messages 格式兼容，可直接拼入 prompt
        """
        context: List[dict] = []

        summary = self.get_summary()
        if summary:
            context.append({
                "role": "system",
                "content": f"[对话前情摘要 — 用户此前提供的关键信息]\n{summary}"
            })

        context.extend(self.get_window())
        return context

    def get_conversation_history(self) -> List[tuple]:
        """返回 [(human, ai), ...] 格式的对话历史（兼容现有 Agent 接口）"""
        pairs: List[tuple] = []
        current_human = ""
        for msg in self._full_history:
            if msg["role"] == "user":
                current_human = msg["content"]
            elif msg["role"] == "assistant":
                if current_human:
                    pairs.append((current_human, msg["content"]))
                    current_human = ""
        return pairs

    def clear(self) -> None:
        """清空当前会话的短期记忆"""
        self._full_history.clear()
        self._summary = ""
        self._delete_from_redis()

    # ------------------------------------------------------------------
    # 摘要生成
    # ------------------------------------------------------------------

    def _update_summary(self) -> None:
        """将超窗的早期消息压缩为摘要"""
        early = self._full_history[:-self.max_window_size]
        if not early:
            return

        # 优先 LLM 摘要
        llm_summary = self._llm_summarize(early)
        if llm_summary:
            self._summary = llm_summary
        else:
            # 降级：关键信息提取
            self._summary = self._keyword_summarize(early)

    def _llm_summarize(self, early_messages: List[dict]) -> Optional[str]:
        """用 LLM 生成早期对话的结构化摘要"""
        try:
            from langchain_openai import ChatOpenAI
        except Exception:
            return None

        # 将早期消息转为文本
        transcript = "\n".join(
            f"{'用户' if m['role'] == 'user' else 'Agent'}: {m['content'][:300]}"
            for m in early_messages
        )

        if not transcript.strip():
            return None

        model_name = settings.memory_summary_model or settings.llm_model

        prompt = (
            "你是一个对话摘要器。请将以下对话片段压缩为一段结构化摘要，聚焦于：\n"
            "1. 用户意图：用户想解决什么问题？\n"
            "2. 关键事实：用户给出了哪些具体配置、版本号、错误信息？\n"
            "3. 已完成操作：Agent 已经尝试了哪些步骤？用户反馈如何？\n"
            "4. 偏好与约束：用户是否有时间、预算、技术偏好的限制？\n\n"
            "只输出摘要，不要添加额外说明。\n\n"
            f"【对话片段】\n{transcript}"
        )

        try:
            llm = ChatOpenAI(
                model=model_name,
                api_key=settings.openai_api_key,
                base_url=settings.openai_api_base,
                temperature=0.0,
            )
            result = llm.invoke(prompt)
            return result.content.strip()
        except Exception as e:
            logger.warning("LLM summarization failed: %s, falling back to keyword", e)
            return None

    def _keyword_summarize(self, early_messages: List[dict]) -> str:
        """关键词提取降级方案（无需 LLM）"""
        keywords = [
            "password", "reset", "2fa", "api key", "sso", "version", "sdk",
            "error", "403", "401", "429", "500", "timeout", "sync",
            "stuck", "domain", "cors", "billing", "refund", "cancel",
        ]

        key_points: List[str] = []
        for msg in early_messages:
            content = msg.get("content", "")
            matched = [kw for kw in keywords if kw in content.lower()]
            if matched:
                snippet = content[:120].replace("\n", " ")
                key_points.append(
                    f"- {msg['role']}: [{', '.join(matched)}] {snippet}"
                )

        if key_points:
            return "用户在此对话中提到了以下关键信息：\n" + "\n".join(key_points[:10])
        return ""

    # ------------------------------------------------------------------
    # Redis 持久化
    # ------------------------------------------------------------------

    def _redis_key(self) -> str:
        return f"ea:stm:{self.session_id}"

    def _save_to_redis(self) -> None:
        r = _get_redis()
        if r is None:
            return
        try:
            payload = json.dumps({
                "history": self._full_history,
                "summary": self._summary,
            })
            r.setex(self._redis_key(), settings.short_term_ttl, payload)
        except Exception as e:
            logger.debug("ShortTermMemory Redis save failed: %s", e)

    def _load_from_redis(self) -> None:
        r = _get_redis()
        if r is None:
            return
        try:
            payload = r.get(self._redis_key())
            if payload:
                data = json.loads(payload)
                self._full_history = data.get("history", [])
                self._summary = data.get("summary", "")
                logger.debug("Restored short-term memory from Redis: %d msgs",
                             len(self._full_history))
        except Exception as e:
            logger.debug("ShortTermMemory Redis load failed: %s", e)

    def _delete_from_redis(self) -> None:
        r = _get_redis()
        if r is None:
            return
        try:
            r.delete(self._redis_key())
        except Exception:
            pass
