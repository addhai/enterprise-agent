"""内容合规校验

两级检测：
    1. 本地正则：快速检测敏感词、违规内容（零依赖）
    2. 云端 API：对接阿里云内容安全（可选）

检测结果用于文档拦截和权限升级。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ComplianceResult:
    """合规检测结果"""
    safe: bool = True              # 是否安全（未被拦截）
    blocked: bool = False          # 是否被拦截
    reason: str = ""               # 拦截原因
    risk_level: str = "low"        # 风险等级
    categories: Dict[str, bool] = field(default_factory=dict)
    local_score: float = 0.0       # 本地检测得分（0-1）
    cloud_score: Optional[float] = None  # 云端检测得分（如有）


class ContentComplianceChecker:
    """内容合规校验器

    本地检测规则：
        - 涉政敏感词
        - 涉黄内容
        - 涉暴恐怖
        - 广告垃圾
        - 违禁品

    云端检测（可选）：
        - 对接阿里云内容安全 API
        - 结果与本地检测合并
    """

    def __init__(self) -> None:
        self.local_enabled = settings.safety_compliance_local_enabled
        self.cloud_enabled = settings.safety_compliance_cloud_enabled
        self.api_key = settings.safety_compliance_api_key
        self.auto_block = settings.safety_compliance_auto_block

        self._local_patterns = self._build_local_patterns()

    def check(self, text: str) -> ComplianceResult:
        """检查文本合规性

        Args:
            text: 待检测文本

        Returns:
            ComplianceResult
        """
        if not text:
            return ComplianceResult(safe=True)

        result = ComplianceResult()

        # 1. 本地检测
        if self.local_enabled:
            local_result = self._local_check(text)
            result.categories.update(local_result.categories)
            result.local_score = local_result.local_score
            result.blocked = result.blocked or local_result.blocked
            result.reason = local_result.reason if local_result.blocked else result.reason
            if local_result.risk_level not in ("low",):
                result.risk_level = local_result.risk_level

        # 2. 云端检测（可选）
        if self.cloud_enabled and self.api_key:
            cloud_result = self._cloud_check(text)
            if cloud_result:
                result.cloud_score = cloud_result.score
                result.categories.update(cloud_result.categories)
                if cloud_result.blocked:
                    result.blocked = True
                    result.reason = cloud_result.reason
                    result.risk_level = "high"

        # 综合判定
        if result.blocked and not self.auto_block:
            result.blocked = False  # 仅标记不拦截

        result.safe = not result.blocked
        return result

    def _local_check(self, text: str) -> ComplianceResult:
        """本地正则检测"""
        result = ComplianceResult()
        score = 0.0

        for category, patterns in self._local_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    result.categories[category] = True
                    score += 0.3
                    result.blocked = True
                    result.reason = f"local:{category}"
                    break

        result.local_score = min(score, 1.0)
        if result.local_score >= 0.6:
            result.risk_level = "high"
        elif result.local_score >= 0.3:
            result.risk_level = "medium"
        else:
            result.risk_level = "low"

        return result

    def _build_local_patterns(self) -> Dict[str, List[str]]:
        """构建本地检测正则模式"""
        return {
            # 涉政敏感词（示例，实际应配置化）
            "politics": [
                r"(?:国家领导人|敏感政治事件|反动)",
            ],
            # 涉黄
            "pornography": [
                r"(?:色情|淫秽|裸照|AV)",
            ],
            # 涉暴
            "violence": [
                r"(?:爆炸物制作|自制武器|恐怖活动)",
            ],
            # 广告垃圾
            "spam": [
                r"(?:加QQ群|加微信|点击链接|免费领取)",
            ],
            # 违禁品
            "contraband": [
                r"(?:毒品|枪支|管制刀具)",
            ],
        }

    def _cloud_check(self, text: str) -> Optional[ComplianceResult]:
        """云端内容安全检测（阿里云）"""
        # TODO: 对接阿里云内容安全 API
        logger.debug("Cloud compliance check not yet implemented")
        return None


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def check_compliance(text: str) -> ComplianceResult:
    """便捷函数：检查文本合规性"""
    checker = ContentComplianceChecker()
    return checker.check(text)
