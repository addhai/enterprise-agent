"""EvaluationTracker 单元测试

覆盖：
- record_chat（记录对话）
- stats（汇总统计）
- 空统计 / 有数据统计
- 会话级统计（resolved / needs_human）
- 单例 get_evaluation_tracker
"""
import pytest

from src.evaluation.tracker import EvaluationTracker, get_evaluation_tracker


@pytest.fixture
def tracker():
    """每个测试用新的 EvaluationTracker"""
    return EvaluationTracker()


# ============================================================
# record_chat
# ============================================================

class TestRecordChat:
    def test_record_basic_chat(self, tracker):
        tracker.record_chat(
            session_id="s1",
            intent="faq",
            latency_ms=100.0,
        )
        assert len(tracker._records) == 1
        assert tracker._records[0]["session_id"] == "s1"
        assert tracker._records[0]["intent"] == "faq"
        assert tracker._records[0]["latency_ms"] == 100.0

    def test_record_with_all_fields(self, tracker):
        tracker.record_chat(
            session_id="s2",
            intent="rag",
            latency_ms=200.0,
            quality_score=0.8,
            needs_human=False,
            suggest_human=False,
            turn_count=3,
            resolved=True,
        )
        record = tracker._records[0]
        assert record["quality_score"] == 0.8
        assert record["needs_human"] is False
        assert record["resolved"] is True
        assert record["turn_count"] == 3

    def test_record_updates_session_stats(self, tracker):
        tracker.record_chat("s1", "faq", 100, resolved=True)
        tracker.record_chat("s1", "rag", 200, needs_human=True)

        sess = tracker._sessions["s1"]
        assert sess["total_turns"] == 2
        assert sess["needs_human"] is True
        assert sess["resolved"] is True

    def test_record_creates_new_session(self, tracker):
        tracker.record_chat("s-new", "faq", 50)
        sess = tracker._sessions["s-new"]
        assert sess["total_turns"] == 1
        assert sess["needs_human"] is False
        assert sess["resolved"] is None


# ============================================================
# stats — 空数据
# ============================================================

class TestEmptyStats:
    def test_empty_tracker_stats(self, tracker):
        stats = tracker.stats()
        assert stats["total_requests"] == 0
        assert stats["total_sessions"] == 0
        assert stats["resolved"] == 0
        assert stats["unresolved"] == 0
        assert stats["resolution_rate"] == 0
        assert stats["avg_latency_ms"] == 0
        assert stats["avg_quality_score"] == 0
        assert stats["escalation_rate"] == 0
        assert stats["avg_turns"] == 0


# ============================================================
# stats — 有数据
# ============================================================

class TestStatsWithData:
    def test_resolution_rate_calculation(self, tracker):
        tracker.record_chat("s1", "faq", 100, resolved=True)
        tracker.record_chat("s2", "rag", 200, resolved=False)
        tracker.record_chat("s3", "human", 300, needs_human=True)

        stats = tracker.stats()
        assert stats["total_requests"] == 3
        assert stats["total_sessions"] == 3
        assert stats["resolved"] == 1
        assert stats["unresolved"] == 2
        assert abs(stats["resolution_rate"] - 1 / 3) < 0.01

    def test_avg_latency_calculation(self, tracker):
        tracker.record_chat("s1", "faq", 100.0)
        tracker.record_chat("s2", "rag", 300.0)
        tracker.record_chat("s3", "faq", 200.0)

        stats = tracker.stats()
        assert abs(stats["avg_latency_ms"] - 200.0) < 0.01

    def test_avg_quality_score_calculation(self, tracker):
        tracker.record_chat("s1", "faq", 100, quality_score=0.6)
        tracker.record_chat("s2", "rag", 200, quality_score=0.9)
        tracker.record_chat("s3", "faq", 200, quality_score=None)

        stats = tracker.stats()
        assert abs(stats["avg_quality_score"] - 0.75) < 0.01

    def test_escalation_rate_calculation(self, tracker):
        tracker.record_chat("s1", "faq", 100, needs_human=False)
        tracker.record_chat("s2", "rag", 200, needs_human=True)
        tracker.record_chat("s3", "faq", 200, needs_human=True)

        stats = tracker.stats()
        assert abs(stats["escalation_rate"] - 2 / 3) < 0.01

    def test_avg_turns_calculation(self, tracker):
        tracker.record_chat("s1", "faq", 100)
        tracker.record_chat("s1", "rag", 200)
        tracker.record_chat("s2", "faq", 100)

        stats = tracker.stats()
        # s1 有 2 turns，s2 有 1 turn，总共 3 turns / 2 sessions = 1.5
        assert abs(stats["avg_turns"] - 1.5) < 0.01

    def test_uptime_seconds_positive(self, tracker):
        stats = tracker.stats()
        assert stats["uptime_seconds"] >= 0


# ============================================================
# 会话级统计
# ============================================================

class TestSessionStats:
    def test_resolved_session_count(self, tracker):
        tracker.record_chat("s1", "faq", 100, resolved=True)
        tracker.record_chat("s2", "rag", 200, resolved=True)
        tracker.record_chat("s3", "faq", 100, resolved=False)

        stats = tracker.stats()
        assert stats["resolved"] == 2
        assert stats["unresolved"] == 1

    def test_unresolved_includes_needs_human(self, tracker):
        tracker.record_chat("s1", "faq", 100, resolved=True)
        tracker.record_chat("s2", "rag", 200, needs_human=True)

        stats = tracker.stats()
        assert stats["resolved"] == 1
        assert stats["unresolved"] == 1

    def test_partial_resolved_flag_overwrites(self, tracker):
        """后续 record 用 resolved=True 会覆盖 needs_human 状态"""
        tracker.record_chat("s1", "rag", 200, needs_human=True)
        tracker.record_chat("s1", "faq", 100, resolved=True)

        stats = tracker.stats()
        # s1 resolved=True，且 needs_human=True
        # unresolved 计算: resolved is False OR needs_human
        # s1: resolved=True -> 不计入；但 needs_human=True -> 计入
        # 注意：tracker 的 unresolved 逻辑是 (resolved is False or needs_human)
        # 所以 s1 仍会被计入 unresolved（因为 needs_human=True）
        assert stats["resolved"] == 1
        assert stats["unresolved"] == 1


# ============================================================
# 单例
# ============================================================

class TestSingleton:
    def test_get_evaluation_tracker_returns_same_instance(self):
        t1 = get_evaluation_tracker()
        t2 = get_evaluation_tracker()
        assert t1 is t2

    def test_singleton_is_evaluation_tracker(self):
        t = get_evaluation_tracker()
        assert isinstance(t, EvaluationTracker)


# ============================================================
# Hallucination 计数（v0.7 新增接线）
# ============================================================

class TestHallucinationStats:
    def test_empty_stats_exposes_hallucination_fields(self, tracker):
        """空 tracker.stats() 也应暴露 hallucinations_detected/blocked 字段（值 0）。"""
        stats = tracker.stats()
        assert "hallucinations_detected" in stats
        assert "hallucinations_blocked" in stats
        assert stats["hallucinations_detected"] == 0
        assert stats["hallucinations_blocked"] == 0

    def test_record_hallucination_detected(self, tracker):
        tracker.record_safety_event("hallucination_detected")
        tracker.record_safety_event("hallucination_detected")
        stats = tracker.stats()
        assert stats["hallucinations_detected"] == 2
        # safety_events 也要包含原始计数
        assert stats["safety_events"].get("hallucination_detected") == 2

    def test_record_hallucination_blocked(self, tracker):
        tracker.record_safety_event("hallucination_blocked")
        stats = tracker.stats()
        assert stats["hallucinations_blocked"] == 1
        assert stats["safety_events"].get("hallucination_blocked") == 1

    def test_hallucination_counts_independent_from_other_safety_events(self, tracker):
        """幻觉计数与 prompt 注入 / 安全违规计数互不污染。"""
        tracker.record_safety_event("hallucination_detected")
        tracker.record_safety_event("hallucination_blocked")
        tracker.record_safety_event("prompt_injection_blocked")
        tracker.record_safety_event("safety_violation")
        stats = tracker.stats()
        assert stats["hallucinations_detected"] == 1
        assert stats["hallucinations_blocked"] == 1
        assert stats["prompt_injections_blocked"] == 1
        assert stats["safety_violations"] == 1
