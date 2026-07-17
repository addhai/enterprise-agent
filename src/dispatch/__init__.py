"""分发模块 — 多渠道消息标准化与路由仲裁

对外暴露：
    - MessageNormalizer: 消息标准化器
    - Arbitrator: 多渠道消息仲裁器
"""
from src.dispatch.normalizer import (
    MessageNormalizer,
    NormalizedMessage,
    get_message_normalizer,
)
from src.dispatch.arbitrator import Arbitrator, get_arbitrator

__all__ = [
    "MessageNormalizer",
    "NormalizedMessage",
    "get_message_normalizer",
    "Arbitrator",
    "get_arbitrator",
]
