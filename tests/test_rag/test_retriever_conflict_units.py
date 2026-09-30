"""检索去重与来源配额的纯逻辑单测（不依赖 Embedding / 网络）。

覆盖 ``HybridRetriever._resolve_version_conflicts`` 两条关键事实：
    1. chunk 不是 version —— 同一篇文档的多个片段不得被当成「多个版本」互相折叠；
    2. 来源配额: 单篇文档最多贡献
       ``settings.retrieval_source_cap`` 条，避免占满 top_k。

用 ``object.__new__`` 构造实例，跳过 __init__（不建向量库、不连 Embedding）。
"""

import pytest
from langchain_core.documents import Document
from src.config import settings
from src.rag.retriever import HybridRetriever


def _r():
    return object.__new__(HybridRetriever)


def _doc(text: str, source: str, **meta):
    return Document(page_content=text, metadata={"source": source, **meta})


class TestChunksAreNotVersions:
    def test_same_source_chunks_without_version_are_all_kept(self):
        """无 version 元数据的同源 chunk 不是「版本冲突」，应保留（受配额约束）"""
        cap = settings.retrieval_source_cap
        results = [
            (_doc("片段1", "manual.md"), 0.9),
            (_doc("片段2", "manual.md"), 0.8),
            (_doc("片段3", "manual.md"), 0.7),
        ]
        resolved = _r()._resolve_version_conflicts(results, top_k=5)
        kept = [d.page_content for d, _ in resolved]
        assert kept == ["片段1", "片段2", "片段3"][:cap]
        assert len(resolved) <= cap

    def test_per_source_cap_keeps_other_sources_represented(self):
        """配额让 top_k 覆盖多个来源，而不是被一篇文档占满"""
        results = [
            (_doc("a1", "a.md"), 0.9),
            (_doc("a2", "a.md"), 0.89),
            (_doc("a3", "a.md"), 0.88),
            (_doc("b1", "b.md"), 0.5),
            (_doc("c1", "c.md"), 0.4),
        ]
        resolved = _r()._resolve_version_conflicts(results, top_k=5)
        sources = [d.metadata["source"] for d, _ in resolved]
        assert sources.count("a.md") == settings.retrieval_source_cap
        assert "b.md" in sources and "c.md" in sources

    def test_global_relevance_order_preserved(self):
        """输出顺序应保持入参的相关性顺序，不因按 source 分组而错乱"""
        results = [
            (_doc("a1", "a.md"), 0.9),
            (_doc("b1", "b.md"), 0.8),
            (_doc("a2", "a.md"), 0.7),
            (_doc("c1", "c.md"), 0.6),
        ]
        resolved = _r()._resolve_version_conflicts(results, top_k=5)
        assert [d.page_content for d, _ in resolved] == ["a1", "b1", "a2", "c1"]

    def test_top_k_truncation_applies(self):
        results = [(_doc(f"a{i}", f"s{i}.md"), 1.0 - i / 100) for i in range(6)]
        resolved = _r()._resolve_version_conflicts(results, top_k=3)
        assert len(resolved) == 3


class TestRealVersionConflicts:
    def test_latest_active_version_is_kept(self):
        """真有多个版本号时，只保留最新的活跃版本"""
        results = [
            (_doc("旧版内容", "policy.md", version="v1.0"), 0.9),
            (_doc("新版内容", "policy.md", version="v2.0"), 0.8),
        ]
        resolved = _r()._resolve_version_conflicts(results, top_k=5)
        assert [d.page_content for d, _ in resolved] == ["新版内容"]

    def test_deprecated_version_filtered_out(self):
        results = [
            (_doc("废弃版", "policy.md", version="v1.0", status="deprecated"), 0.9),
            (_doc("生效版", "policy.md", version="v2.0", status="active"), 0.8),
        ]
        resolved = _r()._resolve_version_conflicts(results, top_k=5)
        assert [d.page_content for d, _ in resolved] == ["生效版"]

    def test_conflict_warning_attached_to_metadata(self):
        """多个活跃版本同时存在时，在结果 metadata 中标注冲突提示"""
        results = [
            (_doc("v1", "policy.md", version="v1.0"), 0.9),
            (_doc("v2", "policy.md", version="v2.0"), 0.8),
        ]
        resolved = _r()._resolve_version_conflicts(results, top_k=5)
        assert resolved[0][0].metadata.get("has_conflicts") is True
        assert resolved[0][0].metadata.get("version_conflicts")


class TestSourceCapConfig:
    """来源配额必须是可配置项（settings.retrieval_source_cap），且取值非法要兜底。"""

    def test_default_cap_is_positive(self):
        assert settings.retrieval_source_cap >= 1

    def test_cap_reads_from_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "retrieval_source_cap", 3)
        assert _r()._source_chunk_cap() == 3
        results = [(_doc(f"a{i}", "a.md"), 1.0 - i / 100) for i in range(5)]
        resolved = _r()._resolve_version_conflicts(results, top_k=5)
        assert len(resolved) == 3

    def test_zero_cap_is_clamped_to_one(self, monkeypatch):
        """配额 0 会把结果整体截空，属于配置事故，必须夹到 1"""
        monkeypatch.setattr(settings, "retrieval_source_cap", 0)
        assert _r()._source_chunk_cap() == 1

    def test_negative_cap_is_clamped_to_one(self, monkeypatch):
        monkeypatch.setattr(settings, "retrieval_source_cap", -5)
        assert _r()._source_chunk_cap() == 1

    def test_non_numeric_cap_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(settings, "retrieval_source_cap", "abc")
        assert _r()._source_chunk_cap() == 2

    def test_cap_missing_attribute_falls_back(self, monkeypatch):
        monkeypatch.delattr(settings, "retrieval_source_cap", raising=False)
        assert _r()._source_chunk_cap() == 2


class TestEdgeCases:
    def test_empty_results(self):
        assert _r()._resolve_version_conflicts([], top_k=5) == []

    def test_single_chunk_passthrough(self):
        results = [(_doc("唯一", "only.md"), 0.5)]
        resolved = _r()._resolve_version_conflicts(results, top_k=5)
        assert [d.page_content for d, _ in resolved] == ["唯一"]


@pytest.mark.parametrize(
    "version,expected",
    [
        ("v3.2", 302),
        ("v1.0", 100),
        ("unknown", 0),
        ("", 0),
    ],
)
def test_version_sort_key(version, expected):
    """版本号排序键：主版本*100+次版本"""
    assert _r()._version_to_sort_key(version) == expected
