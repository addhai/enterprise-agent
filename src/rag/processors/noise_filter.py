"""噪声过滤处理器（页眉页脚、导航元素）"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from src.rag.processors.base import BaseProcessor, ProcessingContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 导航元素模式（纯噪音，直接过滤）
# ---------------------------------------------------------------------------

_NAV_PATTERNS = [
    r"^(Home|About|Contact|Support|Pricing|Login|Sign\s*up)$",
    r"^(Home\s*\|\s*(About|Contact|Support|Pricing|Login))(\s*\|\s*.+)?$",
    r"^©\s*\d{4}\s+CloudSync$",
    r"^CloudSync\s+Confidential$",
    r"^Table\s+of\s+Contents$",
    r"^(Disclaimer|Terms\s+of\s+Service|Privacy\s+Policy)$",
]
_nav_regexes = [re.compile(p, re.IGNORECASE) for p in _NAV_PATTERNS]

# 页码提取模式
_PAGE_PATTERNS = [
    r"^(?:Page|页|P\.?)\s*(\d+)\s*(?:of\s+(\d+))?$",
    r"^(\d+)\s*/\s*(\d+)$",
    r"^第\s*(\d+)\s*页(\s*/\s*\d+)?$",
    r"^\s*(\d+)\s*$",
]
_page_regexes = [re.compile(p) for p in _PAGE_PATTERNS]

# 文档标题提取模式
_TITLE_PATTERNS = [
    r"^(.+?)\s*(?:—|–|-|：)\s*(v\d+(?:\.\d+)*)$",
    r"^(.+?)\s*(?:—|–|-|：)\s*(Confidential|Internal|Draft|机密)$",
    r"^(.+?)\s+v(\d+(?:\.\d+)*)$",
    r"^#{1,3}\s+.+$",
]
_title_regexes = [re.compile(p) for p in _TITLE_PATTERNS]


class NoiseFilterProcessor(BaseProcessor):
    """页眉页脚和导航噪声过滤处理器

    执行：
        1. 过滤导航元素（Home, About, Copyright 等）
        2. 提取页码信息到 metadata
        3. 提取文档标题到 metadata
    """

    @property
    def name(self) -> str:
        return "noise_filter"

    def process(self, doc: "Document", ctx: ProcessingContext) -> "Document":
        doc.page_content = _filter_noise_paragraphs(doc.page_content)
        return doc


def _try_extract_page(line: str) -> Optional[dict]:
    """尝试从一行文本中提取页码信息"""
    stripped = line.strip()
    for pattern in _page_regexes:
        m = pattern.match(stripped)
        if m:
            groups = m.groups()
            return {
                "page": int(groups[0]),
                "total_pages": int(groups[1]) if groups[1] else None,
            }
    return None


def _try_extract_title(line: str) -> Optional[dict]:
    """尝试从一行文本中提取文档标题信息"""
    stripped = line.strip()
    for pattern in _title_regexes:
        m = pattern.match(stripped)
        if m:
            groups = m.groups()
            if not groups:
                continue
            result: Dict[str, str] = {"document_title": groups[0]}
            if len(groups) > 1:
                result["version"] = groups[1]
                result["classification"] = groups[1]
            return result
    return None


def _is_nav_noise(line: str) -> bool:
    """判断一行是否为导航元素或版权信息（纯噪音）"""
    stripped = line.strip()
    if len(stripped) < 3:
        return True
    for pattern in _nav_regexes:
        if pattern.match(stripped):
            return True
    return False


def _process_page_header_footer(
    lines: List[str],
) -> Tuple[str, dict, dict]:
    """处理页眉页脚行：提取有用信息，过滤纯噪音

    Returns:
        (filtered_text, page_info, title_info)
    """
    page_info: Dict[str, object] = {}
    title_info: Dict[str, str] = {}
    filtered_lines: List[str] = []

    for line in lines:
        stripped = line.strip()

        pg = _try_extract_page(stripped)
        if pg:
            page_info.update(pg)
            filtered_lines.append(f"Page {pg['page']}")
            continue

        tl = _try_extract_title(stripped)
        if tl:
            title_info.update(tl)
            filtered_lines.append(stripped)
            continue

        if _is_nav_noise(stripped):
            continue

        filtered_lines.append(line)

    return "\n".join(filtered_lines), page_info, title_info


def _filter_noise_paragraphs(text: str) -> str:
    """过滤页眉页脚中的噪音，保留有用信息"""
    lines = text.split("\n")
    filtered, _, _ = _process_page_header_footer(lines)
    return filtered
