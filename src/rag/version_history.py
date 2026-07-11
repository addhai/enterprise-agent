"""文档版本历史管理

为每个处理过的文档保留完整版本历史，支持：
    - 版本快照：记录每次处理的内容、元数据、chunk IDs
    - 版本对比：对比两个版本之间的差异
    - 版本回滚：回滚到指定版本
    - 双存储：JSON（默认）+ SQLite（可选）

数据流：
    文件加载 → 处理 → 生成快照 → 存储到版本历史
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class VersionDiff:
    """两个版本之间的差异"""
    field: str
    old_value: str
    new_value: str
    changed: bool = True

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "changed": self.changed,
        }


@dataclass
class VersionSnapshot:
    """单次处理的完整快照

    Attributes:
        snapshot_id: 唯一快照 ID（UUID）
        file_path: 源文件绝对路径
        version: 版本号（从 1 开始递增）
        content_hash: 内容 SHA-256 哈希
        content_preview: 内容前 200 字符（用于对比）
        metadata_snapshot: 处理后的完整元数据
        doc_ids: 生成的 chunk IDs
        processed_at: 处理时间
        processing_time_ms: 处理耗时（毫秒）
        rejected_reason: 被拦截的原因（如有）
        quality_status: 质量状态
    """
    snapshot_id: str = ""
    file_path: str = ""
    version: int = 0
    content_hash: str = ""
    content_preview: str = ""
    metadata_snapshot: dict = field(default_factory=dict)
    doc_ids: List[str] = field(default_factory=list)
    processed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    processing_time_ms: float = 0.0
    rejected_reason: Optional[str] = None
    quality_status: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["processed_at"] = self.processed_at.isoformat() if self.processed_at else datetime.now(timezone.utc).isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "VersionSnapshot":
        data = dict(data)
        data["processed_at"] = datetime.fromisoformat(data["processed_at"])
        return cls(**data)

    @classmethod
    def compare(cls, v1: "VersionSnapshot", v2: "VersionSnapshot") -> List[VersionDiff]:
        """对比两个版本的差异"""
        diffs: List[VersionDiff] = []

        # 内容对比
        if v1.content_hash != v2.content_hash:
            diffs.append(VersionDiff(
                field="content_hash",
                old_value=v1.content_hash[:16] + "...",
                new_value=v2.content_hash[:16] + "...",
            ))

        # 预览对比
        if v1.content_preview != v2.content_preview:
            diffs.append(VersionDiff(
                field="content_preview",
                old_value=v1.content_preview[:100],
                new_value=v2.content_preview[:100],
            ))

        # 元数据对比
        all_keys = set(v1.metadata_snapshot.keys()) | set(v2.metadata_snapshot.keys())
        for key in sorted(all_keys):
            old_val = str(v1.metadata_snapshot.get(key, "<missing>"))
            new_val = str(v2.metadata_snapshot.get(key, "<missing>"))
            if old_val != new_val:
                # 截断长值
                old_display = old_val[:200] if len(old_val) > 200 else old_val
                new_display = new_val[:200] if len(new_val) > 200 else new_val
                diffs.append(VersionDiff(field=key, old_value=old_display, new_value=new_display))

        # Chunk IDs 对比
        if set(v1.doc_ids) != set(v2.doc_ids):
            diffs.append(VersionDiff(
                field="doc_ids",
                old_value=f"{len(v1.doc_ids)} chunks",
                new_value=f"{len(v2.doc_ids)} chunks",
            ))

        # 质量状态对比
        if v1.quality_status != v2.quality_status:
            diffs.append(VersionDiff(
                field="quality_status",
                old_value=v1.quality_status or "N/A",
                new_value=v2.quality_status or "N/A",
            ))

        return diffs


# ---------------------------------------------------------------------------
# 版本历史管理器
# ---------------------------------------------------------------------------


class VersionHistory:
    """文档版本历史管理器

    存储方式：
        - JSON: 默认 {chroma_data}/.version_history.json
        - SQLite: 可选，通过 config 启用

    用法：
        history = VersionHistory()
        history.save_snapshot(snapshot)
        versions = history.get_versions("/path/to/file.md")
        diffs = VersionSnapshot.compare(versions[-2], versions[-1])
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.enabled = settings.version_history.enabled
        self.backend = settings.version_history.storage_backend
        self.max_versions = settings.version_history.max_versions_per_file
        self.store_preview = settings.version_history.store_content_preview
        self.store_full = settings.version_history.store_full_content

        if db_path:
            self.db_path = Path(db_path).resolve()
        else:
            persist_dir = Path(settings.chroma.persist_dir)
            self.db_path = persist_dir / ".version_history"

        self.db_path.mkdir(parents=True, exist_ok=True)

        if self.backend == "sqlite":
            self._db_file = self.db_path / "versions.db"
            self._init_sqlite()
        else:
            self._json_file = self.db_path / "versions.json"

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: VersionSnapshot) -> None:
        """保存版本快照"""
        if not self.enabled:
            return

        # 限制快照大小
        if not self.store_full and snapshot.content_preview:
            snapshot.content_preview = snapshot.content_preview[:200]

        if self.backend == "sqlite":
            self._save_sqlite(snapshot)
        else:
            self._save_json(snapshot)

        logger.debug(
            "VersionHistory: saved v%d for %s (%d chunks)",
            snapshot.version, Path(snapshot.file_path).name, len(snapshot.doc_ids),
        )

    def get_versions(self, file_path: str) -> List[VersionSnapshot]:
        """获取某文件的所有版本（按 version 升序）"""
        if self.backend == "sqlite":
            return self._get_versions_sqlite(file_path)
        else:
            return self._get_versions_json(file_path)

    def get_latest(self, file_path: str) -> Optional[VersionSnapshot]:
        """获取某文件的最新版本"""
        versions = self.get_versions(file_path)
        return versions[-1] if versions else None

    def get_version(self, file_path: str, version: int) -> Optional[VersionSnapshot]:
        """获取指定版本"""
        versions = self.get_versions(file_path)
        for v in versions:
            if v.version == version:
                return v
        return None

    def compare(self, file_path: str, v1: int, v2: int) -> List[VersionDiff]:
        """对比两个版本"""
        snap1 = self.get_version(file_path, v1)
        snap2 = self.get_version(file_path, v2)
        if snap1 and snap2:
            return VersionSnapshot.compare(snap1, snap2)
        return []

    def list_changes(self, file_path: str, since_version: int = 1) -> List[VersionDiff]:
        """列出从指定版本以来的所有变更"""
        versions = self.get_versions(file_path)
        diffs: List[VersionDiff] = []
        for i in range(len(versions) - 1):
            if versions[i].version >= since_version:
                diffs.extend(VersionSnapshot.compare(versions[i], versions[i + 1]))
        return diffs

    # ------------------------------------------------------------------
    # JSON 存储
    # ------------------------------------------------------------------

    def _save_json(self, snapshot: VersionSnapshot) -> None:
        """保存到 JSON 文件"""
        data: Dict[str, List[dict]] = {}
        if self._json_file.exists():
            try:
                with open(self._json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = {}

        path = snapshot.file_path
        if path not in data:
            data[path] = []

        entry = snapshot.to_dict()
        data[path].append(entry)

        # 限制版本数
        if len(data[path]) > self.max_versions:
            data[path] = data[path][-self.max_versions:]

        with open(self._json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _get_versions_json(self, file_path: str) -> List[VersionSnapshot]:
        """从 JSON 加载版本"""
        if not self._json_file.exists():
            return []

        try:
            with open(self._json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        entries = data.get(file_path, [])
        return [VersionSnapshot.from_dict(e) for e in sorted(entries, key=lambda x: x["version"])]

    # ------------------------------------------------------------------
    # SQLite 存储
    # ------------------------------------------------------------------

    def _init_sqlite(self) -> None:
        """初始化 SQLite 表"""
        with sqlite3.connect(str(self._db_file)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS version_snapshots (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content_hash TEXT,
                    content_preview TEXT,
                    metadata_snapshot TEXT,
                    doc_ids TEXT,
                    processed_at TEXT,
                    processing_time_ms REAL,
                    rejected_reason TEXT,
                    quality_status TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_file_path ON version_snapshots(file_path)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_file_version ON version_snapshots(file_path, version)")
            conn.commit()

    def _save_sqlite(self, snapshot: VersionSnapshot) -> None:
        """保存到 SQLite"""
        with sqlite3.connect(str(self._db_file)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO version_snapshots
                (id, file_path, version, content_hash, content_preview,
                 metadata_snapshot, doc_ids, processed_at, processing_time_ms,
                 rejected_reason, quality_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.snapshot_id,
                snapshot.file_path,
                snapshot.version,
                snapshot.content_hash,
                snapshot.content_preview,
                json.dumps(snapshot.metadata_snapshot, ensure_ascii=False),
                json.dumps(snapshot.doc_ids),
                snapshot.processed_at.isoformat(),
                snapshot.processing_time_ms,
                snapshot.rejected_reason,
                snapshot.quality_status,
            ))
            conn.commit()

    def _get_versions_sqlite(self, file_path: str) -> List[VersionSnapshot]:
        """从 SQLite 加载版本"""
        with sqlite3.connect(str(self._db_file)) as conn:
            rows = conn.execute(
                "SELECT * FROM version_snapshots WHERE file_path = ? ORDER BY version",
                (file_path,),
            ).fetchall()

        results = []
        for row in rows:
            data = {
                "snapshot_id": row[0], "file_path": row[1], "version": row[2],
                "content_hash": row[3], "content_preview": row[4],
                "metadata_snapshot": json.loads(row[5]) if row[5] else {},
                "doc_ids": json.loads(row[6]) if row[6] else [],
                "processed_at": row[7], "processing_time_ms": row[8],
                "rejected_reason": row[9], "quality_status": row[10],
            }
            results.append(VersionSnapshot.from_dict(data))
        return results
