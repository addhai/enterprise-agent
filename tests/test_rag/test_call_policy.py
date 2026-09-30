"""rag/call_policy.py 单元测试（Phase5 第一步）

覆盖范围：
    - resolve_mode：三值透传 / 大小写与空白归一 / 未配置 / 非法值回落 always
    - normalize_text + content_key：全角半角统一、空白折叠、前 100 字符相同的回归用例
    - dedup_docs：内容级去重、保留高分、doc_id|page 辅键、缺字段安全性
    - apply_rules：闲聊 / 操作指令 / 指代承接三类规则 + 技术特征闸门反例
    - judge_probe：空列表 / 向量相似度绝对信号 / RRF 原始分下限 / 无信号退化
    - decide_retrieval：两段式契约（needs_probe、probe_reused）、异常回落
    - warn_if_over_budget：软上限 3 次 warning 不阻断
    - 模块纯度：不得依赖 settings / 网络库（纯函数约束）

全部为纯逻辑用例：不联网、不依赖 LLM、不触碰数据库。
"""

import inspect

import pytest
from langchain_core.documents import Document
from src.rag import call_policy
from src.rag.call_policy import (
    MODE_ALWAYS,
    MODE_NEVER,
    MODE_SMART,
    SOFT_RETRIEVAL_LIMIT,
    apply_rules,
    content_key,
    decide_retrieval,
    dedup_docs,
    doc_dedup_keys,
    judge_probe,
    normalize_text,
    resolve_mode,
    warn_if_over_budget,
)


def _doc(text, **meta):
    return Document(page_content=text, metadata=dict(meta))


# ---------------------------------------------------------------- resolve_mode
@pytest.mark.parametrize("raw", [MODE_ALWAYS, MODE_SMART, MODE_NEVER])
def test_resolve_mode_passthrough(raw):
    assert resolve_mode(raw) == (raw, False)


@pytest.mark.parametrize("raw", [" SMART ", "smart", "Never", "\talways\n"])
def test_resolve_mode_normalizes_case_and_space(raw):
    mode, fallback = resolve_mode(raw)
    assert mode in (MODE_ALWAYS, MODE_SMART, MODE_NEVER)
    assert fallback is False


def test_resolve_mode_unset_uses_default_without_fallback_flag():
    assert resolve_mode(None) == (MODE_ALWAYS, False)
    assert resolve_mode("") == (MODE_ALWAYS, False)
    assert resolve_mode("   ") == (MODE_ALWAYS, False)


@pytest.mark.parametrize("raw", ["automatic", "smart2", "smartly", "1", "真假"])
def test_resolve_mode_invalid_falls_back_to_always(raw):
    assert resolve_mode(raw) == (MODE_ALWAYS, True)


def test_resolve_mode_custom_default():
    assert resolve_mode("bogus", default=MODE_NEVER) == (MODE_NEVER, True)


# ------------------------------------------------- normalize_text / content_key
def test_normalize_text_fullwidth_to_halfwidth():
    assert normalize_text("Ｅ－２０７１") == "E-2071"
    # NFKC 连带效果：℃(U+2103) 被分解为 °C，两侧一致即可
    assert normalize_text("８５℃") == "85°C"


def test_normalize_text_collapses_whitespace():
    assert normalize_text("  冷却水\n\t进水   温度  ") == "冷却水 进水 温度"


def test_normalize_text_none_and_non_str():
    assert normalize_text(None) == ""
    assert normalize_text(2071) == "2071"


def test_content_key_ignores_width_and_space_diff():
    assert content_key("Ｅ－２０７１ 报警") == content_key("E-2071  报警")


def test_content_key_distinguishes_different_content():
    assert content_key("冷却水进水温度") != content_key("冷却水出水温度")


def test_content_key_prefix_100_same_tail_differs():
    """回归用例：旧 [:100] 截断式去重会误判为重复，内容级哈希必须区分。"""
    prefix = "E" * 100
    a = prefix + "报警阈值 85 度"
    b = prefix + "报警阈值 105 度"
    assert content_key(a) != content_key(b)


def test_doc_dedup_keys_aux_from_source_and_page():
    ck, aux = doc_dedup_keys(_doc("正文", source="manual.md", page=3))
    assert len(ck) == 40
    assert aux == "manual.md|3"


def test_doc_dedup_keys_aux_none_when_fields_missing():
    _, aux = doc_dedup_keys(_doc("正文"))
    assert aux is None
    _, aux2 = doc_dedup_keys(_doc("正文", doc_id="d1"))
    assert aux2 is None


# ------------------------------------------------------------------- dedup_docs
def test_dedup_keeps_higher_score_on_same_content():
    low = _doc("冷却水进水温度", raw_score=0.01)
    high = _doc("冷却水进水温度", raw_score=0.03)
    out = dedup_docs([low, high])
    assert out == [high]


def test_dedup_keeps_lower_only_when_it_is_first_and_higher():
    a = _doc("冷却水进水温度", raw_score=0.03)
    b = _doc("冷却水进水温度", raw_score=0.01)
    assert dedup_docs([a, b]) == [a]


def test_dedup_treats_fullwidth_variants_as_duplicate():
    a = _doc("Ｅ－２０７１ 报警", raw_score=0.02)
    b = _doc("E-2071 报警", raw_score=0.02)
    assert len(dedup_docs([a, b])) == 1


def test_dedup_keeps_prefix_100_same_tail_different():
    prefix = "E" * 100
    a = _doc(prefix + "阈值 85", raw_score=0.02)
    b = _doc(prefix + "阈值 105", raw_score=0.02)
    assert len(dedup_docs([a, b])) == 2


def test_dedup_aux_key_collapses_same_page_chunks():
    a = _doc("第一段正文", doc_id="d1", page=2, raw_score=0.01)
    b = _doc("第二段正文（同页不同切片）", doc_id="d1", page=2, raw_score=0.02)
    assert dedup_docs([a, b]) == [b]


def test_dedup_preserves_order_and_handles_empty():
    d1 = _doc("甲", raw_score=0.02)
    d2 = _doc("乙", raw_score=0.02)
    assert dedup_docs([d1, d2]) == [d1, d2]
    assert dedup_docs([]) == []
    assert dedup_docs(None) == []


def test_dedup_score_fallback_to_relative_score():
    a = _doc("同内容", score=0.4)
    b = _doc("同内容", score=0.9)
    assert dedup_docs([a, b]) == [b]


def test_dedup_safe_with_missing_metadata():
    class _Bare:
        page_content = "纯文本无 metadata"

    out = dedup_docs([_Bare(), _Bare()])
    assert len(out) == 1


# ----------------------------------------------------------- warn_if_over_budget
def test_budget_within_limit_no_warning(caplog):
    with caplog.at_level("WARNING"):
        assert warn_if_over_budget(SOFT_RETRIEVAL_LIMIT) is False
    assert not caplog.records


def test_budget_over_limit_warns_but_not_blocks(caplog):
    with caplog.at_level("WARNING"):
        assert (
            warn_if_over_budget(4, query="冷却水进水温度是多少", source="probe") is True
        )
    assert any("超软上限" in r.getMessage() for r in caplog.records)


def test_budget_custom_limit():
    assert warn_if_over_budget(2, limit=1) is True


# ------------------------------------------------------------------ apply_rules
@pytest.mark.parametrize(
    "question",
    [
        "你好",
        "您好！",
        "谢谢啦",
        "在吗？",
        "辛苦了，先这样吧",
        "Hello~~~",
        "嗯嗯",
        "好的",
    ],
)
def test_rules_chitchat(question):
    verdict = apply_rules(question)
    assert verdict.matched is True
    assert verdict.rule == "chitchat"


@pytest.mark.parametrize(
    "question",
    [
        "你好，E-2071 报警怎么处理？",
        "E-2071 冷却水进水温度是多少",
        "帮我查下 XG-9000 的保养周期",
    ],
)
def test_rules_technical_hint_blocks_short_circuit(question):
    """技术特征闸门：混流提问绝不能被寒暄规则误杀。"""
    assert apply_rules(question).matched is False


@pytest.mark.parametrize("question", ["帮我转人工", "我要投诉", "麻烦开个工单"])
def test_rules_operation_short_circuit(question):
    verdict = apply_rules(question)
    assert verdict.matched is True
    assert verdict.rule == "operation"


def test_rules_operation_blocked_by_technical_hint():
    """「工单提交后多久处理」是知识问题，不是操作指令，不得短路。"""
    assert apply_rules("工单提交后多久处理？").matched is False


def test_rules_followup_requires_prior_citations():
    assert apply_rules("继续说").matched is False
    verdict = apply_rules("继续说", has_prior_citations=True)
    assert (verdict.matched, verdict.rule) == (True, "followup")


def test_rules_followup_with_technical_word_not_short_circuited():
    assert (
        apply_rules("上面那个再详细说下参数", has_prior_citations=True).matched is False
    )


@pytest.mark.parametrize("question", ["", None, "   "])
def test_rules_empty_or_noise(question):
    assert apply_rules(question).matched is False


def test_rules_punctuation_only_is_chitchat():
    assert apply_rules("！！").matched is True


def test_rules_single_char_acknowledgement_is_chitchat():
    verdict = apply_rules("嗯")
    assert (verdict.matched, verdict.rule) == (True, "chitchat")


@pytest.mark.parametrize(
    "question",
    ["谢谢，那个阀门要注意什么？", "收到，E-2071 报警怎么处理", "好的，那保养周期呢"],
)
def test_rules_greeting_plus_real_question_not_short_circuited(question):
    """混流提问（寒暄 + 实质问题）必须放行检索。"""
    assert apply_rules(question).matched is False


# ------------------------------------------------------------------ judge_probe
def test_judge_probe_empty_list_rejects():
    verdict = judge_probe([])
    assert verdict.should_inject is False
    assert verdict.signal == "empty"
    assert (verdict.hit_count, verdict.doc_count) == (0, 0)


def test_judge_probe_nonempty_without_absolute_signal_injects():
    verdict = judge_probe([_doc("正文", score=1.0, raw_score=0.03)])
    assert verdict.should_inject is True
    assert verdict.signal == "nonempty"
    assert verdict.hit_count == 1
    assert verdict.top1_rel_score == 1.0
    assert verdict.top1_raw_score == 0.03


def test_judge_probe_vector_similarity_threshold_hit():
    docs = [
        _doc("甲", vector_similarity=0.31, score=1.0),
        _doc("乙", vector_similarity=0.22, score=0.9),
        _doc("丙", vector_similarity=0.11, score=0.8),
    ]
    verdict = judge_probe(docs, min_vector_similarity=0.2)
    assert verdict.signal == "vector_similarity"
    assert verdict.hit_count == 2
    assert verdict.should_inject is True


def test_judge_probe_vector_similarity_threshold_reject():
    verdict = judge_probe(
        [_doc("甲", vector_similarity=0.11), _doc("乙", vector_similarity=0.05)],
        min_vector_similarity=0.2,
    )
    assert verdict.should_inject is False
    assert verdict.hit_count == 0


def test_judge_probe_falls_through_when_vector_field_absent():
    verdict = judge_probe([_doc("甲", score=1.0)], min_vector_similarity=0.2)
    assert verdict.signal == "nonempty"


def test_judge_probe_raw_rrf_threshold():
    docs = [_doc("甲", raw_score=0.0328), _doc("乙", raw_score=0.0164)]
    hit = judge_probe(docs, min_raw_score=0.02)
    assert (hit.signal, hit.hit_count, hit.should_inject) == ("raw_rrf", 1, True)


def test_judge_probe_raw_rrf_reject_below_threshold():
    verdict = judge_probe([_doc("甲", raw_score=0.0164)], min_raw_score=0.02)
    assert verdict.should_inject is False
    assert verdict.signal == "raw_rrf"


def test_judge_probe_raw_score_invalid_value_treated_as_missing():
    verdict = judge_probe([_doc("甲", raw_score="not-a-number")], min_raw_score=0.02)
    assert verdict.signal == "nonempty"


def test_judge_probe_vector_similarity_takes_priority_over_raw():
    docs = [_doc("甲", vector_similarity=0.9, raw_score=0.01)]
    verdict = judge_probe(docs, min_vector_similarity=0.2, min_raw_score=0.02)
    assert verdict.signal == "vector_similarity"


def test_judge_probe_handles_none_and_doc_without_metadata():
    class _Bare:
        page_content = "纯文本"

    assert judge_probe(None).signal == "empty"
    assert judge_probe([_Bare()]).signal == "nonempty"


# -------------------------------------------------------------- decide_retrieval
def test_decide_rule_hit_skips_retrieval_without_probe():
    decision = decide_retrieval("你好")
    assert decision.should_retrieve is False
    assert decision.reason == "rule"
    assert decision.rule == "chitchat"
    assert decision.needs_probe is False
    assert decision.probe_reused is False


def test_decide_without_probe_requests_probe():
    decision = decide_retrieval("E-2071 冷却水进水温度是多少")
    assert decision.should_retrieve is True
    assert decision.reason == "fallback"
    assert decision.signal == "missing_probe"
    assert decision.needs_probe is True
    assert decision.probe_reused is False


def test_decide_probe_hit_reuses_probe_result():
    docs = [_doc("冷却水进水温度 85℃", score=1.0, raw_score=0.03)]
    decision = decide_retrieval("冷却水进水温度是多少", probe_docs=docs)
    assert decision.should_retrieve is True
    assert decision.reason == "score"
    assert decision.probe_reused is True
    assert decision.doc_count == 1
    assert decision.needs_probe is False


def test_decide_probe_empty_rejects_without_extra_retrieval():
    decision = decide_retrieval("冷却水进水温度是多少", probe_docs=[])
    assert decision.should_retrieve is False
    assert decision.reason == "score_reject"
    assert decision.signal == "empty"
    assert decision.probe_reused is False


def test_decide_probe_reject_with_vector_signal():
    docs = [_doc("无关文档", vector_similarity=0.05)]
    decision = decide_retrieval(
        "今天午饭吃什么", probe_docs=docs, min_vector_similarity=0.2
    )
    assert decision.should_retrieve is False
    assert decision.reason == "score_reject"
    assert decision.signal == "vector_similarity"
    assert decision.hit_count == 0


def test_decide_exception_falls_back_to_retrieval():
    class _Boom:
        def __str__(self):
            raise RuntimeError("boom")

    decision = decide_retrieval(_Boom())
    assert decision.should_retrieve is True
    assert decision.reason == "fallback"
    assert decision.signal == "policy_error"


# ------------------------------------------------------------------- 模块纯度
def test_module_has_no_settings_or_network_dependency():
    src = inspect.getsource(call_policy)
    for forbidden in ("src.config", "requests", "httpx", "openai", "aiohttp"):
        assert forbidden not in src


def test_module_public_api_is_stable():
    for name in (
        "resolve_mode",
        "normalize_text",
        "content_key",
        "doc_dedup_keys",
        "dedup_docs",
        "warn_if_over_budget",
        "apply_rules",
        "judge_probe",
        "decide_retrieval",
    ):
        assert callable(getattr(call_policy, name))
