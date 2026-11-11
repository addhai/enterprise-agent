"""HybridRetriever.search_with_expansion 融合逻辑单测（离线）。

不构造真实 Embedding/Chroma，全部通道用内存假件，锁定四个契约：
    1. 无扩展产物时等价普通检索，不触发额外向量调用
    2. 扩展召回按 page_content 去重，新块进候选池
    3. 合并后用原查询统一 rerank，再走权限过滤
    4. 单路扩展向量异常被吞掉，基线结果不受影响
"""

import pytest
from langchain_core.documents import Document
from src.config import settings
from src.rag.retriever import HybridRetriever


def _doc(content, meta=None):
    return Document(content, metadata=meta or {})


@pytest.fixture
def retriever(monkeypatch):
    r = object.__new__(HybridRetriever)
    monkeypatch.setattr(settings, "rerank_enabled", False)

    base_docs = [(_doc("基线块一"), 0.9), (_doc("基线块二"), 0.8)]
    r.search_with_scores = lambda *a, **k: list(base_docs)

    vector_map = {
        "问法甲": [(_doc("扩展块甲"), 0.7)],
        "问法乙": [(_doc("基线块一"), 0.6), (_doc("扩展块乙"), 0.5)],
        "hyde段落": [(_doc("HyDE块"), 0.4)],
    }

    def _fake_vector_search(query, top_k, filter_by):
        return list(vector_map.get(query, []))

    r._vector_search = _fake_vector_search
    r._filter_by_permission = lambda docs, *a, **k: list(docs)

    rerank_calls = []

    def _fake_rerank(query, candidates):
        rerank_calls.append((query, len(candidates)))
        return candidates

    r._rerank = _fake_rerank
    r._rerank_calls = rerank_calls
    return r


def test_empty_expansion_equals_plain_search(retriever):
    out = retriever.search_with_expansion("原问题", top_k=5)

    assert [d.page_content for d in out] == ["基线块一", "基线块二"]


def test_expansion_merges_dedup_and_keeps_topk(retriever):
    out = retriever.search_with_expansion(
        "原问题",
        extra_queries=["问法甲", "问法乙"],
        hyde_text="hyde段落",
        top_k=5,
    )
    contents = [d.page_content for d in out]

    # 基线 2 块 + 扩展去重后 3 块（问法乙的基线块一重复被剔）
    assert set(contents) == {"基线块一", "基线块二", "扩展块甲", "扩展块乙", "HyDE块"}

    # 同输入小 top_k 必须截断
    truncated = retriever.search_with_expansion(
        "原问题",
        extra_queries=["问法甲", "问法乙"],
        hyde_text="hyde段落",
        top_k=3,
    )
    assert len(truncated) == 3
    assert {d.page_content for d in truncated}.issubset(set(contents))


def test_identical_expansion_query_ignored(retriever):
    called = []

    def _spy(query, top_k, filter_by):
        called.append(query)
        return []

    retriever._vector_search = _spy

    retriever.search_with_expansion("原问题", extra_queries=["原问题", ""])

    assert called == []


def test_rerank_uses_original_query(retriever, monkeypatch):
    monkeypatch.setattr(settings, "rerank_enabled", True)

    retriever.search_with_expansion(
        "原问题", extra_queries=["问法甲"], hyde_text="hyde段落", top_k=5
    )

    assert retriever._rerank_calls
    queried, pool_size = retriever._rerank_calls[0]
    assert queried == "原问题"
    assert pool_size == 4  # 2 基线 + 甲 + HyDE


def test_permission_filter_applied_to_merged_pool(retriever):
    def _strict_filter(docs, tenant_id, user_id, levels):
        # 模拟密级过滤：剔除含「机密」的块
        return [(d, s) for d, s in docs if "机密" not in d.page_content]

    retriever._filter_by_permission = _strict_filter
    retriever._vector_search = lambda q, top_k, fb: [(_doc("机密扩展块"), 0.3)]

    out = retriever.search_with_expansion("原问题", extra_queries=["问法甲"], top_k=5)

    assert all("机密" not in d.page_content for d in out)


def test_expansion_vector_failure_does_not_break_baseline(retriever):
    def _boom(query, top_k, filter_by):
        raise RuntimeError("embedding service down")

    retriever._vector_search = _boom

    out = retriever.search_with_expansion(
        "原问题", extra_queries=["问法甲"], hyde_text="hyde段落", top_k=5
    )

    assert [d.page_content for d in out] == ["基线块一", "基线块二"]


def test_no_new_extras_returns_baseline_directly(retriever):
    # 扩展召回全部与基线重复，无新块时直接返回基线
    retriever._vector_search = lambda q, top_k, fb: [(_doc("基线块一"), 0.5)]

    out = retriever.search_with_expansion("原问题", extra_queries=["问法乙"], top_k=5)

    assert [d.page_content for d in out] == ["基线块一", "基线块二"]
