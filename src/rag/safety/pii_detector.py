"""敏感信息检测（PII Detection）

检测文本中的个人敏感信息并支持脱敏：
    - 身份证号码
    - 手机号
    - 银行卡号（含 Luhn 校验）
    - API 密钥 / Token
    - 邮箱地址
    - IP 地址

检测结果用于权限升级和内容安全打标。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PiiFinding:
    """单个敏感信息发现"""
    pii_type: str          # id_card, phone, bank_card, api_key, email, ip_address
    matched_text: str      # 原始匹配文本
    start: int             # 在文本中的起始位置
    end: int               # 结束位置
    masked: str            # 脱敏后的文本
    severity: str = "medium"  # low | medium | high | critical


@dataclass
class PiiResult:
    """PII 检测结果"""
    has_pii: bool = False
    findings: List[PiiFinding] = field(default_factory=list)
    types: List[str] = field(default_factory=list)
    count: int = 0
    severity: str = "low"  # 最高严重程度
    masked_text: str = ""  # 脱敏后的完整文本


class PiiDetector:
    """敏感个人信息检测器

    检测规则：
        1. 身份证号码（18位，含校验码验证）
        2. 手机号（中国大陆 11 位）
        3. 银行卡号（16-19 位，Luhn 校验）
        4. API 密钥（多种格式）
        5. 邮箱地址
        6. IP 地址

    脱敏规则：
        - 身份证: 310***********1234
        - 手机号: 138****5678
        - 银行卡: 6222******1234
        - API Key: sk-****...xxxx
        - 邮箱: j***@example.com
        - IP: 192.168.x.x
    """

    def __init__(self, masking: bool = False) -> None:
        self.masking = masking
        self._patterns: List[tuple] = self._build_patterns()

    def _build_patterns(self) -> List[tuple]:
        """构建正则模式列表"""
        return [
            # 身份证号码（18位，最后一位可以是 X）
            (r"\b([1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx])\b",
             "id_card", self._mask_id_card),
            # 手机号（中国大陆 11 位，1开头）
            (r"\b(1[3-9]\d{9})\b", "phone", self._mask_phone),
            # 银行卡号（16-19位数字）
            (r"\b(\d{16,19})\b", "bank_card", self._mask_bank_card),
            # API 密钥（sk-, AKIA-, wX等格式）
            (r"\b(sk-[a-zA-Z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[a-zA-Z0-9]{36})\b",
             "api_key", self._mask_api_key),
            # 通用 API Key / Token（key=xxx / token: xxx）
            (r"(?:api[_-]?key|secret|token)[=:]\s*[\'\"]?([a-zA-Z0-9_-]{16,})[\'\"]?",
             "api_key", self._mask_api_key),
            # 邮箱地址
            (r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b",
             "email", self._mask_email),
            # IPv4 地址
            (r"\b((?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?))\b",
             "ip_address", self._mask_ip),
        ]

    def detect(self, text: str) -> PiiResult:
        """检测文本中的敏感信息

        Args:
            text: 待检测的文本

        Returns:
            PiiResult 包含所有发现
        """
        if not text:
            return PiiResult()

        findings: List[PiiFinding] = []
        seen_ranges: set = set()  # 避免重叠匹配

        for pattern, pii_type, mask_func in self._patterns:
            for match in re.finditer(pattern, text):
                start, end = match.start(), match.end()
                # 跳过重叠
                overlap = False
                for sr, se in seen_ranges:
                    if start < se and end > sr:
                        overlap = True
                        break
                if overlap:
                    continue

                matched_text = match.group(0)
                if pii_type == "bank_card":
                    # 银行卡号需要 Luhn 校验
                    if not self._luhn_check(matched_text):
                        continue
                elif pii_type == "id_card":
                    # 身份证需要校验码验证
                    if not self._validate_id_card(matched_text):
                        continue

                masked = mask_func(matched_text)
                severity = self._severity_for_type(pii_type)
                findings.append(PiiFinding(
                    pii_type=pii_type,
                    matched_text=matched_text,
                    start=start,
                    end=end,
                    masked=masked,
                    severity=severity,
                ))
                seen_ranges.add((start, end))

        if not findings:
            return PiiResult()

        # 按严重程度排序
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        findings.sort(key=lambda f: severity_order.get(f.severity, 0), reverse=True)

        # 生成脱敏文本
        masked_text = text
        for f in reversed(findings):
            if self.masking:
                masked_text = masked_text[:f.start] + f.masked + masked_text[f.end:]

        types = list(set(f.pii_type for f in findings))
        max_severity = findings[0].severity if findings else "low"

        return PiiResult(
            has_pii=True,
            findings=findings,
            types=types,
            count=len(findings),
            severity=max_severity,
            masked_text=masked_text if self.masking else text,
        )

    # ------------------------------------------------------------------
    # 脱敏函数
    # ------------------------------------------------------------------

    @staticmethod
    def _mask_id_card(text: str) -> str:
        if len(text) <= 6:
            return text
        return text[:3] + "*" * (len(text) - 6) + text[-4:]

    @staticmethod
    def _mask_phone(text: str) -> str:
        return text[:3] + "****" + text[-4:]

    @staticmethod
    def _mask_bank_card(text: str) -> str:
        if len(text) <= 8:
            return text
        return text[:4] + "*" * (len(text) - 8) + text[-4:]

    @staticmethod
    def _mask_api_key(text: str) -> str:
        if len(text) <= 8:
            return text
        return text[:4] + "****" + text[-4:]

    @staticmethod
    def _mask_email(text: str) -> str:
        if "@" not in text:
            return text
        local, domain = text.rsplit("@", 1)
        if len(local) <= 2:
            masked_local = local[0] + "***"
        else:
            masked_local = local[0] + "***" + local[-1]
        return f"{masked_local}@{domain}"

    @staticmethod
    def _mask_ip(text: str) -> str:
        parts = text.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.x.x"
        return text

    # ------------------------------------------------------------------
    # 校验函数
    # ------------------------------------------------------------------

    @staticmethod
    def _luhn_check(number: str) -> bool:
        """Luhn 算法校验银行卡号"""
        try:
            digits = [int(d) for d in number]
            total = 0
            reverse_digits = digits[::-1]
            for i, d in enumerate(reverse_digits):
                if i % 2 == 1:
                    d *= 2
                    if d > 9:
                        d -= 9
                total += d
            return total % 10 == 0
        except (ValueError, IndexError):
            return False

    @staticmethod
    def _validate_id_card(text: str) -> bool:
        """身份证号码校验码验证"""
        if len(text) != 18:
            return False
        try:
            weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
            check_codes = "10X98765432"
            total = sum(int(text[i]) * weights[i] for i in range(17))
            return check_codes[total % 11] == text[17].upper()
        except (ValueError, IndexError):
            return False

    @staticmethod
    def _severity_for_type(pii_type: str) -> str:
        """根据 PII 类型返回严重程度"""
        mapping = {
            "id_card": "critical",
            "bank_card": "critical",
            "api_key": "high",
            "phone": "high",
            "email": "medium",
            "ip_address": "low",
        }
        return mapping.get(pii_type, "medium")
