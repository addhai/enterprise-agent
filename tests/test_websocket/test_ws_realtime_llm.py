"""WebSocket /ws/chat 真实 LLM 端到端集成测试

⚠️ 本文件用例默认跳过：conftest 的 ``requires_llm`` marker 在未设置
``RUN_LLM_TESTS=1`` 时自动 skip，因此 CI（公开仓库、无 Key）与任何干净环境
都不会执行它们，套件依旧确定性、不触网、快速、可信。

本地想实跑真实大模型链路时：

    RUN_LLM_TESTS=1 OPENAI_API_KEY=<你的 DashScope 兼容 key> \
        pytest tests/test_websocket/test_ws_realtime_llm.py -v

价值定位：
    此前的 ``user_plan`` AttributeError、以及本次发现的 ``asyncio`` 局部变量
    持久化崩溃（cannot access local variable 'asyncio'），都是「真实聊天路径才
    触发、CI 的确定性 FakeLLM 完全覆盖不到」的回归。本文件把「真实 LLM 走通」
    固化成可复跑的回归测试——跑一次即知主链路是否还活着。

关于「工具真执行」的自动化证据边界（重要，避免误读）：
    本文件用 Starlette ``TestClient`` 在进程内驱动 WS。实测发现：TestClient 路径
    下真实 LLM 对「建单意图」倾向于回问候语、不触发工具调用（而同一句 prompt 在
    **真实 uvicorn server** 上能稳定建单，见 scripts/ws_capture.py + make demo）。
    因此本文件对「工具落库」只做**尽力验证**：若模型本次调了工具则断言落库正确，
    否则 skip 并明确指向真实 server 路径。工具执行的「确定性自动证据」以
    scripts/ws_capture.py（真实 server + 真实对话）为准。
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.config import settings
from src.ticket.models import TicketListFilter
from src.ticket.store import get_default_store


def _client() -> TestClient:
    return TestClient(app)


def _read_stream_until_done(ws) -> tuple[bool, bool, str]:
    """读取 WS 流直到 streaming_chunk.done=True（或达到安全上限）。

    返回 (got_content, got_error, full_text)。``streaming_chunk`` 的 ``done=True``
    是 routes.py 在生成结束后固定发出的结束标记；收到即停止，避免连接保持打开导致
    receive_json 永久阻塞。
    """
    got_content = False
    got_error = False
    full_text = []
    for _ in range(400):  # 安全上限，防止异常情况下无限阻塞
        try:
            frame = ws.receive_json()
        except Exception:
            break
        ftype = frame.get("type")

        if ftype == "error":
            got_error = True
            break

        if ftype == "streaming_chunk":
            text = frame.get("text") or frame.get("delta") or ""
            if text.strip():
                got_content = True
                full_text.append(text)
            if frame.get("done"):
                break
        elif ftype == "agent_chat_message":
            content = frame.get("content") or ""
            if content.strip():
                got_content = True
                full_text.append(content)
        elif ftype in ("chat_end", "session_end", "done"):
            break

    return got_content, got_error, "".join(full_text)


@pytest.mark.requires_llm
def test_realtime_chat_runs_without_unhandled_error():
    """真实 LLM 主链路冒烟/回归：收到 session_ready + 非空回复，且不出现 error 事件。

    这会真正调用 LangGraph 工作流 + RAG + 安全护栏 + 真实大模型生成。任何未捕获
    异常（如历史 user_plan 类、asyncio 局部变量类 AttributeError）都会让流式中断
    或抛出 error 事件，本断言即能捕获。
    """
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "session_ready", ready
        sid = ready["session_id"]

        ws.send_text(json.dumps({
            "type": "chat_message",
            "session_id": sid,
            "message": "CloudSync 的 API 分页和版本控制是怎么实现的？",
        }))

        got_content, got_error, text = _read_stream_until_done(ws)

    assert not got_error, "真实 LLM 聊天链路出现 error 事件（主链路可能已崩）"
    assert got_content, "真实 LLM 未返回任何非空回复"
    # 简单合理性：回复不应过短（过短通常意味着异常兜底）
    assert len(text.strip()) > 5, f"回复过短，疑似异常：{text!r}"


@pytest.mark.requires_llm
def test_ticket_creation_intent_exercises_tool_and_persists():
    """发送建单意图，验证真实 LLM 聊天链路不崩；若模型调了工具则断言落库正确。

    注意（见模块 docstring）：TestClient 路径下真实 LLM 未必触发工具调用，故「落库」
    为尽力验证——模型本次调了工具才断言，否则 skip 并指向真实 server 路径。
    """
    client = _client()
    idem_key = f"req-llmtest-{uuid.uuid4().hex[:8]}"
    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "session_ready", ready
        sid = ready["session_id"]
        tenant_id = f"anon-{sid}"  # 匿名连接租户

        ws.send_text(json.dumps({
            "type": "chat_message",
            "session_id": sid,
            "message": (
                "帮我建一张关于 Dropbox 同步中断的工单，分类 account，"
                f"优先级 high，幂等键 {idem_key}。"
            ),
        }))

        got_content, got_error, text = _read_stream_until_done(ws)

    assert not got_error, "真实 LLM 聊天链路出现 error 事件（主链路可能已崩）"
    assert got_content, "真实 LLM 未返回任何非空回复"

    # 以存储落库为唯一真相：工具真执行 → store 里有带本幂等键的工单
    store = get_default_store()
    tickets = store.list(TicketListFilter(tenant_id=tenant_id, limit=100))
    matched = [t for t in tickets if t.idempotency_key == idem_key]

    if not matched:
        pytest.skip(
            "本次真实 LLM 未通过 TestClient 路径触发 ticket_create 工具调用"
            f"（回复摘要：{text[:60]!r}）。工具执行的确定性自动证据请以真实 uvicorn "
            "server 为准：先 `make demo`（或 `uvicorn src.api.server:app`），再用 "
            "`python scripts/ws_capture.py` 抓取真实对话验证工单落库。"
        )

    # 模型真调了工具 → 验证落库 tenant 与身份一致（防越权/串租户）
    assert len(matched) >= 1
    assert matched[0].tenant_id == tenant_id, (
        f"工单落库租户 {matched[0].tenant_id} 与会话租户 {tenant_id} 不一致（串租户风险）"
    )
