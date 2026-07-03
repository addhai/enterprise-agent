"""同步状态数据结构

维护文件系统的快照：每个文件的路径、修改时间、内容哈希、
处理状态、以及对应的向量库文档 ID。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 状态枚举
# ---------------------------------------------------------------------------


class SyncStatus(Enum):
    """文件同步状态"""
    PROCESSED = "PROCESSED"     # 成功处理
    FAILED = "FAILED"           # 处理失败（保留以便重试）
    SKIPPED = "SKIPPED"         # 跳过（未变更）


# ---------------------------------------------------------------------------
# 同步状态条目
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SyncStateEntry:
    """单个文件的同步状态记录

    Attributes:
        file_path: 规范化绝对路径（用作同步表的 key）
        content_hash: 归一化文本的 SHA-256 哈希
        mtime: 文件最后修改时间戳
        status: 处理状态
        standard_chunk_ids: 标准粒度 chunk 的 Chroma ID 列表
        sentence_chunk_ids: 句子粒度 chunk 的 Chroma ID 列表
        processed_at: 上次成功处理的时间（UTC）
        error_message: 失败时的错误信息
    """

    file_path: str
    content_hash: str
    mtime: float
    status: SyncStatus
    standard_chunk_ids: List[str]
    sentence_chunk_ids: List[str]
    processed_at: datetime
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        """序列化为字典（用于 JSON 存储）"""
        d = asdict(self)
        d["status"] = self.status.value
        d["processed_at"] = self.processed_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SyncStateEntry":
        """从字典反序列化"""
        data = dict(data)
        data["status"] = SyncStatus(data["status"])
        data["processed_at"] = datetime.fromisoformat(data["processed_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# 同步表管理
# ---------------------------------------------------------------------------

SyncTable = Dict[str, SyncStateEntry]  # key = 规范化绝对路径


class SyncStateStore:
    """同步状态持久化存储

    使用 JSON 文件存储，路径默认为 Chroma 数据目录下的 .sync_state.json。
    未来可迁移到 SQLite。

    Usage::

        store = SyncStateStore(sync_file="/path/to/.sync_state.json")
        table = store.load()          # 加载
        table["/abs/path/file.md"] = entry
        store.save(table)             # 持久化
    """

    SCHEMA_VERSION = 1

    def __init__(self, sync_file: str) -> None:
        self.sync_file = Path(sync_file).resolve()

    def load(self) -> SyncTable:
        """加载同步状态表

        文件不存在或格式错误时返回空表。
        """
        if not self.sync_file.exists():
            logger.debug("Sync state file not found: %s", self.sync_file)
            return {}

        try:
            with open(self.sync_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read sync state: %s", e)
            return {}

        # 版本检查
        version = data.get("version", 0)
        if version != self.SCHEMA_VERSION:
            logger.warning(
                "Sync state version mismatch: expected %d, got %d. Resetting.",
                self.SCHEMA_VERSION, version,
            )
            return {}

        files: SyncTable = {}
        for path, entry_data in data.get("files", {}).items():
            try:
                files[path] = SyncStateEntry.from_dict(entry_data)
            except Exception as e:
                logger.warning("Failed to parse entry for %s: %s", path, e)

        logger.info(
            "Loaded sync state: %d files (root=%s, last_sync=%s)",
            len(files),
            data.get("sync_root", "unknown"),
            data.get("last_sync_at", "never"),
        )
        return files

    def save(self, table: SyncTable, sync_root: str) -> None:
        """持久化同步状态表"""
        # 确保父目录存在
        self.sync_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": self.SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_sync_at": datetime.now(timezone.utc).isoformat(),
            "sync_root": sync_root,
            "files": {path: entry.to_dict() for path, entry in table.items()},
        }

        try:
            with open(self.sync_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(
                "Saved sync state: %d files to %s", len(table), self.sync_file
            )
        except OSError as e:
            logger.error("Failed to save sync state: %s", e)
            raise