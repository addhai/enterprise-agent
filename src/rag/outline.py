"""文档大纲提取模块

从 Markdown / PDF / HTML / DOCX 等格式的标题层级中提取结构化大纲，
将文档按章节边界拆分为多个 Document，每个 Document 携带 chapter_path
和 heading_level 元数据，供下游分块器和检索器使用。

数据流：
    原始文本 → 提取标题列表(level, text) → 构建 OutlineTree
    → split_documents() → 按章节切分为多个 Document
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OutlineNode — 大纲树节点
# ---------------------------------------------------------------------------


@dataclass
class OutlineNode:
    """大纲树的一个节点

    Attributes:
        text: 标题文本（如 "2.1 认证方式"）
        level: 层级（1-6）
        page: PDF 页码（如有）
        children: 子节点列表
    """

    text: str
    level: int
    page: Optional[int] = None
    children: List["OutlineNode"] = field(default_factory=list)

    def add_child(self, node: "OutlineNode") -> None:
        self.children.append(node)

    def to_dict(self) -> dict:
        """序列化为字典（用于存入 metadata）"""
        return {
            "text": self.text,
            "level": self.level,
            "page": self.page,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OutlineNode":
        """从字典反序列化"""
        node = cls(
            text=data["text"],
            level=data["level"],
            page=data.get("page"),
        )
        for child_data in data.get("children", []):
            node.add_child(cls.from_dict(child_data))
        return node


# ---------------------------------------------------------------------------
# OutlineTree — 大纲树构建器
# ---------------------------------------------------------------------------


class OutlineTree:
    """大纲树

    从扁平的标题列表构建嵌套树结构，支持按章节拆分文档。

    用法：
        tree = OutlineTree()
        tree.build(headings)          # headings: [(level, text), ...]
        chapters = tree.split(text)   # → List[Document]
    """

    def __init__(self) -> None:
        self.root: Optional[OutlineNode] = None
        self.headings: List[Tuple[int, str, Optional[int]]] = []  # (level, text, page)

    def build(self, headings: List[Tuple[int, str, Optional[int]]]) -> "OutlineTree":
        """从扁平标题列表构建大纲树

        算法：维护一个栈，当前标题压栈，子标题弹出父级直到找到合适层级。

        Args:
            headings: [(level, text, page), ...] 按文档顺序排列的标题列表
        """
        self.headings = headings
        if not headings:
            self.root = None
            return self

        self.root = OutlineNode(text=headings[0][1], level=headings[0][0], page=headings[0][2])
        stack: List[OutlineNode] = [self.root]

        for level, text, page in headings[1:]:
            node = OutlineNode(text=text, level=level, page=page)

            # 弹出栈中层级 >= 当前层级的节点
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()

            # 当前栈顶是当前节点的父级
            stack[-1].add_child(node)
            stack.append(node)

        return self

    def flatten(self) -> List[Tuple[str, str, int]]:
        """返回扁平化的 [(chapter_path, heading_text, level), ...]

        chapter_path 是祖先标题拼接的路径，如 "1. 概述 / 2.1 认证方式"。
        """
        if not self.root:
            return []

        result: List[Tuple[str, str, int]] = []

        def _walk(node: OutlineNode, ancestors: List[str]) -> None:
            path = " / ".join(ancestors + [node.text])
            result.append((path, node.text, node.level))
            for child in node.children:
                _walk(child, ancestors + [node.text])

        _walk(self.root, [])
        return result

    def get_chapter_path(self, level: int, text: str) -> str:
        """查找某个标题对应的 chapter_path"""
        for path, heading_text, _ in self.flatten():
            if heading_text == text:
                return path
        return ""

    def split(
        self,
        full_text: str,
        base_meta: dict,
        source_file: str = "",
        store_outline_json: bool = False,
    ) -> List["_Doc"]:
        """按章节边界拆分文档为多个 Document

        每个 Document 的 metadata 包含：
            - chapter_path: 所属章节路径（如 "1. 概述 / 2.1 认证方式"）
            - heading_level: 该章节的标题层级
            - heading_text: 该章节的标题文本
            - outline: 完整大纲树 JSON（仅当 store_outline_json=True 时存入）

        如果没有标题，整篇文档作为单个 Document 返回。

        章节边界规则：
            一个 Hn 标题包含其后所有文本，直到遇到同级或更高级别（<=n）的标题。
            子标题（>n 级）的内容归属于父标题章节。

        Args:
            full_text: 完整文档文本
            base_meta: 基础元数据（会被合并到每个 Document 的 metadata）
            source_file: 源文件路径（用于生成确定性 chunk ID）
            store_outline_json: 是否在 metadata 中存储完整大纲 JSON。
                False（默认）：仅存 chapter_path / heading_level / heading_text，
                节省存储体积。适合大多数场景。
                True：额外存储 outline 完整树 JSON，
                支持检索时按章节路径路由、过滤。
        """
        if not self.root:
            # 无标题 → 整篇作为一个文档
            from langchain_core.documents import Document
            meta = {**base_meta, "source_file": source_file}
            return [Document(page_content=full_text.strip(), metadata=meta)]

        # 按标题定位章节边界
        heading_pattern = re.compile(
            r"^(#{1,6})\s+(.+)$", re.MULTILINE
        )
        matches = list(heading_pattern.finditer(full_text))

        if not matches:
            # 无匹配标题 → 整篇作为一个文档
            from langchain_core.documents import Document
            meta = {**base_meta, "source_file": source_file}
            return [Document(page_content=full_text.strip(), metadata=meta)]

        from langchain_core.documents import Document

        # 序列化大纲树（可选，避免不必要的 JSON 开销）
        outline_json: Optional[str] = None
        if store_outline_json:
            outline_json = json.dumps(self.root.to_dict(), ensure_ascii=False)

        chapters: List["_Doc"] = []
        flat_headings = self.flatten()

        for i, match in enumerate(matches):
            # 标题文本和层级
            heading_text = match.group(2).strip()
            heading_level = len(match.group(1))

            # 查找对应的 chapter_path
            chapter_path = ""
            for path, ht, lvl in flat_headings:
                if ht == heading_text and lvl == heading_level:
                    chapter_path = path
                    break
            if not chapter_path:
                chapter_path = heading_text

            # 章节内容：从当前标题后面到下一个同级或更高级别标题前面
            # 子标题（更深层级）的内容归属于父标题
            end_pos = len(full_text)
            for j in range(i + 1, len(matches)):
                next_level = len(matches[j].group(1))
                if next_level <= heading_level:
                    end_pos = matches[j].start()
                    break

            content = full_text[match.end():end_pos].strip()

            if not content:
                continue

            meta = {
                **base_meta,
                "source_file": source_file,
                "chapter_path": chapter_path,
                "heading_level": heading_level,
                "heading_text": heading_text,
            }
            # 仅在开启时存储完整大纲 JSON
            if store_outline_json and outline_json is not None:
                meta["outline"] = outline_json

            chapters.append(Document(page_content=content, metadata=meta))

        logger.info(
            "OutlineTree.split: %d headings → %d chapters (store_outline_json=%s)",
            len(matches), len(chapters), store_outline_json,
        )
        return chapters


# ---------------------------------------------------------------------------
# 标题提取工具函数
# ---------------------------------------------------------------------------


def extract_markdown_headings(text: str) -> List[Tuple[int, str, Optional[int]]]:
    """从 Markdown 文本中提取标题列表

    Args:
        text: Markdown 格式的文本

    Returns:
        [(level, text, page), ...]
        level: 1-6 对应 # 到 ######
    """
    pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    headings: List[Tuple[int, str, Optional[int]]] = []
    for match in pattern.finditer(text):
        level = len(match.group(1))
        title = match.group(2).strip()
        headings.append((level, title, None))
    return headings


def extract_html_headings(soup) -> List[Tuple[int, str, Optional[int]]]:
    """从 BeautifulSoup 的 soup 中提取 h1-h6 标题

    Args:
        soup: BeautifulSoup 对象

    Returns:
        [(level, text, page), ...]
    """
    headings: List[Tuple[int, str, Optional[int]]] = []
    for level in range(1, 7):
        for tag in soup.find_all(f"h{level}"):
            text = tag.get_text(strip=True)
            if text:
                headings.append((level, text, None))
    return headings


def extract_docx_headings(paragraphs) -> List[Tuple[int, str, Optional[int]]]:
    """从 python-docx 的 paragraph 列表中提取 Heading 样式的标题

    Args:
        paragraphs: docx.document.Document.paragraphs

    Returns:
        [(level, text, page), ...]
    """
    headings: List[Tuple[int, str, Optional[int]]] = []
    for para in paragraphs:
        style_name = (para.style.name or "").lower()
        if "heading" in style_name:
            # 提取层级数字
            match = re.search(r"(\d+)", style_name)
            level = int(match.group(1)) if match else 1
            level = min(level, 6)  # 上限 6
            text = para.text.strip()
            if text:
                headings.append((level, text, None))
    return headings


def extract_pdf_bookmarks(doc) -> List[Tuple[int, str, Optional[int]]]:
    """从 PyMuPDF 文档中提取书签（outline）

    Args:
        doc: fitz.Document 对象

    Returns:
        [(level, text, page), ...]
        level 基于标题文本中的 # 模式推断（书签本身没有层级）
    """
    bookmarks = doc.get_toc()  # [(level, title, page, ...) ]
    # PyMuPDF 的 toc level: 1=H1, 2=H2, ... 6=H6
    headings: List[Tuple[int, str, Optional[int]]] = []
    for level, title, page in bookmarks:
        level = min(max(level, 1), 6)
        text = title.strip()
        if text:
            headings.append((level, text, page))
    return headings


def extract_pdf_body_headings(text: str) -> List[Tuple[int, str, Optional[int]]]:
    """从 PDF 正文文本中提取标题模式（书签缺失时的降级方案）

    支持的标题模式：
        - Markdown 风格: # Title, ## Subtitle
        - 中文风格: 第一章、第一节
        - 数字编号: 1. Title, 1.1 Subtitle
    """
    headings: List[Tuple[int, str, Optional[int]]] = []

    # Markdown 风格
    for match in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE):
        level = len(match.group(1))
        text_val = match.group(2).strip()
        if text_val:
            headings.append((level, text_val, None))

    # 中文章节风格: "第一章"、"第一节"、"第三部分"
    cn_pattern = r"^([一二三四五六七八九十]+)[章节篇部回]\s*(.+)$"
    for match in re.finditer(cn_pattern, text, re.MULTILINE):
        headings.append((1, f"{match.group(1)}{match.group(2)}", None))

    # 数字编号风格: "1. Title", "1.1 Subtitle"
    num_pattern = r"^(\d+(?:\.\d+)*)\.\s+(.+)$"
    for match in re.finditer(num_pattern, text, re.MULTILINE):
        parts = match.group(1).split(".")
        level = min(len(parts), 6)
        text_val = match.group(2).strip()
        if text_val:
            headings.append((level, text_val, None))

    return headings
