"""低分难例挖掘接口测试（离线，挖掘函数打桩）。"""

import pytest
from fastapi.testclient import TestClient
from src.evaluation import feedback_loop as fl


@pytest.fixture
def client():
    from src.api.server import app

    return TestClient(app)


def _login(client, username):
    resp = client.post(
        "/api/v1/auth/login", json={"username": username, "password": f"{username}123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture
def fake_cases(monkeypatch):
    cases = [
        fl.HardCase(
            case_id="abc123",
            session_id="sess-1",
            user_id="u1",
            score=1,
            tags=["答非所问"],
            comment="",
            question="T200 测温范围",
            answer="-20~550℃",
            answer_metadata={"answer_path": "direct_synthesis"},
            feedback_created_at=1000.0,
            golden_candidate=True,
        )
    ]
    monkeypatch.setattr(fl, "mine_hard_cases", lambda **kw: list(cases))
    monkeypatch.setattr(fl, "export_jsonl", lambda cs: '{"case_id":"abc123"}')
    return cases


def test_admin_lists_hard_cases(client, fake_cases):
    auth = _login(client, "admin")

    resp = client.get(
        "/api/v1/satisfaction/hard_cases?score_threshold=2&limit=10", headers=auth
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["golden_candidates"] == 1
    assert body["cases"][0]["question"] == "T200 测温范围"
    assert "abc123" in body["jsonl"]


def test_agent_forbidden(client, fake_cases):
    auth = _login(client, "agent")

    resp = client.get("/api/v1/satisfaction/hard_cases", headers=auth)

    assert resp.status_code == 403


def test_unauthenticated_rejected(client, fake_cases):
    resp = client.get("/api/v1/satisfaction/hard_cases")

    assert resp.status_code in (401, 403)


def test_invalid_threshold_rejected(client, fake_cases):
    auth = _login(client, "admin")

    resp = client.get("/api/v1/satisfaction/hard_cases?score_threshold=5", headers=auth)

    assert resp.status_code == 422
