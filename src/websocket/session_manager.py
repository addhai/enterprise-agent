"""WebSocket 会话管理器

维护所有活跃的 WebSocket 连接，支持：
- 按 session_id 路由消息
- 按 agent_id 路由到人工坐席
- 心跳检测与自动断开
- 会话状态机（ai_chatting / waiting_human / human_chatting 等）

架构：
┌─────────────────────────────────────────────┐
│           WebSocketSessionManager            │
│                                             │
│  _sessions: session_id → SessionState       │
│  _agents:    agent_id  → WebSocket          │
│  _queues:    session_id → asyncio.Queue     │
└─────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SessionMode(Enum):
    """会话模式"""
    AI_CHAT = "ai_chat"           # AI 对话中
    AI_THINKING = "ai_thinking"   # AI 正在思考（流式输出中）
    WAITING_HUMAN = "waiting_human"  # 等待人工接入
    HUMAN_CHAT = "human_chat"     # 人工对话中
    ESCALATED = "escalated"       # 已转接完成
    CLOSED = "closed"             # 已关闭


@dataclass
class SessionState:
    """单个会话的状态"""
    session_id: str
    user_id: str
    tenant_id: str
    mode: SessionMode = SessionMode.AI_CHAT
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    turn_count: int = 0
    needs_human: bool = False
    assigned_agent: Optional[str] = None  # 人工坐席 ID
    conversation_history: list = field(default_factory=list)
    # 转接上下文（人工坐席可见）
    handoff_context: Optional[Dict[str, Any]] = None
    # 消息队列（用于异步推送）
    message_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    # 心跳超时
    heartbeat_timeout: float = 30.0
    # WebSocket 连接引用（用于坐席回复推送）
    _websocket_ref: Any = None


class WebSocketSessionManager:
    """WebSocket 会话管理器 — 单例"""

    _instance: Optional["WebSocketSessionManager"] = None

    def __new__(cls) -> "WebSocketSessionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # session_id → SessionState
        self._sessions: Dict[str, SessionState] = {}
        # agent_id → WebSocket 连接引用（通过外部注册）
        self._agents: Dict[str, Any] = {}
        # 清理任务
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动后台清理任务"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("WebSocketSessionManager started")

    async def stop(self):
        """停止并清理所有会话"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self._sessions.clear()
        self._agents.clear()
        logger.info("WebSocketSessionManager stopped")

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    def create_session(
        self,
        session_id: str,
        user_id: str,
        tenant_id: str = "",
        mode: SessionMode = SessionMode.AI_CHAT,
    ) -> SessionState:
        """创建新会话"""
        state = SessionState(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            mode=mode,
        )
        self._sessions[session_id] = state
        logger.info(
            "Session created: %s (user=%s, mode=%s)",
            session_id, user_id, mode.value,
        )
        return state

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """获取会话状态"""
        state = self._sessions.get(session_id)
        if state:
            state.last_active = time.time()
        return state

    def update_mode(self, session_id: str, mode: SessionMode) -> bool:
        """更新会话模式"""
        state = self._sessions.get(session_id)
        if not state:
            return False
        old_mode = state.mode
        state.mode = mode
        state.last_active = time.time()
        logger.info(
            "Session %s mode: %s → %s",
            session_id, old_mode.value, mode.value,
        )
        return True

    def remove_session(self, session_id: str) -> bool:
        """移除会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info("Session removed: %s", session_id)
            return True
        return False

    # ------------------------------------------------------------------
    # 人工坐席管理
    # ------------------------------------------------------------------

    def register_agent(self, agent_id: str, websocket: Any) -> None:
        """注册人工坐席 WebSocket 连接"""
        self._agents[agent_id] = websocket
        logger.info("Agent registered: %s", agent_id)

    def unregister_agent(self, agent_id: str) -> None:
        """注销人工坐席"""
        self._agents.pop(agent_id, None)
        logger.info("Agent unregistered: %s", agent_id)

    def get_agent(self, agent_id: str) -> Optional[Any]:
        """获取坐席连接"""
        return self._agents.get(agent_id)

    def list_online_agents(self) -> list:
        """列出所有在线坐席"""
        return list(self._agents.keys())

    def assign_agent_to_session(
        self, session_id: str, agent_id: str
    ) -> bool:
        """将会话分配给人工坐席"""
        state = self._sessions.get(session_id)
        if not state or agent_id not in self._agents:
            return False
        state.assigned_agent = agent_id
        state.mode = SessionMode.HUMAN_CHAT
        state.last_active = time.time()
        logger.info(
            "Session %s assigned to agent %s", session_id, agent_id,
        )
        return True

    # ------------------------------------------------------------------
    # 消息推送
    # ------------------------------------------------------------------

    async def push_to_session(
        self, session_id: str, data: Dict[str, Any]
    ) -> bool:
        """向会话推送消息（通过 WebSocket）"""
        state = self._sessions.get(session_id)
        if not state:
            return False
        await state.message_queue.put(data)
        return True

    async def push_to_agent(
        self, agent_id: str, data: Dict[str, Any]
    ) -> bool:
        """向人工坐席推送消息"""
        ws = self._agents.get(agent_id)
        if ws is None:
            return False
        try:
            await ws.send_json(data)
            return True
        except Exception as e:
            logger.warning("Push to agent %s failed: %s", agent_id, e)
            return False

    # ------------------------------------------------------------------
    # 心跳与清理
    # ------------------------------------------------------------------

    async def _cleanup_loop(self):
        """定期清理过期会话"""
        while True:
            await asyncio.sleep(60)  # 每分钟检查一次
            now = time.time()
            expired = []
            for sid, state in self._sessions.items():
                if now - state.last_active > state.heartbeat_timeout * 3:
                    expired.append(sid)
            for sid in expired:
                self.remove_session(sid)
                logger.info("Expired session cleaned up: %s", sid)

    def get_stats(self) -> Dict[str, Any]:
        """获取管理器统计信息"""
        mode_counts = {}
        for state in self._sessions.values():
            mode_counts[state.mode.value] = mode_counts.get(state.mode.value, 0) + 1
        return {
            "total_sessions": len(self._sessions),
            "sessions_by_mode": mode_counts,
            "online_agents": len(self._agents),
            "agent_ids": list(self._agents.keys()),
        }


# 全局单例
_session_manager: Optional[WebSocketSessionManager] = None


def get_session_manager() -> WebSocketSessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = WebSocketSessionManager()
    return _session_manager
