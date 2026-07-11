"""消息归一化层 — 调度中枢的第一道门

职责：
    将来自不同渠道的消息统一为内部标准格式，消除渠道差异。

支持的渠道：
    - web_chat:       网页聊天（WebSocket / HTTP POST）
    - wechat_mp:      微信公众号/小程序
    - wechat_app:     微信 APP
    - phone_ivr:      电话 IVR（语音转文字后）
    - ticket_form:    工单表单
    - app_push:       APP 推送消息
    - email:          邮件

归一化后格式：
    {
        "channel": "web_chat",
        "user_id": "u123",
        "session_id": "s456",
        "tenant_id": "t789",
        "content": "用户原始消息",
        "content_type": "text",  # text / image / audio / form
        "metadata": {
            "user_agent": "...",
            "ip": "...",
            "custom_fields": {}
        },
        "timestamp": 1234567890.0,
        "priority": "normal"  # normal / high / critical
    }
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ChannelType(str, Enum):
    """渠道类型枚举"""
    WEB_CHAT = "web_chat"
    WECHAT_MP = "wechat_mp"
    WECHAT_APP = "wechat_app"
    PHONE_IVR = "phone_ivr"
    TICKET_FORM = "ticket_form"
    APP_PUSH = "app_push"
    EMAIL = "email"


@dataclass
class NormalizedMessage:
    """归一化后的标准消息格式"""
    channel: str
    user_id: str
    session_id: str
    tenant_id: str
    content: str
    content_type: str = "text"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    priority: str = "normal"
    raw_payload: Optional[Dict] = None


class MessageNormalizer:
    """消息归一化器

    将各渠道原始消息转换为标准格式，供调度中枢统一处理。
    """

    # 渠道到优先级的默认映射
    CHANNEL_PRIORITY_MAP = {
        ChannelType.PHONE_IVR.value: "high",       # 电话用户等待成本高
        ChannelType.WECHAT_MP.value: "normal",
        ChannelType.WECHAT_APP.value: "normal",
        ChannelType.WEB_CHAT.value: "normal",
        ChannelType.TICKET_FORM.value: "normal",
        ChannelType.APP_PUSH.value: "normal",
        ChannelType.EMAIL.value: "low",             # 邮件可异步处理
    }

    def normalize(
        self,
        raw_payload: Dict[str, Any],
        channel: str,
    ) -> NormalizedMessage:
        """将原始消息归一化为标准格式

        Args:
            raw_payload: 渠道原始消息载荷
            channel: 渠道类型

        Returns:
            NormalizedMessage 标准消息对象
        """
        # 1. 提取用户 ID
        user_id = self._extract_user_id(raw_payload, channel)

        # 2. 提取会话 ID
        session_id = raw_payload.get("session_id", "")
        if not session_id:
            session_id = self._generate_session_id(user_id, channel)

        # 3. 提取租户 ID
        tenant_id = raw_payload.get("tenant_id", "") or self._infer_tenant(user_id)

        # 4. 提取消息内容
        content, content_type = self._extract_content(raw_payload, channel)

        # 5. 提取元数据
        metadata = self._extract_metadata(raw_payload, channel)

        # 6. 确定优先级
        priority = self.CHANNEL_PRIORITY_MAP.get(channel, "normal")
        # 用户消息中如有紧急关键词，提升优先级
        if any(kw in content for kw in ["紧急", "马上", "投诉", "complaint", "refund"]):
            priority = "high"

        return NormalizedMessage(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
            tenant_id=tenant_id,
            content=content,
            content_type=content_type,
            metadata=metadata,
            priority=priority,
            raw_payload=raw_payload,
        )

    def _extract_user_id(self, payload: Dict, channel: str) -> str:
        """从各渠道提取用户 ID"""
        # 微信渠道：openid
        if channel in (ChannelType.WECHAT_MP.value, ChannelType.WECHAT_APP.value):
            return payload.get("openid", payload.get("unionid", "anonymous"))
        # 电话渠道：手机号
        if channel == ChannelType.PHONE_IVR.value:
            return payload.get("phone", "anonymous")
        # 工单渠道：form 中的 user_id
        if channel == ChannelType.TICKET_FORM.value:
            return payload.get("user_id", payload.get("customer_id", "anonymous"))
        # 邮件渠道：email 地址
        if channel == ChannelType.EMAIL.value:
            email = payload.get("from_email", "")
            if email:
                return f"email:{email}"
            return "anonymous"
        # Web/App 渠道
        return payload.get("user_id", payload.get("uid", "anonymous"))

    def _generate_session_id(self, user_id: str, channel: str) -> str:
        """为无 session_id 的消息生成会话 ID"""
        import uuid
        return f"{channel}:{user_id}:{uuid.uuid4().hex[:8]}"

    def _infer_tenant(self, user_id: str) -> str:
        """从用户 ID 推断租户（简化版，实际从 CRM/权限系统查询）"""
        # 如果 user_id 中包含 tenant 信息，提取出来
        match = re.search(r'tenant[_-]?(\w+)', user_id, re.IGNORECASE)
        if match:
            return match.group(1)
        return ""

    def _extract_content(self, payload: Dict, channel: str) -> tuple[str, str]:
        """从各渠道提取消息内容和类型"""
        # 微信：text / image / voice
        if channel in (ChannelType.WECHAT_MP.value, ChannelType.WECHAT_APP.value):
            msg_type = payload.get("msgtype", "text")
            content_map = {
                "text": payload.get("text", {}).get("content", ""),
                "image": payload.get("image", {}).get("pic_url", ""),
                "voice": payload.get("voice", {}).get("media_id", ""),
            }
            content = content_map.get(msg_type, "")
            content_type = msg_type if msg_type in ("text", "image", "voice") else "text"
            return content, content_type

        # 电话 IVR：ASR 转录文本
        if channel == ChannelType.PHONE_IVR.value:
            return payload.get("asr_text", payload.get("speech_text", "")), "audio_transcript"

        # 工单表单
        if channel == ChannelType.TICKET_FORM.value:
            subject = payload.get("subject", "")
            description = payload.get("description", "")
            content = f"[{subject}] {description}" if subject else description
            return content, "form"

        # 邮件
        if channel == ChannelType.EMAIL.value:
            subject = payload.get("subject", "")
            body = payload.get("body", "")
            content = f"[{subject}] {body}" if subject else body
            return content, "email"

        # 默认：web/app 渠道
        return payload.get("message", payload.get("content", "")), "text"

    def _extract_metadata(self, payload: Dict, channel: str) -> Dict[str, Any]:
        """从各渠道提取元数据"""
        metadata = {}

        # 通用字段
        metadata["raw_channel"] = channel
        metadata["received_at"] = time.time()

        # 渠道特有字段
        if channel in (ChannelType.WECHAT_MP.value, ChannelType.WECHAT_APP.value):
            metadata["openid"] = payload.get("openid", "")
            metadata["msg_type"] = payload.get("msgtype", "text")

        if channel == ChannelType.PHONE_IVR.value:
            metadata["phone"] = payload.get("phone", "")
            metadata["asr_confidence"] = payload.get("asr_confidence", 0.0)

        if channel == ChannelType.TICKET_FORM.value:
            metadata["ticket_id"] = payload.get("ticket_id", "")
            metadata["priority_field"] = payload.get("priority", "normal")

        if channel == ChannelType.EMAIL.value:
            metadata["from_email"] = payload.get("from_email", "")
            metadata["subject"] = payload.get("subject", "")

        # 附加 payload 中的其他字段
        for key in ("ip", "user_agent", "device", "location"):
            if key in payload:
                metadata[key] = payload[key]

        return metadata


# 全局单例
_normalizer: Optional[MessageNormalizer] = None


def get_message_normalizer() -> MessageNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = MessageNormalizer()
    return _normalizer
