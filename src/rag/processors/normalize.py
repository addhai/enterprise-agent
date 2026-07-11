"""文本归一化处理器"""
from __future__ import annotations

import logging
import re

from src.rag.processors.base import BaseProcessor, ProcessingContext

logger = logging.getLogger(__name__)


class NormalizeTextProcessor(BaseProcessor):
    """文本规范化处理器

    执行：
        1. 全角→半角
        2. 中文省略号标准化
        3. 合并连续空白/换行
        4. 去除行首尾空白（保留段落结构）
    """

    @property
    def name(self) -> str:
        return "normalize_text"

    def process(self, doc: "Document", ctx: ProcessingContext) -> "Document":
        doc.page_content = normalize_text(doc.page_content)
        return doc


def normalize_text(text: str) -> str:
    """文本规范化：全角→半角、多余空白、中文标点统一

    不做语义变更，只做格式标准化。
    """
    if not text:
        return text

    # 全角字母/数字 → 半角
    result = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:  # 全角 ASCII 范围
            result.append(chr(code - 0xFEE0))
        else:
            result.append(ch)
    text = "".join(result)

    # 中文省略号 → 标准省略号
    text = text.replace("……", "…")

    # 合并连续空白为单个空格
    text = re.sub(r"[ \t]+", " ", text)
    # 合并连续换行（3+ 个）为 2 个
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 去除行首尾空白（保留段落结构）
    text = "\n".join(line.strip() for line in text.splitlines())

    return text.strip()
