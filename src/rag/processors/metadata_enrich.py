"""元数据增强处理器（权限标注 + 业务域分类）"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.rag.processors.base import BaseProcessor, ProcessingContext

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


class MetadataEnrichProcessor(BaseProcessor):
    """元数据增强处理器

    执行：
        1. 根据文档内容关键词标注访问权限（public/internal/confidential/restricted）
        2. 根据关键词分类业务域（product/sales/support/engineering/legal）
    """

    @property
    def name(self) -> str:
        return "metadata_enrich"

    def process(self, doc: "_Doc", ctx: ProcessingContext) -> "_Doc":
        text = doc.page_content
        filename = doc.metadata.get("source", "")

        # 权限标注（尊重已有安全检测的升级结果）
        existing_level = doc.metadata.get("access_level", "")
        new_level = classify_access_level(text, filename)
        # 取更高权限等级
        priority = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
        if priority.get(new_level, 0) > priority.get(existing_level, 0):
            doc.metadata["access_level"] = new_level
        else:
            doc.metadata["access_level"] = existing_level or new_level

        doc.metadata["business_domain"] = classify_business_domain(text, filename)

        return doc


# ---------------------------------------------------------------------------
# 权限标注规则
# ---------------------------------------------------------------------------

_ACCESS_RULES = [
    (["pricing", "价格", "定价", "plan", "套餐"], "public"),
    (["overview", "概述", "介绍", "feature", "功能"], "public"),
    (["faq", "常见问题", "support", "客服"], "internal"),
    (["config", "配置", "setup", "安装", "guide", "指南"], "internal"),
    (["contract", "合同", "financial", "财务", "invoice", "发票", "legal", "法律"],
     "confidential"),
    (["api_key", "密码", "credential", "凭证", "secret", "密钥"],
     "restricted"),
]


def classify_access_level(text: str, filename: str = "") -> str:
    """根据文档内容关键词标注访问权限

    规则：
        - 命中 restricted 关键词 → restricted（最高优先级）
        - 命中 confidential 关键词 → confidential
        - 命中 public/internal 关键词 → 对应等级
        - 默认 → internal（保守策略）
    """
    combined = (text + " " + filename).lower()

    # 先检查最高权限
    for keywords, level in _ACCESS_RULES:
        if level in ("restricted", "confidential"):
            if any(kw in combined for kw in keywords):
                return level

    # 再检查 public/internal
    for keywords, level in _ACCESS_RULES:
        if level in ("public", "internal"):
            if any(kw in combined for kw in keywords):
                return level

    return "internal"


# ---------------------------------------------------------------------------
# 业务域分类规则
# ---------------------------------------------------------------------------

_DOMAIN_RULES = [
    (["pricing", "价格", "plan", "套餐", "feature", "功能", "overview", "概述"],
     "product"),
    (["contract", "合同", "invoice", "发票", "quote", "报价", "sales", "销售"],
     "sales"),
    (["faq", "常见问题", "support", "客服", "troubleshoot", "排查", "guide", "指南"],
     "support"),
    (["api", "sdk", "integration", "集成", "deploy", "部署", "configure", "配置",
      "error", "错误", "debug", "调试", "code", "代码"],
     "engineering"),
    (["legal", "法律", "privacy", "隐私", "compliance", "合规", "term", "条款",
      "gdpr", "数据保护"],
     "legal"),
]

_DOMAIN_PRIORITY = [
    "engineering",
    "legal",
    "sales",
    "support",
    "product",
]


def classify_business_domain(text: str, filename: str = "") -> str:
    """根据文档内容关键词分类业务域

    规则：
        - 命中多个业务域 → 取最高优先级
        - 未命中 → 默认 product
    """
    combined = (text + " " + filename).lower()

    matched = []
    for keywords, domain in _DOMAIN_RULES:
        if any(kw in combined for kw in keywords):
            matched.append(domain)

    for domain in _DOMAIN_PRIORITY:
        if domain in matched:
            return domain

    return "product"
