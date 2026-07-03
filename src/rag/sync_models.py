"""同步模型：变更类型、错误、结果

供 FileSyncManager 使用，描述同步过程中的各种状态。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from src.rag.sync_state import SyncStateEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 变更类型
# ---------------------------------------------------------------------------


class ChangeType(Enum):
    """文件变更类型"""
    NEW = "NEW"               # 新增文件
    MODIFIED = "MODIFIED"     # 已修改
    DELETED = "DELETED"       # 已删除
    UNCHANGED = "UNCHANGED"   # 未变更


# ---------------------------------------------------------------------------
# 文件变更
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileChange:
    """单个文件的变更描述"""

    file_path: str
    change_type: ChangeType
    old_entry: Optional[SyncStateEntry] = None       # 旧状态（NEW 时为 None）
    new_content_hash: Optional[str] = None           # 新内容哈希（DELETED 时为 None）

    @property
    def is_relevant(self) -> bool:
        """是否需要同步处理（新增、修改、删除）"""
        return self.change_type in (ChangeType.NEW, ChangeType.MODIFIED, ChangeType.DELETED)


# ---------------------------------------------------------------------------
# 同步错误
# ---------------------------------------------------------------------------


@dataclass
class SyncError:
    """同步过程中发生的错误"""

    file_path: str
    error_type: str           # LOAD_ERROR | CHUNK_ERROR | VECTOR_ERROR | HASH_ERROR
    message: str


# ---------------------------------------------------------------------------
# 同步结果
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    """同步操作的结果汇总"""

    files_scanned: int = 0
    files_new: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    files_unchanged: int = 0
    chunks_added: int = 0
    chunks_removed: int = 0
    errors: List[SyncError] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        """是否有错误"""
        return len(self.errors) == 0

    def __str__(self) -> str:
        parts = [
            f"SyncResult(scanned={self.files_scanned})",
            f"new={self.files_new}",
            f"modified={self.files_modified}",
            f"deleted={self.files_deleted}",
            f"unchanged={self.files_unchanged}",
            f"chunks_added={self.chunks_added}",
            f"chunks_removed={self.chunks_removed}",
            f"errors={len(self.errors)}",
            f"duration={self.duration_seconds:.2f}s",
        ]
        return f"{' '.join(parts)}"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def compute_content_hash(normalized_text: str) -> str:
    """计算归一化文本的 SHA-256 哈希

    用于增量同步时检测文件内容是否变更。
    对归一化文本而非原始字节求哈希，确保内容不变但格式微调不会触发重新处理。
    """
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
