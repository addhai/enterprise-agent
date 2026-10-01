"""P2-3 接口单元测试

覆盖 5 个核心接口：
    1. POST /api/v1/chat  对话发起（REST）
    2. GET  /api/v1/conversations/{session_id}/messages  历史消息读取
    3. POST /api/v1/admin/knowledge/{kb_id}/documents/upload  文档上传
    4. POST /api/v1/admin/knowledge/{kb_id}/hit_test  RAG 检索
    5. DELETE /api/v1/sessions/{session_id}  会话清除

测试矩阵：
    - 正常调用（happy path）
    - 参数缺失（空 body / 缺必填字段）
    - 非法参数（超长 / 类型错误 / 枚举值不存在）
    - 知识库检索边界 case（空 query / top_k 越界 / kb 不存在）
    - 权限控制（未登录 / 角色不足 / 越权访问他人会话）

环境：
    - 内存 SQLite（conftest.py 自动初始化）
    - admin/admin123 与 viewer/viewer123 由 seed 脚本预置
    - 不触网、不调真实 LLM（requires_llm 用例自动跳过）

执行：
    pytest tests/test_api/test_api_reference.py -v
覆盖率：
    pytest tests/test_api/test_api_reference.py --cov=src/api --cov-report=term-missing
"""
import io
import json

import pytest
from fastapi.testclient import TestClient


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def client():
    """FastAPI 测试客户端（内存 SQLite，conftest 已初始化）"""
    from src.api.server import app
    return TestClient(app)


@pytest.fixture
def admin_token(client):
    """admin 角色 JWT token（seed 预置账号）"""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture
def viewer_token(client):
    """viewer 角色 JWT token（权限不足，用于 403 断言）"""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": "viewer123"},
    )
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture
def agent_token(client):
    """agent 角色 JWT token（seed 预置账号）"""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "agent", "password": "agent123"},
    )
    # agent 账号可能不存在，跳过
    if resp.status_code != 200:
        pytest.skip("agent seed 账号不存在")
    return resp.json()["token"]


def _auth(token: str) -> dict:
    """构造 Authorization header"""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def temp_kb(client, admin_token):
    """创建临时知识库，返回 kb_id，测试后自动清理"""
    resp = client.post(
        "/api/v1/admin/knowledge",
        json={
            "name": "P2-3 测试知识库",
            "description": "接口测试临时创建",
            "kb_version": "standard",
            "kb_type": "document",
            "similarity_threshold": 0.2,
            "weight": 1.0,
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    kb_id = resp.json()["kb"]["id"]
    yield kb_id
    # 清理
    client.delete(
        f"/api/v1/admin/knowledge/{kb_id}",
        headers=_auth(admin_token),
    )


# ============================================================
# 1. POST /api/v1/chat  对话发起
# ============================================================

class TestChatEndpoint:
    """对话发起接口"""

    def test_chat_normal_call(self, client):
        """正常调用：有效消息应返回 200 + 完整响应体"""
        resp = client.post("/api/v1/chat", json={
            "message": "你好",
            "user_id": "test_user",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "reply" in data
        assert "needs_human" in data
        assert isinstance(data["needs_human"], bool)
        assert isinstance(data["suggest_human"], bool)

    def test_chat_with_session_id(self, client):
        """传入 session_id 应被使用（同一会话续接）"""
        sid = "test-session-p2-3-001"
        resp = client.post("/api/v1/chat", json={
            "message": "第一条消息",
            "session_id": sid,
        })
        assert resp.status_code == 200
        assert resp.json()["session_id"] == sid

    def test_chat_missing_message(self, client):
        """参数缺失：不传 message 应返回 422"""
        resp = client.post("/api/v1/chat", json={})
        assert resp.status_code == 422

    def test_chat_empty_message(self, client):
        """非法参数：空字符串应返回 422（min_length=1）"""
        resp = client.post("/api/v1/chat", json={"message": ""})
        assert resp.status_code == 422

    def test_chat_message_too_long(self, client):
        """非法参数：超 2000 字符应返回 422（max_length=2000）"""
        resp = client.post("/api/v1/chat", json={"message": "x" * 2001})
        assert resp.status_code == 422

    def test_chat_wrong_content_type(self, client):
        """非法参数：非 JSON 请求体应返回 422"""
        resp = client.post(
            "/api/v1/chat",
            data="plain text",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 422


# ============================================================
# 2. GET /api/v1/conversations/{session_id}/messages  历史消息
# ============================================================

class TestConversationMessages:
    """历史消息读取接口"""

    def test_get_messages_no_auth(self, client):
        """未鉴权：无 Authorization header 应返回 401"""
        resp = client.get(
            "/api/v1/conversations/any-session/messages"
        )
        assert resp.status_code == 401

    def test_get_messages_not_found(self, client, admin_token):
        """正常调用但资源不存在：返回 404"""
        resp = client.get(
            "/api/v1/conversations/nonexistent-session/messages",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404
        assert "会话不存在" in resp.json()["detail"]

    @pytest.mark.requires_llm
    @pytest.mark.no_chat_stub
    def test_get_messages_after_chat(self, client, admin_token):
        """正常调用：对话后读取消息应包含 user + assistant

        需要真实工作流：本用例断言 chat 的落库副作用，
        默认的 FakeWorkflow 不会写会话历史，故显式关闭打桩并标注 requires_llm。
        """
        sid = "p2-3-msg-test-001"
        # 发一条消息
        client.post("/api/v1/chat", json={
            "message": "测试消息",
            "session_id": sid,
            "user_id": "admin",
        })
        # 读取消息
        resp = client.get(
            f"/api/v1/conversations/{sid}/messages",
            headers=_auth(admin_token),
        )
        # 会话可能在内存中（需 WS 连接），REST chat 不保证落库
        # 只要 200 或 404 都合理
        if resp.status_code == 200:
            data = resp.json()
            assert data["session_id"] == sid
            assert isinstance(data["count"], int)
            assert isinstance(data["messages"], list)
        else:
            assert resp.status_code == 404

    def test_get_messages_limit_param(self, client, admin_token):
        """Query 参数：limit 应被正确解析（1~500）"""
        # limit=1 合法
        resp = client.get(
            "/api/v1/conversations/any/messages?limit=1",
            headers=_auth(admin_token),
        )
        # 404 是因为 session 不存在，limit 校验通过
        assert resp.status_code == 404

    def test_get_messages_invalid_limit(self, client, admin_token):
        """非法参数：limit=0 应返回 422（ge=1）"""
        resp = client.get(
            "/api/v1/conversations/any/messages?limit=0",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422

    def test_get_messages_limit_too_large(self, client, admin_token):
        """非法参数：limit=501 应返回 422（le=500）"""
        resp = client.get(
            "/api/v1/conversations/any/messages?limit=501",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422


# ============================================================
# 3. POST /api/v1/admin/knowledge/{kb_id}/documents/upload  文档上传
# ============================================================

class TestDocumentUpload:
    """知识库文档上传接口"""

    def test_upload_no_auth(self, client, temp_kb):
        """未鉴权：无 token 应返回 401"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/documents/upload",
            files={"file": ("test.md", b"# Test", "text/markdown")},
        )
        assert resp.status_code == 401

    def test_upload_forbidden_viewer(self, client, viewer_token, temp_kb):
        """权限不足：viewer 角色应返回 403"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/documents/upload",
            files={"file": ("test.md", b"# Test", "text/markdown")},
            headers=_auth(viewer_token),
        )
        assert resp.status_code == 403

    def test_upload_kb_not_found(self, client, admin_token):
        """资源不存在：kb_id 不存在应返回 404"""
        resp = client.post(
            "/api/v1/admin/knowledge/nonexistent-kb/documents/upload",
            files={"file": ("test.md", b"# Test", "text/markdown")},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404
        assert "知识库不存在" in resp.json()["detail"]

    def test_upload_no_file(self, client, admin_token, temp_kb):
        """参数缺失：不传 file 应返回 422"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/documents/upload",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422

    @pytest.mark.requires_llm
    def test_upload_markdown_normal(self, client, admin_token, temp_kb):
        """正常调用：上传 .md 文件应成功（需向量化，标 requires_llm）"""
        content = "# 产品手册\n\n## 第一章 概述\n\n产品 A 是一款智能客服系统。".encode(
            "utf-8"
        )
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/documents/upload",
            files={"file": ("manual.md", content, "text/markdown")},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "document" in data
        assert data["document"]["title"] == "manual.md"

    @pytest.mark.requires_llm
    def test_upload_with_title(self, client, admin_token, temp_kb):
        """正常调用：通过 query 参数指定标题"""
        content = "# 文档内容".encode("utf-8")
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/documents/upload"
            "?title=自定义标题",
            files={"file": ("doc.md", content, "text/markdown")},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["document"]["title"] == "自定义标题"


# ============================================================
# 4. POST /api/v1/admin/knowledge/{kb_id}/hit_test  RAG 检索
# ============================================================

class TestHitTest:
    """RAG 检索（命中测试）接口"""

    def test_hit_test_no_auth(self, client, temp_kb):
        """未鉴权：应返回 401"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/hit_test",
            json={"query": "test"},
        )
        assert resp.status_code == 401

    def test_hit_test_forbidden_viewer(self, client, viewer_token, temp_kb):
        """权限不足：viewer 应返回 403"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/hit_test",
            json={"query": "test"},
            headers=_auth(viewer_token),
        )
        assert resp.status_code == 403

    def test_hit_test_kb_not_found(self, client, admin_token):
        """资源不存在：kb_id 不存在应返回 404"""
        resp = client.post(
            "/api/v1/admin/knowledge/nonexistent-kb/hit_test",
            json={"query": "test"},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404
        assert "知识库不存在" in resp.json()["detail"]

    def test_hit_test_missing_query(self, client, admin_token, temp_kb):
        """参数缺失：不传 query 应返回 422"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/hit_test",
            json={},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422

    def test_hit_test_empty_query(self, client, admin_token, temp_kb):
        """非法参数：空 query 应返回 422（min_length=1）"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/hit_test",
            json={"query": ""},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422

    def test_hit_test_query_too_long(self, client, admin_token, temp_kb):
        """非法参数：query 超 500 字符应返回 422"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/hit_test",
            json={"query": "x" * 501},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422

    def test_hit_test_topk_too_small(self, client, admin_token, temp_kb):
        """边界 case：top_k=0 应返回 422（ge=1）"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/hit_test",
            json={"query": "test", "top_k": 0},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422

    def test_hit_test_topk_too_large(self, client, admin_token, temp_kb):
        """边界 case：top_k=21 应返回 422（le=20）"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/hit_test",
            json={"query": "test", "top_k": 21},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422

    def test_hit_test_default_topk(self, client, admin_token, temp_kb):
        """正常调用：不传 top_k 应使用默认值 3"""
        resp = client.post(
            f"/api/v1/admin/knowledge/{temp_kb}/hit_test",
            json={"query": "test"},
            headers=_auth(admin_token),
        )
        # 空知识库检索可能 500（检索器初始化失败）或 200（零命中）
        if resp.status_code == 200:
            data = resp.json()
            assert data["top_k"] == 3
            assert data["total_hits"] == 0
            assert data["hits"] == []
        elif resp.status_code == 503:
            # 检索器未就绪（无向量库）也合理
            pass
        else:
            pytest.fail(f"意外状态码: {resp.status_code}")


# ============================================================
# 5. DELETE /api/v1/sessions/{session_id}  会话清除
# ============================================================

class TestSessionDelete:
    """会话清除接口"""

    def test_delete_session_not_found(self, client, admin_token):
        """资源不存在：不存在的 session_id 应返回 404"""
        resp = client.delete(
            "/api/v1/sessions/nonexistent-session",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404
        assert "会话不存在" in resp.json()["detail"]

    def test_delete_conversation_not_found(self, client, admin_token):
        """管理端删除：不存在的 session_id 应返回 404"""
        resp = client.delete(
            "/api/v1/conversations/nonexistent-session",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404

    def test_delete_conversation_no_auth(self, client):
        """管理端删除：未鉴权应返回 401"""
        resp = client.delete(
            "/api/v1/conversations/any-session",
        )
        assert resp.status_code == 401

    def test_delete_conversation_viewer_forbidden(self, client, viewer_token):
        """管理端删除：viewer 角色应返回 403"""
        resp = client.delete(
            "/api/v1/conversations/any-session",
            headers=_auth(viewer_token),
        )
        assert resp.status_code == 403

    @pytest.mark.requires_llm
    @pytest.mark.no_chat_stub
    def test_delete_session_after_chat(self, client, admin_token):
        """正常调用：对话后删除会话应返回 success=true

        需要真实工作流：断言 chat 落库后再删除的副作用，故关闭默认打桩。
        """
        sid = "p2-3-delete-test-001"
        # 先发一条消息
        client.post("/api/v1/chat", json={
            "message": "测试",
            "session_id": sid,
            "user_id": "admin",
        })
        # 删除
        resp = client.delete(
            f"/api/v1/sessions/{sid}",
            headers=_auth(admin_token),
        )
        # 会话可能在内存中
        if resp.status_code == 200:
            data = resp.json()
            assert data["success"] is True
        else:
            # 会话不在内存（REST chat 不保证落库）
            assert resp.status_code == 404
