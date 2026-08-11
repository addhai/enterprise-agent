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


#: 已知的结构提示标记，用于幂等性检测（防止处理器重复执行导致标记堆叠）
_KNOWN_HINTS = ("[Contains code blocks]", "[Contains tables]", "[Contains lists]")


def _strip_existing_hints(text: str) -> str:
    """剥离开头已存在的结构提示标记

    处理器可能在流水线中被重复调用（或文档被二次入库），
    若不剥离会出现 "[Contains code blocks]" 堆叠多份的情况，
    既浪费 embedding token，也污染回传给 LLM 的上下文。
    """
    lines = text.split("\n")
    idx = 0
    while idx < len(lines) and lines[idx].strip() in _KNOWN_HINTS:
        idx += 1
    return "\n".join(lines[idx:])


def _structure_hint(doc: "Document") -> str:
    """根据结构检测结果生成结构化提示，注入到 page_content 前面（幂等）"""
    # 先剥离旧标记，保证重复执行结果一致
    body = _strip_existing_hints(doc.page_content)

    info = _detect_structure(body)
    hints = []
    if info["has_code"]:
        hints.append("[Contains code blocks]")
    if info["has_table"]:
        hints.append("[Contains tables]")
    if info["has_list"]:
        hints.append("[Contains lists]")
    if hints:
        return "\n".join(hints) + "\n" + body
    return body
