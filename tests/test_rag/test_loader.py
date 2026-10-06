from pathlib import Path

from src.rag.loader import DocumentLoader


def test_load_markdown_directory():
    """加载 data/docs 目录下的所有 Markdown 文件"""
    loader = DocumentLoader()
    docs_dir = Path(__file__).parent.parent.parent / "data" / "docs"

    documents = loader.load_directory(str(docs_dir))

    assert len(documents) >= 5, f"Expected >= 5 documents, got {len(documents)}"

    # 每个文档应有内容和元数据（目录同时含 md 与 pdf 语料）
    for doc in documents:
        # PDF 按章节拆分后可能有较短的小节，非空且达到最小可读长度即可
        assert len(doc.page_content.strip()) >= 20, (
            f"Document too short: {doc.page_content[:50]}"
        )
        assert "source" in doc.metadata
        assert doc.metadata["source"].endswith((".md", ".pdf"))


def test_load_single_file():
    """加载单个文件"""
    loader = DocumentLoader()
    docs_dir = Path(__file__).parent.parent.parent / "data" / "docs"
    faq_path = docs_dir / "faq_full.md"

    documents = loader.load_file(str(faq_path))

    assert len(documents) > 0
    assert any("温度单位" in doc.page_content for doc in documents)


def test_metadata_contains_filename():
    """元数据应包含文件名"""
    loader = DocumentLoader()
    docs_dir = Path(__file__).parent.parent.parent / "data" / "docs"

    documents = loader.load_directory(str(docs_dir))

    filenames = [doc.metadata.get("source", "") for doc in documents]
    assert any("faq_full.md" in f for f in filenames)
    assert any("fault_troubleshooting_manual.md" in f for f in filenames)
