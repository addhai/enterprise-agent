"""graph/nodes.py 纯逻辑 helper 单元测试（确定性，不触网/不依赖 LLM）"""

from types import SimpleNamespace

from src.graph.nodes import (
    _detect_missing_info,
    _detect_negative_emotion,
    _generate_clarification_question,
    _is_nonsensical_input,
    _is_refusal_response,
    _looks_like_react_output,
    _rewrite_query,
    _try_infer_from_memory,
    query_corpus_bigram_overlap,
)


def _doc(text):
    return SimpleNamespace(page_content=text)


class TestIsNonsensicalInput:
    def test_short(self):
        assert _is_nonsensical_input("a") is True

    def test_pure_digits(self):
        assert _is_nonsensical_input("12345") is True

    def test_pure_symbols(self):
        assert _is_nonsensical_input("!!!???") is True

    def test_repeated_chars(self):
        assert _is_nonsensical_input("哈哈哈") is True

    def test_gibberish_digits(self):
        # 长度>5、中英文<2、数字占比>80%
        assert _is_nonsensical_input("1234567890") is True

    def test_normal(self):
        assert _is_nonsensical_input("我的订单什么时候发货") is False

    def test_empty(self):
        assert _is_nonsensical_input("") is True


class TestLooksLikeReact:
    def test_action(self):
        assert _looks_like_react_output("Action: search_knowledge_base") is True

    def test_final_answer(self):
        assert _looks_like_react_output("Final Answer: 这是答案") is True

    def test_normal(self):
        assert _looks_like_react_output("这是一段正常回复") is False

    def test_empty(self):
        assert _looks_like_react_output("") is False


class TestIsRefusal:
    def test_sing(self):
        assert _is_refusal_response("我是 CloudSync 客服，不唱歌") is True

    def test_unsupported(self):
        assert _is_refusal_response("不支持音乐播放功能") is True

    def test_normal(self):
        assert _is_refusal_response("好的，我来帮您查询。") is False

    def test_empty(self):
        assert _is_refusal_response("") is False


class TestDetectMissingInfo:
    def test_error_no_code(self):
        r = _detect_missing_info("我的程序报错了", "")
        assert "错误码或错误详情" in r

    def test_error_with_code(self):
        r = _detect_missing_info("程序报错 code 404", "")
        assert "错误码或错误详情" not in r

    def test_config_no_product(self):
        r = _detect_missing_info("怎么配置这个服务", "")
        assert "设备型号或产品名称" in r

    def test_normal(self):
        assert _detect_missing_info("你好", "") == []


class TestInferFromMemory:
    def test_sdk_version(self):
        r = _try_infer_from_memory(["SDK 版本"], "用户使用 sdk v2.3 调用")
        assert r.get("SDK 版本") == "v2.3"

    def test_env(self):
        r = _try_infer_from_memory(["技术环境"], "环境是 windows 系统")
        assert r.get("操作系统") == "Windows"

    def test_empty_memory(self):
        assert _try_infer_from_memory(["SDK 版本"], "") == {}

    def test_nothing_missing(self):
        assert _try_infer_from_memory([], "sdk v1") == {}


class TestRewriteQuery:
    def test_no_infer(self):
        assert _rewrite_query("原问题", {}) == "原问题"

    def test_with_infer(self):
        out = _rewrite_query("原问题", {"SDK 版本": "v2.3"})
        assert "v2.3" in out and "原问题" in out


class TestGenerateClarification:
    def test_empty(self):
        assert _generate_clarification_question([], "原问题") == ""

    def test_with_missing(self):
        out = _generate_clarification_question(["错误码或错误详情"], "原问题")
        assert "错误码或错误详情" in out


class TestDetectNegativeEmotion:
    def test_anger(self):
        assert _detect_negative_emotion("气死我了，什么破系统") == "愤怒"

    def test_repeat_exclaim(self):
        assert _detect_negative_emotion("不行不行不行") == "急躁"

    def test_punctuation(self):
        assert _detect_negative_emotion("到底行不行啊！！！") == "急躁"

    def test_none(self):
        assert _detect_negative_emotion("谢谢您的帮助") is None

    def test_empty(self):
        assert _detect_negative_emotion("") is None

    def test_operation_word_not_anger_gp04_gp07(self):
        # 单字「操」误伤回归（金标题 GP04/GP07 实测）：
        # 正常「操作/操作步骤」不得被判为愤怒转人工
        assert _detect_negative_emotion("一个校准点的数据采集怎么操作") is None
        assert _detect_negative_emotion("设置高温报警阈值的按键操作步骤") is None

    def test_explicit_profanity_still_detected(self):
        # 收紧词表后明确脏话仍要检出
        assert _detect_negative_emotion("这破东西操蛋得很") == "愤怒"
        assert _detect_negative_emotion("操你妈的破系统") == "愤怒"


class TestQueryCorpusBigramOverlap:
    def test_gr05_printer_near_zero(self):
        # GR05 实测：打印机/卡纸在测温语料零出现，仅「激光」偶命中
        docs = [
            _doc("T100 红外测温仪激光定位说明与常见故障维修条目"),
        ]
        ratio = query_corpus_bigram_overlap(
            "顺便问一下，我办公室的激光打印机卡纸了怎么修？", docs
        )
        assert ratio < 0.12

    def test_gp04_calibration_high_overlap(self):
        # GP04 实测：校准/读数/稳定/仪器/设置在召回语料高频
        docs = [
            _doc(
                "专业黑体校准一个校准点的数据采集：仪器发射率设置，"
                "读数次数连续10次，稳定判据为读数稳定"
            ),
        ]
        ratio = query_corpus_bigram_overlap(
            "专业黑体校准时一个校准点的数据采集怎么操作（仪器设置、读数次数、稳定判据）",
            docs,
        )
        assert ratio > 0.3

    def test_english_token_match(self):
        docs = [_doc("ThermoView T100 supports USB data export to CSV files.")]
        ratio = query_corpus_bigram_overlap("T100 USB CSV export?", docs)
        assert ratio >= 0.5

    def test_no_content_words_returns_one(self):
        # 提不出实词时返回 1.0，宁可不收口也不误伤
        assert query_corpus_bigram_overlap("怎么？", [_doc("无关内容")]) == 1.0
        assert query_corpus_bigram_overlap("", [_doc("无关内容")]) == 1.0

    def test_empty_docs_zero_overlap(self):
        ratio = query_corpus_bigram_overlap("打印机卡纸怎么修", [])
        assert ratio == 0.0
