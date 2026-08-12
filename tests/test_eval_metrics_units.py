"""评估指标模块单元测试（纯逻辑部分 + LLM-Judge 早退/模拟路径）"""
import json

import pytest

from src.evaluation import metrics as M


class _FakeLLM:
    """返回固定 JSON 的假 LLM，覆盖 DialogueJudge.evaluate 的 LLM 分支"""

    class _Resp:
        content = json.dumps({
            "relevance": 4, "accuracy": 5, "completeness": 4,
            "safety": 5, "tone": 4, "overall": 4.4,
            "needs_human_review": False, "flags": [],
        })

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
