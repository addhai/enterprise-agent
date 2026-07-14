"""消息标准化器 — 将多渠道消息转换为统一格式

支持渠道: web, wechat, phone, chatwoot
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class NormalizedMessage:
    """标准化消息格式 — 所有渠道统一转换为此结构"""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    channel: str = "web"            # web / wechat / phone / chatwoot
    user_id: str = "anonymous"
    tenant_id: str = ""
    session_id: str = ""
    content: str = ""               # 纯文本内容
    content_type: str = "text"      # text / image / voice / event
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class MessageNormalizer:
    """消息标准化器工厂

    每个渠道注册一个 normalizer，将渠道原始消息转为 NormalizedMessage。
    """

    def __init__(self):
        self._normalizers: Dict[str, callable] = {}

    def register(self, channel: str, normalizer: callable):
        """注册渠道标准化器"""
        self._normalizers[channel] = normalizer
        logger.debug("Registered normalizer for channel: %s", channel)

    def normalize(self, channel: str, raw: dict) -> NormalizedMessage:
        """将渠道原始消息标准化"""
        normalizer = self._normalizers.get(channel)
        if normalizer:
            return normalizer(raw)

        # 默认：直接使用原始消息文本
        return NormalizedMessage(
            channel=channel,
            content=raw.get("content", raw.get("message", str(raw))),
            raw_payload=raw,
        )


# ---- 全局单例 ----
_normalizer: Optional[MessageNormalizer] = None


def get_message_normalizer() -> MessageNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = MessageNormalizer()
    return _normalizer
