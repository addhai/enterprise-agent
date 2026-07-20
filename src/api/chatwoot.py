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

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from src.graph.state import AgentState
from src.api.dependencies import get_workflow
from src.config import settings
from langchain_core.messages import HumanMessage, AIMessage

logger = logging.getLogger(__name__)
router = APIRouter()

WORKFLOW_TIMEOUT = 15.0


def _validate_webhook_token(token: str) -> bool:
    """验证 Webhook 请求的 access_token"""
    if not settings.channel_chatwoot_webhook_token:
        return True  # 未配置时跳过验证（开发模式）
    return token == settings.channel_chatwoot_webhook_token


async def _send_reply_to_chatwoot(
    account_id: int,
    conversation_id: int,
    content: str,
    is_private: bool = False,
) -> bool:
    """通过 Chatwoot API 发送回复"""
    headers = {
        "Content-Type": "application/json",
        "api_access_token": settings.channel_chatwoot_api_token,
    }
    payload = {
        "message": {
            "content": content,
            "message_type": "template" if is_private else "outgoing",
            "private": is_private,
        }
    }

    url = f"{settings.channel_chatwoot_base_url}/accounts/{account_id}/conversations/{conversation_id}/messages"

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


@router.get("/chatwoot/webhook")
async def chatwoot_webhook_verify(request: Request):
    """Chatwoot Webhook 验证端点

    Chatwoot 在配置 webhook 时会发送一个带 challenge 参数的 GET 请求，
    我们需要原样返回 challenge 值来验证端点可用性。
    """
    challenge = request.query_params.get("challenge", "")
    logger.info("Chatwoot webhook verify: challenge=%s", challenge)
    return {"challenge": challenge}


@router.post("/chatwoot/webhook")
async def chatwoot_webhook(request: Request):
    """Chatwoot Webhook 入口

    接收 Chatwoot 推送的新消息，通过 LangGraph 工作流处理，
    然后将回复发送回 Chatwoot。
    """
    if not settings.channel_chatwoot_enabled:
        raise HTTPException(status_code=403, detail="Chatwoot 渠道未启用")

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
            url = f"{settings.channel_chatwoot_base_url}/accounts/{account_id}/conversations/{conversation_id}/messages"
            resp = await client.get(url, headers={"api_access_token": settings.channel_chatwoot_api_token})
            resp.raise_for_status()
            chatwoot_messages = resp.json().get("items", [])
    except Exception as e:
        logger.warning("Failed to fetch Chatwoot history: %s", e)

    # 5. 构建对话历史
    history = _build_conversation_history(chatwoot_messages)

    # 6. 异步处理消息（先返回200，避免Chatwoot超时重发）
    asyncio.create_task(_process_chatwoot_message(
        account_id, conversation_id, user_message, sender, chatwoot_messages
    ))

    return {"status": "accepted", "message": "消息已接收，正在处理中"}


async def _process_chatwoot_message(
    account_id: int,
    conversation_id: int,
    user_message: str,
    sender: Dict[str, Any],
    chatwoot_messages: list,
):
    """后台处理 Chatwoot 消息并发送回复"""
    reply = ""
    needs_human = False
    intent = "unknown"
    
    try:
        app = get_workflow()
        session_id = f"cw-{account_id}-{conversation_id}"
        history = _build_conversation_history(chatwoot_messages)

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

        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: app.invoke(
                    state,
                    config={"configurable": {"thread_id": session_id}},
                )
            ),
            timeout=WORKFLOW_TIMEOUT,
        )

        reply = result.get("final_response", "抱歉，处理您的消息时出错。")
        needs_human = result.get("needs_human", False)
        intent = result.get("intent", "unknown")

    except asyncio.TimeoutError:
        logger.warning("Chatwoot workflow timed out after %.1fs", WORKFLOW_TIMEOUT)
        reply = _get_fallback_reply(user_message)
        needs_human = True
        intent = "timeout"
    except Exception as e:
        logger.exception("Chatwoot message processing failed")
        reply = _get_fallback_reply(user_message)
        needs_human = True
        intent = "error"

    # 发送回复回 Chatwoot
    try:
        if needs_human and intent in ("timeout", "error"):
            await _send_reply_to_chatwoot(
                account_id, conversation_id,
                f"{reply}\n\n[系统提示] AI 处理超时或出错，已为您转接人工客服。",
                is_private=False,
            )
        elif needs_human:
            await _send_reply_to_chatwoot(
                account_id, conversation_id,
                f"[AI 转接] 无法处理（intent={intent}）。已转人工客服。",
                is_private=True,
            )
        else:
            await _send_reply_to_chatwoot(
                account_id, conversation_id, reply, is_private=False,
            )
        logger.info("Chatwoot reply sent: conv=%d, intent=%s", conversation_id, intent)
    except Exception as e:
        logger.error("Failed to send Chatwoot reply: %s", e)


def _get_fallback_reply(user_message: str) -> str:
    """工作流不可用时的 fallback 回复"""
    msg_lower = user_message.lower()
    if any(k in msg_lower for k in ["你好", "您好", "hello", "hi", "在吗"]):
        return "您好！我是智能客服助手，很高兴为您服务。请问有什么可以帮助您的？\n\n您可以咨询以下问题：\n- 产品功能介绍\n- 账户与账单\n- 技术支持\n- API 接入"
    if any(k in msg_lower for k in ["价格", "费用", "多少钱", "收费", "套餐"]):
        return "关于价格和套餐信息：\n\n我们提供多种订阅方案：\n- 免费版：基础功能，每月100次调用\n- 专业版：¥99/月，完整功能，每月5000次调用\n- 企业版：定制价格，无限调用，专属技术支持\n\n如需详细报价，请联系销售团队。"
    if any(k in msg_lower for k in ["功能", "介绍", "能做什么", "特性"]):
        return "我们的智能客服系统主要功能：\n\n1. **智能对话**：AI 自动回答常见问题\n2. **多渠道接入**：支持网页、微信、Chatwoot 等多种渠道\n3. **工单管理**：自动创建和分配工单\n4. **知识库检索**：基于 RAG 的文档问答\n5. **人工转接**：复杂问题自动转人工客服\n6. **数据分析**：详细的对话和满意度统计"
    if any(k in msg_lower for k in ["人工", "客服", "转人工", "真人"]):
        return "正在为您转接人工客服，请稍候...\n\n工作时间：周一至周五 9:00-18:00\n您也可以留下您的问题，我们会尽快回复。"
    return "感谢您的咨询！我已记录您的问题，稍后会有专人回复您。\n\n如果问题比较紧急，建议您：\n1. 查看我们的帮助文档\n2. 在工作时间联系在线客服\n3. 发送邮件至 support@example.com"


@router.get("/chatwoot/events")
async def chatwoot_event_subscribe(request: Request):
    """Chatwoot 事件订阅验证

    Chatwoot 在配置 Webhook 时会发送一个验证请求，
    需要返回相同的 challenge 值。
    """
    challenge = request.query_params.get("challenge", "")
    if challenge:
        return {"challenge": challenge}
    return {"status": "ok"}
