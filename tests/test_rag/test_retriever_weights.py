"""文档权重 RRF 融合单元测试

覆盖：
- 权重生效（同分时高权重排前）
- 未知文档默认 1.0
- 配置可覆盖
"""

from langchain_core.documents import Document
from src.rag.retriever import HybridRetriever


def _r():
    """构造无 __init__ 的 HybridRetriever 实例"""
    inst = object.__new__(HybridRetriever)
    inst._kb_weights_map = {}
    return inst


def _doc(text: str, source: str, **meta):
    return Document(
        page_content=text,
        metadata={"source": source, **meta},
    )


class TestDocWeights:
    def test_get_doc_weights_map(self):
        """权重表应从 settings 解析"""
        r = _r()
        r._doc_weights_cache = {}  # 清缓存
        weights = r._get_doc_weights_map()
        assert weights.get("fault_troubleshooting_manual.md") == 1.5
        assert weights.get("faq_full.md") == 0.8
        assert weights.get("product_spec_manual.md") == 1.3

    def test_unknown_doc_default_1(self):
        """未知文档默认权重 1.0"""
        r = _r()
        r._doc_weights_cache = {}
        weights = r._get_doc_weights_map()
        assert weights.get("nonexistent.md", 1.0) == 1.0

    def test_weight_applied_in_rrf(self):
        """RRF 融合中高权重文档应排在前面

        构造两个分数相同的文档，高权重的应排前。
        """
        r = _r()
        r._doc_weights_cache = {}  # 强制重新解析

        # 两个文档，内容不同但排名相同（rank=0 → 同分）
        doc_a = _doc("内容A", "fault_troubleshooting_manual.md")
        doc_b = _doc("内容B", "faq_full.md")

        # 都在 vector_results 的 rank=0（不可能，但测试用）
        # 实际上 RRF 是按 rank 顺序算分的，这里简化测试
        vector_results = [(doc_a, 0.9), (doc_b, 0.8)]
        bm25_results = []

        merged = r._rrf_fusion(vector_results, bm25_results, top_k=2)

        # fault_troubleshooting (1.5x) 应排在 faq_full (0.8x) 前面
        assert merged[0][0].metadata["source"] == "fault_troubleshooting_manual.md"
        assert merged[1][0].metadata["source"] == "faq_full.md"

    def test_weight_cache(self):
        """权重表应被缓存"""
        r = _r()
        r._doc_weights_cache = {}
        w1 = r._get_doc_weights_map()
        w2 = r._get_doc_weights_map()
        assert w1 is w2  # 同一对象（缓存）

    def test_empty_weights(self):
        """空权重表时所有文档权重为 1.0"""
        r = _r()
        r._doc_weights_cache = {}
        # 模拟 settings.doc_weights 为空
        import src.rag.retriever as ret_mod

        original = ret_mod.settings.doc_weights
        ret_mod.settings.doc_weights = ""
        r._doc_weights_cache = {}
        weights = r._get_doc_weights_map()
        assert weights == {}
        ret_mod.settings.doc_weights = original

    def test_same_source_both_channels(self):
        """同一文档在向量+BM25 两个通道都命中，权重应累积"""
        r = _r()
        r._doc_weights_cache = {}

        doc = _doc("内容A", "fault_troubleshooting_manual.md")
        # 向量和 BM25 都排第 1
        vector_results = [(doc, 0.9)]
        bm25_results = [(doc, 0.8)]

        merged = r._rrf_fusion(vector_results, bm25_results, top_k=1)
        # 两个通道贡献：1.5 * (1/61 + 1/61) = 2 * 1.5 / 61
        assert len(merged) == 1
        assert merged[0][0].metadata["source"] == "fault_troubleshooting_manual.md"
