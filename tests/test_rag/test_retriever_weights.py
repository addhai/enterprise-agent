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

    def test_bare_rank_beats_weight_in_rrf(self):
        """裸 RRF 排名优先：高权重不得跨 rank 翻盘（F02 回归教训）

        rank0 的低权重文档必须排在 rank1 的高权重文档前面。
        RRF 相邻 rank 分差仅约 1.6%，1.5x 乘法加权可越过约 20 个 rank，
        会让高权重文档的低相关 chunk 挤掉他源最相关块。
        """
        r = _r()
        r._doc_weights_cache = {}

        doc_low_w_rank0 = _doc("内容A", "faq_full.md")  # 权重 0.8，rank0
        doc_high_w_rank1 = _doc(
            "内容B", "fault_troubleshooting_manual.md"
        )  # 权重 1.5，rank1

        merged = r._rrf_fusion(
            [(doc_low_w_rank0, 0.9), (doc_high_w_rank1, 0.8)],
            [],
            top_k=2,
        )

        assert merged[0][0].metadata["source"] == "faq_full.md"
        assert merged[1][0].metadata["source"] == "fault_troubleshooting_manual.md"

    def test_weight_tiebreak_on_equal_rrf(self):
        """裸 RRF 分完全相同时，高权重文档借平局裁决排前"""
        r = _r()
        r._doc_weights_cache = {}

        doc_high = _doc("内容A", "fault_troubleshooting_manual.md")  # 1.5
        doc_low = _doc("内容B", "faq_full.md")  # 0.8

        # 两个文档分别只在一个通道出现且同为 rank0 → 裸分同为 1/61
        merged = r._rrf_fusion(
            [(doc_high, 0.9)],
            [(doc_low, 0.8)],
            top_k=2,
        )

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


class TestDocWeightsParsing:
    """_parse_doc_weights：JSON 与逗号简写双格式（生产 .env 长期用简写）"""

    def test_shorthand_production_value(self):
        # 与 deploy/prod/.env.production.example 同形的 5 条生产配置
        raw = (
            "fault_troubleshooting_manual.md:1.5,product_spec_manual.md:1.3,"
            "calibration_guide.md:1.2,faq_full.md:0.8,application_guide.md:0.9"
        )
        weights = HybridRetriever._parse_doc_weights(raw)
        assert weights == {
            "fault_troubleshooting_manual.md": 1.5,
            "product_spec_manual.md": 1.3,
            "calibration_guide.md": 1.2,
            "faq_full.md": 0.8,
            "application_guide.md": 0.9,
        }

    def test_shorthand_whitespace_and_trailing_comma(self):
        weights = HybridRetriever._parse_doc_weights(" a.md : 1.2 , b.md:0.7 , ")
        assert weights == {"a.md": 1.2, "b.md": 0.7}

    def test_shorthand_clamps_range(self):
        weights = HybridRetriever._parse_doc_weights("a.md:9,b.md:0.1")
        assert weights == {"a.md": 2.0, "b.md": 0.5}

    def test_json_still_supported(self):
        weights = HybridRetriever._parse_doc_weights('{"a.md": 1.4}')
        assert weights == {"a.md": 1.4}

    def test_empty_returns_empty_dict(self):
        assert HybridRetriever._parse_doc_weights("") == {}
        assert HybridRetriever._parse_doc_weights("   ") == {}

    def test_missing_colon_rejects_whole_config(self):
        # 半份配置不得静默生效：一个条目非法 → 整份判失效
        assert HybridRetriever._parse_doc_weights("a.md:1.5,bad_item") is None

    def test_non_numeric_weight_rejects(self):
        assert HybridRetriever._parse_doc_weights("a.md:heavy") is None

    def test_json_non_dict_rejects(self):
        assert HybridRetriever._parse_doc_weights("[1, 2, 3]") is None

    def test_invalid_config_warns_and_falls_back_to_empty(self, caplog):
        """_get_doc_weights_map 对非法配置告警并按空表（全 1.0）处理"""
        import src.rag.retriever as ret_mod

        original = ret_mod.settings.doc_weights
        ret_mod.settings.doc_weights = "a.md:1.5,not-a-pair"
        try:
            r = _r()
            r._doc_weights_cache = {}
            with caplog.at_level("WARNING"):
                weights = r._get_doc_weights_map()
            assert weights == {}
            assert any("Invalid doc_weights" in rec.message for rec in caplog.records)
        finally:
            ret_mod.settings.doc_weights = original
