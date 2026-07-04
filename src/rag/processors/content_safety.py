"""内容安全检测处理器

在管道中执行：
    1. PII 检测 → 打标 / 脱敏
    2. 合规校验 → 拦截违规内容
    3. 权限升级 → 发现敏感信息自动提升保密等级
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from src.rag.processors.base import BaseProcessor, ProcessingContext
from src.rag.safety.pii_detector import PiiDetector, PiiResult
from src.rag.safety.content_compliance import ContentComplianceChecker, ComplianceResult

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


class ContentSafetyProcessor(BaseProcessor):
    """内容安全检测处理器

    执行步骤：
        1. PII 检测：识别身份证、手机号、银行卡、API 密钥等
        2. 合规校验：本地正则检测违规内容
        3. 权限升级：发现敏感信息自动提升保密等级
        4. 脱敏（可选）：对敏感信息打掩码
    """

    def __init__(self, masking: bool = None) -> None:
        from src.config import settings
        self.masking = masking if masking is not None else settings.safety_pii_masking_enabled
        self.pii_detector = PiiDetector(masking=self.masking)
        self.compliance_checker = ContentComplianceChecker()

    @property
    def name(self) -> str:
        return "content_safety"

    def process(self, doc: "_Doc", ctx: ProcessingContext) -> Optional["_Doc"]:
        text = doc.page_content
        filename = doc.metadata.get("source", "")

        # 1. PII 检测
        pii_result = self.pii_detector.detect(text)
        if pii_result.has_pii:
            doc.metadata["pii_detected"] = True
            doc.metadata["pii_types"] = pii_result.types
            doc.metadata["pii_count"] = pii_result.count
            doc.metadata["pii_severity"] = pii_result.severity
            logger.info(
                "PII detected in %s: %d items (%s)",
                filename, pii_result.count, pii_result.types,
            )

            # 脱敏
            if self.masking and pii_result.masked_text:
                doc.page_content = pii_result.masked_text

        # 2. 合规校验
        compliance = self.compliance_checker.check(text)
        if compliance.blocked:
            doc.metadata["compliance_blocked"] = True
            doc.metadata["compliance_reason"] = compliance.reason
            doc.metadata["compliance_risk"] = compliance.risk_level
            logger.warning(
                "Content blocked in %s: %s (%s)",
                filename, compliance.reason, compliance.risk_level,
            )

        # 3. 权限升级
        access_level = self._upgrade_access_level(
            doc.metadata.get("access_level", "internal"),
            pii_result,
            compliance,
        )
        doc.metadata["access_level"] = access_level

        return doc

    def _upgrade_access_level(
        self,
        current_level: str,
        pii_result: PiiResult,
        compliance: ComplianceResult,
    ) -> str:
        """升级权限等级

        规则：
            - PII 检测到 critical 级别 → restricted
            - PII 检测到 high 级别 → confidential
            - 合规检测被拦截 → restricted
            - 取最高等级
        """
        priority = {
            "public": 0,
            "internal": 1,
            "confidential": 2,
            "restricted": 3,
        }

        new_level = current_level
        current_priority = priority.get(new_level, 1)

        # PII 升级
        if pii_result.has_pii:
            severity_priority = {
                "critical": 3,
                "high": 2,
                "medium": 1,
                "low": 0,
            }
            pii_priority = severity_priority.get(pii_result.severity, 0)
            if pii_priority > current_priority:
                for level, prio in priority.items():
                    if prio == pii_priority:
                        new_level = level
                        break

        # 合规升级
        if compliance.blocked:
            risk_priority = {"high": 3, "medium": 2, "low": 1}
            risk_prio = risk_priority.get(compliance.risk_level, 0)
            if risk_prio > current_priority:
                for level, prio in priority.items():
                    if prio == risk_prio:
                        new_level = level
                        break

        if new_level != current_level:
            logger.info(
                "Access level upgraded: %s → %s (pii=%s, compliance=%s)",
                current_level, new_level, pii_result.severity, compliance.risk_level,
            )

        return new_level
