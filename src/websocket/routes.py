"""WebSocket 路由 — 处理实时通信

提供两个 WebSocket 端点：
    /ws/chat          — 用户客户端（AI 对话）
    /ws/agent/{agent_id} — 人工坐席工作台

消息协议：
    用户端：
        发送: chat_message, heartbeat
        接收: streaming_chunk, typing_indicator, transfer_notice, error

    坐席端：
        发送: agent_send_reply, agent_login, agent_logout
        接收: new_transfer, session_update, copilot_suggestion
"""
from __future__ import annotations

import json
import logging
import time
import uuid
import asyncio
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Path

from src.websocket.protocol import (
    build_error,
    build_handoff_context,
    build_session_update,
    build_streaming_chunk,
    build_transfer_notice,
    build_typing_indicator,
    TYPE_AGENT_CHAT_MESSAGE,
    TYPE_AGENT_SEND_REPLY,
    TYPE_CLIENT_CHAT,
    TYPE_CLIENT_HEARTBEAT,
)
from src.websocket.session_manager import (
    SessionMode,
    WebSocketSessionManager,
    get_session_manager,
)
from src.websocket.dispatcher import get_dispatcher
from src.db.engine import _decode_pg_error

# JWT 校验（无状态 HS256，与 REST 鉴权同一套 secret，支持多副本部署）
from src.api.jwt_utils import (
    decode_token as _ws_decode_token,
    JWTExpired as _WS_JWTExpired,
    JWTInvalid as _WS_JWTInvalid,
)
from src.config import settings as _ws_settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_ws_identity(websocket, session_id: str):
    """解析 WS 连接身份，返回 (user_id, tenant_id, user_plan, role, is_authed)。

    Token 来源：URL query ``?token=``（浏览器 WebSocket 无法设 Authorization 头，用 query 最稳）。
    行为：
        - 携带有效 JWT：解码得到 sub(user_id)，再查库取真实 tenant_id / role。
          租户与身份以服务端解析为准，客户端无法伪造（防越权串租户）。
        - 匿名（无有效 token）：按「连接粒度」隔离租户（``anon-<session_id>``），
          保证不同匿名会话的数据互不串台；匿名默认禁止查询云资源（resource.py 已拦截）。
    """
    token = None
    try:
        token = websocket.query_params.get("token")
    except Exception:
        token = None

    if token:
        try:
            from src.db.repositories import user_get_by_id
            payload = _ws_decode_token(token, _ws_settings.jwt_secret)
            uid = payload.get("sub")
            if uid:
                u = user_get_by_id(uid)
                if u:
                    return (
                        u.get("user_id", uid),
                        u.get("tenant_id", "default"),
                        "free",  # 用户表未存订阅计划，默认 free
                        u.get("role", "agent"),
                        True,
                    )
        except (_WS_JWTExpired, _WS_JWTInvalid, Exception):
            logger.warning("WS token 校验失败，降级为匿名隔离会话")

    # 匿名隔离：每个连接独立租户命名空间，避免跨会话数据串台
    return ("anonymous", f"anon-{session_id}", "free", "", False)


# ====================================================================
# 用户端 WebSocket
# ====================================================================

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """用户客户端 WebSocket 端点

    流程：
        1. 客户端连接 → 建立会话
        2. 客户端发送 chat_message → 触发 LangGraph DAG
        3. DAG 执行期间推送 typing_indicator + streaming_chunk
        4. 需要转人工时推送 transfer_notice
        5. 心跳保活
    """
    session_id = str(uuid.uuid4())
    # 解析 WS 身份：携带有效 JWT 则按 token 派生真实租户；否则按连接粒度隔离租户
    _auth_user_id, _auth_tenant_id, _auth_plan, _auth_role, _is_authed = _resolve_ws_identity(websocket, session_id)
    user_id = _auth_user_id
    tenant_id = _auth_tenant_id
    user_plan = _auth_plan

    # 接受连接
    await websocket.accept()
    logger.info("WebSocket connected: session=%s", session_id)

    # 创建会话
    session_mgr = get_session_manager()
    session_mgr.create_session(
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        mode=SessionMode.AI_CHAT,
    )
    # 存储 WebSocket 引用（用于坐席回复推送）
    session_mgr.get_session(session_id)._websocket_ref = websocket

    # 推送会话就绪通知
    await websocket.send_json({
        "type": "session_ready",
        "session_id": session_id,
        "message": "连接成功",
        "timestamp": time.time(),
    })

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(build_error(
                    session_id, "INVALID_JSON", "消息格式错误",
                ))
                continue

            msg_type = msg.get("type", "")

            # --- 心跳 ---
            if msg_type == TYPE_CLIENT_HEARTBEAT:
                await websocket.send_json({
                    "type": "heartbeat_ack",
                    "timestamp": time.time(),
                })
                continue

            # --- resume_session 握手（前端连接后第一条消息，用于跨连接/重启续接历史）---
            if msg_type == "resume_session":
                incoming_session = msg.get("session_id")
                incoming_plan = msg.get("user_plan", "free")

                if not incoming_session:
                    # 客户端没带 session_id → 复用本连接已建会话；告知前端
                    await websocket.send_json({
                        "type": "session_resumed",
                        "session_id": session_id,
                        "restored_count": 0,
                        "message": "未携带 session_id，沿用当前会话",
                        "timestamp": time.time(),
                    })
                    continue

                existing = session_mgr.get_session(incoming_session)
                if existing:
                    # 内存仍有该会话（同生命周期内的重连）→ 直接复用，更新连接引用；
                    # 租户/身份以服务端解析为准（防客户端伪造 tenant_id 越权串台）
                    session_id = incoming_session
                    existing._websocket_ref = websocket
                    user_id = _auth_user_id
                    tenant_id = _auth_tenant_id
                    user_plan = _auth_plan
                    restored_count = len(getattr(existing, "conversation_history", []))
                    await websocket.send_json({
                        "type": "session_resumed",
                        "session_id": session_id,
                        "restored_count": restored_count,
                        "source": "memory",
                        "message": "会话已从内存续接",
                        "timestamp": time.time(),
                    })
                else:
                    # 内存无此会话（如服务重启）→ 以该 id 重建，并从 DB 恢复历史；
                    # 租户/身份以服务端解析为准
                    session_id = incoming_session
                    user_id = _auth_user_id
                    tenant_id = _auth_tenant_id
                    user_plan = incoming_plan or _auth_plan
                    session_mgr.create_session(
                        session_id=session_id,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        mode=SessionMode.AI_CHAT,
                    )
                    new_state = session_mgr.get_session(session_id)
                    if new_state is not None:
                        new_state._websocket_ref = websocket
                        # 从 DB 恢复历史
                        restored_count = 0
                        try:
                            from src.db.repositories import message_list
                            restored = await asyncio.to_thread(message_list, session_id, 200)
                            if restored:
                                new_state.conversation_history = [
                                    {"role": r["role"], "content": r["content"]} for r in restored
                                ]
                                restored_count = len(restored)
                                logger.info(
                                    "[resume_session] 从DB恢复 %d 条历史: session=%s",
                                    restored_count, session_id,
                                )
                        except Exception as e:
                            logger.warning("[resume_session] 恢复历史失败（非致命）: %s", _decode_pg_error(e))
                        await websocket.send_json({
                            "type": "session_resumed",
                            "session_id": session_id,
                            "restored_count": restored_count,
                            "source": "database",
                            "message": "会话已重建并从历史恢复",
                            "timestamp": time.time(),
                        })
                continue

            # --- 用户主动请求转人工 ---
            if msg_type == "human_escalation":
                incoming_session = msg.get("session_id")
                reason = msg.get("reason", "user_requested")
                target_session_id = incoming_session or session_id

                current_state = session_mgr.get_session(target_session_id)
                if current_state:
                    # 幂等检查：如果已经在转接队列中或已转接，直接返回提示
                    if current_state.mode in (SessionMode.WAITING_HUMAN, SessionMode.HUMAN_CHAT, SessionMode.ESCALATED):
                        await websocket.send_json({
                            "type": "info",
                            "session_id": target_session_id,
                            "text": "您已在转接队列中，请耐心等待",
                            "timestamp": time.time(),
                        })
                        continue

                    if current_state.mode != SessionMode.HUMAN_CHAT:
                        # 更新会话状态
                        session_mgr.update_mode(target_session_id, SessionMode.WAITING_HUMAN)

                        # 构建转接通知
                        transfer_notice = build_transfer_notice(
                            session_id=target_session_id,
                            reason=f"用户主动请求转人工（{reason}）",
                        )
                        await websocket.send_json(transfer_notice)

                        # 构建转接上下文
                        messages_state = current_state.conversation_history
                        handoff_ctx = build_handoff_context(
                            session_id=target_session_id,
                            summary=f"用户主动请求转人工: {reason}",
                            conversation=[
                                {"role": m.get("role", "user"),
                                 "content": m.get("content", "")[:500]}
                                for m in messages_state
                            ],
                            user_profile={"user_id": user_id, "plan": user_plan},
                            attempted_solutions=["AI 对话"],
                        )
                        await websocket.send_json(handoff_ctx)

                        # 触发转接分发
                        dispatcher = get_dispatcher()
                        from langchain_core.messages import HumanMessage, AIMessage
                        msg_objects = []
                        for m in messages_state:
                            if m.get("role") == "user":
                                msg_objects.append(HumanMessage(content=m.get("content", "")))
                            else:
                                msg_objects.append(AIMessage(content=m.get("content", "")))
                        await dispatcher.handle_escalation(
                            target_session_id,
                            {"needs_human": True, "intent": "user_requested", "messages": msg_objects},
                            msg_objects,
                        )
                continue

            # --- 聊天消息 ---
            if msg_type == TYPE_CLIENT_CHAT:
                user_text = msg.get("message", "").strip()
                image_base64 = msg.get("image_base64", "")
                audio_base64 = msg.get("audio_base64", "")

                # 至少要有文本、图片或音频之一
                if not user_text and not image_base64 and not audio_base64:
                    continue
                # 输入长度限制（防止内存攻击）
                if len(user_text) > 2000:
                    await websocket.send_json(build_error(
                        session_id, "MESSAGE_TOO_LONG", "消息过长，最多 2000 字符",
                    ))
                    continue

                # 提取可选参数（仅 session_id / user_plan 用于续接；租户与身份由服务端按 token 解析，不接受客户端伪造）
                incoming_session = msg.get("session_id")
                incoming_plan = msg.get("user_plan", "free")

                # 优先使用客户端携带的 session_id（支持跨连接 / 重启续接历史）
                if incoming_session:
                    existing = session_mgr.get_session(incoming_session)
                    if existing:
                        # 内存中仍有该会话（同生命周期内的重连）→ 直接复用；
                        # 租户/身份以服务端解析为准（防客户端伪造 tenant_id 越权串台）
                        session_id = incoming_session
                        user_id = _auth_user_id
                        tenant_id = _auth_tenant_id
                        user_plan = _auth_plan
                    else:
                        # 内存无此会话（如服务重启）→ 以该 id 重建，稍后从 DB 恢复历史；
                        # 租户/身份以服务端解析为准
                        session_id = incoming_session
                        user_id = _auth_user_id
                        tenant_id = _auth_tenant_id
                        user_plan = incoming_plan or _auth_plan
                        session_mgr.create_session(
                            session_id=session_id,
                            user_id=user_id,
                            tenant_id=tenant_id,
                            mode=SessionMode.AI_CHAT,
                        )
                        # 保存 WebSocket 引用（关键！）
                        session_mgr.get_session(session_id)._websocket_ref = websocket
                elif session_id and session_mgr.get_session(session_id):
                    # 客户端未带 session_id，复用本连接自动创建的会话；
                    # 租户/身份以服务端解析为准
                    user_id = _auth_user_id
                    tenant_id = _auth_tenant_id
                    user_plan = _auth_plan
                else:
                    # 兜底：新建会话；租户/身份以服务端解析为准
                    session_id = str(uuid.uuid4())
                    user_id = _auth_user_id
                    tenant_id = _auth_tenant_id
                    user_plan = _auth_plan
                    session_mgr.create_session(
                        session_id=session_id,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        mode=SessionMode.AI_CHAT,
                    )
                    # 保存 WebSocket 引用（关键！）
                    session_mgr.get_session(session_id)._websocket_ref = websocket
                    # 推送新的 session_id
                    await websocket.send_json({
                        "type": "session_ready",
                        "session_id": session_id,
                        "message": "新会话已创建",
                        "timestamp": time.time(),
                    })

                # 检查会话状态
                current_state = session_mgr.get_session(session_id)
                if current_state:
                    # 等待人工转接中：用户发消息，提示请稍候
                    if current_state.mode == SessionMode.WAITING_HUMAN:
                        await websocket.send_json({
                            "type": "info",
                            "session_id": session_id,
                            "text": "🔄 正在为您转接人工客服，请稍候...",
                            "timestamp": time.time(),
                        })
                        continue
                    
                    # 人工对话模式：用户发的消息转发给坐席
                    if current_state.mode == SessionMode.HUMAN_CHAT:
                        dispatcher = get_dispatcher()
                        transfer_id = dispatcher.get_session_transfer(session_id)
                        if transfer_id:
                            record = dispatcher.get_transfer_record(transfer_id)
                            if record and record.assigned_agent:
                                await websocket.send_json({
                                    "type": "message_received",
                                    "status": "forwarded_to_agent",
                                    "session_id": session_id,
                                    "timestamp": time.time(),
                                })
                                agent_ws = session_mgr.get_agent(record.assigned_agent)
                                if agent_ws:
                                    await agent_ws.send_json({
                                        "type": TYPE_AGENT_CHAT_MESSAGE,
                                        "session_id": session_id,
                                        "user_message": user_text,
                                        "timestamp": time.time(),
                                    })
                                continue

                # 处理 AI 对话
                await _handle_ai_chat(
                    websocket, session_id, user_text, user_id,
                    tenant_id, user_plan, session_mgr,
                    image_base64=image_base64,
                    audio_base64=audio_base64,
                )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s", session_id)
        session_mgr.remove_session(session_id)
    except Exception as e:
        logger.exception("WebSocket error: session=%s", session_id)
        try:
            await websocket.send_json(build_error(
                session_id, "INTERNAL_ERROR", str(e)[:200],
            ))
        except Exception:
            pass
        session_mgr.remove_session(session_id)


def _build_citations(retrieved_docs) -> List[Dict[str, Any]]:
    """把 graph 返回的检索文档规整成前端可展示的引用卡片。

    检索结果里每个 doc 是 langchain Document（有 page_content 与 metadata），
    metadata 可能含 source / doc_id / kb_id / title 等字段。null / 异常都安全降级。
    """
    citations: List[Dict[str, Any]] = []
    for d in retrieved_docs or []:
        if not d:
            continue
        meta = getattr(d, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        source = meta.get("source") or meta.get("doc_id") or ""
        doc_id = meta.get("doc_id") or ""
        title = meta.get("title") or meta.get("source") or doc_id or "未知文档"
        kb_id = meta.get("kb_id") or ""
        content = getattr(d, "page_content", None) or ""
        if isinstance(content, str):
            content = content[:500]
        else:
            content = str(content)[:500]
        try:
            # 优先 doc.score（langchain Document 的 pydantic 字段），回退到 metadata.score / metadata.rrf_score
            score = float(
                getattr(d, "score", 0)
                or (isinstance(meta, dict) and (meta.get("score") or meta.get("rrf_score") or 0))
                or 0
            )
        except (TypeError, ValueError):
            score = 0.0
        citations.append({
            "title": title,
            "content": content,
            "score": round(score, 4),
            "source": source,
            "doc_id": doc_id,
            "kb_id": kb_id,
        })
    return citations


async def _handle_ai_chat(
    websocket: WebSocket,
    session_id: str,
    message: str,
    user_id: str,
    tenant_id: str,
    user_plan: str,
    session_mgr: WebSocketSessionManager,
    image_base64: str = "",
    audio_base64: str = "",
):
    """处理用户消息 → 触发 AI 回复 → 流式推送"""
    from src.api.routes import AgentState
    from langchain_core.messages import HumanMessage, AIMessage
    from src.api.dependencies import get_workflow

    start_time = time.time()

    # ---- Phase 3: 持久化用户输入，并确保会话行存在（重启后可恢复上下文）----
    try:
        from src.db.repositories import conversation_ensure, message_save
        await asyncio.to_thread(conversation_ensure, session_id, tenant_id, user_id, "web")
        await asyncio.to_thread(
            message_save, session_id, tenant_id, user_id, "user", message,
            metadata={"has_image": bool(image_base64), "has_audio": bool(audio_base64)},
        )
    except Exception as e:
        logger.warning("[Persistence] 用户消息落库失败（非致命）: %s", e)

    # 1. 发送"正在思考"
    await websocket.send_json(build_typing_indicator(
        session_id, is_typing=True, status="正在理解您的问题...",
    ))

    try:
        # 构建多模态消息内容（通过视觉引擎/语音引擎处理）
        from src.websocket.multimodal import process_multimodal_message
        display_text, multimodal_content = process_multimodal_message(
            message,
            image_base64=image_base64,
            audio_base64=audio_base64,
        )

        # 先展示图片/语音识别结果给用户看
        if display_text != message and (image_base64 or audio_base64):
            await websocket.send_json(build_streaming_chunk(
                session_id, text=display_text, delta=display_text,
            ))
            await websocket.send_json(build_streaming_chunk(
                session_id, text="", done=True,
            ))

        # 2. 获取工作流
        app = get_workflow()

        # 3. 构建 AgentState
        # 从会话状态中读取上一轮的失败次数和历史消息
        session_state = session_mgr.get_session(session_id)
        # Phase 3: 若内存会话无历史（如服务重启后重连），从 DB 恢复多轮上下文
        if session_state is not None and not getattr(session_state, "conversation_history", []):
            try:
                from src.db.repositories import message_list
                restored = await asyncio.to_thread(message_list, session_id, 200)
                if restored:
                    session_state.conversation_history = [
                        {"role": r["role"], "content": r["content"]} for r in restored
                    ]
                    logger.info(
                        "[ContextMemory] 从DB恢复 %d 条历史: session=%s",
                        len(restored), session_id,
                    )
            except Exception as e:
                logger.warning("恢复对话历史失败（非致命）: %s", e)
        prev_failed_attempts = 0
        history_messages = []
        if session_state:
            prev_failed_attempts = getattr(session_state, 'failed_attempts', 0)
            # 从 conversation_history 读取历史消息并转换为 Message 对象
            conv_history = getattr(session_state, 'conversation_history', [])
            logger.info(
                "[ContextMemory] session=%s: 读取到 %d 条历史消息",
                session_id, len(conv_history)
            )
            for i, msg_dict in enumerate(conv_history):
                role = msg_dict.get("role", "user")
                content = msg_dict.get("content", "")
                logger.debug(
                    "[ContextMemory] session=%s 历史[%d]: role=%s, content=%s",
                    session_id, i, role, content[:100]
                )
                if role == "user":
                    history_messages.append(HumanMessage(content=content))
                else:
                    history_messages.append(AIMessage(content=content))
        else:
            logger.warning("[ContextMemory] session=%s: 会话状态不存在", session_id)

        # 历史消息 + 当前消息
        all_messages = history_messages + [HumanMessage(content=multimodal_content)]
        logger.info(
            "[ContextMemory] session=%s: 调用 app.invoke 前消息总数=%d (历史=%d + 当前=1)",
            session_id, len(all_messages), len(history_messages)
        )

        state = AgentState(
            messages=all_messages,
            intent=None,
            retrieved_docs=[],
            needs_human=False,
            turn_count=0,
            final_response="",
            user_id=user_id,
            session_id=session_id,
            tenant_id=tenant_id,
            user_access_levels=["public", "internal", "confidential", "restricted"],
            user_roles=[],
            user_plan=user_plan,
            faq_match=None,
            effective_max_turns=5,
            has_reflected=False,
            memory_context="",
            quality_score=None,
            access_filtered=0,
            failed_attempts=prev_failed_attempts,
            suggest_human=False,
            # HITL 字段
            awaiting_human=False,
            human_handoff_context=None,
            human_response=None,
            human_agent_id=None,
            human_handled=False,
        )

        # 4. 执行工作流（异步 offload，避免阻塞事件循环）
        import asyncio
        thread_config = {"configurable": {"thread_id": session_id}}
        result = await asyncio.to_thread(
            app.invoke, state, thread_config,
        )

        # ===== HITL 检测：检查工作流是否被 interrupt() 暂停 =====
        is_interrupted = False
        interrupt_value = None
        try:
            state_snapshot = app.get_state(thread_config)
            if state_snapshot and state_snapshot.next:
                is_interrupted = True
                for task in (state_snapshot.tasks or []):
                    if hasattr(task, "interrupts") and task.interrupts:
                        interrupt_value = task.interrupts[0].value
                        break
        except Exception as hitl_err:
            logger.warning("[HITL] 检查中断状态失败: %s", hitl_err)

        if is_interrupted:
            # 工作流被暂停 → 记录到 HITL 管理器，等待人工介入
            from src.graph.hitl_manager import get_hitl_manager
            hitl = get_hitl_manager()
            await hitl.add_pending(
                thread_id=session_id,
                interrupt_value=interrupt_value or {},
                session_id=session_id,
                user_id=user_id,
            )
            logger.info("[HITL] 工作流暂停，等待人工介入: session=%s", session_id)

            # 推送"正在转接"消息给用户
            await websocket.send_json(build_typing_indicator(session_id, is_typing=False))
            await websocket.send_json(build_streaming_chunk(
                session_id,
                text="正在为您转接人工客服，请稍候...",
                delta="正在为您转接人工客服，请稍候...",
            ))
            # 完成标记（带 HITL 元信息，前端可据此显示"等待人工"状态）
            await websocket.send_json({
                **build_streaming_chunk(session_id, text="", done=True),
                "needs_human": True,
                "awaiting_human": True,
                "thread_id": session_id,
            })

            # 更新会话状态为"等待人工"
            session_mgr.update_mode(session_id, SessionMode.WAITING_HUMAN)
            return  # 工作流暂停，直接返回，等待人工恢复

        # 打印调用后的结果消息数量
        result_messages = result.get("messages", [])
        logger.info(
            "[ContextMemory] session=%s: 调用 app.invoke 后结果消息数=%d",
            session_id, len(result_messages)
        )

        # 5. 发送思考完毕
        await websocket.send_json(build_typing_indicator(
            session_id, is_typing=False,
        ))

        # 6. 推送最终回复
        final_response = result.get("final_response", "")
        needs_human = result.get("needs_human", False)
        intent = result.get("intent", "unknown")
        quality_score = result.get("quality_score")
        suggest_human = result.get("suggest_human", False)
        failed_attempts = result.get("failed_attempts", 0)

        # 引用知识片段：把 RAG 检索结果透传给前端（坐席/用户可见「本回答基于哪些知识」）
        citations = _build_citations(result.get("retrieved_docs") or [])

        # 保存失败次数和建议转人工状态到会话状态
        if session_state:
            session_state.failed_attempts = failed_attempts
            session_state.suggest_human = suggest_human

        if final_response:
            # 清理：彻底过滤掉 Agent 内部的 ReAct 格式标记
            import re
            
            # 方法1：查找 Final Answer: 的位置，只保留其后的内容
            final_answer_match = re.search(r'Final Answer:\s*', final_response, flags=re.IGNORECASE)
            if final_answer_match:
                cleaned = final_response[final_answer_match.end():]
            else:
                # 方法2：如果没有 Final Answer，查找最后一个内部标记之后的内容
                # 匹配所有 ReAct 标记：Question:, Thought:, Action:, Action Input:, Observation:
                react_markers = ['Question:', 'Thought:', 'Action:', 'Action Input:', 'Observation:', 'Final Answer:']
                last_pos = 0
                for marker in react_markers:
                    matches = list(re.finditer(re.escape(marker), final_response, flags=re.IGNORECASE))
                    if matches:
                        last_match = matches[-1]
                        # 取标记后面的内容（跳过标记本身）
                        marker_end = last_match.end()
                        candidate = final_response[marker_end:].strip()
                        # 如果这段内容看起来是真正的回答（不以其他标记开头），则使用它
                        if candidate and not any(candidate.startswith(m) for m in react_markers):
                            cleaned = candidate
                            last_pos = marker_end
                            break
                else:
                    # 方法3：直接删除所有内部标记及其内容
                    cleaned = re.sub(r'(Question:|Thought:|Action:|Action Input:|Observation:).*?(?=\n\n|\n|$)', '', final_response, flags=re.DOTALL | re.IGNORECASE)
            
            cleaned = cleaned.strip()
            cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
            if cleaned:
                final_response = cleaned

            # 流式推送：按句号/换行分段，每段推送一次（豆包风格）
            # 先按段落拆分，再按句号拆分
            suggest_human = result.get("suggest_human", False)
            paragraphs = final_response.split('\n')
            all_chunks = []
            for para in paragraphs:
                if not para.strip():
                    continue
                # 按句号/感叹号/问号分段
                parts = re.split(r'([。！？])', para)
                buf = ""
                for p in parts:
                    buf += p
                    if re.match(r'[。！？]$', p):
                        all_chunks.append(buf.strip())
                        buf = ""
                if buf.strip():
                    all_chunks.append(buf.strip())
            
            # 发送所有分段，最后一段带上 suggest_human
            for i, chunk in enumerate(all_chunks):
                is_last = (i == len(all_chunks) - 1)
                await websocket.send_json(build_streaming_chunk(
                    session_id, text=chunk, delta=chunk,
                    suggest_human=suggest_human if is_last else False,
                ))

            # 完成标记（附带本回答引用的知识片段，供前端做「引用知识片段」气泡）
            await websocket.send_json(build_streaming_chunk(
                session_id, text="", done=True, suggest_human=suggest_human,
                citations=citations,
            ))

        # 6.5 保存对话历史到会话状态
        if session_state and final_response:
            # 追加用户消息和 AI 回复到 conversation_history
            user_msg = {"role": "user", "content": message}
            ai_msg = {"role": "assistant", "content": final_response}
            session_state.conversation_history.append(user_msg)
            session_state.conversation_history.append(ai_msg)
            # 更新轮次计数
            session_state.turn_count += 1
            # Phase 3: 持久化 AI 回复（与内存历史并行落库）
            try:
                from src.db.repositories import message_save
                await asyncio.to_thread(
                    message_save, session_id, tenant_id, user_id, "assistant",
                    final_response, intent=intent or "",
                    metadata={"quality_score": quality_score, "citations": citations},
                )
            except Exception as e:
                logger.warning("[Persistence] AI回复落库失败（非致命）: %s", e)
            logger.info(
                "[ContextMemory] session=%s: 保存对话历史，当前总消息数=%d, turn_count=%d",
                session_id, len(session_state.conversation_history), session_state.turn_count
            )
            logger.debug(
                "[ContextMemory] session=%s: 新增 user_msg=%s, ai_msg=%s",
                session_id, message[:100], final_response[:100]
            )

        # 7. 如果需要转人工
        if needs_human:
            # 更新会话状态
            session_mgr.update_mode(session_id, SessionMode.WAITING_HUMAN)

            # 构建转接通知
            transfer_notice = build_transfer_notice(
                session_id=session_id,
                reason=f"AI 无法处理（intent={intent}）",
            )
            await websocket.send_json(transfer_notice)

            # 构建转接上下文
            messages = result.get("messages", [])
            handoff_ctx = build_handoff_context(
                session_id=session_id,
                summary=f"AI 无法处理: {final_response[:200]}",
                conversation=[
                    {"role": "user" if isinstance(m, HumanMessage) else "assistant",
                     "content": (m.content if hasattr(m, "content") else str(m))[:500]}
                    for m in messages
                ],
                user_profile={"user_id": user_id, "plan": user_plan},
                attempted_solutions=["RAG 检索", "FAQ 匹配"],
                quality_score=quality_score,
            )
            await websocket.send_json(handoff_ctx)

            # 触发转接分发
            dispatcher = get_dispatcher()
            await dispatcher.handle_escalation(session_id, result, messages)

            # 发送系统通知给人工客服
            try:
                from src.api.notifications import add_handoff_notification
                add_handoff_notification(session_id, user_id, reason=f"AI 无法处理（intent={intent}）")
            except Exception as e:
                logger.warning("Failed to send handoff notification: %s", e)

        # 8. 如果有权限过滤
        access_filtered = result.get("access_filtered", 0)
        if access_filtered > 0:
            await websocket.send_json({
                "type": "info",
                "session_id": session_id,
                "text": f"[注：本次检索有 {access_filtered} 条结果因权限不足被过滤]",
                "timestamp": time.time(),
            })

        # 9. 记录业务指标
        try:
            from src.evaluation.tracker import get_evaluation_tracker
            tracker = get_evaluation_tracker()
            end_time = time.time()
            latency_ms = (end_time - (start_time if 'start_time' in locals() else end_time)) * 1000
            quality_score = result.get("quality_score")
            intent = result.get("intent", "unknown")
            turn_count = result.get("turn_count", 1)
            resolved = not needs_human and quality_score is not None and quality_score > 0.3
            tracker.record_chat(
                session_id=session_id,
                intent=intent,
                latency_ms=latency_ms,
                quality_score=quality_score,
                needs_human=needs_human,
                suggest_human=suggest_human,
                turn_count=turn_count,
                resolved=resolved,
            )
            # 真实安全计数：prompt 注入拦截 + 转人工升级（供 /metrics/risk 暴露）
            if result.get("injection_blocked"):
                tracker.record_safety_event("prompt_injection_blocked")
            if needs_human:
                tracker.record_safety_event("escalation")
        except Exception as e:
            logger.warning("Failed to record metrics: %s", e)

    except Exception as e:
        logger.exception("Error processing chat: session=%s", session_id)
        await websocket.send_json(build_error(
            session_id, "CHAT_ERROR", str(e)[:200],
        ))
        # 出错也尝试转人工
        try:
            dispatcher = get_dispatcher()
            await dispatcher.handle_escalation(
                session_id,
                {"needs_human": True, "intent": "error", "messages": []},
                [],
            )
        except Exception:
            pass


# ====================================================================
# 人工坐席 WebSocket
# ====================================================================

@router.websocket("/ws/agent/{agent_id}")
async def websocket_agent(websocket: WebSocket, agent_id: str = Path(...)):
    """人工坐席工作台 WebSocket 端点

    流程：
        1. 坐席连接 → 注册到 session_manager
        2. 有新转接时收到 new_transfer 通知
        3. 坐席回复用户 → agent_send_reply → 推送到用户
        4. Copilot 模式：用户发消息时自动推送建议回复
    """
    session_mgr = get_session_manager()

    # 接受连接
    await websocket.accept()
    session_mgr.register_agent(agent_id, websocket)
    logger.info("Agent connected: %s", agent_id)

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            # --- 坐席发送回复 ---
            if msg_type == TYPE_AGENT_SEND_REPLY:
                session_id = msg.get("session_id", "")
                reply_text = msg.get("text", "").strip()
                if not session_id or not reply_text:
                    continue

                dispatcher = get_dispatcher()
                success = await dispatcher.agent_reply(agent_id, session_id, reply_text)

                await websocket.send_json({
                    "type": "agent_reply_ack",
                    "session_id": session_id,
                    "sent": success,
                    "timestamp": time.time(),
                })

            # --- 坐席登出 ---
            elif msg_type == "agent_logout":
                break

            # --- 心跳 ---
            elif msg_type == TYPE_CLIENT_HEARTBEAT:
                await websocket.send_json({
                    "type": "heartbeat_ack",
                    "timestamp": time.time(),
                })

    except WebSocketDisconnect:
        logger.info("Agent disconnected: %s", agent_id)
    finally:
        session_mgr.unregister_agent(agent_id)
