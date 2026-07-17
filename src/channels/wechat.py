"""企业微信渠道适配器

支持两种接入方式：
1. 企业微信回调消息（应用消息回调）：receive_message 解析企业微信推送的 XML 回调
2. 企业微信群机器人 webhook：send_message 通过群机器人 webhook 发送消息

企业微信回调消息（明文 XML，简化示例）：
    <xml>
        <ToUserName><![CDATA[ww1234567890]]></ToUserName>
        <FromUserName><![CDATA[userid]]></FromUserName>
        <CreateTime>1348831860</CreateTime>
        <MsgType><![CDATA[text]]></MsgType>
        <Content><![CDATA[你好]]></Content>
        <MsgId>1234567890123456</MsgId>
        <AgentID>1000002</AgentID>
    </xml>

企业微信群机器人 webhook：
    POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=<KEY>
    Body: { "msgtype": "text", "text": { "content": "..." } }
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx

from src.channels.base import BaseChannel

logger = logging.getLogger(__name__)

_DEFAULT_WEBHOOK_BASE = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
_DEFAULT_TIMEOUT = 10.0


def _parse_wechat_xml(xml_str: str) -> dict:
    """解析企业微信回调 XML，返回字段字典

    企业微信推送的 XML 中各节点均使用 CDATA 包裹，ElementTree 会自动还原文本。
    """
    result: dict = {}
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        logger.warning("企业微信 XML 解析失败: %s", e)
        return result

    for child in root:
        result[child.tag] = child.text or ""
    return result


class WeChatWorkChannel(BaseChannel):
    """企业微信渠道适配器"""

    def __init__(
        self,
        webhook_key: Optional[str] = None,
        webhook_url: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        # 群机器人 webhook key（或完整 URL）
        self.webhook_key = webhook_key or os.environ.get("WECHAT_WORK_WEBHOOK_KEY", "")
        self.webhook_url = webhook_url or os.environ.get("WECHAT_WORK_WEBHOOK_URL", "")
        self.timeout = timeout

    @property
    def channel_name(self) -> str:
        return "wechat"

    async def receive_message(self, raw_data: dict) -> dict:
        """解析企业微信回调消息

        支持两种 raw_data 形式：
            1. {"xml": "<完整 XML 字串>"}  —— 来自原始 HTTP body
            2. {"xml": "<xml>...</xml>", ...}  —— 直接传入字段
            3. 直接传入已解析字段（如 {"FromUserName": ..., "Content": ...}）

        为兼容起见，若 raw_data 内含 "xml" 键，优先解析 XML。
        """
        msg_id = str(uuid.uuid4())
        sender_id = ""
        sender_name = ""
        content = ""
        content_type = "text"
        conversation_id = ""
        agent_id = ""
        metadata: dict = {}

        # 1) 尝试解析 XML 字符串
        xml_str = raw_data.get("xml") if isinstance(raw_data, dict) else None
        if xml_str and isinstance(xml_str, str) and xml_str.lstrip().startswith("<"):
            parsed = _parse_wechat_xml(xml_str)
            sender_id = parsed.get("FromUserName", "") or ""
            content = parsed.get("Content", "") or ""
            msg_id = parsed.get("MsgId", msg_id)
            msg_type = parsed.get("MsgType", "text") or "text"
            agent_id = parsed.get("AgentID", "") or ""
            conversation_id = parsed.get("FromUserName", "") or ""  # 单聊以 userid 为会话标识
            metadata = {
                "to_user_name": parsed.get("ToUserName", ""),
                "create_time": parsed.get("CreateTime", ""),
                "msg_type": msg_type,
                "agent_id": agent_id,
            }
            # 非 text 消息标记为 event，避免进入对话流程
            if msg_type != "text":
                content_type = "event"
        else:
            # 2) 直接传入字段
            sender_id = str(raw_data.get("FromUserName") or raw_data.get("sender_id") or "")
            sender_name = str(raw_data.get("sender_name") or "")
            content = str(raw_data.get("Content") or raw_data.get("content") or "")
            msg_id = str(raw_data.get("MsgId") or raw_data.get("message_id") or msg_id)
            agent_id = str(raw_data.get("AgentID") or "")
            conversation_id = str(raw_data.get("conversation_id") or sender_id)
            msg_type = str(raw_data.get("MsgType") or raw_data.get("content_type") or "text")
            metadata = {
                "msg_type": msg_type,
                "agent_id": agent_id,
                "to_user_name": raw_data.get("ToUserName", ""),
            }
            if msg_type != "text":
                content_type = "event"

        return {
            "message_id": msg_id,
            "channel": self.channel_name,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "content": content,
            "content_type": content_type,
            "conversation_id": conversation_id,
            "tenant_id": agent_id,  # 企业微信以 AgentID 区分应用，复用为 tenant
            "raw_payload": raw_data,
            "metadata": metadata,
        }

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
                msg_type: 消息类型（默认 text）
                mentioned_list: 需要 @ 的用户 ID 列表（默认 None）
                mentioned_mobile_list: 需要 @ 的手机号列表（默认 None）
        """
        # 解析 webhook URL
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
            # 其他类型回退为 text
            payload["msgtype"] = "text"
            payload["text"] = {"content": content}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(webhook_url, json=payload)
                resp.raise_for_status()
                body = resp.json()
                # 企业微信成功返回 errcode == 0
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
        # 1) target 本身是完整 URL
        if target and target.startswith("http"):
            return target
        # 2) target 是 key
        if target:
            return f"{_DEFAULT_WEBHOOK_BASE}?key={target}"
        # 3) 回退到构造时传入的 URL
        if self.webhook_url:
            return self.webhook_url
        # 4) 回退到构造时传入的 key
        if self.webhook_key:
            return f"{_DEFAULT_WEBHOOK_BASE}?key={self.webhook_key}"
        return ""
