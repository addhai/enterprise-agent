"""文档级向量生命周期单测（离线、不触网、不起真实 Embedding）。

覆盖 2026-11 P0 修复引入的两个新契约：
    1. VectorStoreManager.delete_by_metadata：Chroma where 删除与计数
    2. HybridRetriever.delete_document_vectors：双集合级联删除 + BM25 重建
    3. HybridRetriever.index_sentence_chunks：tenant 戳补全与空操作语义

沿用 test_retriever_warmup.py 的 object.__new__ 手法绕过 __init__，
杜绝真实 Embedder / Chroma 初始化。
"""

import pytest
from langchain_core.documents import Document
from src.rag.retriever import HybridRetriever
from src.rag.vector_store import VectorStoreManager


class FakeCollection:
    """模拟 chromadb Collection 的 get/delete 最小契约。"""

    def __init__(self, hit_ids):
        self._hit_ids = list(hit_ids)
        self.delete_calls = []
        self.get_calls = []

    def get(self, where=None, include=None):  # noqa: ARG002 - 模拟第三方签名
        self.get_calls.append(where)
        return {"ids": list(self._hit_ids)}

    def delete(self, where=None, ids=None):
        self.delete_calls.append({"where": where, "ids": ids})


class FakeLangChainStore:
    def __init__(self, collection):
        self._collection = collection


class FakeVectorStore:
    def __init__(self, hit_ids=None):
        self.collection = FakeCollection(hit_ids or [])
        self.delete_calls = []

    def delete_by_metadata(self, where):
        self.delete_calls.append(where)
        return len(self.collection._hit_ids)

    def get_all_documents(self):
        return []


# ---------------------------------------------------------------------------
# VectorStoreManager.delete_by_metadata
# ---------------------------------------------------------------------------


def _make_manager():
    manager = object.__new__(VectorStoreManager)
    manager._backend = "chroma"
    return manager


def test_delete_by_metadata_chroma_counts_then_deletes():
    manager = _make_manager()
    fake_collection = FakeCollection(["c1", "c2", "c3"])
    manager._store = FakeLangChainStore(fake_collection)

    removed = manager.delete_by_metadata({"doc_id": "KB-1"})

    assert removed == 3
    assert fake_collection.get_calls == [{"doc_id": "KB-1"}]
    assert fake_collection.delete_calls == [{"where": {"doc_id": "KB-1"}, "ids": None}]


def test_delete_by_metadata_no_match_skips_delete():
    manager = _make_manager()
    fake_collection = FakeCollection([])
    manager._store = FakeLangChainStore(fake_collection)

    removed = manager.delete_by_metadata({"doc_id": "KB-GHOST"})

    assert removed == 0
    assert fake_collection.delete_calls == []


def test_delete_by_metadata_rejects_empty_where():
    manager = _make_manager()
    with pytest.raises(ValueError, match="拒绝空条件"):
        manager.delete_by_metadata({})


# ---------------------------------------------------------------------------
# HybridRetriever.delete_document_vectors
# ---------------------------------------------------------------------------


def _make_retriever(with_sentence=True, backend="chroma"):
    r = object.__new__(HybridRetriever)
    r.backend = backend
    r.vector_store = FakeVectorStore(["s1", "s2"])
    r.sentence_store = FakeVectorStore(["q1"]) if with_sentence else None
    warmup_calls = []
    # 实例属性遮蔽类方法，避免拉起真实 BM25Retriever
    r.warmup_bm25_from_store = lambda: warmup_calls.append(1) or 0
    r._warmup_calls = warmup_calls
    return r


def test_delete_document_vectors_cascades_both_collections():
    r = _make_retriever(with_sentence=True)

    result = r.delete_document_vectors("KB-9", tenant_id="t1")

    assert result == {"standard_deleted": 2, "sentence_deleted": 1}
    assert r.vector_store.delete_calls == [{"doc_id": "KB-9"}]
    assert r.sentence_store.delete_calls == [{"doc_id": "KB-9"}]
    assert len(r._warmup_calls) == 1


def test_delete_document_vectors_without_sentence_store():
    r = _make_retriever(with_sentence=False)

    result = r.delete_document_vectors("KB-9")

    assert result == {"standard_deleted": 2, "sentence_deleted": 0}
    assert len(r._warmup_calls) == 1


def test_delete_document_vectors_rejects_remote_backend():
    r = _make_retriever(backend="remote")
    with pytest.raises(NotImplementedError):
        r.delete_document_vectors("KB-9")


def test_delete_document_vectors_requires_doc_id():
    r = _make_retriever()
    with pytest.raises(ValueError):
        r.delete_document_vectors("")


# ---------------------------------------------------------------------------
# HybridRetriever.index_sentence_chunks
# ---------------------------------------------------------------------------


def test_index_sentence_chunks_stamps_tenant_and_writes():
    r = object.__new__(HybridRetriever)
    fake_store = FakeVectorStore()
    r.sentence_store = fake_store

    captured = {}

    def add_documents(docs):
        captured["docs"] = docs

    fake_store.add_documents = add_documents
    chunks = [
        Document("句子一。", metadata={"doc_id": "KB-1"}),
        Document("句子二。", metadata={"doc_id": "KB-1"}),
    ]

    r.index_sentence_chunks(chunks, tenant_id="acme")

    assert all(d.metadata["tenant_id"] == "acme" for d in captured["docs"])
    assert all(d.metadata["doc_id"] == "KB-1" for d in captured["docs"])


def test_index_sentence_chunks_default_tenant_when_blank():
    r = object.__new__(HybridRetriever)
    fake_store = FakeVectorStore()
    captured = {}
    fake_store.add_documents = lambda docs: captured.update(docs=docs)
    r.sentence_store = fake_store

    r.index_sentence_chunks([Document("测试句子内容。")], tenant_id="")

    assert captured["docs"][0].metadata["tenant_id"] == "default"


def test_index_sentence_chunks_noop_when_store_offline():
    r = object.__new__(HybridRetriever)
    r.sentence_store = None
    # 无句子通道时静默跳过，不应抛异常
    r.index_sentence_chunks([Document("测试句子内容。")], tenant_id="t1")


def test_index_sentence_chunks_noop_on_empty_input():
    r = object.__new__(HybridRetriever)
    fake_store = FakeVectorStore()
    add_calls = []
    fake_store.add_documents = lambda docs: add_calls.append(docs)
    r.sentence_store = fake_store

    r.index_sentence_chunks([], tenant_id="t1")

    assert add_calls == []
