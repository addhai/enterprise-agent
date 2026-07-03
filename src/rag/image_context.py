"""图文上下文关联

将图片与其在原文档中的上下文（前后文段落、章节标题）关联起来，
存入 Document metadata，提升检索相关性。

当前阶段：图片作为独立文件加载时上下文为空，为后续文档内插图
（图片嵌入在 PDF/HTML/DOCX 中）预留接口。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ImageContext:
    """图片上下文信息

    Attributes:
        image_path: 图片文件路径
        image_type: 图片类型（screenshot/diagram/scanned_document 等）
        source_file: 来源文档路径（如图片嵌入在 PDF 中）
        page_number: 所在页码（PDF/扫描件）
        preceding_paragraphs: 前 N 段文字（文档内插图时有效）
        following_paragraphs: 后 N 段文字（文档内插图时有效）
        heading_context: 所属章节标题路径（如 "2.1 认证方式"）
        extraction_method: 提取方式（vision_dashscope / ocr_paddle 等）
        model: 使用的模型名（视觉引擎）
    """

    image_path: str
    image_type: str = "generic"
    source_file: str = ""
    page_number: Optional[int] = None
    preceding_paragraphs: List[str] = field(default_factory=list)
    following_paragraphs: List[str] = field(default_factory=list)
    heading_context: str = ""
    extraction_method: str = ""
    model: str = ""

    def to_metadata(self) -> dict:
        """序列化为 Document metadata 字典"""
        meta: dict = {
            "image_type": self.image_type,
            "extraction_method": self.extraction_method,
            "model": self.model,
        }
        if self.source_file:
            meta["source_file"] = self.source_file
        if self.page_number is not None:
            meta["page_number"] = self.page_number
        if self.heading_context:
            meta["heading_context"] = self.heading_context
        if self.preceding_paragraphs:
            meta["preceding_context"] = "\n".join(self.preceding_paragraphs)
        if self.following_paragraphs:
            meta["following_context"] = "\n".join(self.following_paragraphs)
        return meta


def infer_image_type(image_path: str) -> str:
    """根据文件名推断图片类型

    与 ImageLoader._classify_image_type 逻辑一致，
    避免重复实现。
    """
    path_lower = image_path.lower()
    if any(kw in path_lower for kw in ["screenshot", "screen_shot", "ui", "interface"]):
        return "screenshot"
    if any(kw in path_lower for kw in ["error", "exception", "stacktrace", "log"]):
        return "error_screenshot"
    if any(kw in path_lower for kw in ["chart", "diagram", "architecture", "flow"]):
        return "diagram"
    if any(kw in path_lower for kw in ["scan", "paper", "handwritten", "photo"]):
        return "scanned_document"
    if any(kw in path_lower for kw in ["table", "spreadsheet", "data"]):
        return "table_image"
    return "generic"
