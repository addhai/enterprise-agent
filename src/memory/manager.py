"""MemoryManager — 统一记忆生命周期管理

职责：
    - 管理 ShortTermMemory 实例池（按 session_id 路由）
    - 持有 LongTermMemory 单例
    - 提供三个 LangGraph 接入点的标准接口：
        on_entry()      → 注入长期记忆上下文
        on_rag_start()  → 记录用户消息到短期记忆，提取历史上下文
        on_completion() → 持久化到长期记忆，触发评估

架构：
    ┌──────────────────────────────┐
    │       MemoryManager          │
    │  ┌──────────┐ ┌────────────┐ │
    │  │ ShortTerm │ │ LongTerm   │ │
    │  │ (session  │ │ (user_id   │ │
    │  │  → Redis) │ │  → PG+Chr) │ │
    │  └──────────┘ └────────────┘ │
    └──────────────────────────────┘
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from src.config import settings
from src.memory.short_term import ShortTermMemory
from src.memory.long_term import LongTermMemory, MemoryEntry

logger = logging.getLogger(__name__)


class MemoryManager:
    """记忆管理器 — LangGraph 工作流的记忆中枢

    使用方式（在 graph nodes 中）：
        memory = MemoryManager()

        # entry_node
        ctx = memory.on_entry(session_id, user_id, current_message)

        # rag_node
        history = memory.on_rag_start(session_id, user_message)

        # reply_node 完成后
        memory.on_completion(session_id, user_id, intent, final_response, retrieved_docs)
    """

    def __init__(self):
        # ShortTermMemory 池：session_id → ShortTermMemory
        self._stm_pool: Dict[str, ShortTermMemory] = {}

        # LongTermMemory 单例
        self._ltm: Optional[LongTermMemory] = None

    @property
    def long_term(self) -> LongTermMemory:
        if self._ltm is None:
            self._ltm = LongTermMemory()
        return self._ltm

    def get_short_term(self, session_id: str) -> ShortTermMemory:
        """获取或创建 session 级别的短期记忆"""
        if session_id not in self._stm_pool:
            self._stm_pool[session_id] = ShortTermMemory(
                session_id=session_id,
            )
        return self._stm_pool[session_id]

    # ==================================================================
    # 接入点 1: entry_node — 注入长期记忆上下文
    # ==================================================================

    def on_entry(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
    ) -> str:
        """entry_node 调用：注入长期记忆 + 用户画像作为系统上下文

        Returns:
            注入到 System Prompt 的上下文文本（空字符串表示无历史记忆）
        """
        if not user_id or user_id == "anonymous":
            return ""

        # 1. 确保 session 短期记忆存在
        stm = self.get_short_term(session_id)
        stm.add_message("user", user_message)

        # 2. 从长期记忆中检索相关记忆
        memories = self.long_term.search(
            user_id=user_id,
            query=user_message,
            top_k=settings.memory_context_max_docs,
        )

        if not memories:
            return ""

        # 3. 构建注入上下文
        parts: List[str] = ["[长期记忆 — 历史对话信息]\n"]

        for i, mem in enumerate(memories, 1):
            parts.append(f"## {i}. {mem.topic}")
            parts.append(mem.content[:300])
            if mem.metadata:
                parts.append(f"   元数据: {json_dumps_compact(mem.metadata)}")
            parts.append("")

        # 4. 用户画像
        try:
            profile = self.long_term.get_user_profile(user_id)
            if profile.get("preferences") or profile.get("tech_stack"):
                parts.append("## 用户画像")
                if profile.get("plan", "unknown") != "unknown":
                    parts.append(f"- 订阅计划: {profile['plan']}")
                for pref in profile.get("preferences", []):
                    parts.append(f"- 偏好: {pref}")
                for key, val in profile.get("tech_stack", {}).items():
                    parts.append(f"- {key}: {val}")
                parts.append("")
        except Exception as e:
            logger.debug("User profile generation skipped: %s", e)

        context = "\n".join(parts)
        logger.debug("Memory context injected for user %s: %d chars, %d memories",
                     user_id, len(context), len(memories))
        return context

    # ==================================================================
    # 接入点 2: rag_node — 提取对话历史
    # ==================================================================

    def on_rag_start(
        self,
        session_id: str,
        user_message: str = "",
    ) -> List[tuple]:
        """rag_node 调用：返回 LLM 可用的对话历史"""
        stm = self.get_short_term(session_id)

        # 如果传入了新消息，先记录
        if user_message:
            stm.add_message("user", user_message)

        return stm.get_conversation_history()

    # ==================================================================
    # 接入点 3: reply_node 完成后 — 持久化 + 评估
    # ==================================================================

    def on_completion(
        self,
        session_id: str,
        user_id: str,
        intent: str,
        final_response: str,
        user_message: str = "",
        is_escalated: bool = False,
    ) -> None:
        """reply_node 之后调用：持久化长期记忆，记录评估数据"""
        if not user_id or user_id == "anonymous":
            return

        stm = self.get_short_term(session_id)
        stm.add_message("assistant", final_response)

        # 1. 提取值得长期记忆的对话内容
        self._persist_memories(
            user_id=user_id,
            user_message=user_message,
            final_response=final_response,
            intent=intent,
            is_escalated=is_escalated,
        )

        # 2. 更新对话摘要（利用已有的短期记忆窗口）
        summary = stm.get_summary()
        if summary:
            self.long_term.add_memory(
                user_id=user_id,
                topic="conversation_summary",
                content=summary,
                importance=0.3,
                metadata={
                    "session_id": session_id,
                    "intent": intent,
                    "timestamp": datetime.now().isoformat(),
                },
            )

    def _persist_memories(
        self,
        user_id: str,
        user_message: str,
        final_response: str,
        intent: str,
        is_escalated: bool,
    ) -> None:
        """从一轮对话中提取值得长期记忆的内容"""

        # 检测技术性事实（用户提到版本、配置、环境等）
        tech_keywords_map = {
            "api_version": ["api version", "api 版本", "v1", "v2", "v3"],
            "sdk_config": ["sdk", "client", "endpoint", "region"],
            "error_pattern": ["error", "错误", "fail", "失败", "timeout", "超时"],
            "sso_provider": ["okta", "azure ad", "google workspace", "saml", "sso"],
            "domain_info": ["domain", "域名", "callback url", "cors"],
            "plan_change": ["upgrade", "downgrade", "change plan", "升级", "降级"],
        }

        msg_lower = user_message.lower()
        for topic, keywords in tech_keywords_map.items():
            if any(kw in msg_lower for kw in keywords):
                # 提取相关的 AI 回复片段
                snippet = final_response[:300] if final_response else ""
                importance = 0.6 if is_escalated else 0.4
                self.long_term.add_memory(
                    user_id=user_id,
                    topic=topic,
                    content=f"用户问题: {user_message[:200]}\nAgent回复摘要: {snippet}",
                    importance=importance,
                    metadata={
                        "intent": intent,
                        "escalated": is_escalated,
                    },
                )

        # 提取用户显式偏好
        if any(kw in msg_lower for kw in ["prefer", "want", "need", "喜欢", "需要", "想要"]):
            self.long_term.add_memory(
                user_id=user_id,
                topic="user_preference",
                content=user_message[:300],
                importance=0.5,
                metadata={"intent": intent},
            )

    # ==================================================================
    # 评估接口
    # ==================================================================

    def record_quality(
        self,
        session_id: str,
        user_id: str,
        score: float,
        dimensions: Optional[dict] = None,
    ) -> None:
        """记录对话质量分（评估模块调用）"""
        stm = self.get_short_term(session_id)
        stm.add_message("system", json_dumps_compact({
            "type": "quality_score",
            "score": score,
            "dimensions": dimensions or {},
        }))

    def get_context_for_evaluation(self, session_id: str) -> dict:
        """获取评估所需上下文"""
        stm = self.get_short_term(session_id)
        return {
            "window": stm.get_window(),
            "summary": stm.get_summary(),
            "history": stm.get_conversation_history(),
        }

    # ==================================================================
    # 生命周期
    # ==================================================================

    def cleanup_session(self, session_id: str) -> None:
        """清理会话短期记忆（会话结束时调用）"""
        if session_id in self._stm_pool:
            self._stm_pool[session_id].clear()
            del self._stm_pool[session_id]
            logger.debug("Cleaned up session: %s", session_id)

    def cleanup_expired(self, max_age_seconds: int = 7200) -> int:
        """清理过期会话（定时任务调用）"""
        # 短期记忆的 TTL 由 Redis 管理，内存池按 size 控制
        MAX_POOL_SIZE = 10000
        if len(self._stm_pool) > MAX_POOL_SIZE:
            # 简单的 FIFO 清理
            keys = list(self._stm_pool.keys())
            for key in keys[:len(keys) - MAX_POOL_SIZE]:
                del self._stm_pool[key]
            return len(keys) - MAX_POOL_SIZE
        return 0


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def json_dumps_compact(obj: dict) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)
