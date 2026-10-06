"""文档切块模块

支持的切块策略：
    1. 标准切块（RecursiveCharacterTextSplitter）
       - 按 H2/H3 标题层级优先断开
       - chunk_size + chunk_overlap
       - 适合技术文档长文段

    2. 句子窗口切块（SentenceWindowSplitter）
       - 小粒度检索（句子级）+ 大上下文生成（前后 N 句）
       - 适合 FAQ、错误码、参数等精确查询

    3. 混合切块（HybridSplitter）
       - 同时生成两种粒度
       - 检索走小粒度，生成用大上下文
"""

from __future__ import annotations

import logging
import re

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# pdf_loader 在页与页之间插入的硬边界标记
PAGE_BREAK = "\n---PAGE-BREAK---"


def expand_pdf_pages(documents: list[Document]) -> list[Document]:
    """把含 PAGE-BREAK 的 PDF 文档按物理页展开为多个 Document 并盖 page 戳。

    切块器把页边标记当硬切分边界，但切完从不回写页码，导致检索命中后
    无法告诉用户「答案在手册第几页」（2026-10-07 生产索引实测 164 块
    page 全空）。page 取物理页序（从 1 开始）；页眉印刷页码与物理页序
    的映射（doc.metadata["page_numbers"]）留待后续增强，现阶段物理页序
    已是可靠溯源信息。非 PDF 或无标记文档原样返回。
    """
    expanded: list[Document] = []
    for doc in documents:
        text = doc.page_content
        # 章节切片时记录的物理页偏移（见 outline.py）。该键是内部协议，
        # 无论走哪个分支都必须弹出，绝不允许进入 Chroma metadata。
        meta = dict(doc.metadata)
        offset_present = "_page_offset" in meta
        page_offset = int(meta.pop("_page_offset", 0) or 0)

        if PAGE_BREAK not in text:
            # 章节内容完全落在单个物理页内时（章末页最常见），章节文本
            # 不含 PAGE-BREAK，但偏移键存在，页码就是首页页本身。
            if offset_present:
                expanded.append(
                    Document(
                        page_content=text,
                        metadata={**meta, "page": page_offset + 1},
                    )
                )
            else:
                # 非 PDF 文档：meta 未变化时直接复用原对象
                expanded.append(
                    doc
                    if len(meta) == len(doc.metadata)
                    else Document(page_content=text, metadata=meta)
                )
            continue

        for idx, page_text in enumerate(text.split(PAGE_BREAK), start=1):
            if not page_text.strip():
                continue
            expanded.append(
                Document(
                    page_content=page_text,
                    metadata={**meta, "page": page_offset + idx},
                )
            )
    return expanded


# ---------------------------------------------------------------------------
# 句子分割器
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    """分割中文/英文句子

    支持的分隔符：
        中文：。！？；… （句号、感叹号、问号、分号、省略号）
        英文：.!?  （句点、感叹号、问号）
        段落：\n\n（空行）
    """
    if not text:
        return []

    # 先按段落分割
    paragraphs = re.split(r"\n\s*\n", text)
    sentences: list[str] = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # 中文/英文句子分割
        # 匹配：中文句号/叹号/问号 + 可选引号/括号
        parts = re.split(r"(?<=[。！？；\.\!\?])\s*", para)
        for part in parts:
            part = part.strip()
            if part:
                sentences.append(part)

    return sentences


# ---------------------------------------------------------------------------
# 句子窗口切块
# ---------------------------------------------------------------------------


class SentenceWindowSplitter:
    """Small2Big 切块：小粒度检索 + 大上下文生成

    工作流程：
        文档 → 句子级切分 → 每个句子独立成块（检索索引）
              → 同时保存前后 N 句的原文（生成上下文）

    示例（window=3）：
        原文：10 个句子
        切分后：10 个句子块 + 每个块携带前后最多 3 句的上下文

        检索命中第 5 句时：
          上下文 = [句2, 句3, 句4, ★句5, 句6, 句7, 句8]
          → LLM 拿到的是一个完整的上下文段落，而非孤立的一句话
    """

    def __init__(
        self,
        context_window: int = 3,
        min_sentence_length: int = 10,
    ):
        self.context_window = context_window
        self.min_sentence_length = min_sentence_length

    def split(self, documents: list[Document]) -> list[Document]:
        """将文档切分为句子级块，每个块携带上下文

        Returns:
            句子级 Document 列表，每个文档的 metadata 中包含：
                - _context_before: 前文句子列表
                - _context_after: 后文句子列表
                - _expanded_content: 合并后的完整上下文
        """
        chunks: list[Document] = []

        for doc in documents:
            sentences = _split_sentences(doc.page_content)

            # 过滤太短的句子（可能是标题、列表项等）
            sentences = [
                s for s in sentences if len(s.strip()) >= self.min_sentence_length
            ]

            if not sentences:
                continue

            for i, sentence in enumerate(sentences):
                # 获取前后上下文
                start = max(0, i - self.context_window)
                end = min(len(sentences), i + self.context_window + 1)
                before = sentences[start:i]
                after = sentences[i + 1 : end]

                # 构建扩展内容
                expanded_parts = before + [sentence] + after
                expanded_content = "\n".join(expanded_parts)

                # 创建句子级 chunk
                chunk_meta = {
                    **doc.metadata,
                    "_is_expanded": False,  # 标记这是小粒度块
                }

                chunk = Document(
                    page_content=sentence,
                    metadata=chunk_meta,
                )

                # 存储上下文信息（检索时不暴露，生成时才用）
                # Chroma 不接受空列表作为 metadata 值，转为 JSON 字符串
                import json

                chunk.metadata["_context_before"] = json.dumps(
                    before, ensure_ascii=False
                )
                chunk.metadata["_context_after"] = json.dumps(after, ensure_ascii=False)
                chunk.metadata["_expanded_content"] = expanded_content

                chunks.append(chunk)

        logger.info(
            "SentenceWindowSplitter: %d docs → %d sentence chunks (window=%d)",
            len(documents),
            len(chunks),
            self.context_window,
        )
        return chunks

    def expand_context(self, chunk: Document) -> str:
        """从 chunk 的 metadata 中恢复完整上下文"""
        expanded = chunk.metadata.get("_expanded_content", "")
        if expanded:
            return expanded
        return chunk.page_content

    def expand_context_from_json(self, chunk: Document) -> str:
        """从 JSON 序列化的 metadata 中恢复上下文（兼容新格式）"""
        import json

        expanded = chunk.metadata.get("_expanded_content", "")
        if expanded:
            return expanded

        # 从 JSON 反序列化前后文
        before_str = chunk.metadata.get("_context_before", "[]")
        after_str = chunk.metadata.get("_context_after", "[]")

        try:
            before = (
                json.loads(before_str) if isinstance(before_str, str) else before_str
            )
            after = json.loads(after_str) if isinstance(after_str, str) else after_str
        except (json.JSONDecodeError, TypeError):
            before, after = [], []

        if isinstance(before, list):
            before = [s for s in before if s]
        if isinstance(after, list):
            after = [s for s in after if s]

        parts = before + [chunk.page_content] + after
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# 混合切块器（标准 + 句子窗口）
# ---------------------------------------------------------------------------


class HybridChunker:
    """同时生成两种粒度的切块

    用途：一套索引（标准粒度）+ 一套索引（句子粒度）
    检索时两路并行，RRF 融合后返回。

    也可以只生成句子粒度，然后在检索后动态展开上下文。
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        context_window: int = 3,
    ):
        self.standard_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            # 页边标记作为硬切分边界，防止跨页切断句子
            separators=[
                "\n## ",  # H2 标题
                "\n### ",  # H3 标题
                "\n#### ",  # H4 标题
                "\n---PAGE-BREAK---",  # 页边标记（PDF 专用）
                "\n",  # 段落
                " ",  # 空格
                "",  # 字符
            ],
            length_function=len,
        )
        self.sentence_splitter = SentenceWindowSplitter(
            context_window=context_window,
        )

    def split_standard(
        self, documents: list[Document], source_file: str | None = None
    ) -> list[Document]:
        """标准粒度切块（适合技术文档长文段）

        Args:
            documents: 待切分的文档列表
            source_file: 可选的源文件路径。若提供，为每个 chunk 分配
                确定性 ID ``f"file:{source_file}:{i}"``，否则使用 LangChain
                默认的 UUID。
        """
        chunks = self.standard_splitter.split_documents(expand_pdf_pages(documents))

        if source_file is not None:
            for i, chunk in enumerate(chunks):
                chunk.id = f"file:{source_file}:{i}"
                chunk.metadata["source_file"] = source_file
                chunk.metadata["chunk_index"] = i
                chunk.metadata["chunk_type"] = "standard"

        return chunks

    def split_sentences(
        self, documents: list[Document], source_file: str | None = None
    ) -> list[Document]:
        """句子粒度切块（适合 FAQ/错误码精确匹配）

        Args:
            documents: 待切分的文档列表
            source_file: 可选的源文件路径。若提供，为每个 chunk 分配
                确定性 ID ``f"file:{source_file}:sentence:{i}"``。
        """
        chunks = self.sentence_splitter.split(expand_pdf_pages(documents))

        if source_file is not None:
            for idx, doc in enumerate(chunks):
                doc.id = f"file:{source_file}:sentence:{idx}"
                doc.metadata["source_file"] = source_file
                doc.metadata["chunk_index"] = idx
                doc.metadata["chunk_type"] = "sentence"

        return chunks

    def split_both(
        self,
        documents: list[Document],
        source_file: str | None = None,
    ) -> tuple[list[Document], list[Document]]:
        """同时生成两种粒度

        Args:
            documents: 待切分的文档列表
            source_file: 可选的源文件路径

        Returns:
            (standard_chunks, sentence_chunks)
        """
        standard = self.split_standard(documents, source_file=source_file)
        sentences = self.split_sentences(documents, source_file=source_file)
        return standard, sentences
