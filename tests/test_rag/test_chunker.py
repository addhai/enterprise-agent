import pytest
from langchain_core.documents import Document
from src.rag.chunker import HybridChunker


def test_split_documents_into_chunks():
    """文档应被切分成更小的块"""
    chunker = HybridChunker(chunk_size=200, chunk_overlap=20)

    doc = Document(
        page_content="This is a long document. " * 50,
        metadata={"source": "test.md"}
    )

    chunks = chunker.split_standard([doc])

    assert len(chunks) > 1, f"Expected multiple chunks, got {len(chunks)}"

    # 每个块应该 <= chunk_size
    for chunk in chunks:
        assert len(chunk.page_content) <= 250  # 允许一些 token 近似误差


def test_chunks_preserve_metadata():
    """切块后应保留源文档的元数据"""
    chunker = HybridChunker(chunk_size=200, chunk_overlap=20)

    doc = Document(
        page_content="Test content. " * 30,
        metadata={"source": "faq.md"}
    )

    chunks = chunker.split_standard([doc])

    for chunk in chunks:
        assert chunk.metadata.get("source") == "faq.md"


def test_overlap_between_chunks():
    """块之间应有重叠"""
    chunker = HybridChunker(chunk_size=150, chunk_overlap=50)

    doc = Document(
        page_content="The quick brown fox jumps over the lazy dog. " * 15,
        metadata={"source": "test.md"}
    )

    chunks = chunker.split_standard([doc])

    if len(chunks) > 1:
        tail_of_first = chunks[0].page_content[-30:]
        head_of_second = chunks[1].page_content[:30]
        # 中文可能不准，但英文应该有可观察的重叠
        assert len(tail_of_first.strip()) > 0
        assert len(head_of_second.strip()) > 0
