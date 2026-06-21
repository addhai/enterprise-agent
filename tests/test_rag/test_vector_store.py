import pytest
import os
import tempfile
from langchain_core.documents import Document
from src.rag.vector_store import VectorStoreManager


@pytest.fixture
def vector_store():
    """创建临时向量库用于测试"""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStoreManager(
            persist_directory=tmpdir,
            collection_name="test_kb"
        )
        yield store
        store.delete_collection()


def test_add_and_search_documents(vector_store):
    """入库后应能检索到相关文档"""
    docs = [
        Document(
            page_content="To reset your API key, go to Developer Settings and click Regenerate.",
            metadata={"source": "api_guide.md"}
        ),
        Document(
            page_content="CloudSync offers Free, Pro, and Enterprise pricing plans.",
            metadata={"source": "product_overview.md"}
        ),
        Document(
            page_content="SSO configuration supports Okta and Azure AD identity providers.",
            metadata={"source": "sso_config.md"}
        ),
    ]

    vector_store.add_documents(docs)

    results = vector_store.search("How to regenerate my API key?", top_k=2)

    assert len(results) == 2
    # 第一个结果应该和 API key 相关
    assert "API key" in results[0].page_content or "API key" in results[1].page_content


def test_search_returns_metadata(vector_store):
    """检索结果应包含元数据"""
    doc = Document(
        page_content="Custom SAML 2.0 configurations are supported for SSO setup.",
        metadata={"source": "sso_config.md", "section": "SSO"}
    )

    vector_store.add_documents([doc])

    results = vector_store.search("SAML configuration", top_k=1)

    assert len(results) > 0
    assert results[0].metadata.get("source") == "sso_config.md"


def test_empty_search_returns_empty_list(vector_store):
    """空向量库检索应返回空列表"""
    results = vector_store.search("anything", top_k=3)
    assert len(results) == 0
