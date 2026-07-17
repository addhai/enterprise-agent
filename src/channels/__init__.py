"""多渠道接入模块

提供统一的渠道适配器接口，支持 Chatwoot、企业微信等渠道的接入。
每个适配器继承 BaseChannel，实现 receive_message / send_message。
"""
from src.channels.base import BaseChannel
from src.channels.chatwoot import ChatwootChannel
from src.channels.wechat import WeChatWorkChannel

__all__ = ["BaseChannel", "ChatwootChannel", "WeChatWorkChannel"]
