"""评估指标模块单元测试（纯逻辑部分 + LLM-Judge 早退/模拟路径）"""

import json

from src.evaluation import metrics as M


class _FakeLLM:
    """返回固定 JSON 的假 LLM，覆盖 DialogueJudge.evaluate 的 LLM 分支"""

    class _Resp:
        content = json.dumps(
            {
                "relevance": 4,
                "accuracy": 5,
                "completeness": 4,
                "safety": 5,
                "tone": 4,
                "overall": 4.4,
                "needs_human_review": False,
                "flags": [],
            }
        )

    def invoke(self, prompt):
        return self._Resp()


class TestEvaluateRetrieval:
    def test_perfect(self):
        r = M.evaluate_retrieval(["a", "b"], ["a", "b"])
        assert r["recall"] == 1.0 and r["precision"] == 1.0 and r["mrr"] == 1.0

    def test_partial(self):
        r = M.evaluate_retrieval(["a", "b", "c"], ["a"])
        assert r["recall"] == 1.0
        assert r["precision"] == round(1 / 3, 4)
        assert r["f1"] > 0

    def test_empty_expected(self):
        r = M.evaluate_retrieval(["a"], [])
        assert r == {"recall": 1.0, "precision": 1.0, "mrr": 1.0, "f1": 1.0}

    def test_no_relevant(self):
        r = M.evaluate_retrieval(["x", "y"], ["a"])
        assert r["recall"] == 0.0
        assert r["precision"] == 0.0


class TestMRR:
    def test_found(self):
        assert M.mean_reciprocal_rank([["x", "a"]], {"a"}) == 1 / 2

    def test_not_found(self):
        assert M.mean_reciprocal_rank([["x", "y"]], {"a"}) == 0.0

    def test_empty(self):
        assert M.mean_reciprocal_rank([], {"a"}) == 0.0


class TestDialogueJudge:
    def test_disabled_returns_zeros(self, monkeypatch):
        monkeypatch.setattr(M.settings, "eval_llm_judge_enabled", False)
        j = M.DialogueJudge()
        out = j.evaluate("你好", "默认回复")
        assert out["overall"] == 0.0
        assert out["dimensions"] == {}
        assert out["needs_human_review"] is False

    def test_empty_response_returns_zeros(self, monkeypatch):
        monkeypatch.setattr(M.settings, "eval_llm_judge_enabled", True)
        j = M.DialogueJudge()
        out = j.evaluate("你好", "")
        assert out["overall"] == 0.0

    def test_llm_path_parses(self, monkeypatch):
        monkeypatch.setattr(M.settings, "eval_llm_judge_enabled", True)
        j = M.DialogueJudge()
        j._llm = _FakeLLM()
        out = j.evaluate("你好", "这是一段回复", retrieved_docs=["doc"])
        assert out["overall"] == 4.4
        assert out["dimensions"]["relevance"] == 4
        assert out["needs_human_review"] is False
        assert out["flags"] == []


class TestShouldSample:
    def test_rate_zero(self, monkeypatch):
        monkeypatch.setattr(M.settings, "eval_online_sampling_rate", 0.0)
        assert M.should_sample("user1") is False

    def test_rate_one(self, monkeypatch):
        monkeypatch.setattr(M.settings, "eval_online_sampling_rate", 1.0)
        assert M.should_sample("user1") is True

    def test_deterministic_by_user(self, monkeypatch):
        monkeypatch.setattr(M.settings, "eval_online_sampling_rate", 0.5)
        a = M.should_sample("consistent_user")
        b = M.should_sample("consistent_user")
        assert a == b  # 同一 user 一致


class TestCheckHallucination:
    def test_empty(self):
        assert M.check_hallucination("", [])["is_clean"] is True

    def test_clean(self):
        out = M.check_hallucination(
            "参考 REDIS_TIMEOUT_ERROR 处理",
            [type("D", (), {"page_content": "REDIS_TIMEOUT_ERROR happened"})()],
        )
        assert out["is_clean"] is True

    def test_hallucinated(self):
        out = M.check_hallucination(
            "参考 REDIS_TIMEOUT_ERROR 与 KAFKA_DOWN 处理",
            [type("D", (), {"page_content": "REDIS_TIMEOUT_ERROR 发生"})()],
        )
        assert "KAFKA_DOWN" in out["hallucinated"]
        assert out["is_clean"] is False

    # ---- 2026-11 中文工业语料标识符扩展 ----

    def test_chinese_fault_code_grounded(self):
        # 故障码紧贴汉字，旧 \b 正则无法定界，新断言必须命中且正确接地
        out = M.check_hallucination(
            "F02故障表示测温信号异常，请按手册排查。",
            [type("D", (), {"page_content": "F02：测温传感器信号异常处理流程"})()],
        )
        assert out["hallucinated"] == []
        assert out["is_clean"] is True

    def test_chinese_fault_code_hallucinated(self):
        out = M.check_hallucination(
            "屏幕显示F99，建议重启设备。",
            [type("D", (), {"page_content": "常见故障码为 F02 与 F05"})()],
        )
        assert "F99" in out["hallucinated"]
        assert out["is_clean"] is False

    def test_model_number_grounding(self):
        out = M.check_hallucination(
            "ThermoView T200 的测温上限更高。",
            [type("D", (), {"page_content": "T200 系列规格说明书"})()],
        )
        assert "T200" not in out["hallucinated"]
        assert out["is_clean"] is True

    def test_fabricated_model_detected(self):
        out = M.check_hallucination(
            "T999 旗舰型号支持该功能。",
            [type("D", (), {"page_content": "在售型号为 T100 与 T200"})()],
        )
        assert "T999" in out["hallucinated"]

    def test_parameter_claim_grounded_by_term_name(self):
        # 值的书写格式与资料不同，只要参数名有源就不判幻觉
        out = M.check_hallucination(
            "测温范围：-20℃~550℃",
            [type("D", (), {"page_content": "测温范围 -20 到 550 摄氏度"})()],
        )
        assert out["hallucinated"] == []
        assert out["is_clean"] is True

    def test_parameter_claim_without_source_flagged(self):
        out = M.check_hallucination(
            "防护等级：IP68，可长时间浸水。",
            [type("D", (), {"page_content": "本设备说明书仅介绍测温与充电规范"})()],
        )
        assert any("防护等级" in h for h in out["hallucinated"])
        assert out["is_clean"] is False

    def test_plain_chinese_prose_no_false_positive(self):
        out = M.check_hallucination(
            "设备外壳需要定期清洁，避免灰尘遮挡镜头。",
            [type("D", (), {"page_content": "日常维护包括外壳清洁与镜头保养"})()],
        )
        assert out["hallucinated"] == []
        assert out["is_clean"] is True

    def test_mixed_english_chinese_identifiers(self):
        out = M.check_hallucination(
            "ERR_TIMEOUT 与 F02 同时出现，T200 可参考该流程。",
            [
                type(
                    "D",
                    (),
                    {"page_content": "ERR_TIMEOUT 超时处理；F02 信号异常；T200 手册"},
                )()
            ],
        )
        assert out["hallucinated"] == []
        assert out["score"] == 1.0
