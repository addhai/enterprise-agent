"""消息标准化器 — 将多渠道消息转换为统一格式

支持渠道: web, wechat, chatwoot, phone

标准化消息为 dict（与 src.channels.base.BaseChannel.receive_message 返回格式一致）：
    {
        "message_id": str,
        "channel": str,
        "sender_id": str,
        "sender_name": str,
        "content": str,
        "content_type": str,        # text / image / voice / event
        "conversation_id": str,
        "tenant_id": str,
        "raw_payload": dict,
        "metadata": dict,
    }
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class NormalizedMessage:
    """标准化消息格式 — 所有渠道统一转换为此结构（保留以兼容旧代码）"""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    channel: str = "web"            # web / wechat / chatwoot / phone
    user_id: str = "anonymous"
    tenant_id: str = ""
    session_id: str = ""
    content: str = ""               # 纯文本内容
    content_type: str = "text"      # text / image / voice / event
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# 渠道消息识别 + 标准化函数
# ---------------------------------------------------------------------------

def _detect_channel(raw: dict) -> str:
    """根据原始消息特征识别来源渠道

    判定优先级：
        1. 显式 channel 字段
        2. Chatwoot 特征（event + account + message）
        3. 企业微信特征（xml 字符串 或 FromUserName/MsgType）
        4. 默认 web
    """
    if not isinstance(raw, dict):
        return "web"

    # 1) 显式声明
    explicit = raw.get("channel")
    if explicit and isinstance(explicit, str):
        return explicit

    # 2) Chatwoot 特征
    if raw.get("event") in ("message_created", "conversation_created") or (
        isinstance(raw.get("message"), dict) and "conversation_id" in raw.get("message", {})
    ):
        return "chatwoot"

    # 3) 企业微信特征
    xml_str = raw.get("xml")
    if isinstance(xml_str, str) and xml_str.lstrip().startswith("<"):
        return "wechat"
    if raw.get("FromUserName") or raw.get("MsgType") or raw.get("AgentID"):
        return "wechat"

    return "web"


def _normalize_chatwoot(raw: dict) -> dict:
    """Chatwoot webhook 消息 → 标准化 dict

    复用 src.channels.chatwoot.ChatwootChannel 的解析逻辑，保持单一真相源。
    """
    from src.channels.chatwoot import ChatwootChannel

    # 同步函数中调用 async receive_message：手动执行一次
    channel = ChatwootChannel()
    import asyncio
    try:
        # 已在事件循环中 → 用 ensure_future 等待
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 已有循环运行时，使用 run_until_complete 会报错；这里 normalizer
            # 一般在同步上下文调用，直接用 asyncio.ensure_future + 同步等待
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                channel.receive_message(raw), loop,
            )
            return future.result(timeout=10)
        return loop.run_until_complete(channel.receive_message(raw))
    except RuntimeError:
        # 没有事件循环 → 创建新的
        return asyncio.run(channel.receive_message(raw))


def _normalize_wechat(raw: dict) -> dict:
    """企业微信回调消息 → 标准化 dict"""
    from src.channels.wechat import WeChatWorkChannel

    channel = WeChatWorkChannel()
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                channel.receive_message(raw), loop,
            )
            return future.result(timeout=10)
        return loop.run_until_complete(channel.receive_message(raw))
    except RuntimeError:
        return asyncio.run(channel.receive_message(raw))


def _normalize_web(raw: dict) -> dict:
    """Web 渠道消息（默认）→ 标准化 dict"""
    return {
        "message_id": str(raw.get("message_id") or raw.get("id") or uuid.uuid4()),
        "channel": "web",
        "sender_id": str(raw.get("sender_id") or raw.get("user_id") or "anonymous"),
        "sender_name": str(raw.get("sender_name") or raw.get("username") or ""),
        "content": str(raw.get("content") or raw.get("message") or raw.get("text") or ""),
        "content_type": str(raw.get("content_type") or "text"),
        "conversation_id": str(raw.get("conversation_id") or raw.get("session_id") or ""),
        "tenant_id": str(raw.get("tenant_id") or ""),
        "raw_payload": raw,
        "metadata": raw.get("metadata", {}),
    }


class MessageNormalizer:
    """消息标准化器工厂

    每个渠道注册一个 normalizer，将渠道原始消息转为标准化 dict。
    若未指定渠道，会自动识别消息来源。
    """

    def __init__(self):
        # channel -> callable(raw: dict) -> dict
        self._normalizers: Dict[str, Callable[[dict], dict]] = {}
        # 注册内置渠道
        self.register("chatwoot", _normalize_chatwoot)
        self.register("wechat", _normalize_wechat)
        self.register("web", _normalize_web)

    def register(self, channel: str, normalizer: Callable[[dict], dict]):
        """注册渠道标准化器"""
        self._normalizers[channel] = normalizer
        logger.debug("已注册渠道标准化器: %s", channel)

    def detect_channel(self, raw: dict) -> str:
        """识别消息所属渠道"""
        return _detect_channel(raw)

    def normalize(self, raw: dict, channel: Optional[str] = None) -> dict:
        """将原始消息标准化为统一 dict 格式

        Args:
            raw: 原始消息
            channel: 显式指定渠道；为 None 时自动识别

        Returns:
            标准化消息 dict
        """
        if not isinstance(raw, dict):
            raw = {"content": str(raw), "channel": "web"}

        target_channel = channel or self.detect_channel(raw)
        normalizer = self._normalizers.get(target_channel)

        if normalizer:
            try:
                return normalizer(raw)
            except Exception as e:
                logger.warning(
                    "渠道 %s 标准化失败，回退到 web: %s", target_channel, e,
                )

        # 回退：当作 web 渠道处理
        result = _normalize_web(raw)
        result["channel"] = target_channel or "web"
        return result


# ---- 全局单例 ----
_normalizer: Optional[MessageNormalizer] = None


def get_message_normalizer() -> MessageNormalizer:
    """获取全局 MessageNormalizer 实例"""
    global _normalizer
    if _normalizer is None:
        _normalizer = MessageNormalizer()
    return _normalizer
