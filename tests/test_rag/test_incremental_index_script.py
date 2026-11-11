"""incremental_index.py 纯函数契约单测（离线、不构造真实检索器）。

向量写入路径由 test_file_sync_manager 与 test_document_vector_lifecycle
覆盖，本文件只锁定增量脚本自身的确定性逻辑：
    1. stable_doc_id 同路径恒定、异路径不同、带 fs- 前缀
    2. detect_changes 正确分类 new/updated/deleted，且跳过簿记字段
"""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "incremental_index.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("incremental_index", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inc = _load_module()


def test_stable_doc_id_deterministic():
    p = str(Path("data/docs/manual.md").resolve())
    assert inc.stable_doc_id(p) == inc.stable_doc_id(p)


def test_stable_doc_id_unique_per_path(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")

    id_a = inc.stable_doc_id(str(a))
    id_b = inc.stable_doc_id(str(b))

    assert id_a != id_b
    assert id_a.startswith("fs-")
    assert id_b.startswith("fs-")


def test_detect_changes_classifies_three_states(tmp_path):
    existing = tmp_path / "existing.md"
    updated = tmp_path / "updated.md"
    existing.write_text("新文件内容，需要足够长以模拟真实语料。", encoding="utf-8")
    updated.write_text(
        "旧版本内容，同样需要足够长度才能通过切块门槛。",
        encoding="utf-8",
    )

    old_hash = inc.compute_file_hash(str(updated))
    meta = {
        str(updated): {"hash": old_hash, "doc_id": "fs-old"},
        str(tmp_path / "gone.md"): {"hash": "x", "doc_id": "fs-gone"},
        # 簿记字段不得被误判为删除文件
        "updated_at": "2026-11-10T00:00:00",
    }

    # 改写 updated.md 制造哈希漂移
    updated.write_text(
        "修订后的内容，与旧版本完全不同，哈希必然发生变化。", encoding="utf-8"
    )

    changes = inc.detect_changes(str(tmp_path), meta)

    assert changes["new"] == [str(existing)]
    assert changes["updated"] == [str(updated)]
    assert changes["deleted"] == [str(tmp_path / "gone.md")]


def test_detect_changes_no_change(tmp_path):
    f = tmp_path / "stable.md"
    f.write_text("稳定不变的语料内容，保持哈希一致。", encoding="utf-8")
    meta = {str(f): {"hash": inc.compute_file_hash(str(f)), "doc_id": "fs-1"}}

    changes = inc.detect_changes(str(tmp_path), meta)

    assert changes == {"new": [], "updated": [], "deleted": []}
