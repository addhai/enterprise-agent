"""阶段二回归测试 — 知识库隔离（kb_id 过滤）+ 多知识源（URL / 文本）摄取

设计要点：
    - 全部离线、确定性，不依赖 OpenAI / Chroma / 网络，可在 CI 白名单内稳定通过。
    - 检索器测试通过 patch 掉真实向量库（避免 Embedder / Chroma 联网），
      只验证「增量入库 + 真正调用向量库 + kb_id 元数据注入 + 按 kb_id 过滤」这一
      核心隔离逻辑。其中过滤由 RRF 融合前 _apply_filter 实现，直接对该纯函数
      做确定性断言；不再依赖 BM25 对混合中英文关键词的召回率（不稳定）。
    - 多源摄取测试直接调用 source_ingest 的纯函数；URL 联网抓取用本地 HTML 替身 mock。
"""
import pytest
from langchain_core.documents import Document


# ---------------------------------------------------------------------------
# 检索器：增量入库 + kb_id 隔离
# ---------------------------------------------------------------------------

class _FakeEmbedder:
    """零依赖的假向量化器：固定维度、不触网、不需要任何 API Key。"""

    dimensions = 8

    def embed_text(self, text: str):
        return [0.0] * self.dimensions

    def embed_texts(self, texts):
        return [[0.0] * self.dimensions for _ in texts]

    # 兼容 LangChain Embeddings 接口
    def embed_query(self, text: str):
        return self.embed_text(text)

    def embed_documents(self, texts):
        return self.embed_texts(texts)


@pytest.fixture
def isolated_retriever(monkeypatch):
    """构造一个离线检索器：屏蔽真实向量库，只保留 BM25 + 元数据过滤路径。

    ⚠️ Embedder 必须在构造 HybridRetriever *之前* 替换。
    VectorStoreManager.__init__ 会立即 `Embedder()`，无 API Key 时当场抛
    openai.OpenAIError；等对象构造完再给 add_documents 打桩已经来不及
    （本 fixture 早期版本正是这样，导致本文件在无 Key 环境下 5 个用例直接 error，
    与文件开头声称的"全部离线"不符）。
    """
    monkeypatch.setattr("src.rag.vector_store.Embedder", _FakeEmbedder)

    from src.rag.retriever import HybridRetriever

    retriever = HybridRetriever(collection_name=None)
    # 屏蔽真实向量库检索路径（只保留 BM25 + 元数据过滤）
    retriever.vector_store.add_documents = lambda *a, **k: []
    retriever.vector_store.search_with_scores = lambda *a, **k: []
    if retriever.sentence_store is not None:
        retriever.sentence_store.add_documents = lambda *a, **k: []
        retriever.sentence_store.search_with_scores = lambda *a, **k: []
    yield retriever
    try:
        retriever.delete_collection()
    except Exception:
        pass


def test_add_documents_is_incremental_and_injects_tenant(isolated_retriever):
    """add_documents 不应清空既有索引，且应为缺失 tenant_id 的 chunk 补上租户。"""
    r = isolated_retriever
    docs_a = [Document("ALPHATOKEN_A 知识库A的独有内容", metadata={"kb_id": "KBA", "source": "a.md"})]
    r.add_documents(docs_a, tenant_id="tenant_X")
    assert docs_a[0].metadata["tenant_id"] == "tenant_X"

    docs_b = [Document("BETATOKEN_B 知识库B的独有内容", metadata={"kb_id": "KBB", "source": "b.md"})]
    r.add_documents(docs_b, tenant_id="")

    # 第二次增量添加后，累积文档数应为 2（证明未清空既有索引）
    assert len(r._all_documents) == 2
    assert docs_a[0] in r._all_documents
    assert docs_b[0] in r._all_documents


def test_add_documents_calls_vector_store(isolated_retriever):
    """回归点：add_documents 必须真正调用向量库 add_documents（修复前缺失该方法，
    导致上传的文档被标记为 INDEXED 却从未进入向量索引，检索永远召回不到）。"""
    calls = {"n": 0}

    def spy(documents, *args, **kwargs):
        calls["n"] += 1
        return []

    isolated_retriever.vector_store.add_documents = spy
    isolated_retriever.add_documents(
        [Document("内容A", metadata={"kb_id": "KBA"})], tenant_id=""
    )
    assert calls["n"] == 1


def test_apply_filter_by_kb_id_is_deterministic(isolated_retriever):
    """_apply_filter 按 kb_id 精确过滤（纯函数，确定性断言）。"""
    results = [
        (Document("内容A", metadata={"kb_id": "KBA"}), 0.9),
        (Document("内容B", metadata={"kb_id": "KBB"}), 0.8),
        (Document("内容C", metadata={}), 0.7),
    ]
    filtered = isolated_retriever._apply_filter(results, {"kb_id": "KBA"})
    assert len(filtered) == 1
    assert filtered[0][0].metadata["kb_id"] == "KBA"


def test_kb_id_filter_returns_only_matching_kb(isolated_retriever):
    """按 kb_id 过滤时，返回结果中只含该知识库的 chunk。"""
    r = isolated_retriever
    r.add_documents([Document("ALPHATOKEN_A 知识库A内容", metadata={"kb_id": "KBA"})], tenant_id="")
    r.add_documents([Document("BETATOKEN_B 知识库B内容", metadata={"kb_id": "KBB"})], tenant_id="")

    hits = r.search_with_scores("ALPHATOKEN_A", top_k=5, filter_by={"kb_id": "KBA"})
    # 即便 BM25 召回了无关文档，过滤后仍只保留 KBA
    assert hits, "应至少在过滤后保留 KBA 的文档"
    for doc, _ in hits:
        assert doc.metadata.get("kb_id") == "KBA"


def test_kb_id_filter_no_cross_leak(isolated_retriever):
    """知识库隔离：过滤 KBA 时，返回结果中不得出现 KBB 的内容。"""
    r = isolated_retriever
    r.add_documents([Document("ALPHATOKEN_A 知识库A内容", metadata={"kb_id": "KBA"})], tenant_id="")
    r.add_documents([Document("BETATOKEN_B 知识库B内容", metadata={"kb_id": "KBB"})], tenant_id="")

    # 用 B 的关键词 + 限定只看下一个 KBA → 结果里绝不能出现 KBB
    hits = r.search_with_scores("BETATOKEN_B", top_k=5, filter_by={"kb_id": "KBA"})
    leaked = [doc for doc, _ in hits if doc.metadata.get("kb_id") == "KBB"]
    assert not leaked, "KBA 过滤下不应泄漏 KBB 的内容（kb_id 隔离失效）"


# ---------------------------------------------------------------------------
# 多知识源摄取：纯文本 / 网页 URL
# ---------------------------------------------------------------------------

def test_text_to_documents_ingestion():
    """纯文本来源应被切分为带元数据的 Document 列表。"""
    from src.rag import source_ingest

    text = (
        "企业客服助手支持自动应答。当客户询问退款流程时，"
        "系统会调用工单工具创建售后单。本段文本用于测试文本入库管线。"
    )
    docs = source_ingest.text_to_documents(text, "测试文本", tenant_id="t1")
    assert docs, "纯文本应被切分为至少一个 chunk"
    assert any("文本入库管线" in d.page_content for d in docs)
    # _load_text_via_loader 会为每条 chunk 标注 source / category
    assert all("source" in d.metadata for d in docs)
    assert all(d.metadata.get("category") == "text" for d in docs)


def test_url_to_documents_ingestion_offline(monkeypatch):
    """网页来源摄取：离线用本地 HTML 替身替换联网抓取，验证整条管线。"""
    from src.rag import source_ingest

    html = (
        "<html><body>"
        "<h1>ALPHATOKEN_URL 帮助中心标题</h1>"
        "<p>这是从网页正文提取的段落，用于验证 URL 摄取管线。</p>"
        "</body></html>"
    )
    monkeypatch.setattr(source_ingest, "fetch_url_text", lambda url, timeout=15.0: html)

    docs = source_ingest.url_to_documents("https://example.com/doc", "示例网页", tenant_id="t1")
    assert docs, "网页内容应被切分为 chunk"
    assert any("ALPHATOKEN_URL" in d.page_content for d in docs)
    assert all(d.metadata.get("category") == "web" for d in docs)
    assert all(d.metadata.get("source_url") == "https://example.com/doc" for d in docs)


# ---------------------------------------------------------------------------
# 入库落库：kb_id 注入到每个 chunk 元数据（隔离的根因保障）
# ---------------------------------------------------------------------------

def test_ingest_internal_injects_kb_id_into_chunks(monkeypatch):
    """_ingest_document_internal 必须为每个 chunk 注入 kb_id / tenant_id / doc_id，
    并调用 retriever.add_documents（修复前缺失该方法导致索引静默失败）。"""
    from src.api.knowledge import KBSet, _ingest_document_internal
    import src.api.dependencies as dep

    class FakeRetriever:
        def __init__(self):
            self.added = []
            self.calls = 0

        def add_documents(self, documents, tenant_id=""):
            self.calls += 1
            self.added.extend(documents)

    fake = FakeRetriever()
    monkeypatch.setattr(dep, "get_retriever", lambda: fake)

    docs = [Document("ALPHATOKEN_A 知识库A内容", metadata={"source": "x.md"})]
    kb = KBSet(
        id="KBS-TEST",
        tenant_id="t1",
        name="测试知识库",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    item = _ingest_document_internal(
        tenant_id="t1",
        kb_id="KBS-TEST",
        file_path=None,
        title="我的文本",
        source_type="text",
        upload_method="agent",
        kb=kb,
        docs=docs,
    )

    # 落库字段正确
    assert item.kb_id == "KBS-TEST"
    assert item.source_type == "text"
    assert item.status.value == "indexed"

    # 真正调用了向量入库（核心回归点）
    assert fake.calls == 1
    # 每个 chunk 都被打上隔离元数据
    assert all(d.metadata.get("kb_id") == "KBS-TEST" for d in fake.added)
    assert all(d.metadata.get("tenant_id") == "t1" for d in fake.added)
    assert all(d.metadata.get("doc_id") == item.id for d in fake.added)
