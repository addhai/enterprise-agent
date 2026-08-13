"""tests for src.rag.vector_store (chroma 后端)

用 FakeEmbedder + FakeChroma 覆盖 VectorStoreManager 的 chroma 路径：
延迟初始化、空文档、相似度搜索、带分数搜索、过滤、删除、计数。
Milvus 分支依赖外部服务，跳过。
"""
from langchain_core.documents import Document

import pytest

import src.rag.vector_store as vs
from src.rag.vector_store import VectorStoreManager


class FakeEmbedder:
    def __init__(self, *a, **k):
        pass


class FakeCollection:
    def __init__(self):
        self._docs = []
        self.deleted = []

    def count(self):
        return len(self._docs)

    def delete(self, ids=None):
        self.deleted = ids or []
        self._docs = []


class FakeChroma:
    def __init__(self, collection_name, embedding_function, persist_directory):
        self.collection_name = collection_name
        self._collection = FakeCollection()
        self._next_id = 0

    def add_documents(self, documents):
        for _ in documents:
            self._collection._docs.append(1)
            self._next_id += 1
        return [str(i) for i in range(len(documents))]

    def similarity_search(self, query, k=4):
        return [Document(page_content=f"res:{query}", metadata={"i": 0})]

    def similarity_search_with_relevance_scores(self, query, k=4, filter=None):
        return [(Document(page_content=f"res:{query}", metadata=filter or {}), 0.9)]

    def delete_collection(self):
        self._collection._docs = []


@pytest.fixture
def manager(monkeypatch):
    import langchain_chroma

    monkeypatch.setattr(vs, "Embedder", FakeEmbedder)
    monkeypatch.setattr(langchain_chroma, "Chroma", FakeChroma)
    monkeypatch.setattr(vs.settings, "vector_store_backend", "chroma")
    monkeypatch.setattr(vs.settings, "retrieval_top_k", 4)
    m = VectorStoreManager(persist_directory="/tmp/x", collection_name="c")
    return m


def test_backend_is_chroma(manager):
    assert manager.backend == "chroma"


def test_add_documents_empty(manager):
    assert manager.add_documents([]) == []


def test_add_documents_normal(manager):
    docs = [Document(page_content="hello", metadata={"tenant_id": "t1"})]
    ids = manager.add_documents(docs)
    assert ids == ["0"]
    assert manager.count() == 1


def test_search_empty_collection(manager):
    assert manager.search("query") == []


def test_search_with_results(manager):
    manager.add_documents([Document(page_content="a", metadata={})])
    res = manager.search("q")
    assert len(res) == 1
    assert res[0].page_content.startswith("res:")


def test_search_with_scores_no_filter(manager):
    manager.add_documents([Document(page_content="a", metadata={})])
    res = manager.search_with_scores("q")
    assert len(res) == 1
    assert isinstance(res[0], tuple)
    assert res[0][1] == 0.9


def test_search_with_scores_with_filter(manager):
    manager.add_documents([Document(page_content="a", metadata={})])
    res = manager.search_with_scores("q", where={"tenant_id": "acme"})
    assert len(res) == 1
    # filter 透传到 metadata
    assert res[0][0].metadata.get("tenant_id") == "acme"


def test_delete_by_ids_empty(manager):
    assert manager.delete_by_ids([]) == 0


def test_delete_by_ids_normal(manager):
    manager.add_documents([Document(page_content="a", metadata={})])
    n = manager.delete_by_ids(["0"])
    assert n == 1
    assert manager.count() == 0


def test_delete_collection(manager):
    manager.add_documents([Document(page_content="a", metadata={})])
    manager.delete_collection()
    assert manager.count() == 0


def test_count_no_store(monkeypatch):
    # 不初始化 store 时 count 返回 0
    m = VectorStoreManager.__new__(VectorStoreManager)
    m._store = None
    m._milvus_store = None
    m._backend = "chroma"  # 避免 .backend 触发 _init_store
    assert m.count() == 0
