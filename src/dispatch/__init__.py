"""调度中枢模块"""
from src.dispatch.normalizer import (
    MessageNormalizer,
    NormalizedMessage,
    ChannelType,
    get_message_normalizer,
)

__all__ = [
    "MessageNormalizer",
    "NormalizedMessage",
    "ChannelType",
    "get_message_normalizer",
]
