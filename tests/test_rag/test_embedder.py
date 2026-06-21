import pytest
import os
from src.rag.embedder import Embedder


@pytest.fixture
def embedder():
    """需要有 OPENAI_API_KEY 才能跑"""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    return Embedder()


def test_embed_single_text(embedder):
    """单条文本应返回 1536 维向量"""
    result = embedder.embed_text("How do I reset my API key?")

    assert isinstance(result, list)
    assert len(result) == 1536
    # 向量应该有非零值
    assert any(abs(v) > 0.001 for v in result)


def test_embed_multiple_texts(embedder):
    """批量文本应返回多个向量"""
    texts = [
        "How do I reset my password?",
        "What is the pricing plan?",
        "How to configure SSO?"
    ]

    results = embedder.embed_documents(texts)

    assert len(results) == 3
    assert all(len(v) == 1536 for v in results)


def test_similar_texts_have_closer_vectors(embedder):
    """语义相近的文本向量距离应更近"""
    query = embedder.embed_text("reset password")
    similar = embedder.embed_text("forgot password recovery")
    different = embedder.embed_text("pricing plans billing")

    # 余弦相似度：query vs similar 应 > query vs different
    from numpy import dot
    from numpy.linalg import norm

    def cosine(a, b):
        return dot(a, b) / (norm(a) * norm(b))

    sim_similar = cosine(query, similar)
    sim_different = cosine(query, different)

    assert sim_similar > sim_different, \
        f"Expected {sim_similar:.3f} > {sim_different:.3f}"
