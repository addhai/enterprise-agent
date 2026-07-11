"""Chatwoot Webhook 端点

职责：
    接收 Chatwoot 通过 Webhook 发送的消息，处理后返回回复。
    Chatwoot → POST /api/v1/chatwoot/webhook → FastAPI → LangGraph → 回复

Chatwoot Webhook 消息格式：
    {
        "access_token": "xxx",
        "account": { "id": 1, "name": "CloudSync" },
        "message": {
            "id": 123,
            "content": "你好",
            "message_type": "incoming",
            "inbox_id": 1,
            "sender": { "id": 456, "name": "张三" },
            "conversation_id": 789,
            "created_at": "2026-07-08T10:00:00Z"
        },
        "event": "message_created"
    }

回复格式（Chatwoot API）：
    POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages
    { "message": { "content": "AI 回复...", "message_type": "outgoing" } }
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from src.graph.state import AgentState
from src.api.dependencies import get_workflow
from langchain_core.messages import HumanMessage, AIMessage

logger = logging.getLogger(__name__)
router = APIRouter()

# Chatwoot 配置
CHATWOOT_WEBHOOK_TOKEN = os.environ.get("CHATWOOT_SECRET_KEY", "")
CHATWOOT_BASE_URL = os.environ.get("CHATWOOT_BASE_URL", "http://chatwoot:3000/api/v1")


def _validate_webhook_token(token: str) -> bool:
    """验证 Webhook 请求的 access_token"""
    if not CHATWOOT_WEBHOOK_TOKEN:
        return True  # 未配置时跳过验证（开发模式）
    return token == CHATWOOT_WEBHOOK_TOKEN


async def _send_reply_to_chatwoot(
    account_id: int,
    conversation_id: int,
    content: str,
    is_private: bool = False,
) -> bool:
    """通过 Chatwoot API 发送回复"""
    headers = {
        "Content-Type": "application/json",
        "api_access_token": CHATWOOT_WEBHOOK_TOKEN,
    }
    payload = {
        "message": {
            "content": content,
            "message_type": "template" if is_private else "outgoing",
            "private": is_private,
        }
    }

    url = f"{CHATWOOT_BASE_URL}/accounts/{account_id}/conversations/{conversation_id}/messages"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            logger.info("Chatwoot reply sent: account=%d, conv=%d", account_id, conversation_id)
            return True
    except Exception as e:
        logger.error("Failed to send Chatwoot reply: %s", e)
        return False


def _build_conversation_history(chatwoot_messages: list) -> list:
    """将 Chatwoot 历史消息转换为 LangChain 格式"""
    history = []
    for msg in chatwoot_messages:
        sender_type = msg.get("sender_type", "user")
        content = msg.get("content", "")
        if sender_type == "user":
            history.append((content, ""))  # (human, assistant)
        else:
            if history:
                history[-1] = (history[-1][0], content)
    return history


@router.post("/chatwoot/webhook")
async def chatwoot_webhook(request: Request):
    """Chatwoot Webhook 入口

    接收 Chatwoot 推送的新消息，通过 LangGraph 工作流处理，
    然后将回复发送回 Chatwoot。
    """
    body = await request.json()

    # 1. 验证事件类型
    event = body.get("event", "")
    if event != "message_created":
        return {"status": "ignored", "event": event}

    # 2. 验证 token
    access_token = body.get("access_token", "")
    if not _validate_webhook_token(access_token):
        logger.warning("Invalid Chatwoot webhook token")
        raise HTTPException(status_code=401, detail="Invalid token")

    # 3. 提取消息信息
    message = body.get("message", {})
    account = body.get("account", {})
    conversation_id = message.get("conversation_id")
    account_id = account.get("id", 1)
    user_message = message.get("content", "")
    sender = message.get("sender", {})

    if not user_message or not conversation_id:
        return {"status": "error", "message": "Missing message or conversation_id"}

    logger.info(
        "Chatwoot webhook: account=%d, conv=%d, user=%s, msg=%s",
        account_id, conversation_id,
        sender.get("id"), user_message[:50],
    )

    # 4. 获取对话历史（从 Chatwoot API 拉取）
    chatwoot_messages = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = f"{CHATWOOT_BASE_URL}/accounts/{account_id}/conversations/{conversation_id}/messages"
            resp = await client.get(url, headers={"api_access_token": CHATWOOT_WEBHOOK_TOKEN})
            resp.raise_for_status()
            chatwoot_messages = resp.json().get("items", [])
    except Exception as e:
        logger.warning("Failed to fetch Chatwoot history: %s", e)

    # 5. 构建对话历史
    history = _build_conversation_history(chatwoot_messages)

    # 6. 调用 LangGraph 工作流
    try:
        app = get_workflow()
        session_id = f"cw-{account_id}-{conversation_id}"

        state = AgentState(
            messages=[HumanMessage(content=user_message)],
            intent=None,
            retrieved_docs=[],
            needs_human=False,
            turn_count=len(history),
            final_response="",
            user_id=str(sender.get("id", "anonymous")),
            session_id=session_id,
            tenant_id="",
            user_access_levels=["public", "internal", "confidential", "restricted"],
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
        )

        result = app.invoke(
            state,
            config={"configurable": {"thread_id": session_id}},
        )

        reply = result.get("final_response", "抱歉，处理您的消息时出错。")
        needs_human = result.get("needs_human", False)
        intent = result.get("intent", "unknown")

        # 7. 发送回复回 Chatwoot
        if needs_human:
            # 转人工：发送私有的 agent 备注
            await _send_reply_to_chatwoot(
                account_id, conversation_id,
                f"[AI 转接] 无法处理（intent={intent}）。已转人工客服。",
                is_private=True,
            )
        else:
            # 正常回复
            await _send_reply_to_chatwoot(
                account_id, conversation_id, reply, is_private=False,
            )

        return {"status": "ok", "reply": reply[:100], "needs_human": needs_human}

    except Exception as e:
        logger.exception("Chatwoot webhook processing failed")
        await _send_reply_to_chatwoot(
            account_id, conversation_id,
            "抱歉，服务暂时不可用。请稍后重试。",
        )
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.get("/chatwoot/events")
async def chatwoot_event_subscribe():
    """Chatwoot 事件订阅验证

    Chatwoot 在配置 Webhook 时会发送一个验证请求，
    需要返回相同的 challenge 值。
    """
    params = dict(request.query_params) if (request := None) else {}
    # 简化：直接返回 200
    return {"status": "ok"}
