"""结构感知处理器（代码块、表格、列表检测）"""
from __future__ import annotations

import logging
import re

from src.rag.processors.base import BaseProcessor, ProcessingContext

logger = logging.getLogger(__name__)


class StructureDetectProcessor(BaseProcessor):
    """结构检测与标记处理器

    检测文本中的结构化元素（代码块、表格、列表），
    并在文档内容前注入结构化提示，帮助下游模型理解文档结构。
    """

    @property
    def name(self) -> str:
        return "structure_detect"

    def process(self, doc: "Document", ctx: ProcessingContext) -> "Document":
        doc.page_content = _structure_hint(doc)
        return doc


def _detect_structure(text: str) -> dict:
    """检测文本中的结构化元素（代码块、表格、列表）

    Returns:
        {"code_blocks": int, "tables": int, "lists": int,
         "has_code": bool, "has_table": bool, "has_list": bool}
    """
    info = {
        "code_blocks": len(re.findall(r"^```", text, re.MULTILINE)),
        "tables": len(re.findall(r"^\|.*\|", text, re.MULTILINE)),
        "lists": len(re.findall(r"^\s*[-*•]\s+", text, re.MULTILINE))
                  + len(re.findall(r"^\s*\d+\.\s+", text, re.MULTILINE)),
    }
    info["has_code"] = info["code_blocks"] > 0
    info["has_table"] = info["tables"] >= 3
    info["has_list"] = info["lists"] > 0
    return info


def _structure_hint(doc: "Document") -> str:
    """根据结构检测结果生成结构化提示，注入到 page_content 前面"""
    info = _detect_structure(doc.page_content)
    hints = []
    if info["has_code"]:
        hints.append("[Contains code blocks]")
    if info["has_table"]:
        hints.append("[Contains tables]")
    if info["has_list"]:
        hints.append("[Contains lists]")
    if hints:
        return "\n".join(hints) + "\n" + doc.page_content
    return doc.page_content
