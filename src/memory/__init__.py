"""Enterprise Agent 记忆管理系统

三层架构：
    MemoryManager   — 统一入口，协调短期/长期记忆
    ShortTermMemory — 会话级滑动窗口 + LLM 摘要（Redis 优先）
    LongTermMemory  — 用户级持久化记忆 + 用户画像（PG + Chroma 优先）
"""

from .short_term import ShortTermMemory
from .long_term import LongTermMemory, MemoryEntry
from .manager import MemoryManager

__all__ = [
    "ShortTermMemory",
    "LongTermMemory",
    "MemoryEntry",
    "MemoryManager",
]
