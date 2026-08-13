"""rag/reranker.py 单元测试

reranker 是纯逻辑（RRF 融合后的二次排序 + 分数归一化），不依赖 LLM / 网络：
    - BaseReranker.rerank：空输入处理、排序、失败回退
    - _normalize：三种归一化分支（已在区间内 / 超范围 min-max / 无差异截断）
    - LLMReranker：无 LLM 时退化为长度启发式
    - create_reranker 工厂：llm / local_bge / dashscope(无 key 抛错) / 不支持 provider

注意：DashscopeReranker / LocalBgeReranker 的 _compute_scores 分别依赖
网络 API 与 sentence-transformers 模型，不在单测范围（类定义随 import 被触及）。
"""
import os

import pytest
from langchain_core.documents import Document

from src.rag.reranker import (
    BaseReranker,
    LLMReranker,
    LocalBgeReranker,
    create_reranker,
)


def _docs(texts):
    return [(Document(page_content=t), 0.5) for t in texts]


def test_rerank_empty_query_returns_input():
    r = LLMReranker()
    docs = _docs(["a", "b"])
    assert r.rerank("", docs) == docs


def test_rerank_empty_docs_returns_empty():
    r = LLMReranker()
    assert r.rerank("q", []) == []


def test_rerank_llm_none_length_heuristic():
    r = LLMReranker(llm=None)
    docs = _docs(["short", "this is a much longer document"])
    out = r.rerank("q", docs)
    assert len(out) == 2
    # 长文档分数更高，应排在最前
    assert out[0][0].page_content == "this is a much longer document"


def test_rerank_sorts_by_score():
    class _FakeReranker(BaseReranker):
        def _compute_scores(self, q, texts):
            return [0.1, 0.9, 0.5]

    docs = _docs(["a", "b", "c"])
    out = _FakeReranker().rerank("q", docs, top_n=3)
    assert out[0][0].page_content == "b"  # 0.9 最高


def test_rerank_top_n_truncates():
    class _FakeReranker(BaseReranker):
        def _compute_scores(self, q, texts):
            return [0.1, 0.9, 0.5]

    docs = _docs(["a", "b", "c"])
    out = _FakeReranker().rerank("q", docs, top_n=2)
    assert len(out) == 2


def test_rerank_fallback_on_compute_error():
    class _BoomReranker(BaseReranker):
        def _compute_scores(self, q, texts):
            raise RuntimeError("boom")

    docs = _docs(["a", "b"])
    out = _BoomReranker().rerank("q", docs)
    assert out == docs


def test_normalize_already_in_range():
    assert BaseReranker._normalize([0.2, 0.8]) == [0.2, 0.8]


def test_normalize_out_of_range_minmax():
    res = BaseReranker._normalize([0, 10, 5])
    assert min(res) >= 0 and max(res) <= 1
    assert abs(res[1] - 1.0) < 1e-6  # 最大值归一化为 1


def test_normalize_no_span_clamped():
    res = BaseReranker._normalize([5.0, 5.0])
    assert all(0.0 <= x <= 1.0 for x in res)


def test_create_reranker_llm():
    assert isinstance(create_reranker("llm"), LLMReranker)


def test_create_reranker_local_bge():
    assert isinstance(create_reranker("local_bge"), LocalBgeReranker)


def test_create_reranker_dashscope_no_key_raises():
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        with pytest.raises(ValueError):
            create_reranker("dashscope")
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved


def test_create_reranker_unsupported():
    with pytest.raises(ValueError):
        create_reranker("nope")
