"""Chatwoot 渠道适配器

处理 Chatwoot webhook 推送的消息，并通过 Chatwoot REST API 发送回复。

Chatwoot webhook payload 格式（message_created 事件）：
    {
        "access_token": "xxx",
        "account": { "id": 1, "name": "CloudSync" },
        "message": {
            "id": 123,
            "content": "你好",
            "message_type": "incoming",   # incoming / outgoing
            "inbox_id": 1,
            "sender": { "id": 456, "name": "张三" },
            "conversation_id": 789,
            "created_at": "2026-07-08T10:00:00Z"
        },
        "event": "message_created"
    }

Chatwoot 发送消息 API：
    POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages
    Headers: { "api_access_token": "<token>" }
    Body:    { "message": { "content": "...", "message_type": "outgoing" } }
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

import httpx

from src.channels.base import BaseChannel

logger = logging.getLogger(__name__)

# 默认配置（可通过环境变量覆盖，与 src/api/chatwoot.py 保持一致）
_DEFAULT_BASE_URL = "http://chatwoot:3000/api/v1"
_DEFAULT_TIMEOUT = 10.0


class ChatwootChannel(BaseChannel):
    """Chatwoot 渠道适配器"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_token: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.base_url = (base_url or os.environ.get("CHATWOOT_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")
        # 优先使用显式传入的 token，其次读取环境变量
        self.api_token = api_token or os.environ.get("CHATWOOT_SECRET_KEY", "")
        self.timeout = timeout

    @property
    def channel_name(self) -> str:
        return "chatwoot"

    async def receive_message(self, raw_data: dict) -> dict:
        """解析 Chatwoot webhook payload，提取标准化消息字段

        只处理 event == "message_created" 且 message_type == "incoming" 的消息，
        其他事件返回 content_type="event"，由调用方决定是否忽略。
        """
        event = raw_data.get("event", "")
        message = raw_data.get("message", {}) or {}
        account = raw_data.get("account", {}) or {}
        sender = message.get("sender", {}) or {}

        conversation_id = message.get("conversation_id")
        account_id = account.get("id")
        message_id = str(message.get("id")) if message.get("id") else str(uuid.uuid4())

        # 非消息创建事件 → 标记为 event，不参与对话流程
        if event != "message_created":
            return {
                "message_id": message_id,
                "channel": self.channel_name,
                "sender_id": str(sender.get("id", "")),
                "sender_name": sender.get("name", ""),
                "content": "",
                "content_type": "event",
                "conversation_id": str(conversation_id) if conversation_id is not None else "",
                "tenant_id": str(account_id) if account_id is not None else "",
                "raw_payload": raw_data,
                "metadata": {"event": event, "account_id": account_id},
            }

        content = message.get("content", "") or ""
        message_type = message.get("message_type", "incoming")

        return {
            "message_id": message_id,
            "channel": self.channel_name,
            "sender_id": str(sender.get("id", "")),
            "sender_name": sender.get("name", ""),
            "content": content,
            # 仅 incoming 视为文本消息；outgoing 视为事件，避免回环
            "content_type": "text" if message_type == "incoming" else "event",
            "conversation_id": str(conversation_id) if conversation_id is not None else "",
            "tenant_id": str(account_id) if account_id is not None else "",
            "raw_payload": raw_data,
            "metadata": {
                "event": event,
                "account_id": account_id,
                "inbox_id": message.get("inbox_id"),
                "message_type": message_type,
                "created_at": message.get("created_at"),
            },
        }

    async def send_message(
        self,
        target: str,
        content: str,
        **kwargs,
    ) -> bool:
        """通过 Chatwoot API 发送消息到指定会话

        Args:
            target: 形如 "{account_id}:{conversation_id}" 或纯 conversation_id
                    （此时 account_id 需通过 kwargs.account_id 提供，或回退到 1）
            content: 消息文本
            **kwargs:
                account_id: Chatwoot 账号 ID（覆盖 target 解析）
                is_private: 是否为私有备注（默认 False）
                message_type: 消息类型（默认 outgoing）
        """
        account_id = kwargs.get("account_id")
        conversation_id = target

        # 支持 "account_id:conversation_id" 形式
        if ":" in target:
            parts = target.split(":", 1)
            account_id = account_id or parts[0]
            conversation_id = parts[1]

        if not account_id:
            account_id = "1"
        if not conversation_id:
            logger.warning("Chatwoot send_message: 缺少 conversation_id")
            return False

        is_private = bool(kwargs.get("is_private", False))
        message_type = kwargs.get("message_type", "outgoing")

        url = f"{self.base_url}/accounts/{account_id}/conversations/{conversation_id}/messages"
        headers = {
            "Content-Type": "application/json",
            "api_access_token": self.api_token,
        }
        payload = {
            "message": {
                "content": content,
                "message_type": message_type,
                "private": is_private,
            }
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                logger.info(
                    "Chatwoot 消息已发送: account=%s, conv=%s",
                    account_id, conversation_id,
                )
                return True
        except httpx.HTTPStatusError as e:
            logger.error(
                "Chatwoot 发送失败 (HTTP %s): %s",
                e.response.status_code, e.response.text[:200],
            )
            return False
        except Exception as e:
            logger.error("Chatwoot 发送异常: %s", e)
            return False
