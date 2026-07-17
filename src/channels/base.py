"""渠道适配器基类 — 定义统一的接收/发送消息接口

所有渠道适配器（Chatwoot、企业微信、电话等）都继承 BaseChannel，
实现 receive_message 与 send_message 方法。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseChannel(ABC):
    """渠道适配器基类"""

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """渠道标识，如 chatwoot / wechat / phone"""
        ...

    @abstractmethod
    async def receive_message(self, raw_data: dict) -> dict:
        """接收原始消息，返回标准化消息

        标准化消息字段（与 dispatch.normalizer 保持一致）：
            - message_id: 消息唯一 ID
            - channel: 渠道名
            - sender_id: 发送者 ID
            - sender_name: 发送者名称（可选）
            - content: 纯文本内容
            - content_type: text / image / voice / event
            - conversation_id: 会话/对话 ID（用于上下文关联）
            - tenant_id: 租户 ID（可选）
            - raw_payload: 原始 payload
            - metadata: 额外元数据
        """
        ...

    @abstractmethod
    async def send_message(self, target: str, content: str, **kwargs) -> bool:
        """发送消息到渠道

        Args:
            target: 发送目标标识（如 conversation_id、群机器人 key、用户 ID）
            content: 文本内容
            **kwargs: 渠道特定参数（如 is_private、message_type）

        Returns:
            是否发送成功
        """
        ...
