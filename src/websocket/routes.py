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

logger = logging.getLogger(__name__)
router = APIRouter()


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
    user_id = "anonymous"
    tenant_id = ""
    user_plan = "free"

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

                # 提取可选参数
                incoming_session = msg.get("session_id")
                incoming_user_id = msg.get("user_id", "anonymous")
                incoming_tenant = msg.get("tenant_id", "")
                incoming_plan = msg.get("user_plan", "free")

                # 优先复用已有的 session（如果 WebSocket 连接已经建立了会话）
                if session_id and session_mgr.get_session(session_id):
                    # 复用当前连接的会话
                    state = session_mgr.get_session(session_id)
                    if incoming_user_id and incoming_user_id != "anonymous":
                        state.user_id = incoming_user_id
                    if incoming_plan:
                        state.user_plan = incoming_plan
                elif incoming_session and session_mgr.get_session(incoming_session):
                    # 使用消息中带的 session_id
                    session_id = incoming_session
                    user_id = incoming_user_id
                    tenant_id = incoming_tenant
                    user_plan = incoming_plan
                    state = session_mgr.get_session(session_id)
                    if user_id and user_id != "anonymous":
                        state.user_id = user_id
                    if user_plan:
                        state.user_plan = user_plan
                else:
                    # 创建新会话
                    session_id = str(uuid.uuid4())
                    user_id = incoming_user_id
                    tenant_id = incoming_tenant
                    user_plan = incoming_plan
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

                # 检查是否已经在人工模式
                current_state = session_mgr.get_session(session_id)
                if current_state and current_state.mode == SessionMode.HUMAN_CHAT:
                    # 人工模式：用户发的消息转发给坐席
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

                    # 坐席直接回复（不在人工模式下也允许）
                    # 这里不做处理，坐席回复通过 agent_reply 推送

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
    from src.api.routes import AgentState, HumanMessage
    from src.api.dependencies import get_workflow

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

        # 先展示图片识别结果给用户看
        if display_text != message and image_base64:
            await websocket.send_json(build_streaming_chunk(
                session_id, text=display_text, delta=display_text,
            ))
            await websocket.send_json(build_streaming_chunk(
                session_id, text="", done=True,
            ))

        # 2. 获取工作流
        app = get_workflow()

        # 3. 构建 AgentState
        state = AgentState(
            messages=[HumanMessage(content=multimodal_content)],
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
        )

        # 4. 执行工作流（异步 offload，避免阻塞事件循环）
        import asyncio
        result = await asyncio.to_thread(
            app.invoke, state,
            {"configurable": {"thread_id": session_id}}
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

        if final_response:
            # 清理：彻底过滤掉 Agent 内部的 Thought/Action/Observation/Final Answer 片段
            import re
            # 先移除 Thought: ... 和 Final Answer: ... 及其前面的内容
            cleaned = re.sub(r'Thought:[^F]*(?=Final Answer:)', '', final_response, flags=re.DOTALL | re.IGNORECASE)
            cleaned = re.sub(r'Final Answer:\s*', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'(Action:|Action Input:|Observation:).*?(?=\n\n|$)', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
            cleaned = cleaned.strip()
            cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
            if cleaned:
                final_response = cleaned

            # 流式推送：按句号/换行分段，每段推送一次（豆包风格）
            # 先按段落拆分，再按句号拆分
            paragraphs = final_response.split('\n')
            for para in paragraphs:
                if not para.strip():
                    continue
                # 按句号/感叹号/问号分段
                parts = re.split(r'([。！？])', para)
                buf = ""
                for p in parts:
                    buf += p
                    if re.match(r'[。！？]$', p):
                        await websocket.send_json(build_streaming_chunk(
                            session_id, text=buf.strip(), delta=buf.strip(),
                        ))
                        buf = ""
                if buf.strip():
                    await websocket.send_json(build_streaming_chunk(
                        session_id, text=buf.strip(), delta=buf.strip(),
                    ))

            # 完成标记
            await websocket.send_json(build_streaming_chunk(
                session_id, text="", done=True,
            ))

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

        # 8. 如果有权限过滤
        access_filtered = result.get("access_filtered", 0)
        if access_filtered > 0:
            await websocket.send_json({
                "type": "info",
                "session_id": session_id,
                "text": f"[注：本次检索有 {access_filtered} 条结果因权限不足被过滤]",
                "timestamp": time.time(),
            })

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
