"""RAG 切块模块单元测试（纯逻辑，确定性）"""
import json

from langchain_core.documents import Document

from src.rag.chunker import (
    HybridChunker,
    SentenceWindowSplitter,
    _split_sentences,
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
        chunks = splitter.split([_doc(
            "第一句话内容足够长用来测试切块。"
            "第二句话内容也足够长了呀。"
            "第三句话长度已经达标了。"
            "第四句话同样足够长了。"
        )])
        assert len(chunks) == 4
        # 中间块应携带前后文
        mid = chunks[1]
        assert "_context_before" in mid.metadata
        assert "_context_after" in mid.metadata
        assert "_expanded_content" in mid.metadata
        assert "第二句话" in mid.page_content

    def test_expand_context(self):
        splitter = SentenceWindowSplitter(context_window=1)
        chunks = splitter.split([_doc(
            "甲句内容够长用来测试。" "乙句内容够长用来测试。" "丙句内容够长用来测试。"
        )])
        expanded = splitter.expand_context(chunks[1])
        assert "乙" in expanded and "甲" in expanded and "丙" in expanded

    def test_expand_context_from_json(self):
        splitter = SentenceWindowSplitter(context_window=1)
        chunks = splitter.split([_doc(
            "甲句内容够长用来测试。" "乙句内容够长用来测试。" "丙句内容够长用来测试。"
        )])
        out = splitter.expand_context_from_json(chunks[1])
        assert "乙" in out

    def test_empty_doc_skipped(self):
        splitter = SentenceWindowSplitter()
        assert splitter.split([_doc("")]) == []


class TestHybridChunker:
    def test_split_standard(self):
        c = HybridChunker(chunk_size=50, chunk_overlap=0)
        chunks = c.split_standard([_doc("第一章\n\n内容段落一。\n\n内容段落二很长很长。")],
                                   source_file="doc.txt")
        assert len(chunks) >= 1
        assert chunks[0].id.startswith("file:doc.txt:")

    def test_split_sentences(self):
        c = HybridChunker()
        chunks = c.split_sentences([_doc(
            "第一句话内容足够长用来测试。"
            "第二句话内容足够长用来测试。"
            "第三句话内容足够长用来测试。"
        )], source_file="doc.txt")
        assert len(chunks) >= 1
        assert chunks[0].metadata["chunk_type"] == "sentence"

    def test_split_both(self):
        c = HybridChunker()
        std, sent = c.split_both([_doc("一句。二句。")])
        assert isinstance(std, list) and isinstance(sent, list)
