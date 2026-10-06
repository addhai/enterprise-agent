"""RAG 切块模块单元测试（纯逻辑，确定性）"""

from langchain_core.documents import Document
from src.rag.chunker import (
    PAGE_BREAK,
    HybridChunker,
    SentenceWindowSplitter,
    _split_sentences,
    expand_pdf_pages,
)


def _doc(text: str) -> Document:
    return Document(page_content=text, metadata={"src": "unit"})


class TestSplitSentences:
    def test_empty(self):
        assert _split_sentences("") == []

    def test_cn_sentences(self):
        s = _split_sentences("你好世界。这是第二句！第三句？")
        assert len(s) == 3

    def test_paragraph_break(self):
        s = _split_sentences("第一段。\n\n第二段。新的句子。")
        assert len(s) >= 2


class TestSentenceWindowSplitter:
    def test_split_creates_window_chunks(self):
        splitter = SentenceWindowSplitter(context_window=2)
        chunks = splitter.split(
            [
                _doc(
                    "第一句话内容足够长用来测试切块。"
                    "第二句话内容也足够长了呀。"
                    "第三句话长度已经达标了。"
                    "第四句话同样足够长了。"
                )
            ]
        )
        assert len(chunks) == 4
        # 中间块应携带前后文
        mid = chunks[1]
        assert "_context_before" in mid.metadata
        assert "_context_after" in mid.metadata
        assert "_expanded_content" in mid.metadata
        assert "第二句话" in mid.page_content

    def test_expand_context(self):
        splitter = SentenceWindowSplitter(context_window=1)
        chunks = splitter.split(
            [_doc("甲句内容够长用来测试。乙句内容够长用来测试。丙句内容够长用来测试。")]
        )
        expanded = splitter.expand_context(chunks[1])
        assert "乙" in expanded and "甲" in expanded and "丙" in expanded

    def test_expand_context_from_json(self):
        splitter = SentenceWindowSplitter(context_window=1)
        chunks = splitter.split(
            [_doc("甲句内容够长用来测试。乙句内容够长用来测试。丙句内容够长用来测试。")]
        )
        out = splitter.expand_context_from_json(chunks[1])
        assert "乙" in out

    def test_empty_doc_skipped(self):
        splitter = SentenceWindowSplitter()
        assert splitter.split([_doc("")]) == []


class TestHybridChunker:
    def test_split_standard(self):
        c = HybridChunker(chunk_size=50, chunk_overlap=0)
        doc = _doc("第一章\n\n内容段落一。\n\n内容段落二很长很长。")
        chunks = c.split_standard([doc], source_file="doc.txt")
        assert len(chunks) >= 1
        assert chunks[0].id.startswith("file:doc.txt:")

    def test_split_sentences(self):
        c = HybridChunker()
        chunks = c.split_sentences(
            [
                _doc(
                    "第一句话内容足够长用来测试。"
                    "第二句话内容足够长用来测试。"
                    "第三句话内容足够长用来测试。"
                )
            ],
            source_file="doc.txt",
        )
        assert len(chunks) >= 1
        assert chunks[0].metadata["chunk_type"] == "sentence"

    def test_split_both(self):
        c = HybridChunker()
        std, sent = c.split_both([_doc("一句。二句。")])
        assert isinstance(std, list) and isinstance(sent, list)


class TestPdfPageStamping:
    """Q3 页码溯源：PDF 按物理页展开并盖 page 戳"""

    def test_non_pdf_doc_passthrough(self):
        doc = _doc("普通 md 内容，没有页边标记。")
        out = expand_pdf_pages([doc])
        assert out == [doc]
        assert "page" not in out[0].metadata

    def test_pages_numbered_from_one(self):
        doc = Document(
            page_content=f"第一页正文。{PAGE_BREAK}第二页正文。{PAGE_BREAK}第三页正文。",
            metadata={"source": "t.pdf"},
        )
        out = expand_pdf_pages([doc])
        assert [d.metadata["page"] for d in out] == [1, 2, 3]
        assert "第二页正文" in out[1].page_content
        # 展开后文本里不再含页边标记
        assert all(PAGE_BREAK not in d.page_content for d in out)

    def test_blank_page_segment_skipped_but_ordinal_kept(self):
        # 末页空白：跳过空段，前页页号不受影响
        doc = Document(
            page_content=f"首页内容。{PAGE_BREAK}次页内容。{PAGE_BREAK}\n",
            metadata={"source": "t.pdf"},
        )
        out = expand_pdf_pages([doc])
        assert [d.metadata["page"] for d in out] == [1, 2]

    def test_chapter_page_offset(self):
        # 章节文档带 _page_offset 时，page 从偏移后继续计数
        doc = Document(
            page_content=f"本章首段。{PAGE_BREAK}本章第二段。",
            metadata={"source": "t.pdf", "_page_offset": 9},
        )
        out = expand_pdf_pages([doc])
        assert [d.metadata["page"] for d in out] == [10, 11]
        # 内部偏移键不得透传到检索层
        assert all("_page_offset" not in d.metadata for d in out)

    def test_split_standard_stamps_page(self):
        c = HybridChunker(chunk_size=200, chunk_overlap=0)
        doc = Document(
            page_content=f"第一页的技术内容足够长一些用于测试切块。{PAGE_BREAK}"
            "第二页的技术内容同样足够长一些用于测试切块。",
            metadata={"source": "t90.pdf", "doc_format": "pdf"},
        )
        chunks = c.split_standard([doc], source_file="t90.pdf")
        pages = {ch.metadata.get("page") for ch in chunks}
        assert pages == {1, 2}

    def test_split_sentences_stamps_page(self):
        c = HybridChunker()
        doc = Document(
            page_content=f"第一页有一个足够长的完整句子用于测试。{PAGE_BREAK}"
            "第二页也有一个足够长的完整句子用于测试。",
            metadata={"source": "t90.pdf"},
        )
        chunks = c.split_sentences([doc], source_file="t90.pdf")
        assert all(ch.metadata.get("page") in (1, 2) for ch in chunks)
        assert {ch.metadata["page"] for ch in chunks} == {1, 2}
