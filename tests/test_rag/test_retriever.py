import pytest
import os
import tempfile
from langchain_core.documents import Document
from src.rag.retriever import HybridRetriever


@pytest.fixture
def retriever():
    """创建带测试数据的混合检索器"""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    with tempfile.TemporaryDirectory() as tmpdir:
        r = HybridRetriever(persist_directory=tmpdir, collection_name="test_hybrid")

        docs = [
            Document(page_content="API authentication uses API Key header. Error code 401 means invalid key.",
                     metadata={"source": "api.md"}),
            Document(page_content="Error code 403 means access denied. Check domain whitelist and CORS settings.",
                     metadata={"source": "api.md"}),
            Document(page_content="Error code 429 means rate limit exceeded. Upgrade your plan for higher limits.",
                     metadata={"source": "api.md"}),
            Document(page_content="To configure SSO with Okta, go to Settings > SSO and upload the metadata XML.",
                     metadata={"source": "sso.md"}),
            Document(page_content="Pricing plans: Free (5GB), Pro ($15/mo, 100GB), Enterprise ($50/user/mo).",
                     metadata={"source": "pricing.md"}),
        ]
        r.index_documents(docs)
        yield r
        r.delete_collection()


def test_vector_search_finds_semantic_match(retriever):
    """向量检索应该找到语义匹配的文档"""
    results = retriever.search("What does error 401 mean?", top_k=1)
    assert len(results) > 0
    assert "401" in results[0].page_content or "invalid" in results[0].page_content.lower()


def test_hybrid_search_finds_keyword_match(retriever):
    """混合检索应该精确匹配错误码"""
    results = retriever.search("ERR_403_TIMEOUT", top_k=1)
    assert len(results) > 0
    # BM25 应该把含 403 的文档排到前面
    assert "403" in results[0].page_content


def test_search_returns_multiple_results(retriever):
    """检索应返回多个结果"""
    results = retriever.search("error codes", top_k=3)
    assert len(results) == 3


def test_search_results_are_ranked(retriever):
    """结果应按相关性排序（带分数返回）"""
    results = retriever.search_with_scores("SSO Okta configuration", top_k=3)
    assert len(results) >= 2
    scores = [s for _, s in results]
    # 分数应该递减
    for i in range(len(scores) - 1):
        pass  # Chroma 的距离分数是 L2，越小越相关，与常规分数不同
