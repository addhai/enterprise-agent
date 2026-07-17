"""企业微信群机器人渠道适配器（仅发送）

仅保留免费的群机器人 webhook 发送消息功能。
企业微信应用消息回调（接收消息）需要企业认证，已移除。

企业微信群机器人 webhook：
    POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=<KEY>
    Body: { "msgtype": "text", "text": { "content": "..." } }

使用场景：
    - 系统通知推送到企业微信群（如告警、日报、工单提醒）
    - 不接收用户消息，仅单向推送
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from src.channels.base import BaseChannel

logger = logging.getLogger(__name__)

_DEFAULT_WEBHOOK_BASE = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
_DEFAULT_TIMEOUT = 10.0


class WeChatWorkChannel(BaseChannel):
    """企业微信群机器人渠道（仅发送）"""

    def __init__(
        self,
        webhook_key: Optional[str] = None,
        webhook_url: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.webhook_key = webhook_key or os.environ.get("WECHAT_WORK_WEBHOOK_KEY", "")
        self.webhook_url = webhook_url or os.environ.get("WECHAT_WORK_WEBHOOK_URL", "")
        self.timeout = timeout

    @property
    def channel_name(self) -> str:
        return "wechat"

    async def receive_message(self, raw_data: dict) -> dict:
        """企业微信渠道不接收消息（仅推送）"""
        raise NotImplementedError(
            "企业微信应用消息回调需要企业认证，已移除。"
            "本渠道仅支持通过群机器人 webhook 发送消息。"
        )

    async def send_message(
        self,
        target: str,
        content: str,
        **kwargs,
    ) -> bool:
        """通过企业微信群机器人 webhook 发送消息

        Args:
            target: 群机器人 key（或完整 webhook URL）
                    若为空，则使用构造时传入的 webhook_key/webhook_url
            content: 文本内容
            **kwargs:
                msg_type: 消息类型（默认 text，支持 markdown）
                mentioned_list: 需要 @ 的用户 ID 列表
                mentioned_mobile_list: 需要 @ 的手机号列表
        """
        webhook_url = self._resolve_webhook_url(target)
        if not webhook_url:
            logger.warning("WeChatWork send_message: 缺少 webhook key/url")
            return False

        msg_type = kwargs.get("msg_type", "text")
        payload: dict = {"msgtype": msg_type}

        if msg_type == "text":
            text_body: dict = {"content": content}
            mentioned = kwargs.get("mentioned_list")
            mentioned_mobile = kwargs.get("mentioned_mobile_list")
            if mentioned:
                text_body["mentioned_list"] = mentioned
            if mentioned_mobile:
                text_body["mentioned_mobile_list"] = mentioned_mobile
            payload["text"] = text_body
        elif msg_type == "markdown":
            payload["markdown"] = {"content": content}
        else:
            payload["msgtype"] = "text"
            payload["text"] = {"content": content}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(webhook_url, json=payload)
                resp.raise_for_status()
                body = resp.json()
                if body.get("errcode", 0) == 0:
                    logger.info("企业微信群机器人消息已发送")
                    return True
                logger.error(
                    "企业微信群机器人发送失败: errcode=%s errmsg=%s",
                    body.get("errcode"), body.get("errmsg"),
                )
                return False
        except httpx.HTTPStatusError as e:
            logger.error(
                "企业微信群机器人 HTTP 错误 (%s): %s",
                e.response.status_code, e.response.text[:200],
            )
            return False
        except Exception as e:
            logger.error("企业微信群机器人发送异常: %s", e)
            return False

    def _resolve_webhook_url(self, target: str) -> str:
        """根据 target / 配置解析出最终 webhook URL"""
        if target and target.startswith("http"):
            return target
        if target:
            return f"{_DEFAULT_WEBHOOK_BASE}?key={target}"
        if self.webhook_url:
            return self.webhook_url
        if self.webhook_key:
            return f"{_DEFAULT_WEBHOOK_BASE}?key={self.webhook_key}"
        return ""
