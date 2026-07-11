"""质量检查处理器（字数、有效期、过期关键词检测）"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List

from src.rag.processors.base import BaseProcessor, ProcessingContext

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


class QualityCheckProcessor(BaseProcessor):
    """质量拦截处理器

    执行：
        1. 字数检查：< 50 字 → 丢弃
        2. 内容有效性检查（纯空白/噪声 → 丢弃）
        3. 过期检查（版本号 < 当前版本 → 丢弃）
        4. 过期关键词检测（deprecated/废弃 → 丢弃）
        5. 修改时间检查（> 180 天 → 标记警告）
    """

    def __init__(
        self,
        max_days_outdated: int = 180,
        current_version: int = 302,
    ) -> None:
        self.max_days_outdated = max_days_outdated
        self.current_version = current_version

    @property
    def name(self) -> str:
        return "quality_check"

    def process(self, doc: "_Doc", ctx: ProcessingContext) -> "_Doc | None":
        text = doc.page_content
        filename = doc.metadata.get("source", "")
        modified_time = doc.metadata.get("modified_time", "")
        version = doc.metadata.get("version", "")

        quality = assess_document_quality(
            text, filename, modified_time, version,
            current_version=self.current_version,
            max_days_outdated=self.max_days_outdated,
        )

        doc.metadata["quality_status"] = quality["status"]
        doc.metadata["quality_word_count"] = quality["word_count"]

        if quality["status"] == "reject_low_quality":
            ctx.inc("rejected_quality")
            logger.info("REJECTED (low quality): %s — %s", filename, quality["reason"])
            return None

        if quality["status"] == "reject_expired":
            ctx.inc("rejected_expired")
            logger.info("REJECTED (expired): %s — %s", filename, quality["reason"])
            return None

        if quality["status"] == "warn_outdated":
            ctx.inc("warn_outdated")
            doc.metadata["outdated_warning"] = quality["reason"]
            logger.info("WARN (outdated): %s — %s", filename, quality["reason"])

        ctx.inc("accepted")
        return doc


def assess_document_quality(
    text: str,
    filename: str,
    modified_time: str = "",
    version: str = "",
    current_version: int = 302,
    max_days_outdated: int = 180,
) -> dict:
    """评估文档质量，拦截低质量和过期文档

    Returns:
        {
            "status": "accept" | "reject_low_quality" | "reject_expired" | "warn_outdated",
            "reason": str,
            "word_count": int,
            "has_content": bool,
            "is_expired": bool,
            "is_outdated": bool,
            "keywords_matched": list,
        }
    """
    result: Dict[str, object] = {
        "status": "accept",
        "reason": "",
        "word_count": len(text.strip()),
        "has_content": False,
        "is_expired": False,
        "is_outdated": False,
        "keywords_matched": [],
    }

    # 1. 字数检查
    wc = result["word_count"]
    if wc < 50:
        result["status"] = "reject_low_quality"
        result["reason"] = f"文档内容过短（{wc} 字），可能是页眉/页脚/导航文本"
        return result

    # 2. 内容有效性检查
    non_whitespace = len(text.strip())
    if non_whitespace < wc * 0.5:
        result["status"] = "reject_low_quality"
        result["reason"] = "文档内容以空白/噪声为主，无实质信息"
        return result

    # 3. 过期检查
    # 3a. 版本号检查
    if version:
        version_match = re.search(r"v(\d+)\.(\d+)", version)
        if version_match:
            ver_num = int(version_match.group(1)) * 100 + int(version_match.group(2))
            if ver_num < current_version:
                result["is_expired"] = True
                result["status"] = "reject_expired"
                result["reason"] = (
                    f"文档版本 v{version_match.group(0)} 低于当前版本 "
                    f"v{current_version//100}.{current_version%100}"
                )

    # 3b. 关键词检测过期信号
    expired_keywords = ["deprecated", "废弃", "obsolete", "淘汰", "legacy", "旧版"]
    combined = text.lower() + " " + filename.lower()

    for kw in expired_keywords:
        pattern = rf"v\d+\.?\d*\s+{re.escape(kw)}|{re.escape(kw)}\s+v\d+\.?\d*"
        if re.search(pattern, combined, re.IGNORECASE):
            result["keywords_matched"].append(kw)
            result["is_expired"] = True
            if result["status"] == "accept":
                result["status"] = "reject_expired"
                result["reason"] = f"文档标记为已废弃：{', '.join(result['keywords_matched'])}"

    for kw in expired_keywords:
        if kw in filename.lower():
            result["keywords_matched"].append(kw)
            result["is_expired"] = True
            if result["status"] == "accept":
                result["status"] = "reject_expired"
                result["reason"] = f"文件名包含废弃标记：{', '.join(result['keywords_matched'])}"

    # 4. 修改时间检查
    if modified_time:
        try:
            mod_dt = datetime.fromisoformat(
                modified_time.replace("Z", "+00:00").split("+")[0]
            )
            days_ago = (datetime.now() - mod_dt.replace(tzinfo=None)).days
            if days_ago > max_days_outdated:
                result["is_outdated"] = True
                if result["status"] == "accept":
                    result["status"] = "warn_outdated"
                    result["reason"] = f"文档最后修改于 {days_ago} 天前，可能已过期"
        except Exception:
            pass

    result["has_content"] = True
    return result
