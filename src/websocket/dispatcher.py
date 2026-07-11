"""转接通知与分发系统

职责：
    1. AI 检测到需要转人工时，构建转接上下文并分发
    2. 通知在线的人工坐席（有可用坐席时立即推送，无人时排队）
    3. 管理转接队列
    4. 会话迁移：将后续消息从 AI 路由切换到人工坐席

架构：
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│  human_node  │────▶│  TransferDispatcher│────│  Agent WS   │
│  (触发转接)   │     │  (分发/队列)      │     │  (坐席工作台) │
└──────────────┘     └──────────────────┘     └─────────────┘
                            │
                     ┌──────┴───────┐
                     │  TransferQueue │
                     │  (排队兜底)     │
                     └────────────────┘
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.websocket.protocol import (
    build_copilot_suggestion,
    build_handoff_context,
    build_new_transfer,
    build_session_update,
    build_streaming_chunk,
    build_transfer_notice,
    TYPE_COPILOT_SUGGESTION,
    TYPE_NEW_TRANSFER,
    TYPE_SESSION_UPDATE,
    TYPE_TRANSFER_NOTICE,
)
from src.websocket.handoff import build_handoff_context as build_context
from src.websocket.session_manager import (
    SessionMode,
    WebSocketSessionManager,
    get_session_manager,
)

logger = logging.getLogger(__name__)


@dataclass
class TransferRecord:
    """转接记录"""
    transfer_id: str
    session_id: str
    user_id: str
    context: Dict[str, Any]
    urgency: str
    created_at: float = field(default_factory=lambda: time.time())
    assigned_agent: Optional[str] = None
    status: str = "pending"  # pending / assigned / active / resolved


class TransferDispatcher:
    """转接分发器 — 单例"""

    _instance: Optional["TransferDispatcher"] = None

    def __new__(cls) -> "TransferDispatcher":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._session_mgr = get_session_manager()
        self._queue: deque[TransferRecord] = deque()
        self._records: Dict[str, TransferRecord] = {}  # transfer_id → record
        self._session_transfers: Dict[str, str] = {}  # session_id → transfer_id
        self._copilot_locks: Dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # 核心入口：AI 检测到需要转人工
    # ------------------------------------------------------------------

    async def handle_escalation(
        self,
        session_id: str,
        state: Dict[str, Any],
        messages: list,
    ) -> Dict[str, Any]:
        """处理 AI 转人工请求

        流程：
            1. 构建转接上下文
            2. 更新会话状态为 WAITING_HUMAN
            3. 通知用户"正在转接"
            4. 尝试分配坐席
            5. 返回转接结果

        Returns:
            转接结果字典，包含 needs_human, transfer_notice, handoff_context
        """
        user_id = state.get("user_id", "anonymous")
        intent = state.get("intent", "unknown")
        quality_score = state.get("quality_score")

        # 1. 构建转接上下文
        context = build_context(
            state=state,
            messages=messages,
            intent=intent,
            quality_score=quality_score,
        )

        # 2. 创建转接记录
        transfer_id = f"transfer_{uuid.uuid4().hex[:8]}"
        record = TransferRecord(
            transfer_id=transfer_id,
            session_id=session_id,
            user_id=user_id,
            context=context,
            urgency=context.get("urgency", "normal"),
        )
        self._records[transfer_id] = record
        self._session_transfers[session_id] = transfer_id

        # 3. 更新会话状态
        self._session_mgr.update_mode(session_id, SessionMode.WAITING_HUMAN)

        # 4. 通知用户
        notice = build_transfer_notice(
            session_id=session_id,
            reason=context.get("reason", ""),
            estimated_wait=30 if record.urgency in ("high", "critical") else 60,
        )

        # 5. 尝试分配坐席
        agent_assigned = await self._try_assign_agent(record)

        result = {
            "needs_human": True,
            "transfer_notice": notice,
            "transfer_id": transfer_id,
            "agent_assigned": agent_assigned,
            "handoff_context": context,
        }

        logger.info(
            "Transfer initiated: %s (urgency=%s, agent=%s)",
            transfer_id, record.urgency, agent_assigned,
        )
        return result

    async def _try_assign_agent(self, record: TransferRecord) -> Optional[str]:
        """尝试分配在线坐席"""
        online_agents = self._session_mgr.list_online_agents()
        if not online_agents:
            logger.info("No online agents, queuing transfer: %s", record.transfer_id)
            self._queue.append(record)
            return None

        # 简单轮询分配
        agent_id = online_agents[0]
        self._session_mgr.assign_agent_to_session(
            record.session_id, agent_id,
        )
        record.assigned_agent = agent_id
        record.status = "assigned"

        # 通知坐席
        await self._notify_agent(agent_id, record)

        return agent_id

    async def _notify_agent(self, agent_id: str, record: TransferRecord) -> None:
        """通知坐席有新转接"""
        ws = self._session_mgr.get_agent(agent_id)
        if ws is None:
            return

        notification = build_new_transfer(
            transfer_id=record.transfer_id,
            session_id=record.session_id,
            user_id=record.user_id,
            summary=record.context.get("summary", ""),
            conversation=record.context.get("conversation", []),
            user_profile=record.context.get("user_profile", {}),
            urgency=record.urgency,
        )

        try:
            await ws.send_json(notification)
            logger.info("Transfer notification sent to agent %s", agent_id)
        except Exception as e:
            logger.warning("Failed to notify agent %s: %s", agent_id, e)
            # 通知失败，加入队列
            record.status = "pending"
            self._queue.append(record)

    # ------------------------------------------------------------------
    # 坐席回复用户
    # ------------------------------------------------------------------

    async def agent_reply(
        self,
        agent_id: str,
        session_id: str,
        reply_text: str,
    ) -> bool:
        """坐席回复用户消息 — 直接推送到用户 WebSocket"""
        state = self._session_mgr.get_session(session_id)
        if not state:
            return False

        # 直接推送到用户的 WebSocket
        ws = state._websocket_ref
        if ws is None:
            # 没有 WebSocket 引用，放入队列等待下次循环消费
            await state.message_queue.put({
                "type": "human_reply",
                "from_agent": agent_id,
                "text": reply_text,
                "timestamp": time.time(),
            })
            return False

        try:
            await ws.send_json({
                "type": "human_reply",
                "from_agent": agent_id,
                "text": reply_text,
                "timestamp": time.time(),
            })
            state.last_active = time.time()
            return True
        except Exception as e:
            logger.warning("Failed to push agent reply to WebSocket: %s", e)
            return False

    # ------------------------------------------------------------------
    # Copilot 辅助模式
    # ------------------------------------------------------------------

    async def get_copilot_suggestions(
        self,
        session_id: str,
        user_message: str,
        conversation: list,
    ) -> List[str]:
        """为坐席生成建议回复（Copilot 模式）

        基于对话历史和知识库检索，生成 2-3 条候选回复供坐席选择。
        简化版：基于关键词匹配返回预设模板。
        """
        suggestions = []

        # 简单关键词匹配 → 返回模板
        content_lower = user_message.lower()

        if any(kw in content_lower for kw in ["error", "报错", "错误", "fail"]):
            suggestions.append(
                "请问您能提供具体的错误码或完整的错误信息吗？"
                "这样我可以更准确地帮您定位问题。"
            )
            suggestions.append(
                "建议您先尝试以下步骤：1) 清除浏览器缓存 2)"
                "检查网络连接 3) 查看控制台是否有具体报错信息。"
            )

        elif any(kw in content_lower for kw in ["退款", "refund", "cancel"]):
            suggestions.append(
                "我理解您的需求。关于退款/取消订阅，"
                "我需要先核实您的账户状态和计费周期。"
                "请稍等，我为您查询相关信息。"
            )
            suggestions.append(
                "根据我们的政策，退款申请将在 3-5 个工作日内处理。"
                "请问您需要我帮您提交正式的退款申请吗？"
            )

        elif any(kw in content_lower for kw in ["配置", "setup", "configure", "安装"]):
            suggestions.append(
                "请问您配置的是哪个产品/服务？以及使用的是哪个 SDK 版本？"
                "不同的产品有不同的配置步骤。"
            )

        elif any(kw in content_lower for kw in ["登录", "login", "password", "密码"]):
            suggestions.append(
                "您可以尝试点击登录页面的'忘记密码'链接，"
                "我们会向您注册邮箱发送重置链接。"
            )
            suggestions.append(
                "如果问题仍然存在，请检查：1) 邮箱地址是否正确 2)"
                "垃圾邮件文件夹 3) 网络连接是否正常。"
            )

        if not suggestions:
            suggestions.append(
                f"您好，我注意到您的问题涉及「{user_message[:50]}」。"
                "让我为您查询相关资料，请稍等。"
            )
            suggestions.append(
                "根据您的描述，我建议先尝试排查以下几个方向："
                "1) 确认账户状态正常 2) 检查网络连接 3)"
                "查看是否有已知的问题公告。"
            )

        return suggestions[:3]

    async def push_copilot_suggestions(
        self,
        session_id: str,
        user_message: str,
        conversation: list,
    ) -> None:
        """生成并推送 Copilot 建议给坐席"""
        record_id = self._session_transfers.get(session_id)
        if not record_id:
            return

        record = self._records.get(record_id)
        if not record or not record.assigned_agent:
            return

        suggestions = await self.get_copilot_suggestions(
            session_id, user_message, conversation,
        )

        ws = self._session_mgr.get_agent(record.assigned_agent)
        if ws is None:
            return

        try:
            await ws.send_json(
                build_copilot_suggestion(
                    session_id=session_id,
                    suggestions=suggestions,
                ),
            )
        except Exception as e:
            logger.warning(
                "Failed to push copilot suggestions: %s", e,
            )

    # ------------------------------------------------------------------
    # 会话迁移
    # ------------------------------------------------------------------

    def migrate_to_human(self, session_id: str) -> bool:
        """将会话从 AI 模式迁移到人工模式"""
        state = self._session_mgr.get_session(session_id)
        if not state:
            return False

        state.mode = SessionMode.HUMAN_CHAT
        state.needs_human = True
        state.last_active = time.time()

        # 推送会话更新通知
        update = build_session_update(
            session_id=session_id,
            mode=SessionMode.HUMAN_CHAT.value,
        )

        logger.info("Session %s migrated to human mode", session_id)
        return True

    def migrate_to_ai(self, session_id: str) -> bool:
        """将会话从人工模式迁回 AI 模式"""
        state = self._session_mgr.get_session(session_id)
        if not state:
            return False

        state.mode = SessionMode.AI_CHAT
        state.needs_human = False
        state.assigned_agent = None
        state.last_active = time.time()

        logger.info("Session %s migrated back to AI mode", session_id)
        return True

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_transfer_record(self, transfer_id: str) -> Optional[TransferRecord]:
        """获取转接记录"""
        return self._records.get(transfer_id)

    def get_pending_count(self) -> int:
        """获取排队中的转接数量"""
        return len(self._queue)

    def get_session_transfer(self, session_id: str) -> Optional[str]:
        """获取会话当前的转接 ID"""
        return self._session_transfers.get(session_id)

    def get_stats(self) -> Dict[str, Any]:
        """获取转接系统统计"""
        return {
            "total_transfers": len(self._records),
            "pending_queue": len(self._queue),
            "active_transfers": sum(
                1 for r in self._records.values() if r.status == "assigned"
            ),
            "queue": [
                {
                    "transfer_id": r.transfer_id,
                    "session_id": r.session_id,
                    "urgency": r.urgency,
                    "status": r.status,
                }
                for r in self._queue
            ],
        }


# 全局单例
_dispatcher: Optional[TransferDispatcher] = None


def get_dispatcher() -> TransferDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = TransferDispatcher()
    return _dispatcher
