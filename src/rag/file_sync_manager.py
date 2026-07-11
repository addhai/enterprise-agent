"""文件同步管理器

增量同步编排器，协调 DocumentLoader → HybridChunker → VectorStoreManager
完成文件的加载、切块、入库和删除。

数据流（增量模式）：
    扫描目录 → 对比同步表 → 分类变更
    → DELETED: 从向量库删除 chunk IDs
    → NEW/MODIFIED: load → chunk(source_file) → add_documents → 更新同步表
    → 持久化同步状态

数据流（全量模式）：
    清空向量库 → 全量加载 → 重建同步表
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from src.rag.chunker import HybridChunker
from src.rag.loader import DocumentLoader
from src.rag.sync_models import (
    ChangeType,
    FileChange,
    SyncError,
    SyncResult,
    compute_content_hash,
)
from src.rag.sync_state import (
    SyncStateEntry,
    SyncStateStore,
    SyncStatus,
    SyncTable,
)
from src.rag.vector_store import VectorStoreManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FileSyncManager
# ---------------------------------------------------------------------------


class FileSyncManager:
    """文件同步管理器

    负责增量同步文件系统与向量库。

    Usage::

        loader = DocumentLoader()
        chunker = HybridChunker()
        store = VectorStoreManager(persist_directory="./chroma_data")
        manager = FileSyncManager(
            vector_store=store,
            chunker=chunker,
            loader=loader,
            sync_dir=Path("./chroma_data/.sync_state.json"),
        )

        # 增量同步
        result = manager.sync("/path/to/docs", mode="incremental")
        print(result)

        # 全量同步
        result = manager.sync("/path/to/docs", mode="full")
    """

    def __init__(
        self,
        vector_store: VectorStoreManager,
        chunker: HybridChunker,
        loader: DocumentLoader,
        sync_dir: Optional[str] = None,
    ) -> None:
        self.vector_store = vector_store
        self.chunker = chunker
        self.loader = loader

        # 同步状态存储路径
        if sync_dir:
            self._state_store = SyncStateStore(sync_dir)
        else:
            # 默认放在 Chroma 数据目录下
            persist_dir = vector_store.persist_directory or "./chroma_data"
            self._state_store = SyncStateStore(
                str(Path(persist_dir) / ".sync_state.json")
            )

    # --------------------------------------------------------------
    # 公共 API
    # --------------------------------------------------------------

    def sync(
        self,
        directory: str,
        mode: Literal["full", "incremental"] = "incremental",
    ) -> SyncResult:
        """执行同步

        Args:
            directory: 要同步的目录路径
            mode: "full" 全量同步 / "incremental" 增量同步

        Returns:
            SyncResult 同步结果汇总
        """
        start = time.time()
        directory = str(Path(directory).resolve())

        if mode == "full":
            return self._sync_full(directory, start)
        else:
            return self._sync_incremental(directory, start)

    def scan(self, directory: str) -> Dict[str, FileChange]:
        """扫描目录，对比同步表，返回变更分类

        不调用加载器或向量库，只做变更检测。
        可用于预览即将发生哪些变更。

        Returns:
            {file_path: FileChange}
        """
        directory = str(Path(directory).resolve())
        table = self._load_or_empty_table()
        changes = self._classify_files(directory, table)
        logger.info(
            "Scan %s: %d new, %d modified, %d deleted, %d unchanged",
            directory,
            sum(1 for c in changes.values() if c.change_type == ChangeType.NEW),
            sum(1 for c in changes.values() if c.change_type == ChangeType.MODIFIED),
            sum(1 for c in changes.values() if c.change_type == ChangeType.DELETED),
            sum(1 for c in changes.values() if c.change_type == ChangeType.UNCHANGED),
        )
        return changes

    # --------------------------------------------------------------
    # 全量同步
    # --------------------------------------------------------------

    def _sync_full(self, directory: str, start: float) -> SyncResult:
        """全量同步：清空向量库，重新加载所有文件"""
        logger.info("Full sync: %s", directory)

        table = self._load_or_empty_table()
        errors: List[SyncError] = []

        # 1. 删除向量库中所有旧文档
        chunks_removed = self._delete_all_vector_docs(table)
        table.clear()

        # 2. 扫描 + 加载所有文件
        changes = self._collect_all_files(directory)
        result = self._process_changes(directory, changes, table, errors)

        # 3. 持久化
        self._state_store.save(table, directory)

        return self._build_result(changes, table, errors, start, chunks_removed=chunks_removed)

    # --------------------------------------------------------------
    # 增量同步
    # --------------------------------------------------------------

    def _sync_incremental(self, directory: str, start: float) -> SyncResult:
        """增量同步：只处理新增/修改/删除的文件"""
        logger.info("Incremental sync: %s", directory)

        table = self._load_or_empty_table()
        errors: List[SyncError] = []

        # 1. 扫描目录，对比同步表
        changes = self._classify_files(directory, table)

        # 2. 处理变更（删除 → 新增/修改）
        chunks_removed = self._handle_deletes(changes, table, errors)
        result = self._process_changes(directory, changes, table, errors)

        # 3. 持久化
        self._state_store.save(table, directory)

        return self._build_result(changes, table, errors, start, chunks_removed=chunks_removed)

    # --------------------------------------------------------------
    # 内部方法：变更检测
    # --------------------------------------------------------------

    def _load_or_empty_table(self) -> SyncTable:
        """加载同步表，不存在则返回空表"""
        try:
            return self._state_store.load()
        except Exception as e:
            logger.warning("Failed to load sync state, starting fresh: %s", e)
            return {}

    def _classify_files(
        self, directory: str, table: SyncTable
    ) -> Dict[str, FileChange]:
        """扫描目录，对比同步表，分类每个文件的变更

        遍历磁盘上的所有文件，计算 hash + mtime，与同步表对比：
            - 不在表中 → NEW
            - mtime 或 hash 不同 → MODIFIED
            - 在表中但磁盘上没有 → DELETED（由 _handle_deletes 处理）
        """
        source = self._get_source_for_dir(directory)
        file_infos = source.list_files()

        changes: Dict[str, FileChange] = {}
        for info in file_infos:
            abs_path = str(info.path.resolve())
            raw_text = source.read_file(info)
            if isinstance(raw_text, bytes):
                raw_text = raw_text.decode(info.metadata.get("encoding", "utf-8"), errors="replace")

            content_hash = compute_content_hash(raw_text)
            mtime = info.path.stat().st_mtime

            old_entry = table.get(abs_path)

            if old_entry is None:
                changes[abs_path] = FileChange(
                    file_path=abs_path,
                    change_type=ChangeType.NEW,
                    new_content_hash=content_hash,
                )
            elif old_entry.content_hash != content_hash or old_entry.mtime != mtime:
                changes[abs_path] = FileChange(
                    file_path=abs_path,
                    change_type=ChangeType.MODIFIED,
                    old_entry=old_entry,
                    new_content_hash=content_hash,
                )
            else:
                changes[abs_path] = FileChange(
                    file_path=abs_path,
                    change_type=ChangeType.UNCHANGED,
                    old_entry=old_entry,
                )

        # 检测删除的文件（在表中但不在磁盘上）
        disk_paths = {str(info.path.resolve()) for info in file_infos}
        for stored_path, entry in table.items():
            if stored_path not in disk_paths:
                changes[stored_path] = FileChange(
                    file_path=stored_path,
                    change_type=ChangeType.DELETED,
                    old_entry=entry,
                )

        return changes

    def _collect_all_files(self, directory: str) -> Dict[str, FileChange]:
        """全量模式下收集所有文件（全部标记为 NEW）"""
        source = self._get_source_for_dir(directory)
        file_infos = source.list_files()

        changes: Dict[str, FileChange] = {}
        for info in file_infos:
            abs_path = str(info.path.resolve())
            raw_text = source.read_file(info)
            if isinstance(raw_text, bytes):
                raw_text = raw_text.decode(info.metadata.get("encoding", "utf-8"), errors="replace")
            content_hash = compute_content_hash(raw_text)
            changes[abs_path] = FileChange(
                file_path=abs_path,
                change_type=ChangeType.NEW,
                new_content_hash=content_hash,
            )
        return changes

    # --------------------------------------------------------------
    # 内部方法：变更处理
    # --------------------------------------------------------------

    def _handle_deletes(
        self,
        changes: Dict[str, FileChange],
        table: SyncTable,
        errors: List[SyncError],
    ) -> int:
        """处理删除的文件：从向量库删除其所有 chunk IDs"""
        total_removed = 0

        for path, change in changes.items():
            if change.change_type != ChangeType.DELETED or change.old_entry is None:
                continue

            ids_to_delete = (
                change.old_entry.standard_chunk_ids +
                change.old_entry.sentence_chunk_ids
            )
            if ids_to_delete:
                removed = self.vector_store.delete_by_ids(ids_to_delete)
                total_removed += removed
                logger.info("Deleted %d chunks for removed file: %s", removed, path)
                del table[path]

        return total_removed

    def _process_changes(
        self,
        directory: str,
        changes: Dict[str, FileChange],
        table: SyncTable,
        errors: List[SyncError],
    ) -> None:
        """处理新增/修改的文件：加载 → 切块 → 入库"""
        source = self._get_source_for_dir(directory)

        for path, change in changes.items():
            if not change.is_relevant:
                continue
            # DELETED 文件已由 _handle_deletes 处理，这里跳过
            if change.change_type == ChangeType.DELETED:
                continue

            try:
                # 加载文件
                docs = self.loader.load_file(path)
                if not docs:
                    logger.warning("No documents produced for %s", path)
                    errors.append(SyncError(
                        file_path=path,
                        error_type="LOAD_ERROR",
                        message="No documents produced by loader",
                    ))
                    # 保留旧状态或标记失败
                    old = changes.get(path, FileChange(path, ChangeType.UNCHANGED)).old_entry
                    if old:
                        table[path] = SyncStateEntry(
                            file_path=path,
                            content_hash=change.new_content_hash or "",
                            mtime=old.mtime,
                            status=SyncStatus.FAILED,
                            standard_chunk_ids=[],
                            sentence_chunk_ids=[],
                            processed_at=datetime.now(timezone.utc),
                            error_message="No documents produced by loader",
                        )
                    continue

                # 生成确定性 doc_id 前缀: doc:{path}:{content_hash}
                from src.rag.loader import DocumentLoader
                # 用空内容占位，实际 content_hash 来自 change.new_content_hash
                # 生成格式: doc:{path}:{content_hash}
                doc_id_prefix = f"doc:{path}:{change.new_content_hash or 'none'}"

                # 切块（带确定性 ID）
                standard_chunks = self.chunker.split_standard(
                    docs, doc_id_prefix=doc_id_prefix
                )
                sentence_chunks = self.chunker.split_sentences(
                    docs, doc_id_prefix=doc_id_prefix
                )

                # 入库
                std_ids = self.vector_store.add_documents(standard_chunks)
                sent_ids = self.vector_store.add_documents(sentence_chunks)

                # 更新同步表
                table[path] = SyncStateEntry(
                    file_path=path,
                    content_hash=change.new_content_hash or "",
                    mtime=Path(path).stat().st_mtime,
                    status=SyncStatus.PROCESSED,
                    standard_chunk_ids=std_ids,
                    sentence_chunk_ids=sent_ids,
                    processed_at=datetime.now(timezone.utc),
                )

                logger.info(
                    "Synced %s: %d standard + %d sentence chunks",
                    path, len(std_ids), len(sent_ids),
                )

            except Exception as e:
                logger.error("Failed to sync %s: %s", path, e)
                errors.append(SyncError(
                    file_path=path,
                    error_type="LOAD_ERROR",
                    message=str(e),
                ))
                # 保留旧状态或标记失败
                old = changes.get(path, FileChange(path, ChangeType.UNCHANGED)).old_entry
                if old:
                    table[path] = SyncStateEntry(
                        file_path=path,
                        content_hash=old.content_hash,
                        mtime=old.mtime,
                        status=SyncStatus.FAILED,
                        standard_chunk_ids=old.standard_chunk_ids,
                        sentence_chunk_ids=old.sentence_chunk_ids,
                        processed_at=old.processed_at,
                        error_message=str(e),
                    )

    # --------------------------------------------------------------
    # 内部方法：向量库清理
    # --------------------------------------------------------------

    def _delete_all_vector_docs(self, table: SyncTable) -> int:
        """删除同步表中所有文件的 chunk IDs"""
        total = 0
        for entry in table.values():
            ids = entry.standard_chunk_ids + entry.sentence_chunk_ids
            if ids:
                total += self.vector_store.delete_by_ids(ids)
        return total

    # --------------------------------------------------------------
    # 内部方法：结果构建
    # --------------------------------------------------------------

    def _build_result(
        self,
        changes: Dict[str, FileChange],
        table: SyncTable,
        errors: List[SyncError],
        start: float,
        chunks_removed: int = 0,
    ) -> SyncResult:
        """构建 SyncResult，基于最终 table 统计 chunk 数"""
        chunks_added = 0
        for path, change in changes.items():
            if not change.is_relevant:
                continue
            entry = table.get(path)
            if entry and entry.standard_chunk_ids:
                std_count = len(entry.standard_chunk_ids)
                sent_count = len(entry.sentence_chunk_ids) or 0
                chunks_added += std_count + sent_count

        return SyncResult(
            files_scanned=len(changes),
            files_new=sum(1 for c in changes.values() if c.change_type == ChangeType.NEW),
            files_modified=sum(1 for c in changes.values() if c.change_type == ChangeType.MODIFIED),
            files_deleted=sum(1 for c in changes.values() if c.change_type == ChangeType.DELETED),
            files_unchanged=sum(1 for c in changes.values() if c.change_type == ChangeType.UNCHANGED),
            chunks_added=chunks_added,
            chunks_removed=chunks_removed,
            errors=errors,
            duration_seconds=time.time() - start,
        )

    # --------------------------------------------------------------
    # 辅助方法
    # --------------------------------------------------------------

    def _get_source_for_dir(self, directory: str):
        """获取指定目录的数据源"""
        from src.rag.data_sources import LocalDirectoryDataSource
        return LocalDirectoryDataSource(directory)

    def _make_file_info(self, abs_path: str, directory: str):
        """从绝对路径构造 FileInfo"""
        from src.rag.data_sources import FileInfo, LocalDirectoryDataSource
        p = Path(abs_path)
        return FileInfo(
            path=p,
            name=p.name,
            ext=p.suffix.lower(),
            size=p.stat().st_size,
        )
