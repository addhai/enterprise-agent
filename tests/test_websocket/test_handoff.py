"""转接上下文构建器单元测试

覆盖 handoff.py：
- build_handoff_context 完整构建
- _build_summary 摘要生成
- _build_attempted_solutions 已尝试方案提取
- _build_user_profile 用户画像
- _assess_urgency 紧急度评估
- _analyze_blocker 卡点分析
"""
import pytest

from langchain_core.messages import HumanMessage, AIMessage

from src.websocket.handoff import (
    build_handoff_context,
    _build_summary,
    _build_attempted_solutions,
    _build_user_profile,
    _assess_urgency,
    _analyze_blocker,
)


# ============================================================
# 摘要构建
# ============================================================

class TestBuildSummary:
    def test_empty_messages(self):
        summary = _build_summary([], "unknown", None)
        assert "用户刚进入对话" in summary

    def test_single_user_message(self):
        msgs = [HumanMessage(content="我的密码忘了")]
        summary = _build_summary(msgs, "faq", None)
        assert "密码忘了" in summary

    def test_multiple_user_messages(self):
        msgs = [
            HumanMessage(content="初始问题"),
            AIMessage(content="回复"),
            HumanMessage(content="追问1"),
        ]
        summary = _build_summary(msgs, "technical", None)
        # 摘要应包含首条用户消息
        assert "初始问题" in summary
        assert "后续追问" in summary

    def test_low_quality_score_annotation(self):
        msgs = [HumanMessage(content="问题")]
        summary = _build_summary(msgs, "technical", 0.2)
        assert "低置信度" in summary

    def test_medium_quality_score_annotation(self):
        msgs = [HumanMessage(content="问题")]
        summary = _build_summary(msgs, "technical", 0.5)
        assert "中等置信度" in summary

    def test_no_user_messages_falls_back_to_intent(self):
        msgs = [AIMessage(content="AI 回复")]
        summary = _build_summary(msgs, "technical", None)
        assert "technical" in summary


# ============================================================
# 已尝试方案提取
# ============================================================

class TestBuildAttemptedSolutions:
    def test_extracts_ai_steps(self):
        msgs = [
            HumanMessage(content="报错了"),
            AIMessage(content="请尝试以下步骤：1. 检查配置"),
        ]
        result = _build_attempted_solutions(msgs, [])
        assert "steps" in result
        assert "confirmed_info" in result
        assert len(result["steps"]) >= 1

    def test_includes_retrieved_docs_count(self):
        msgs = [AIMessage(content="根据文档...")]
        result = _build_attempted_solutions(msgs, ["doc1", "doc2", "doc3"])
        assert any("3" in s for s in result["steps"])

    def test_extracts_error_info_from_user_message(self):
        msgs = [HumanMessage(content="我遇到了 ERR_403 错误")]
        result = _build_attempted_solutions(msgs, [])
        assert any("403" in info for info in result["confirmed_info"])

    def test_extracts_version_info(self):
        msgs = [HumanMessage(content="我用的是 v2.1 版本")]
        result = _build_attempted_solutions(msgs, [])
        assert any("版本" in info for info in result["confirmed_info"])

    def test_no_attempts_returns_default(self):
        result = _build_attempted_solutions([], [])
        assert len(result["steps"]) >= 1


# ============================================================
# 用户画像
# ============================================================

class TestBuildUserProfile:
    def test_empty_memory_context(self):
        profile = _build_user_profile("", "free", ["viewer"])
        assert profile["plan"] == "free"
        assert profile["roles"] == ["viewer"]
        assert profile["has_history"] is False

    def test_extracts_plan_from_memory(self):
        memory_ctx = "订阅计划: enterprise"
        profile = _build_user_profile(memory_ctx, "enterprise", [])
        assert "details" in profile
        assert "plan_detail" in profile["details"]

    def test_extracts_preference(self):
        memory_ctx = "偏好: 中文回复"
        profile = _build_user_profile(memory_ctx, "free", [])
        assert "preference" in profile.get("details", {})

    def test_empty_plan_defaults_to_unknown(self):
        """空 plan 应默认为 unknown"""
        profile = _build_user_profile("", "", [])
        assert profile["plan"] == "unknown"


# ============================================================
# 紧急度评估
# ============================================================

class TestAssessUrgency:
    def test_enterprise_complaint_is_critical(self):
        assert _assess_urgency("我要投诉退款", "enterprise", "general") == "critical"

    def test_enterprise_technical_is_high(self):
        assert _assess_urgency("api 报错", "enterprise", "technical") == "high"

    def test_pro_complaint_is_high(self):
        assert _assess_urgency("我要退款 refund", "pro", "general") == "high"

    def test_normal_complaint(self):
        assert _assess_urgency("我要 cancel 订阅", "free", "general") == "normal"

    def test_low_urgency_default(self):
        assert _assess_urgency("一般问题", "free", "general") == "low"

    def test_english_complaint_keywords(self):
        assert _assess_urgency("I want a refund", "enterprise", "general") == "critical"


# ============================================================
# 卡点分析
# ============================================================

class TestAnalyzeBlocker:
    def test_injection_blocked_blocker(self):
        state = {"injection_blocked": True}
        result = _analyze_blocker(state, [])
        assert result["count"] >= 1
        assert any(b["type"] == "security" for b in result["items"])

    def test_needs_clarification_blocker(self):
        state = {
            "clarity_status": "needs_clarification",
            "clarification_question": "请问您使用的是哪个版本？",
        }
        result = _analyze_blocker(state, [])
        assert any(b["type"] == "missing_info" for b in result["items"])

    def test_low_confidence_blocker(self):
        state = {"quality_score": 0.2}
        result = _analyze_blocker(state, [])
        assert any(b["type"] == "low_confidence" for b in result["items"])

    def test_faq_miss_blocker(self):
        state = {"faq_match": None, "intent": "faq"}
        result = _analyze_blocker(state, [])
        assert any(b["type"] == "faq_miss" for b in result["items"])

    def test_general_blocker_when_no_specific(self):
        state = {"needs_human": True}
        result = _analyze_blocker(state, [])
        assert any(b["type"] == "general" for b in result["items"])


# ============================================================
# 完整 build_handoff_context
# ============================================================

class TestBuildHandoffContext:
    def test_full_context_structure(self):
        state = {
            "user_id": "user-1",
            "tenant_id": "t1",
            "user_plan": "enterprise",
            "user_roles": ["admin"],
            "memory_context": "",
            "retrieved_docs": ["doc1"],
            "needs_human": True,
            "intent": "technical",
            "session_id": "s1",
            "turn_count": 3,
        }
        msgs = [
            HumanMessage(content="API 报错 403"),
            AIMessage(content="请检查权限配置"),
        ]

        ctx = build_handoff_context(state, msgs, intent="technical", quality_score=0.2)

        assert "summary" in ctx
        assert "reason" in ctx
        assert "attempted_solutions" in ctx
        assert "user_profile" in ctx
        assert "conversation" in ctx
        assert "urgency" in ctx
        assert "current_blocker" in ctx
        assert "metadata" in ctx
        assert "built_at" in ctx

    def test_conversation_serialized(self):
        state = {}
        msgs = [
            HumanMessage(content="用户问题"),
            AIMessage(content="AI 回复"),
        ]
        ctx = build_handoff_context(state, msgs)
        assert len(ctx["conversation"]) == 2
        assert ctx["conversation"][0]["role"] == "user"
        assert ctx["conversation"][1]["role"] == "assistant"

    def test_enterprise_technical_urgency(self):
        state = {"user_plan": "enterprise", "needs_human": True}
        msgs = [HumanMessage(content="技术问题")]
        ctx = build_handoff_context(state, msgs, intent="technical")
        assert ctx["urgency"] == "high"

    def test_metadata_includes_session_info(self):
        state = {
            "session_id": "s1",
            "turn_count": 5,
            "injection_blocked": False,
            "access_filtered": 2,
            "clarity_status": "rewritten",
        }
        ctx = build_handoff_context(state, [], intent="faq")
        assert ctx["metadata"]["session_id"] == "s1"
        assert ctx["metadata"]["turn_count"] == 5
        assert ctx["metadata"]["access_filtered"] == 2
