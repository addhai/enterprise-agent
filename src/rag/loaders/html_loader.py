"""HTML 格式加载器（BeautifulSoup 提取正文）"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from src.rag.data_sources import FileInfo
from src.rag.loaders.base import BaseLoader, register_loader
from src.rag.outline import (
    OutlineTree,
    extract_html_headings,
)

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


@register_loader(".html")
@register_loader(".htm")
class HtmlLoader(BaseLoader):
    """加载 HTML 文件，提取正文 + 大纲

    处理流程：
        1. 提取 h1-h6 标题构建大纲树
        2. 移除 heading 标签（避免内容重复）
        3. 按章节拆分文档
    """

    def load(self, info: FileInfo, base_meta: dict) -> List["_Doc"]:
        from src.rag.loader import (
            _filter_noise_paragraphs,
            _structure_hint,
            normalize_text,
        )
        from langchain_core.documents import Document

        encoding = base_meta.get("encoding", "utf-8")
        with open(str(info.path), "r", encoding=encoding, errors="replace") as f:
            html = f.read()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # 1. 提取大纲（在移除 heading 之前）
        headings = extract_html_headings(soup)

        # 2. 移除脚本、样式和导航元素
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 3. 移除 heading 标签（保留文本，避免重复）
        for level in range(1, 7):
            for tag in soup.find_all(f"h{level}"):
                tag.unwrap()  # 移除标签但保留文本内容

        text = soup.get_text(separator="\n")
        text = normalize_text(text)
        text = _filter_noise_paragraphs(text)

        if not text.strip():
            return []

        # 4. 按章节拆分
        outline_tree = OutlineTree()
        outline_tree.build(headings)
        source_name = info.name
        from src.config import settings
        store_json = getattr(settings, "outline_store_full_json", False)
        chapters = outline_tree.split(text, base_meta, source_file=source_name, store_outline_json=store_json)

        # 5. 注入结构感知提示
        for doc in chapters:
            doc.page_content = _structure_hint(doc)

        return chapters
