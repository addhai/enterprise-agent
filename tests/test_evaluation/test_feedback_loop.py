"""反馈闭环难例挖掘单测（离线，仓储层全部打桩）。"""

import json

import pytest
from src.evaluation import feedback_loop as fl


def _sat(record_id, session_id, score, *, user="u1", tags=None, comment="", ts=1000.0):
    return {
        "id": record_id,
        "tenant_id": "default",
        "session_id": session_id,
        "user_id": user,
        "score": score,
        "tags": tags or [],
        "comment": comment,
        "agent_id": None,
        "created_at": ts,
    }


def _msg(role, content, metadata=None):
    return {"role": role, "content": content, "metadata": metadata or {}}


@pytest.fixture
def patched_repos(monkeypatch):
    holder = {"sat": [], "messages": {}}
    monkeypatch.setattr(
        fl,
        "negative_satisfaction_list",
        lambda tenant_id, max_score, limit: list(holder["sat"]),
    )
    monkeypatch.setattr(
        fl,
        "message_list",
        lambda session_id, tenant_id: holder["messages"].get(session_id, []),
    )
    return holder


def test_mine_basic_qa_pair(patched_repos):
    patched_repos["sat"] = [_sat("SAT-1", "sess-1", 1, tags=["答非所问"])]
    patched_repos["messages"]["sess-1"] = [
        _msg("user", "T200 测温范围是多少"),
        _msg(
            "assistant",
            "测温范围是 -20℃ 到 550℃。",
            {"answer_path": "direct_synthesis", "retrieval_count": 3},
        ),
    ]

    cases = fl.mine_hard_cases("default")

    assert len(cases) == 1
    case = cases[0]
    assert case.question == "T200 测温范围是多少"
    assert "550℃" in case.answer
    assert case.score == 1
    assert case.tags == ["答非所问"]
    assert case.golden_candidate is True
    assert len(case.case_id) == 16


def test_dedup_by_question_fingerprint(patched_repos):
    patched_repos["sat"] = [
        _sat("SAT-1", "sess-1", 2, ts=1000.0),
        _sat("SAT-2", "sess-2", 1, ts=2000.0),
    ]
    qa = [
        _msg("user", "设备开不了机怎么办"),
        _msg("assistant", "请检查电池电量。", {"retrieval_count": 1}),
    ]
    patched_repos["messages"]["sess-1"] = qa
    patched_repos["messages"]["sess-2"] = [
        _msg("user", "设备开不了机怎么办"),
        _msg("assistant", "请先充电再试。", {"retrieval_count": 2}),
    ]

    cases = fl.mine_hard_cases("default")

    assert len(cases) == 1
    assert cases[0].occurrence == 2
    # 碰撞后保留更严重的最低分
    assert cases[0].score == 1


def test_skip_when_no_complete_qa(patched_repos):
    patched_repos["sat"] = [
        _sat("SAT-1", "", 1),  # 无会话
        _sat("SAT-2", "sess-2", 1),
    ]
    patched_repos["messages"]["sess-2"] = [_msg("user", "只有提问没有回答")]

    assert fl.mine_hard_cases("default") == []


def test_non_rag_answer_not_golden_candidate(patched_repos):
    patched_repos["sat"] = [_sat("SAT-1", "sess-1", 2)]
    patched_repos["messages"]["sess-1"] = [
        _msg("user", "今天天气怎么样"),
        _msg("assistant", "我无法查询天气。", {}),
    ]

    cases = fl.mine_hard_cases("default")

    assert len(cases) == 1
    assert cases[0].golden_candidate is False


def test_retrieval_count_above_zero_qualifies(patched_repos):
    patched_repos["sat"] = [_sat("SAT-1", "sess-1", 2)]
    patched_repos["messages"]["sess-1"] = [
        _msg("user", "保修多久"),
        _msg("assistant", "十二个月。", {"retrieval_count": "2"}),
    ]

    cases = fl.mine_hard_cases("default")

    assert cases[0].golden_candidate is True


def test_message_load_failure_is_isolated(monkeypatch, patched_repos):
    patched_repos["sat"] = [
        _sat("SAT-1", "sess-bad", 1),
        _sat("SAT-2", "sess-good", 1),
    ]

    def _flaky(session_id, tenant_id):
        if session_id == "sess-bad":
            raise RuntimeError("db connection lost")
        return [
            _msg("user", "正常问题"),
            _msg("assistant", "正常回答。", {"answer_path": "react"}),
        ]

    monkeypatch.setattr(fl, "message_list", _flaky)

    cases = fl.mine_hard_cases("default")

    assert len(cases) == 1
    assert cases[0].session_id == "sess-good"


def test_empty_feedback_returns_empty(patched_repos):
    assert fl.mine_hard_cases("default") == []


def test_export_jsonl_roundtrip(patched_repos):
    patched_repos["sat"] = [_sat("SAT-1", "sess-1", 1, comment="没用")]
    patched_repos["messages"]["sess-1"] = [
        _msg("user", "问题甲"),
        _msg("assistant", "回答甲。", {"answer_path": "direct_synthesis"}),
    ]

    cases = fl.mine_hard_cases("default")
    lines = fl.export_jsonl(cases).splitlines()

    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["question"] == "问题甲"
    assert payload["comment"] == "没用"
    assert payload["golden_candidate"] is True


def test_fingerprint_whitespace_insensitive():
    assert fl._fingerprint("  设备   开不了机 ") == fl._fingerprint("设备 开不了机")
