"""查询改写模块单元测试

覆盖：
- 改写前后查询差异
- 故障码/型号不扩展
- 空查询/特殊字符不崩溃
- 配置开关生效
"""

from src.rag.query_rewriter import QueryRewriter, rewrite_query


class TestQueryRewriter:
    def test_basic_rewrite(self):
        """故障排查类查询应被扩展"""
        rewriter = QueryRewriter()
        original = "激光定位灯不亮"
        rewritten = rewriter.rewrite(original)
        assert rewritten != original
        assert "激光灯" in rewritten
        assert "故障" in rewritten

    def test_no_change_for_no_match(self):
        """无匹配规则的查询应返回原文"""
        rewriter = QueryRewriter()
        original = "今天天气怎么样"
        rewritten = rewriter.rewrite(original)
        assert rewritten == original

    def test_fault_code_not_expanded(self):
        """故障码不应被扩展（交给 find_missing_identifiers 处理）"""
        rewriter = QueryRewriter()
        for code in ["E03", "E-03", "T200", "T100-H"]:
            rewritten = rewriter.rewrite(code)
            assert rewritten == code, f"Fault code {code} was expanded: {rewritten}"

    def test_empty_query(self):
        """空查询不应崩溃"""
        rewriter = QueryRewriter()
        assert rewriter.rewrite("") == ""
        assert rewriter.rewrite("   ") == "   "

    def test_special_characters(self):
        """特殊字符不应崩溃"""
        rewriter = QueryRewriter()
        for q in [
            "'; DROP TABLE--",
            "<script>alert(1)</script>",
            "测\r\n试",
            "null\x00byte",
        ]:
            result = rewriter.rewrite(q)
            assert isinstance(result, str)

    def test_synonym_expansion_content(self):
        """无法开机应扩展出电源键等词"""
        rewriter = QueryRewriter()
        rewritten = rewriter.rewrite("无法开机")
        assert "电源键" in rewritten
        assert "无显示" in rewritten

    def test_batch_rewrite(self):
        """批量改写"""
        rewriter = QueryRewriter()
        queries = ["无法开机", "激光不亮", "E03"]
        results = rewriter.rewrite_batch(queries)
        assert len(results) == 3
        assert results[0] != queries[0]  # 扩展了
        assert results[2] == queries[2]  # 故障码不扩展

    def test_rewrite_query_function(self):
        """便捷函数"""
        result = rewrite_query("测温偏差大")
        assert "校准" in result
        assert "发射率" in result


class TestRewriteConfigSwitch:
    """配置开关测试（通过 settings.rewrite_enabled 控制）"""

    def test_config_exists(self):
        """settings 应有 rewrite_enabled 配置项"""
        from src.config import settings

        assert hasattr(settings, "rewrite_enabled")
        assert settings.rewrite_enabled is True

    def test_doc_weights_config_exists(self):
        """settings 应有 doc_weights 配置项"""
        from src.config import settings

        assert hasattr(settings, "doc_weights")
        assert isinstance(settings.doc_weights, str)
        assert "fault_troubleshooting" in settings.doc_weights
