"""配置热更新的进程内验证：改配置后，真实检索工具是否读到新值

为什么必须是「进程内」
----------------------
配置热更新的实现是 `setattr(settings, field, value)`，改的是**当前进程**的内存。
如果另起一个进程去观察（例如 `docker exec python -c ...`），新进程会重新从
环境变量加载 settings，永远读不到热更新后的值。这不是热更新失效，而是
观察方式错了。本测试用 TestClient 让接口与检索引擎跑在**同一个进程**里，
复现的正是线上单进程 uvicorn 的语义。

为什么用桩检索器而不是真向量库
------------------------------
本测试要验证的是「配置值有没有沿调用链传下去」，不关心向量库返回什么。
注入一个记录入参的桩检索器，断言就能精确到「收到 top_k = ?」，
不依赖知识库里恰好有几篇文档，也不依赖嵌入模型是否可用。

真实的端到端表现（真向量库 + 真文档 + 条数变化）由
scripts/verify_config_hot_reload.py 在容器内验证。
"""

import pytest
from fastapi.testclient import TestClient


class _FakeDoc:
    """最小化的文档替身

    工具内部会访问 doc.metadata.get("source") 与 doc.page_content，
    返回裸字符串会触发 AttributeError，工具捕获后返回报错文本，
    导致条数断言看到 0。这里补齐这两个属性，保持替身与真实 Document 的接口一致。
    """

    def __init__(self, idx: int):
        self.page_content = f"第 {idx} 段内容：XG-9000 腔体预热温度 187 摄氏度。"
        self.metadata = {"source": f"fake_doc_{idx}.md", "kb_id": "KBS-TEST"}


class _RecordingRetriever:
    """桩检索器：记录每次 search 收到的 top_k，并按该值返回等量假文档"""

    def __init__(self):
        self.calls = []

    def search(self, query, top_k=None, **kwargs):
        self.calls.append({"query": query, "top_k": top_k})
        return [_FakeDoc(i) for i in range(int(top_k or 0))]

    # 工具里还可能调用 search_with_scores，一并提供以免 AttributeError
    def search_with_scores(self, query, top_k=None, **kwargs):
        self.calls.append({"query": query, "top_k": top_k})
        return [(_FakeDoc(i), 1.0) for i in range(int(top_k or 0))]


@pytest.fixture
def client():
    from src.api.server import app

    return TestClient(app)


@pytest.fixture
def admin_headers(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture(autouse=True)
def restore_top_k():
    """测试后还原，避免污染其它用例"""
    from src.config import settings

    original = settings.retrieval_top_k
    yield
    settings.retrieval_top_k = original


def _build_kb_tool(retriever):
    """构造与图节点同样的 Agent 工具集，取出知识库检索工具"""
    from src.agent.tools import create_tools

    tools = create_tools(
        retriever=retriever,
        user_id="admin-default",
        tenant_id="default",
        user_access_levels=["public", "internal", "confidential", "restricted"],
        roles=["admin"],
        plan="free",
    )
    return next(t for t in tools if getattr(t, "name", "") == "search_knowledge_base")


class TestHotReloadReachesRetrievalTool:
    """核心断言：PUT 改配置后，真实工具在**同进程内**读到新值"""

    def test_default_value_is_used_by_tool(self, client, admin_headers):
        """未改动时，工具应使用配置里的默认值 5"""
        from src.config import settings

        retriever = _RecordingRetriever()
        tool = _build_kb_tool(retriever)
        tool.invoke({"query": "XG-9000"})

        assert retriever.calls, "工具未调用检索器"
        assert retriever.calls[0]["top_k"] == settings.retrieval_top_k
        assert retriever.calls[0]["top_k"] == 5

    @pytest.mark.parametrize("new_value", [2, 10])
    def test_put_then_tool_uses_new_value(self, client, admin_headers, new_value):
        """PUT 改成 2 / 10 后，工具应立即使用新值（无需重启进程）"""
        # 1. 通过真实接口改配置
        resp = client.put(
            "/api/v1/config/retrieval_top_k",
            json={"value": new_value},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["new_value"] == new_value
        assert resp.json()["changed"] is True

        # 2. 同一进程内调用真实工具
        retriever = _RecordingRetriever()
        tool = _build_kb_tool(retriever)
        tool.invoke({"query": "XG-9000"})

        assert retriever.calls[0]["top_k"] == new_value, (
            f"工具传给检索器的 top_k 应为 {new_value}，"
            f"实际为 {retriever.calls[0]['top_k']}（说明配置未沿调用链生效）"
        )

    def test_sequence_5_2_10_restore(self, client, admin_headers):
        """连续切换 5 → 2 → 10 → 5，每一步工具都要跟上，证明不再是硬编码"""
        observed = []
        for value in [2, 10, 5]:
            resp = client.put(
                "/api/v1/config/retrieval_top_k",
                json={"value": value},
                headers=admin_headers,
            )
            assert resp.status_code == 200

            retriever = _RecordingRetriever()
            tool = _build_kb_tool(retriever)
            tool.invoke({"query": "XG-9000"})
            observed.append(retriever.calls[0]["top_k"])

        assert observed == [2, 10, 5], f"实际观察到的 top_k 序列为 {observed}"

    def test_tool_returns_matching_doc_count(self, client, admin_headers):
        """工具返回体里的命中条数应随配置变化（内容层面的佐证）"""
        counts = []
        for value in [2, 4]:
            client.put(
                "/api/v1/config/retrieval_top_k",
                json={"value": value},
                headers=admin_headers,
            )
            retriever = _RecordingRetriever()
            tool = _build_kb_tool(retriever)
            text = tool.invoke({"query": "XG-9000"})
            text = text if isinstance(text, str) else str(text)
            counts.append(text.count("[Doc "))

        assert counts == [2, 4], f"工具返回体里的命中条数应与配置一致，实际为 {counts}"

    def test_config_endpoint_reflects_new_value(self, client, admin_headers):
        """改完之后，读取接口应返回新值，且带有修改人与时间"""
        client.put(
            "/api/v1/config/retrieval_top_k",
            json={"value": 7},
            headers=admin_headers,
        )
        got = client.get("/api/v1/config/retrieval_top_k", headers=admin_headers).json()
        assert got["value"] == 7
        assert got["modified_at"], "应记录修改时间"
        assert got["modified_by"], "应记录修改人"
