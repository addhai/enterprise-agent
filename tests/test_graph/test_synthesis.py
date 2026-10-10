"""M3 跨块综合编排的确定性单测。

只测纯规则与纯函数（信号检测、标签剥离、保底补块），不触网、
不起真实 LLM/Embedding。直答函数的 LLM 调用部分由金标真机回归覆盖。
"""

from langchain_core.documents import Document
from src.graph.nodes import (
    _distinct_doc_sources,
    _extract_synthesis_sections,
    _supplement_pre_retrieved_docs,
    detect_synthesis_signals,
    merge_supplement_docs,
    should_use_synthesis,
)

# ---------------------------------------------------------------------------
# 信号检测
# ---------------------------------------------------------------------------


def test_signals_warranty_question():
    """GS02 形态：买了 8 个月报故障问在不在保。"""
    q = "我这台 T90 买了 8 个月，现在报 F02 快门卡滞，这个情况在保修范围内吗？"
    assert detect_synthesis_signals(q) == ["保修"]


def test_signals_return_question():
    """GP06 形态：签收第 5 天质量问题能否退货。"""
    q = "签收第 5 天确认仪器存在非人为质量问题，能退货吗？运费谁承担？"
    assert detect_synthesis_signals(q) == ["退货"]


def test_signals_conflict_question():
    """GS01 形态：两份资料参数冲突以哪个为准。"""
    q = "两份资料参数不一致，一个写 500℃ 一个写 550℃，到底以哪个为准？"
    signals = detect_synthesis_signals(q)
    assert "规格说明书 为准" in signals


def test_signals_multiple_signals_dedup_and_order():
    """同时命中保修与退货时按词典优先级返回，且不重复。"""
    signals = detect_synthesis_signals("退货和保修冲突吗，保修内能不能换货退款")
    assert signals[0] == "保修"
    assert "退货" in signals
    assert len(signals) == len(set(signals))


def test_signals_plain_fault_question_no_hit():
    """普通故障处理题不触发保底，避免无谓补块挤占上下文。"""
    assert detect_synthesis_signals("F02 快门卡滞怎么处理？") == []
    assert detect_synthesis_signals("T90 探测器分辨率是多少？") == []


def test_signals_empty_string():
    assert detect_synthesis_signals("") == []


# ---------------------------------------------------------------------------
# 二级门控 should_use_synthesis（50 题 A/B 对照数据驱动，2026-10-09）
# ---------------------------------------------------------------------------


def _doc_with_source(source: str, content: str = "x") -> Document:
    return Document(page_content=content, metadata={"source": source})


def test_gate_multi_source_fact_question_enabled():
    """GS01 形态：跨文档参数冲突裁决，必须启用。"""
    docs = [
        _doc_with_source("product_spec_manual.md"),
        _doc_with_source("application_guide.md"),
    ]
    assert should_use_synthesis("T100 测温上限和距离系数以哪个为准？", docs) is True


def test_gate_warranty_status_multi_source_enabled():
    """GS02 形态：在保判定跨故障手册与售后政策，启用。"""
    docs = [
        _doc_with_source("t90_service_manual.pdf"),
        _doc_with_source("after_sales_policy.md"),
    ]
    assert should_use_synthesis("买了 8 个月报 F02，在保修范围内吗？", docs) is True


def test_gate_single_source_disabled():
    """GP06 形态：只有售后政策一个来源，同文档多事实无跨块可综。"""
    docs = [_doc_with_source("after_sales_policy.md") for _ in range(3)]
    assert should_use_synthesis("签收第 5 天能退货吗？运费谁承担？", docs) is False


def test_gate_empty_docs_disabled():
    assert should_use_synthesis("任意问题", []) is False


def test_gate_step_question_bypassed_even_multi_source():
    """GS14/GP01 形态：步骤清单题即便多来源也走 M2，防 coverage 挤占长答案。"""
    docs = [_doc_with_source("maintenance_guide.md"), _doc_with_source("faq_full.md")]
    assert should_use_synthesis("镜头沾了指纹油污，正确清洁步骤是什么？", docs) is False
    assert (
        should_use_synthesis("请写出冰水 0℃ 点自校验的完整步骤和判定标准。", docs)
        is False
    )


def test_gate_all_flow_words_bypassed():
    docs = [_doc_with_source("a.md"), _doc_with_source("b.md")]
    for word in [
        "操作流程",
        "测试清单",
        "校准规程",
        "数据采集怎么操作",
        "如何操作复位",
        "操作顺序",
        "拆机前几步",
    ]:
        assert should_use_synthesis(word, docs) is False, word


def test_gate_tuple_form_docs_supported():
    """检索链直接传 (Document, score) 元组时同样识别来源。"""
    docs = [
        (_doc_with_source("a.md"), 0.9),
        (_doc_with_source("b.md"), 0.8),
    ]
    assert should_use_synthesis("两个来源的事实综合题", docs) is True


def test_gate_missing_metadata_tolerated():
    bare = Document(page_content="无元数据块", metadata={})
    assert should_use_synthesis("问题", [bare, _doc_with_source("b.md")]) is False


def test_distinct_sources_dedupes_chunks():
    """同一文档多个 chunk 只算一个来源。"""
    docs = [_doc_with_source("same.pdf") for _ in range(5)]
    assert _distinct_doc_sources(docs) == {"same.pdf"}


def test_gate_none_question_disabled():
    docs = [_doc_with_source("a.md"), _doc_with_source("b.md")]
    assert should_use_synthesis("", docs) is False


# ---------------------------------------------------------------------------
# 保底补块合并
# ---------------------------------------------------------------------------


def _doc(content: str, source: str = "s.md") -> Document:
    return Document(page_content=content, metadata={"source": source})


def test_merge_supplement_appends_new_docs():
    primary = [_doc("块A内容"), _doc("块B内容")]
    supplement = [_doc("块C内容", "policy.md")]

    merged = merge_supplement_docs(primary, supplement, max_total=6)

    assert [d.page_content for d in merged] == ["块A内容", "块B内容", "块C内容"]


def test_merge_supplement_dedupes_by_content_prefix():
    """同一块（前 100 字相同）不得重复注入。"""
    same_text = "完全相同的政策块内容" * 20
    primary = [_doc(same_text, "policy.md")]
    supplement = [_doc(same_text, "policy.md"), _doc("另一块", "faq.md")]

    merged = merge_supplement_docs(primary, supplement, max_total=6)

    assert len(merged) == 2
    assert merged[1].page_content == "另一块"


def test_merge_supplement_respects_max_total():
    primary = [_doc(f"主块{i}") for i in range(5)]
    supplement = [_doc(f"补块{i}", "policy.md") for i in range(3)]

    merged = merge_supplement_docs(primary, supplement, max_total=6)

    assert len(merged) == 6
    assert merged[5].page_content == "补块0"


def test_merge_supplement_empty_inputs():
    # 调用方（rag_node）只在主检索非空时调保底；纯函数自身允许空 primary
    assert merge_supplement_docs([], [_doc("x")], max_total=6) == [_doc("x")]
    assert merge_supplement_docs([_doc("x")], [], max_total=6) == [_doc("x")]


# ---------------------------------------------------------------------------
# 保底补块 helper（FakeRetriever，零外部依赖）
# ---------------------------------------------------------------------------


class _FakeRetriever:
    def __init__(self, hits_by_keyword, raise_on=None):
        self._hits = hits_by_keyword
        self._raise_on = raise_on
        self.calls: list[str] = []

    def keyword_search(self, keyword, **kwargs):
        self.calls.append(keyword)
        if self._raise_on and keyword == self._raise_on:
            raise RuntimeError("bm25 boom")
        return list(self._hits.get(keyword, []))


def test_supplement_helper_no_signal_skips_retriever():
    retriever = _FakeRetriever({})
    docs, added = _supplement_pre_retrieved_docs(
        "F02 快门卡滞怎么办",
        [_doc("主块")],
        retriever,
        user_id="u",
        tenant_id="default",
        user_access_levels=None,
    )
    assert retriever.calls == []
    assert added == []
    assert len(docs) == 1


def test_supplement_helper_adds_policy_doc():
    retriever = _FakeRetriever(
        {
            "保修": [_doc("整机保修 12 个月，7 天无理由退货", "after_sales_policy.md")],
        }
    )
    docs, added = _supplement_pre_retrieved_docs(
        "买了 8 个月 F02 在保修范围内吗",
        [_doc("F02 快门卡滞处理步骤", "manual.pdf")],
        retriever,
        user_id="u",
        tenant_id="default",
        user_access_levels=None,
    )
    assert len(docs) == 2
    assert added == [("保修", "after_sales_policy.md")]
    assert "保修 12 个月" in docs[-1].page_content


def test_supplement_helper_swallows_retriever_error():
    retriever = _FakeRetriever({}, raise_on="保修")
    primary = [_doc("主块")]
    docs, added = _supplement_pre_retrieved_docs(
        "保修范围内吗",
        primary,
        retriever,
        user_id="u",
        tenant_id="default",
        user_access_levels=None,
    )
    assert docs == primary  # 异常时原样返回，不阻断主链路
    assert added == []


def test_supplement_helper_without_keyword_search_attr():
    docs, added = _supplement_pre_retrieved_docs(
        "保修范围内吗",
        [_doc("主块")],
        object(),
        user_id="u",
        tenant_id="default",
        user_access_levels=None,
    )
    assert len(docs) == 1
    assert added == []


# ---------------------------------------------------------------------------
# 标签剥离
# ---------------------------------------------------------------------------


def test_extract_well_formed_sections():
    raw = (
        "<coverage>\n① 故障含义 ② 处理方法\n"
        "文档1：F02 快门卡滞\n覆盖：①←文档1 ②←文档1\n</coverage>\n"
        "<answer>\nF02 表示快门卡滞。处理：1.校正 2.检查异物。\n</answer>"
    )
    answer, coverage, well_formed = _extract_synthesis_sections(raw)

    assert well_formed is True
    assert answer.startswith("F02 表示快门卡滞")
    assert "① 故障含义" in coverage
    # 分析段绝不能进答案
    assert "<coverage>" not in answer
    assert "文档1" not in answer


def test_extract_uppercase_tags_tolerated():
    raw = "<COVERAGE>分析</COVERAGE><ANSWER>最终答案</ANSWER>"
    answer, coverage, well_formed = _extract_synthesis_sections(raw)
    assert well_formed is True
    assert answer == "最终答案"
    assert coverage == "分析"


def test_extract_multiple_answer_tags_takes_first():
    raw = "<answer>第一个答案</answer><answer>第二个答案</answer>"
    answer, _, well_formed = _extract_synthesis_sections(raw)
    assert well_formed is True
    assert answer == "第一个答案"


def test_extract_coverage_without_answer_tag_falls_back_to_bare_answer():
    """模型写了 coverage 却忘包 answer：剥离分析段，裸答案不能丢。"""
    raw = "<coverage>提问点①②\n文档1事实</coverage>\n这是直接写在标签外的答案。"
    answer, coverage, well_formed = _extract_synthesis_sections(raw)

    assert well_formed is False
    assert answer == "这是直接写在标签外的答案。"
    assert "提问点" in coverage


def test_extract_no_tags_returns_raw():
    raw = "模型完全不守格式，直接给了一段答案。"
    answer, coverage, well_formed = _extract_synthesis_sections(raw)
    assert well_formed is False
    assert answer == raw
    assert coverage is None


def test_extract_empty_answer_tag_falls_back():
    raw = "<coverage>分析</coverage><answer>   </answer>裸答案文本"
    answer, _, well_formed = _extract_synthesis_sections(raw)
    assert well_formed is False
    assert "裸答案文本" in answer
    assert "分析" not in answer


def test_extract_open_answer_without_closing_tag():
    """真机 2/3 形态：只写 <answer> 开标签就直接作答，无闭合。"""
    raw = "<answer>\n根据文档1和文档3，标准型测温范围为-20℃至550℃，距离系数50:1。"
    answer, coverage, well_formed = _extract_synthesis_sections(raw)

    assert well_formed is False
    assert answer.startswith("根据文档1")
    assert "<answer>" not in answer
    assert "550℃" in answer


def test_extract_open_coverage_and_open_answer():
    """两个标签都漏闭合：coverage 与 answer 仍要正确分离。"""
    raw = (
        "<coverage>\n文档1：7天无理由退货\n文档2：厂家承担运费\n"
        "<answer>\n可以退货，运费由厂家承担，7天内申请。"
    )
    answer, coverage, well_formed = _extract_synthesis_sections(raw)

    assert well_formed is False
    assert answer == "可以退货，运费由厂家承担，7天内申请。"
    assert "7天无理由退货" in coverage
    assert "<coverage>" not in answer and "<answer>" not in answer


def test_extract_open_answer_with_closed_coverage():
    raw = "<coverage>文档1事实</coverage><answer>\n裸答案未闭合"
    answer, coverage, well_formed = _extract_synthesis_sections(raw)
    assert well_formed is False
    assert answer == "裸答案未闭合"
    assert coverage == "文档1事实"


def test_extract_no_tag_residue_in_any_path():
    """标签残骸（含孤立闭合标签）不得外发。"""
    raw = "</answer>正常答案文本</answer>"
    answer, _, _ = _extract_synthesis_sections(raw)
    assert "<answer>" not in answer and "</answer>" not in answer
    assert "正常答案文本" in answer


def test_uncovered_marker_inside_coverage_must_not_trigger():
    """关键防误伤：coverage 说「③无资料」，answer 正常作答时，
    uncovered 判定跑在剥离后的 answer 上，不得误判库外回落 ReAct。"""
    raw = (
        "<coverage>① 含义←文档1 ② 退货期限：无资料</coverage>"
        "<answer>F02 是快门卡滞，请进入维护菜单校正两次。</answer>"
    )
    answer, _, well_formed = _extract_synthesis_sections(raw)
    assert well_formed is True
    # 剥离后的答案不含任何未覆盖标记词
    from src.graph.nodes import _DIRECT_UNANSWERED_MARKERS

    assert not any(m in answer for m in _DIRECT_UNANSWERED_MARKERS)


def test_extract_empty_input():
    answer, coverage, well_formed = _extract_synthesis_sections("")
    assert answer == ""
    assert coverage is None
    assert well_formed is False
