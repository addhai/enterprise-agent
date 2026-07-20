"""仲裁器 — 多渠道消息路由到对应处理流程

职责：
    1. 接收原始消息（来自任意渠道：web / chatwoot / wechat）
    2. 通过 MessageNormalizer 标准化为统一格式
    3. 按渠道路由到注册的 handler；未注册的渠道走默认客服工作流
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from src.dispatch.normalizer import MessageNormalizer, get_message_normalizer

logger = logging.getLogger(__name__)

# handler 签名：async def handler(normalized_message: dict) -> dict
Handler = Callable[[dict], Awaitable[dict]]


class Arbitrator:
    """多渠道消息仲裁器 — 将消息路由到对应处理流程"""

    def __init__(self, normalizer: Optional[MessageNormalizer] = None):
        # 允许注入自定义 normalizer；默认使用全局单例
        self._normalizer = normalizer or get_message_normalizer()
        # channel -> handler
        self._routes: Dict[str, Handler] = {}

    def register_route(self, channel: str, handler: Handler) -> None:
        """注册渠道处理路由

        Args:
            channel: 渠道标识（如 chatwoot / wechat / web）
            handler: 异步处理函数，接收标准化消息 dict，返回响应 dict
        """
        self._routes[channel] = handler
        logger.info("已注册渠道路由: %s", channel)

    async def dispatch(self, raw_message: dict) -> dict:
        """接收原始消息，标准化后路由到对应处理器

        Returns:
            处理器返回的响应 dict，至少包含:
                - reply: 回复文本
                - source: 来源标识（渠道名 或 "default"）
        """
        try:
            normalized = self._normalizer.normalize(raw_message)
        except Exception as e:
            logger.exception("消息标准化失败: %s", e)
            return {
                "reply": "消息格式无法识别，请稍后重试。",
                "source": "error",
                "error": str(e),
            }

        channel = normalized.get("channel", "unknown")
        # 事件类消息（如 Chatwoot 非 message_created 事件）直接跳过
        if normalized.get("content_type") == "event":
            logger.debug("忽略事件类消息: channel=%s, metadata=%s",
                         channel, normalized.get("metadata"))
            return {"reply": "", "source": channel, "ignored": True}

        handler = self._routes.get(channel)
        if handler is not None:
            try:
                return await handler(normalized)
            except Exception as e:
                logger.exception("渠道 %s 处理器异常，回退默认: %s", channel, e)
                # 处理器异常时回退到默认流程

        # 默认路由到客服工作流
        return await self._default_handler(normalized)

    async def _default_handler(self, message: dict) -> dict:
        """默认处理器 — 调用客服工作流

        将标准化消息转换为 AgentState 并调用 LangGraph 工作流，
        返回 final_response 作为回复。
        """
        try:
            # 延迟导入避免循环依赖
            from src.api.dependencies import get_workflow
            from src.graph.state import AgentState
            from langchain_core.messages import HumanMessage

            workflow = get_workflow()

            content = message.get("content", "")
            sender_id = message.get("sender_id", "unknown") or "unknown"
            conversation_id = message.get("conversation_id", "") or ""
            tenant_id = message.get("tenant_id", "") or ""
            session_id = conversation_id or f"disp-{sender_id}-{uuid.uuid4().hex[:8]}"

            state = AgentState(
                messages=[HumanMessage(content=content)] if content else [],
                intent=None,
                retrieved_docs=[],
                needs_human=False,
                turn_count=0,
                final_response="",
                user_id=sender_id,
                session_id=session_id,
                tenant_id=tenant_id,
                user_access_levels=[
                    "public", "internal", "confidential", "restricted",
                ],
                user_roles=[],
                user_plan="free",
                faq_match=None,
                effective_max_turns=5,
                has_reflected=False,
                memory_context="",
                quality_score=None,
                access_filtered=0,
                needs_expert_delegation=False,
                expert_response=None,
                injection_blocked=False,
                injection_type=None,
                failed_attempts=0,
                suggest_human=False,
                # HITL 字段
                awaiting_human=False,
                human_handoff_context=None,
                human_response=None,
                human_agent_id=None,
                human_handled=False,
            )

            thread_config = {"configurable": {"thread_id": session_id}}

            # 优先使用异步接口；工作流可能为同步 Runnable，没有 ainvoke 时回退 invoke
            if hasattr(workflow, "ainvoke"):
                result = await workflow.ainvoke(state, config=thread_config)
            else:
                result = workflow.invoke(state, config=thread_config)

            # ===== HITL 检测：检查工作流是否被 interrupt() 暂停 =====
            # 当 human_node 触发 interrupt() 时，ainvoke 会返回当前状态
            # 此时 workflow.get_state(config).next 非空，表示还有节点待执行
            is_interrupted = False
            interrupt_value = None
            if hasattr(workflow, "get_state"):
                try:
                    state_snapshot = workflow.get_state(thread_config)
                    if state_snapshot and state_snapshot.next:
                        # 工作流被中断
                        is_interrupted = True
                        # 从 tasks 中提取 interrupt 信息
                        for task in (state_snapshot.tasks or []):
                            if hasattr(task, "interrupts") and task.interrupts:
                                interrupt_value = task.interrupts[0].value
                                break
                except Exception as inspect_err:
                    logger.warning("检查 HITL 中断状态失败: %s", inspect_err)

            if is_interrupted:
                # 工作流被暂停，记录到 HITL 管理器，等待人工介入
                from src.graph.hitl_manager import get_hitl_manager
                hitl = get_hitl_manager()
                await hitl.add_pending(
                    thread_id=session_id,
                    interrupt_value=interrupt_value or {},
                    session_id=session_id,
                    user_id=sender_id,
                )

                return {
                    "reply": "正在为您转接人工客服，请稍候...",
                    "source": "default",
                    "needs_human": True,
                    "awaiting_human": True,
                    "session_id": session_id,
                    "thread_id": session_id,
                    "channel": message.get("channel", "unknown"),
                    "interrupt_value": interrupt_value,
                }

            reply = result.get("final_response", "") if isinstance(result, dict) else ""
            needs_human = bool(result.get("needs_human", False)) if isinstance(result, dict) else False

            return {
                "reply": reply or "抱歉，处理您的消息时出现问题。",
                "source": "default",
                "needs_human": needs_human,
                "session_id": session_id,
                "channel": message.get("channel", "unknown"),
            }
        except Exception as e:
            logger.exception("默认处理器调用工作流失败: %s", e)
            return {
                "reply": "服务暂时不可用，请稍后重试。",
                "source": "error",
                "error": str(e),
            }


# ---- 全局单例 ----
_arbitrator: Optional[Arbitrator] = None


def get_arbitrator() -> Arbitrator:
    """获取全局 Arbitrator 实例"""
    global _arbitrator
    if _arbitrator is None:
        _arbitrator = Arbitrator()
    return _arbitrator
