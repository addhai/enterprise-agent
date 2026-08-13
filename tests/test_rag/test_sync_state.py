"""rag/sync_models.py 与 rag/sync_state.py 单元测试

两个模块均为纯数据结构 / 本地 JSON 持久化，无网络 / LLM 依赖：
    - sync_models：ChangeType / FileChange / SyncError / SyncResult / compute_content_hash
    - sync_state：SyncStatus / SyncStateEntry(to_dict|from_dict) / SyncStateStore(load|save)

覆盖点：枚举取值、属性判定、序列化往返、版本检查、异常兜底与持久化路径。
"""
from datetime import datetime, timezone

import pytest

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
)


# ===========================================================================
# ChangeType
# ===========================================================================


def test_change_type_values():
    assert ChangeType.NEW.value == "NEW"
    assert ChangeType.MODIFIED.value == "MODIFIED"
    assert ChangeType.DELETED.value == "DELETED"
    assert ChangeType.UNCHANGED.value == "UNCHANGED"
    assert {c for c in ChangeType} == {
        ChangeType.NEW,
        ChangeType.MODIFIED,
        ChangeType.DELETED,
        ChangeType.UNCHANGED,
    }


# ===========================================================================
# FileChange
# ===========================================================================


def _entry(path: str = "/a.md") -> SyncStateEntry:
    return SyncStateEntry(
        file_path=path,
        content_hash="h",
        mtime=1.0,
        status=SyncStatus.PROCESSED,
        standard_chunk_ids=[],
        sentence_chunk_ids=[],
        processed_at=datetime.now(timezone.utc),
    )


def test_file_change_is_relevant_new():
    fc = FileChange("/a.md", ChangeType.NEW, old_entry=None, new_content_hash="x")
    assert fc.is_relevant is True
    assert fc.old_entry is None
    assert fc.new_content_hash == "x"


def test_file_change_is_relevant_modified():
    old = _entry()
    fc = FileChange("/a.md", ChangeType.MODIFIED, old_entry=old, new_content_hash="y")
    assert fc.is_relevant is True
    assert fc.old_entry is old


def test_file_change_is_relevant_deleted():
    fc = FileChange("/a.md", ChangeType.DELETED, old_entry=_entry(), new_content_hash=None)
    assert fc.is_relevant is True
    assert fc.new_content_hash is None


def test_file_change_is_relevant_unchanged_false():
    fc = FileChange("/a.md", ChangeType.UNCHANGED, old_entry=_entry(), new_content_hash="z")
    assert fc.is_relevant is False


# ===========================================================================
# SyncError
# ===========================================================================


def test_sync_error_dataclass():
    err = SyncError("/a.md", "LOAD_ERROR", "boom")
    assert err.file_path == "/a.md"
    assert err.error_type == "LOAD_ERROR"
    assert err.message == "boom"


# ===========================================================================
# SyncResult
# ===========================================================================


def test_sync_result_success_empty():
    r = SyncResult()
    assert r.success is True
    assert r.errors == []


def test_sync_result_success_with_errors_false():
    r = SyncResult(errors=[SyncError("/a.md", "HASH_ERROR", "bad")])
    assert r.success is False
    assert len(r.errors) == 1


def test_sync_result_str_contains_counters():
    r = SyncResult(
        files_scanned=10,
        files_new=2,
        files_modified=3,
        files_deleted=1,
        files_unchanged=4,
        chunks_added=20,
        chunks_removed=5,
        errors=[SyncError("/a.md", "X", "y")],
        duration_seconds=1.234,
    )
    s = str(r)
    assert "scanned=10" in s
    assert "new=2" in s
    assert "modified=3" in s
    assert "deleted=1" in s
    assert "unchanged=4" in s
    assert "chunks_added=20" in s
    assert "chunks_removed=5" in s
    assert "errors=1" in s
    assert "duration=1.23s" in s


# ===========================================================================
# compute_content_hash
# ===========================================================================


def test_compute_content_hash_deterministic():
    a = compute_content_hash("hello world")
    b = compute_content_hash("hello world")
    assert a == b
    assert isinstance(a, str)
    assert len(a) == 64  # SHA-256 hex digest


def test_compute_content_hash_differs_on_content():
    assert compute_content_hash("hello") != compute_content_hash("world")


def test_compute_content_hash_unicode():
    # 归一化文本而非原始字节：含中文应正常处理
    h = compute_content_hash("中文内容 微调")
    assert len(h) == 64


# ===========================================================================
# SyncStatus
# ===========================================================================


def test_sync_status_values():
    assert SyncStatus.PROCESSED.value == "PROCESSED"
    assert SyncStatus.FAILED.value == "FAILED"
    assert SyncStatus.SKIPPED.value == "SKIPPED"


# ===========================================================================
# SyncStateEntry 序列化往返
# ===========================================================================


def _make_entry() -> SyncStateEntry:
    return SyncStateEntry(
        file_path="/abs/a.md",
        content_hash="abc123",
        mtime=1234.5,
        status=SyncStatus.PROCESSED,
        standard_chunk_ids=["c1", "c2"],
        sentence_chunk_ids=["s1"],
        processed_at=datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        error_message=None,
    )


def test_entry_to_dict():
    e = _make_entry()
    d = e.to_dict()
    assert d["file_path"] == "/abs/a.md"
    assert d["content_hash"] == "abc123"
    assert d["mtime"] == 1234.5
    assert d["status"] == "PROCESSED"  # enum -> value
    assert d["standard_chunk_ids"] == ["c1", "c2"]
    assert d["sentence_chunk_ids"] == ["s1"]
    assert d["processed_at"] == "2024-01-02T03:04:05+00:00"
    assert d["error_message"] is None


def test_entry_from_dict_roundtrip():
    e = _make_entry()
    d = e.to_dict()
    e2 = SyncStateEntry.from_dict(d)
    assert e2 == e
    assert e2.status is SyncStatus.PROCESSED
    assert e2.processed_at == e.processed_at


def test_entry_from_dict_with_error_message():
    e = _make_entry()
    e = e.__class__(
        file_path="/abs/b.md",
        content_hash="h2",
        mtime=9.0,
        status=SyncStatus.FAILED,
        standard_chunk_ids=[],
        sentence_chunk_ids=[],
        processed_at=datetime(2025, 5, 5, 5, 5, 5, tzinfo=timezone.utc),
        error_message="load failed",
    )
    d = e.to_dict()
    assert d["status"] == "FAILED"
    assert d["error_message"] == "load failed"
    e2 = SyncStateEntry.from_dict(d)
    assert e2.status is SyncStatus.FAILED
    assert e2.error_message == "load failed"


# ===========================================================================
# SyncStateStore.load
# ===========================================================================


def test_store_load_missing_file_returns_empty(tmp_path):
    f = tmp_path / ".sync_state.json"
    store = SyncStateStore(str(f))
    assert store.sync_file == f.resolve()
    assert store.load() == {}


def test_store_load_valid(tmp_path):
    f = tmp_path / ".sync_state.json"
    entry = _make_entry()
    data = {
        "version": SyncStateStore.SCHEMA_VERSION,
        "created_at": "2024-01-01T00:00:00+00:00",
        "last_sync_at": "2024-01-01T00:00:00+00:00",
        "sync_root": "/abs",
        "files": {entry.file_path: entry.to_dict()},
    }
    f.write_text(__import__("json").dumps(data), encoding="utf-8")
    store = SyncStateStore(str(f))
    table = store.load()
    assert entry.file_path in table
    assert table[entry.file_path] == entry


def test_store_load_empty_files(tmp_path):
    f = tmp_path / ".sync_state.json"
    data = {
        "version": SyncStateStore.SCHEMA_VERSION,
        "files": {},
    }
    f.write_text(__import__("json").dumps(data), encoding="utf-8")
    store = SyncStateStore(str(f))
    assert store.load() == {}


def test_store_load_version_mismatch_returns_empty(tmp_path):
    f = tmp_path / ".sync_state.json"
    data = {
        "version": SyncStateStore.SCHEMA_VERSION + 99,
        "files": {"/a": _make_entry().to_dict()},
    }
    f.write_text(__import__("json").dumps(data), encoding="utf-8")
    store = SyncStateStore(str(f))
    assert store.load() == {}


def test_store_load_json_decode_error_returns_empty(tmp_path):
    f = tmp_path / ".sync_state.json"
    f.write_text("{not valid json", encoding="utf-8")
    store = SyncStateStore(str(f))
    assert store.load() == {}


def test_store_load_oserror_returns_empty(tmp_path, monkeypatch):
    f = tmp_path / ".sync_state.json"
    store = SyncStateStore(str(f))

    def _boom(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("builtins.open", _boom)
    assert store.load() == {}


def test_store_load_skips_unparsable_entry(tmp_path):
    f = tmp_path / ".sync_state.json"
    bad = _make_entry().to_dict()
    bad["status"] = "NOT_A_REAL_STATUS"  # 反序列化会抛 ValueError
    data = {
        "version": SyncStateStore.SCHEMA_VERSION,
        "files": {
            "/good": _make_entry().to_dict(),
            "/bad": bad,
        },
    }
    f.write_text(__import__("json").dumps(data), encoding="utf-8")
    store = SyncStateStore(str(f))
    table = store.load()
    assert "/good" in table
    assert "/bad" not in table


# ===========================================================================
# SyncStateStore.save
# ===========================================================================


def test_store_save_creates_parent_and_persists(tmp_path):
    nested = tmp_path / "deep" / "nested" / ".sync_state.json"
    store = SyncStateStore(str(nested))
    entry = _make_entry()
    table = {entry.file_path: entry}
    store.save(table, sync_root="/abs")

    assert nested.exists()
    # 重新加载应还原
    reloaded = SyncStateStore(str(nested)).load()
    assert reloaded[entry.file_path] == entry


def test_store_save_roundtrip_multiple(tmp_path):
    f = tmp_path / ".sync_state.json"
    store = SyncStateStore(str(f))
    e1 = _make_entry()
    e2 = _make_entry().__class__(
        file_path="/abs/c.md",
        content_hash="h3",
        mtime=7.0,
        status=SyncStatus.SKIPPED,
        standard_chunk_ids=[],
        sentence_chunk_ids=[],
        processed_at=datetime(2023, 3, 3, 3, 3, 3, tzinfo=timezone.utc),
    )
    table = {e1.file_path: e1, e2.file_path: e2}
    store.save(table, sync_root="/abs")

    reloaded = SyncStateStore(str(f)).load()
    assert set(reloaded.keys()) == {e1.file_path, e2.file_path}
    assert reloaded[e2.file_path].status is SyncStatus.SKIPPED


def test_store_save_oserror_raises(tmp_path, monkeypatch):
    f = tmp_path / ".sync_state.json"
    store = SyncStateStore(str(f))
    table = {_make_entry().file_path: _make_entry()}

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _boom)
    with pytest.raises(OSError):
        store.save(table, sync_root="/abs")
