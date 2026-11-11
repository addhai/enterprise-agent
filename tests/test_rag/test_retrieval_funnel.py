"""search_with_scores 检索漏斗日志与相似度边界单测（离线）。

不构造真实 Embedding/Chroma，用 object.__new__ 绕过 __init__ 后挂内存假件，
锁定 P1-11 / P1-12 两个契约：
    1. 每次检索输出一条漏斗日志，逐阶段记录召回与过滤数量
    2. 权限过滤的前后数量在日志中以 perm=before->after 还原
    3. BM25 独有的纯关键词块（无 vector_similarity 戳）能穿过 RRF 融合，
       证明融合后链路不再套绝对相似度阈值（P1-11 设计保护）
    4. rerank 开启时日志标签是精排后数量，关闭时显示 off
"""

import logging

from langchain_core.documents import Document
from src.config import settings
from src.rag.retriever import HybridRetriever


def _doc(content, **meta):
    return Document(page_content=content, metadata=dict(meta))


def _build_retriever(monkeypatch, *, perm_keep=None, rerank_enabled=False):
    """组装一个所有外部依赖都被内存假件替换的检索器。"""
    monkeypatch.setattr(settings, "rerank_enabled", rerank_enabled)
    r = object.__new__(HybridRetriever)
    r.backend = "chroma"
    # None 让句子通道在 search_with_scores 内直接走空列表分支
    r.sentence_store = None

    vector_docs = [
        (_doc("向量块甲", vector_similarity=0.91), 0.91),
        (_doc("向量块乙", vector_similarity=0.83), 0.83),
    ]
    bm25_docs = [
        (_doc("向量块甲"), 0.0),
        # 纯关键词命中块，不带任何绝对相似度戳
        (_doc("BM25独有故障码块"), 0.0),
    ]
    fused = [
        (_doc("向量块甲", vector_similarity=0.91), 0.032),
        (_doc("向量块乙", vector_similarity=0.83), 0.030),
        (_doc("BM25独有故障码块"), 0.028),
    ]

    r._vector_search = lambda q, k, f: list(vector_docs)
    r._bm25_search = lambda q, k, f: list(bm25_docs)
    r._rrf_fusion = lambda v, b, k: list(fused)
    r._merge_standard_and_sentence = lambda std, sent, k: list(std)

    if perm_keep is not None:
        r._filter_by_permission = lambda docs, *a, **k: list(docs)[:perm_keep]
    else:
        r._filter_by_permission = lambda docs, *a, **k: list(docs)

    r._resolve_version_conflicts = lambda docs, k: list(docs)
    r._rerank = lambda q, candidates: list(candidates)
    return r


def _funnel_line(caplog):
    lines = [rec.message for rec in caplog.records if "Retrieval funnel" in rec.message]
    assert len(lines) == 1
    return lines[0]


def test_funnel_log_records_each_stage_count(monkeypatch, caplog):
    """漏斗日志逐阶段记录三路召回、融合、精排开关与最终数量。"""
    r = _build_retriever(monkeypatch)

    with caplog.at_level(logging.INFO, logger="src.rag.retriever"):
        out = r.search_with_scores("F02 故障", top_k=5)

    assert len(out) == 3
    line = _funnel_line(caplog)
    assert "vector=2" in line
    assert "bm25=2" in line
    assert "sentence=0" in line
    assert "rrf=3" in line
    assert "merged=3" in line
    assert "rerank=off" in line
    assert "perm=3->3" in line
    assert "final=3" in line


def test_funnel_log_shows_permission_drop(monkeypatch, caplog):
    """权限过滤剔除块时，perm 箭头还原过滤前后数量。"""
    r = _build_retriever(monkeypatch, perm_keep=2)

    with caplog.at_level(logging.INFO, logger="src.rag.retriever"):
        out = r.search_with_scores("密级资料查询", top_k=5)

    assert len(out) == 2
    line = _funnel_line(caplog)
    assert "perm=3->2" in line
    assert "final=2" in line


def test_bm25_only_chunk_survives_fusion_without_similarity(monkeypatch):
    """无相似度戳的 BM25 独有块必须进最终结果（P1-11 融合后无相似度门槛）。"""
    r = _build_retriever(monkeypatch)

    out = r.search_with_scores("E105 故障码", top_k=5)
    contents = [doc.page_content for doc, _ in out]

    assert "BM25独有故障码块" in contents
    # 该块确实没有绝对相似度戳，能存活说明拦截只发生在向量通道内
    bm25_only = next(doc for doc, _ in out if doc.page_content == "BM25独有故障码块")
    assert "vector_similarity" not in bm25_only.metadata


def test_funnel_rerank_label_shows_count_when_enabled(monkeypatch, caplog):
    """rerank 开启后日志标签是精排返回数量，不再是 off。"""
    r = _build_retriever(monkeypatch, rerank_enabled=True)

    with caplog.at_level(logging.INFO, logger="src.rag.retriever"):
        r.search_with_scores("带精排的查询", top_k=5)

    line = _funnel_line(caplog)
    assert "rerank=3" in line
    assert "rerank=off" not in line
