"""PDF 格式加载器（PyMuPDF）"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from src.rag.data_sources import FileInfo
from src.rag.loaders.base import BaseLoader, register_loader
from src.rag.outline import (
    OutlineTree,
    extract_pdf_body_headings,
    extract_pdf_bookmarks,
)

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


@register_loader(".pdf")
class PdfLoader(BaseLoader):
    """加载 PDF 文件（逐页合并为完整文档 + 页边标记）

    处理流程：
        1. 逐页提取文字，做结构化页眉页脚处理
        2. 插入页边标记 ---PAGE-BREAK---
        3. 提取大纲：优先 PDF 书签，降级正文标题解析
        4. 按章节拆分文档
    """

    def load(self, info: FileInfo, base_meta: dict) -> List["_Doc"]:
        from src.rag.loader import (
            _filter_noise_paragraphs,
            _process_page_header_footer,
            _structure_hint,
            normalize_text,
        )

        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.warning(
                "PyMuPDF (fitz) not installed. Install with: pip install pymupdf"
            )
            return []

        doc_handle = fitz.open(str(info.path))

        # 从 PDF 内部元数据提取信息
        pdf_meta = doc_handle.metadata or {}
        base_meta["author"] = pdf_meta.get("author", "") or ""
        base_meta["title"] = pdf_meta.get("title", "") or ""
        base_meta["producer"] = pdf_meta.get("producer", "") or ""

        # 逐页提取文字，做结构化处理
        processed_pages: List[str] = []
        page_numbers: List[int] = []
        for page_num in range(len(doc_handle)):
            page = doc_handle[page_num]
            text = page.get_text()
            text = normalize_text(text)

            lines = text.split("\n")
            processed_text, page_info, title_info = _process_page_header_footer(lines)

            if page_info:
                page_numbers.append(page_info.get("page", page_num + 1))

            if title_info and not base_meta.get("title"):
                base_meta["title"] = title_info.get("document_title", "")

            if processed_text.strip():
                processed_pages.append(processed_text)

        doc_handle.close()

        if not processed_pages:
            return []

        # 合并为完整文档
        full_text = "\n---PAGE-BREAK---\n".join(processed_pages)
        meta = {
            **base_meta,
            "total_pages": len(processed_pages),
            "page_numbers": page_numbers if page_numbers else None,
        }

        # 提取大纲：优先书签，降级正文标题解析
        headings = extract_pdf_bookmarks(doc_handle)
        if not headings:
            # 书签缺失 → 从正文标题模式推断
            headings = extract_pdf_body_headings(full_text)
            if headings:
                logger.info("PDF: extracted %d headings from body text (no bookmarks)", len(headings))

        # 按章节拆分
        outline_tree = OutlineTree()
        outline_tree.build(headings)
        from src.config import settings
        store_json = getattr(settings, "outline_store_full_json", False)
        chapters = outline_tree.split(full_text, meta, source_file=info.name, store_outline_json=store_json)

        # 对每个章节注入结构感知提示
        for doc in chapters:
            doc.page_content = _structure_hint(doc)

        return chapters
