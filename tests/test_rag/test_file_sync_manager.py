"""FileSyncManager 增量同步契约单测（离线、不触网、不起真实 Embedding）。

覆盖 2026-11 P0 第 6 项修复的三个缺陷：
    1. 句子块必须写独立 sentence_store，不能再灌进标准 store
    2. MODIFIED 必须先按同步表删除旧 chunk 再重建
    3. DELETED / 全量清理必须同时作用于两个集合
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from langchain_core.documents import Document
from src.rag.file_sync_manager import FileSyncManager
from src.rag.sync_models import ChangeType
from src.rag.sync_state import SyncStateEntry, SyncStateStore, SyncStatus


class FakeVectorStore:
    """记录 add/delete 调用的内存向量库假件。"""

    def __init__(self, name: str):
        self.name = name
        self.added: list[Document] = []
        self.deleted_ids: list[str] = []

    def add_documents(self, documents):
        self.added.extend(documents)
        # 模拟 Chroma 返回生成的 ID 列表
        ids = [
            f"{self.name}-{len(self.added) - len(documents) + i}"
            for i in range(len(documents))
        ]
        for doc, doc_id in zip(documents, ids, strict=False):
            doc.id = doc_id
        return ids

    def delete_by_ids(self, ids):
        self.deleted_ids.extend(ids)
        return len(ids)


class FakeChunker:
    def split_standard(self, docs, source_file=None):
        chunks = []
        for i, d in enumerate(docs):
            c = Document(f"[std] {d.page_content}", metadata=dict(d.metadata))
            c.id = f"file:{source_file}:{i}"
            chunks.append(c)
        return chunks

    def split_sentences(self, docs, source_file=None):
        chunks = []
        for i, d in enumerate(docs):
            c = Document(f"[sent] {d.page_content}", metadata=dict(d.metadata))
            c.id = f"file:{source_file}:sentence:{i}"
            chunks.append(c)
        return chunks


class FakeLoader:
    def load_file(self, path):
        return [
            Document(
                Path(path).read_text(encoding="utf-8"),
                metadata={"source": path},
            )
        ]


@pytest.fixture
def stores():
    return FakeVectorStore("std"), FakeVectorStore("sent")


@pytest.fixture
def manager(stores, tmp_path):
    std_store, sent_store = stores
    return FileSyncManager(
        vector_store=std_store,
        chunker=FakeChunker(),
        loader=FakeLoader(),
        sync_dir=str(tmp_path / ".sync_state.json"),
        sentence_store=sent_store,
    )


@pytest.fixture
def docs_dir(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "manual.md").write_text(
        "# 手册\n\n这是第一段足够长的设备操作说明内容。",
        encoding="utf-8",
    )
    return str(d)


def _make_old_entry(path: str, std_ids, sent_ids) -> SyncStateEntry:
    return SyncStateEntry(
        file_path=path,
        content_hash="old-hash",
        mtime=0.0,
        status=SyncStatus.PROCESSED,
        standard_chunk_ids=list(std_ids),
        sentence_chunk_ids=list(sent_ids),
        processed_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# NEW：双集合分别写入
# ---------------------------------------------------------------------------


def test_new_file_writes_dual_collections(manager, stores, docs_dir):
    result = manager.sync(docs_dir, mode="incremental")

    std_store, sent_store = stores
    assert result.files_new == 1
    assert std_store.added, "标准块必须写入标准集合"
    assert sent_store.added, "句子块必须写入句子集合"
    # 关键回归断言：句子块不得出现在标准集合里
    assert all("[sent]" not in d.page_content for d in std_store.added)
    assert all("[sent]" in d.page_content for d in sent_store.added)
    assert std_store.deleted_ids == []


def test_sync_table_records_both_id_lists(manager, docs_dir, tmp_path):
    manager.sync(docs_dir, mode="incremental")

    table = SyncStateStore(str(tmp_path / ".sync_state.json")).load()
    entry = next(iter(table.values()))
    assert entry.status == SyncStatus.PROCESSED
    assert entry.standard_chunk_ids, "标准 chunk ID 必须入同步表"
    assert entry.sentence_chunk_ids, "句子 chunk ID 必须入同步表"


# ---------------------------------------------------------------------------
# MODIFIED：先删后建
# ---------------------------------------------------------------------------


def test_modified_purges_old_chunks_before_readd(stores, tmp_path):
    std_store, sent_store = stores
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    fpath = docs_dir / "manual.md"
    fpath.write_text("初始版本的足够长说明内容用于首次同步。", encoding="utf-8")
    sync_file = str(tmp_path / ".sync_state.json")

    manager = FileSyncManager(
        std_store,
        FakeChunker(),
        FakeLoader(),
        sync_dir=sync_file,
        sentence_store=sent_store,
    )
    manager.sync(str(docs_dir), mode="incremental")
    first_std_ids = list(std_store.added and [d.id for d in std_store.added])
    first_sent_ids = [d.id for d in sent_store.added]
    assert first_std_ids and first_sent_ids

    # 第二次同步前改写文件，手工塞入旧表项模拟 MODIFIED
    fpath.write_text("修订版本的足够长说明内容，哈希必然发生变化。", encoding="utf-8")
    table = SyncStateStore(sync_file).load()
    key = next(iter(table))
    table[key] = _make_old_entry(key, first_std_ids, first_sent_ids)
    SyncStateStore(sync_file).save(table, str(docs_dir.resolve()))

    manager.sync(str(docs_dir), mode="incremental")

    # 旧 ID 必须在两个集合都被删除，且发生在重新入库之前
    assert set(first_std_ids).issubset(set(std_store.deleted_ids))
    assert set(first_sent_ids).issubset(set(sent_store.deleted_ids))
    # 重新入库后块数翻倍（旧的删除只记 ID，假件 added 列表保留全部历史）
    assert len(std_store.added) == 2 * len(first_std_ids)
    assert len(sent_store.added) == 2 * len(first_sent_ids)


# ---------------------------------------------------------------------------
# DELETED：双集合清理 + 表项移除
# ---------------------------------------------------------------------------


def test_deleted_file_purges_both_collections(stores, tmp_path):
    std_store, sent_store = stores
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    fpath = docs_dir / "doomed.md"
    fpath.write_text(
        "即将被删除的文件内容，需要足够长以形成有效切块。",
        encoding="utf-8",
    )
    sync_file = str(tmp_path / ".sync_state.json")

    manager = FileSyncManager(
        std_store,
        FakeChunker(),
        FakeLoader(),
        sync_dir=sync_file,
        sentence_store=sent_store,
    )
    manager.sync(str(docs_dir), mode="incremental")
    std_ids = [d.id for d in std_store.added]
    sent_ids = [d.id for d in sent_store.added]

    # 磁盘删除后再次同步
    fpath.unlink()
    result = manager.sync(str(docs_dir), mode="incremental")

    assert result.files_deleted == 1
    assert set(std_ids).issubset(set(std_store.deleted_ids))
    assert set(sent_ids).issubset(set(sent_store.deleted_ids))
    assert SyncStateStore(sync_file).load() == {}


def test_delete_failure_keeps_table_entry(stores, tmp_path):
    std_store, sent_store = stores
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    fpath = docs_dir / "doomed.md"
    fpath.write_text("另一份即将被删除的足够长文件内容用于同步。", encoding="utf-8")
    sync_file = str(tmp_path / ".sync_state.json")

    manager = FileSyncManager(
        std_store,
        FakeChunker(),
        FakeLoader(),
        sync_dir=sync_file,
        sentence_store=sent_store,
    )
    manager.sync(str(docs_dir), mode="incremental")

    # 标准集合删除抛错，表项必须保留以便下次重试
    def boom(ids):
        raise RuntimeError("chroma locked")

    std_store.delete_by_ids = boom
    fpath.unlink()
    result = manager.sync(str(docs_dir), mode="incremental")

    # files_deleted 是变更分类计数（磁盘确已删除），成败看 errors 与表项
    assert result.files_deleted == 1
    assert len(result.errors) == 1
    assert result.errors[0].error_type == "VECTOR_ERROR"
    assert SyncStateStore(sync_file).load(), "删除失败时同步表项不得丢失"


# ---------------------------------------------------------------------------
# 降级：未注入 sentence_store
# ---------------------------------------------------------------------------


def test_missing_sentence_store_degrades_gracefully(stores, docs_dir, tmp_path):
    std_store, _ = stores
    manager = FileSyncManager(
        std_store,
        FakeChunker(),
        FakeLoader(),
        sync_dir=str(tmp_path / ".sync_state.json"),
        sentence_store=None,
    )

    result = manager.sync(docs_dir, mode="incremental")

    assert result.files_new == 1
    assert std_store.added
    table = SyncStateStore(str(tmp_path / ".sync_state.json")).load()
    entry = next(iter(table.values()))
    assert entry.sentence_chunk_ids == []


# ---------------------------------------------------------------------------
# 全量同步清理两个集合
# ---------------------------------------------------------------------------


def test_full_sync_delete_all_hits_both_stores(stores, tmp_path):
    std_store, sent_store = stores
    manager = FileSyncManager(
        std_store,
        FakeChunker(),
        FakeLoader(),
        sync_dir=str(tmp_path / ".sync_state.json"),
        sentence_store=sent_store,
    )
    table = {
        "/x/a.md": _make_old_entry("/x/a.md", ["s1", "s2"], ["q1"]),
        "/x/b.md": _make_old_entry("/x/b.md", ["s3"], ["q2", "q3"]),
    }

    removed = manager._delete_all_vector_docs(table)

    assert set(std_store.deleted_ids) == {"s1", "s2", "s3"}
    assert set(sent_store.deleted_ids) == {"q1", "q2", "q3"}
    assert removed == 6


# ---------------------------------------------------------------------------
# scan 预览不触达向量库
# ---------------------------------------------------------------------------


def test_scan_does_not_touch_stores(manager, stores, docs_dir):
    changes = manager.scan(docs_dir)

    std_store, sent_store = stores
    assert any(c.change_type == ChangeType.NEW for c in changes.values())
    assert std_store.added == []
    assert sent_store.added == []
    assert std_store.deleted_ids == []
