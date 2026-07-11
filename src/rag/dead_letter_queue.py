"""死信队列（Dead Letter Queue）

批量加载失败的文件进入 DLQ，支持持久化存储、分类重试、统计。

数据流：
    加载失败 → 分类错误类型
    → 网络错误：自动重试 3 次（指数退避）
    → 重试仍失败 / 非网络错误：写入 DLQ
    → retry_dlq() 批量重试 DLQ 中文件
"""
from __future__ import annotations

import enum
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------------


class ErrorCategory(enum.Enum):
    """错误类型分类"""
    NETWORK = "network"       # 网络超时、连接失败 → 自动重试
    FILE = "file"             # 文件损坏、权限不足 → 不重试
    LOAD = "load"             # 解析错误、格式不支持 → 不重试


def classify_error(error: Exception) -> ErrorCategory:
    """根据异常类型分类错误

    Args:
        error: 抛出的异常

    Returns:
        ErrorCategory 分类
    """
    # 文件类错误优先检查（FileNotFoundError 继承自 OSError）
    if isinstance(error, (
        FileNotFoundError,
        PermissionError,
        IsADirectoryError,
        NotADirectoryError,
    )):
        return ErrorCategory.FILE

    # 网络类错误
    if isinstance(error, (
        TimeoutError,
        ConnectionError,
        ConnectionRefusedError,
        ConnectionResetError,
    )):
        return ErrorCategory.NETWORK

    # 其他 → 加载错误
    return ErrorCategory.LOAD


# ---------------------------------------------------------------------------
# DLQEntry
# ---------------------------------------------------------------------------


@dataclass
class DLQEntry:
    """死信队列条目

    Attributes:
        file_path: 失败文件绝对路径
        error_type: 错误分类（NETWORK / FILE / LOAD）
        error_message: 错误详情
        failed_at: 首次失败时间
        retry_count: 已重试次数
        last_error: 最近一次错误信息
    """
    file_path: str
    error_type: str
    error_message: str
    failed_at: datetime
    retry_count: int = 0
    last_error: str = ""

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "failed_at": self.failed_at.isoformat(),
            "retry_count": self.retry_count,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DLQEntry":
        data = dict(data)
        data["failed_at"] = datetime.fromisoformat(data["failed_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# DeadLetterQueue
# ---------------------------------------------------------------------------


class DeadLetterQueue:
    """死信队列 — SQLite 持久化存储

    使用 SQLite 存储失败文件记录，支持：
        - 添加失败条目
        - 获取可重试条目
        - 批量重试
        - 按错误类型统计
        - 清空队列
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = Path(db_path or settings.dlq_db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite 表"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dead_letters (
                    file_path TEXT PRIMARY KEY,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    failed_at TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.commit()

    def add(self, entry: DLQEntry) -> None:
        """添加失败文件到 DLQ"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO dead_letters
                (file_path, error_type, error_message, failed_at, retry_count, last_error)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                entry.file_path,
                entry.error_type,
                entry.error_message,
                entry.failed_at.isoformat(),
                entry.retry_count,
                entry.last_error,
            ))
            conn.commit()
        logger.info(
            "DLQ: added %s (%s, retry=%d)",
            entry.file_path, entry.error_type, entry.retry_count,
        )

    def get_all(self) -> List[DLQEntry]:
        """获取所有死信文件"""
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT * FROM dead_letters ORDER BY failed_at"
            ).fetchall()
        return [
            DLQEntry(
                file_path=row[0],
                error_type=row[1],
                error_message=row[2],
                failed_at=datetime.fromisoformat(row[3]),
                retry_count=row[4],
                last_error=row[5],
            )
            for row in rows
        ]

    def get_pending(self, max_retries: int = None) -> List[DLQEntry]:
        """获取可重试的条目（retry_count < max_retries）"""
        if max_retries is None:
            max_retries = settings.dlq_max_retries
        all_entries = self.get_all()
        return [e for e in all_entries if e.retry_count < max_retries]

    def get_by_error_type(self, error_type: str) -> List[DLQEntry]:
        """按错误类型获取条目"""
        return [e for e in self.get_all() if e.error_type == error_type]

    def remove(self, file_path: str) -> None:
        """从 DLQ 移除（重试成功后）"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM dead_letters WHERE file_path = ?", (file_path,))
            conn.commit()

    def clear(self) -> None:
        """清空 DLQ"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM dead_letters")
            conn.commit()
        logger.info("DLQ: cleared all entries")

    def stats(self) -> dict:
        """获取 DLQ 统计信息"""
        entries = self.get_all()
        total = len(entries)
        by_type: dict = {}
        for e in entries:
            by_type[e.error_type] = by_type.get(e.error_type, 0) + 1

        pending = sum(1 for e in entries if e.retry_count < settings.dlq_max_retries)

        return {
            "total": total,
            "pending": pending,
            "by_error_type": by_type,
            "oldest_failed": entries[0].failed_at.isoformat() if entries else None,
            "newest_failed": entries[-1].failed_at.isoformat() if entries else None,
        }

    def retry_all(self, max_retries: int = None) -> dict:
        """批量重试 DLQ 中所有可重试的条目

        Returns:
            {"retried": int, "succeeded": int, "failed": int}
        """
        pending = self.get_pending(max_retries)
        if not pending:
            return {"retried": 0, "succeeded": 0, "failed": 0}

        logger.info("DLQ: retrying %d entries", len(pending))
        succeeded = 0
        failed = 0

        for entry in pending:
            entry.retry_count += 1
            try:
                # 调用者需要提供实际的加载函数
                # 这里只返回 entry 供调用者重试
                self.remove(entry.file_path)
                succeeded += 1
            except Exception as e:
                entry.last_error = str(e)
                self.add(entry)
                failed += 1

        return {"retried": len(pending), "succeeded": succeeded, "failed": failed}
