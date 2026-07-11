"""Markdown 格式加载器"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from src.rag.data_sources import FileInfo
from src.rag.loaders.base import BaseLoader, register_loader
from src.rag.outline import OutlineTree, extract_markdown_headings

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


@register_loader(".md")
class MarkdownLoader(BaseLoader):
    """加载 Markdown 文件

    处理流程：
        1. 解析 # 层级标题，构建大纲树
        2. 按章节边界拆分文档
        3. 每个章节 Document 携带 chapter_path / heading_level / outline
    """

    def load(self, info: FileInfo, base_meta: dict) -> List["_Doc"]:
        from langchain_community.document_loaders import TextLoader

        from src.rag.loader import (
            _filter_noise_paragraphs,
            _structure_hint,
            normalize_text,
        )

        encoding = base_meta.get("encoding", "utf-8")
        loader = TextLoader(str(info.path), encoding=encoding)
        docs = loader.load()

        if not docs:
            return []

        # 合并所有文档为一个完整文本
        full_text = "\n\n".join(d.page_content for d in docs)
        full_text = normalize_text(full_text)
        full_text = _filter_noise_paragraphs(full_text)

        if not full_text.strip():
            return []

        # 提取标题，构建大纲树
        headings = extract_markdown_headings(full_text)
        outline_tree = OutlineTree()
        outline_tree.build(headings)

        # 按章节拆分
        source_name = info.name
        from src.config import settings
        store_json = getattr(settings, "outline_store_full_json", False)
        chapters = outline_tree.split(full_text, base_meta, source_file=source_name, store_outline_json=store_json)

        # 对每个章节注入结构感知提示
        for doc in chapters:
            doc.page_content = _structure_hint(doc)
            doc.metadata = {**base_meta, **doc.metadata}

        return chapters
