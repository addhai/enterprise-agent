"""知识库文档索引生命周期 API 测试（离线、不触网）。

覆盖 2026-11 P0 修复的五条管理链路契约：
    1. 入库走 HybridChunker 双粒度管线，标准块与句子块分别写入
    2. 向量化失败如实落 FAILED 并返回 500，禁止伪装 INDEXED
    3. 删除文档先级联清向量再删元数据；向量失败时元数据保留
    4. refresh 真删旧向量再重建；text 来源拒绝刷新
    5. 批量删除对每个文档执行向量级联

retriever 整体 monkeypatch 为内存假件，全程不起 Embedding、不触网。
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.server import app

    return TestClient(app)


@pytest.fixture
def admin_token(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def kb_id(client, auth):
    resp = client.post(
        "/api/v1/admin/knowledge",
        json={
            "name": "索引生命周期测试库",
            "description": "P0 修复验证",
            "kb_version": "standard",
            "kb_type": "document",
            "similarity_threshold": 0.75,
            "weight": 1.0,
        },
        headers=auth,
    )
    assert resp.status_code == 200
    return resp.json()["kb"]["id"]


class FakeRetriever:
    """记录全部索引/删除调用的内存假检索器。"""

    def __init__(self):
        self.standard_added = []
        self.sentence_added = []
        self.purged = []
        self.add_calls = 0
        self.add_raises = None
        self.purge_raises = None

    def add_documents(self, documents, tenant_id=""):
        self.add_calls += 1
        if self.add_raises:
            raise self.add_raises
        self.standard_added.extend(documents)

    def index_sentence_chunks(self, documents, tenant_id=""):
        self.sentence_added.extend(documents)

    def delete_document_vectors(self, doc_id, tenant_id=""):
        if self.purge_raises:
            raise self.purge_raises
        self.purged.append(doc_id)
        return {"standard_deleted": 1, "sentence_deleted": 1}


@pytest.fixture
def fake_retriever(monkeypatch):
    import src.api.dependencies as dep

    fake = FakeRetriever()
    monkeypatch.setattr(dep, "get_retriever", lambda: fake)
    return fake


def _create_text_doc(client, auth, kb_id, title="生命周期文本"):
    content = (
        "这是第一段关于设备保修政策的说明内容。"
        "整机保修期为十二个月，自购买之日起计算。"
        "人为损坏与私自拆机不在保修范围之内。"
    )
    return client.post(
        f"/api/v1/admin/knowledge/{kb_id}/documents",
        json={
            "source_type": "text",
            "content": content,
            "title": title,
            "upload_method": "single",
        },
        headers=auth,
    )


# ---------------------------------------------------------------------------
# 1. 入库双粒度管线
# ---------------------------------------------------------------------------


def test_ingest_writes_standard_and_sentence_chunks(
    client, auth, kb_id, fake_retriever
):
    resp = _create_text_doc(client, auth, kb_id)

    assert resp.status_code == 200
    doc = resp.json()["document"]
    assert doc["status"] == "indexed"
    assert doc["parse_status"] == "completed"
    assert doc["chunk_count"] >= 1

    # 标准块真实经过 add_documents，且全部带隔离与级联删除锚点
    assert fake_retriever.add_calls == 1
    assert fake_retriever.standard_added, "标准块必须写入向量集合"
    doc_id = doc["id"]
    for chunk in fake_retriever.standard_added:
        assert chunk.metadata["doc_id"] == doc_id
        assert chunk.metadata["kb_id"] == kb_id
        assert chunk.metadata["source_type"] == "text"
        assert chunk.metadata["tenant_id"]

    # 句子块走独立通道（丰富文本应切出句子）
    assert fake_retriever.sentence_added, "句子块必须写入句子集合"
    assert all(c.metadata["doc_id"] == doc_id for c in fake_retriever.sentence_added)


# ---------------------------------------------------------------------------
# 2. 失败如实落 FAILED
# ---------------------------------------------------------------------------


def test_ingest_failure_marks_failed_and_returns_500(
    client, auth, kb_id, fake_retriever
):
    fake_retriever.add_raises = RuntimeError("embedder offline")

    resp = _create_text_doc(client, auth, kb_id, title="注定失败的文本")

    assert resp.status_code == 500
    assert "文档索引失败" in resp.json()["detail"]

    # 失败文档仍可在列表中查到，状态为 failed，不再伪装 indexed
    lst = client.get(f"/api/v1/admin/knowledge/{kb_id}/documents", headers=auth).json()[
        "documents"
    ]
    failed = [d for d in lst if d["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["parse_status"].startswith("failed:")
    assert failed[0]["chunk_count"] == 0


def test_ingest_empty_content_rejected_400_and_marked_failed(
    client, auth, kb_id, fake_retriever, tmp_path
):
    # 实测 loader 对仅含极短标题的 md 返回空文档列表（与安全审计用例同构）
    tiny = tmp_path / "tiny.md"
    tiny.write_text("# x", encoding="utf-8")

    resp = client.post(
        f"/api/v1/admin/knowledge/{kb_id}/documents",
        json={
            "source_type": "document",
            "file_path": str(tiny),
            "title": "tiny.md",
            "upload_method": "single",
        },
        headers=auth,
    )

    assert resp.status_code == 400
    lst = client.get(f"/api/v1/admin/knowledge/{kb_id}/documents", headers=auth).json()[
        "documents"
    ]
    failed = [d for d in lst if d["status"] == "failed"]
    assert len(failed) == 1
    assert "DocumentContentEmptyError" in failed[0]["parse_status"]
    # 空内容不得写入任何向量
    assert fake_retriever.standard_added == []


# ---------------------------------------------------------------------------
# 3. 删除级联 + 失败保留元数据
# ---------------------------------------------------------------------------


def test_delete_purges_vectors_then_metadata(client, auth, kb_id, fake_retriever):
    doc_id = _create_text_doc(client, auth, kb_id).json()["document"]["id"]

    resp = client.delete(
        f"/api/v1/admin/knowledge/{kb_id}/documents/{doc_id}", headers=auth
    )

    assert resp.status_code == 200
    assert fake_retriever.purged == [doc_id]

    detail = client.get(
        f"/api/v1/admin/knowledge/{kb_id}/documents/{doc_id}", headers=auth
    )
    assert detail.status_code == 404


def test_delete_keeps_metadata_when_vector_purge_fails(
    client, auth, kb_id, fake_retriever
):
    doc_id = _create_text_doc(client, auth, kb_id).json()["document"]["id"]
    fake_retriever.purge_raises = RuntimeError("chroma locked")

    resp = client.delete(
        f"/api/v1/admin/knowledge/{kb_id}/documents/{doc_id}", headers=auth
    )

    assert resp.status_code == 500
    assert "向量删除失败" in resp.json()["detail"]

    # 元数据保留，运维可凭原 doc_id 重试
    detail = client.get(
        f"/api/v1/admin/knowledge/{kb_id}/documents/{doc_id}", headers=auth
    )
    assert detail.status_code == 200
    assert detail.json()["document"]["id"] == doc_id


# ---------------------------------------------------------------------------
# 4. refresh 真重建
# ---------------------------------------------------------------------------


def test_refresh_text_source_rejected(client, auth, kb_id, fake_retriever):
    doc_id = _create_text_doc(client, auth, kb_id).json()["document"]["id"]

    resp = client.post(
        f"/api/v1/admin/knowledge/{kb_id}/documents/{doc_id}/refresh", headers=auth
    )

    assert resp.status_code == 400
    assert "不支持刷新" in resp.json()["detail"]
    assert fake_retriever.purged == []


def test_refresh_document_purges_then_reindexes(
    client, auth, kb_id, fake_retriever, tmp_path
):
    md_file = tmp_path / "manual.md"
    md_file.write_text(
        "# 设备手册\n\n这是第一章的操作说明内容，需要足够长以形成有效切块。\n\n"
        "第二章描述安全注意事项，禁止在带电状态下拆卸设备外壳。",
        encoding="utf-8",
    )

    created = client.post(
        f"/api/v1/admin/knowledge/{kb_id}/documents",
        json={
            "source_type": "document",
            "file_path": str(md_file),
            "title": "manual.md",
            "upload_method": "single",
        },
        headers=auth,
    )
    assert created.status_code == 200
    doc_id = created.json()["document"]["id"]
    assert fake_retriever.add_calls == 1

    resp = client.post(
        f"/api/v1/admin/knowledge/{kb_id}/documents/{doc_id}/refresh", headers=auth
    )

    assert resp.status_code == 200
    refreshed = resp.json()["document"]
    assert refreshed["status"] == "indexed"
    assert refreshed["chunk_count"] >= 1

    # 先删旧向量，再重新入库，且删除锚点就是当前 doc_id
    assert fake_retriever.purged == [doc_id]
    assert fake_retriever.add_calls == 2
    assert all(
        c.metadata["doc_id"] == doc_id
        for c in fake_retriever.standard_added[
            len(fake_retriever.standard_added) // 2 :
        ]
    )


def test_refresh_failure_marks_failed(client, auth, kb_id, fake_retriever, tmp_path):
    md_file = tmp_path / "broken.md"
    md_file.write_text(
        "# 手册\n\n一段足够长的正常说明内容用于初次入库。", encoding="utf-8"
    )
    doc_id = client.post(
        f"/api/v1/admin/knowledge/{kb_id}/documents",
        json={
            "source_type": "document",
            "file_path": str(md_file),
            "title": "broken.md",
            "upload_method": "single",
        },
        headers=auth,
    ).json()["document"]["id"]

    # 刷新期让重新入库失败
    fake_retriever.add_raises = RuntimeError("disk full")
    resp = client.post(
        f"/api/v1/admin/knowledge/{kb_id}/documents/{doc_id}/refresh", headers=auth
    )

    assert resp.status_code == 500
    detail = client.get(
        f"/api/v1/admin/knowledge/{kb_id}/documents/{doc_id}", headers=auth
    ).json()["document"]
    assert detail["status"] == "failed"
    assert detail["parse_status"].startswith("failed:")


# ---------------------------------------------------------------------------
# 5. 批量删除级联
# ---------------------------------------------------------------------------


def test_batch_delete_purges_each_document(client, auth, kb_id, fake_retriever):
    id1 = _create_text_doc(client, auth, kb_id, title="批量一").json()["document"]["id"]
    id2 = _create_text_doc(client, auth, kb_id, title="批量二").json()["document"]["id"]

    resp = client.post(
        f"/api/v1/admin/knowledge/{kb_id}/documents/batch_delete",
        json={"doc_ids": [id1, id2]},
        headers=auth,
    )

    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2
    assert set(fake_retriever.purged) == {id1, id2}

    for doc_id in (id1, id2):
        assert (
            client.get(
                f"/api/v1/admin/knowledge/{kb_id}/documents/{doc_id}", headers=auth
            ).status_code
            == 404
        )
