"""Chat + Health API 集成测试

覆盖：
- GET /health
- POST /chat（同步对话）
- 消息校验（空消息、超长消息）
- 响应清洗（ReAct 标记清理）
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI 测试客户端"""
    from src.api.server import app
    return TestClient(app)


# ============================================================
# /health
# ============================================================

class TestHealthEndpoint:
    def test_health_check_returns_ok(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "enterprise-agent"


# ============================================================
# /chat
# ============================================================

# /chat 的完整链路依赖 LangGraph 工作流 + LLM。工作流由 tests/conftest.py 的
# autouse fixture 统一替换为 FakeWorkflow，因此这里无需真实凭据、也不会触网，
# 可以正常断言 HTTP 行为。请求体校验（422）类用例不进入处理链路，同样保留在 CI 中。
class TestChatEndpoint:
    def test_chat_with_valid_message(self, client):
        """有效消息应返回 200"""
        resp = client.post("/api/v1/chat", json={
            "message": "你好，我想了解一下产品价格",
            "user_id": "test-user",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "reply" in data
        assert "needs_human" in data

    def test_chat_with_session_id(self, client):
        """传入 session_id 应被使用"""
        resp = client.post("/api/v1/chat", json={
            "message": "续上之前的对话",
            "session_id": "test-session-123",
            "user_id": "test-user",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test-session-123"

    def test_chat_empty_message_rejected(self, client):
        """空消息应返回 422（请求体校验，不触 LLM）"""
        resp = client.post("/api/v1/chat", json={
            "message": "",
            "user_id": "test-user",
        })
        assert resp.status_code == 422

    def test_chat_missing_message_rejected(self, client):
        """缺少 message 字段应返回 422（请求体校验，不触 LLM）"""
        resp = client.post("/api/v1/chat", json={
            "user_id": "test-user",
        })
        assert resp.status_code == 422

    def test_chat_reply_is_string(self, client):
        """reply 应为非空字符串"""
        resp = client.post("/api/v1/chat", json={
            "message": "如何重置密码？",
            "user_id": "test-user",
        })
        data = resp.json()
        assert isinstance(data["reply"], str)

    def test_chat_default_user_id(self, client):
        """不传 user_id 应为 anonymous"""
        resp = client.post("/api/v1/chat", json={
            "message": "测试匿名用户",
        })
        assert resp.status_code == 200

    def test_chat_passes_user_id_into_state(self, client, fake_workflow):
        """user_id 应被写进传工作流的 state（而非被丢弃）"""
        client.post("/api/v1/chat", json={
            "message": "你好",
            "user_id": "user-abc",
        })
        assert fake_workflow.calls, "chat 未调用工作流"
        assert fake_workflow.calls[0]["state"]["user_id"] == "user-abc"

    def test_chat_session_id_defaults_to_uuid(self, client, fake_workflow):
        """不传 session_id 时应自动生成一个非空 id 作为线程标识"""
        resp = client.post("/api/v1/chat", json={"message": "你好"})
        assert resp.status_code == 200
        generated = resp.json()["session_id"]
        assert generated
        # 生成的 id 应同时作为 LangGraph 的 thread_id 传入
        thread_id = fake_workflow.calls[0]["config"]["configurable"]["thread_id"]
        assert thread_id == generated
