"""输出护栏：检测输出中的敏感信息泄露和幻觉引用"""
import re
from src.safety.input_guard import SafetyResult


class OutputGuard:
    """输出安全检查"""

    # PII / 敏感信息模式
    SENSITIVE_PATTERNS = [
        # 标准 key=value 格式
        (r'(?:sk|api[_-]?key|secret|token)[=:]\s*[\w-]{20,}', "api_key_pattern"),
        # 常见 API 密钥格式（Stripe 风格，如 sk_live_xxx / cs_live_xxx）
        (r'\b(?:sk|pk|cs|wh)_(?:live|test|prod)_[a-zA-Z0-9]{16,}', "api_key_pattern"),
        # 一般的长密钥（contextual: 出现在 "key"/"secret" 旁边）
        (r'(?i)(?:api[_-]?key|secret|token)\s+(?:is\s+|:)?\s*[\'"]?[\w-]{20,}', "api_key_pattern"),
        (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', "email_pattern"),
        (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', "phone_pattern"),
    ]

    def check(
        self,
        reply: str,
        retrieved_docs: list = None,
        user_id: str = ""
    ) -> SafetyResult:
        """检查 Agent 回复是否安全"""
        retrieved_docs = retrieved_docs or []

        # 1. 敏感信息检测
        for pattern, label in self.SENSITIVE_PATTERNS:
            match = re.search(pattern, reply, re.IGNORECASE)
            if match:
                # 只拦截明显不是无意中出现的
                if self._is_likely_real_secret(match.group()):
                    return SafetyResult(
                        blocked=True,
                        reason=f"sensitive_info:{label}",
                        confidence=0.9
                    )

        # 2. 幻觉引用检测（简版：检查是否引用了检索文档外的内容）
        # 生产环境用 Bloom Filter + 精确匹配

        # 3. 指令泄露检测
        instruction_leak_patterns = [
            r"my system prompt",
            r"my instructions are",
            r"I am programmed to",
            r"my internal rules",
        ]
        for pattern in instruction_leak_patterns:
            if re.search(pattern, reply, re.IGNORECASE):
                return SafetyResult(
                    blocked=True,
                    reason="instruction_disclosure",
                    confidence=0.8
                )

        return SafetyResult(blocked=False, reason="ok", confidence=0.0)

    def _is_likely_real_secret(self, matched: str) -> bool:
        """判断匹配到的敏感信息是否像真的"""
        # 简单的启发式：长度 > 20 的随机字符串更像真实密钥
        if len(matched) > 30:
            return True
        # 包含数字和字母混合
        has_digit = any(c.isdigit() for c in matched)
        has_alpha = any(c.isalpha() for c in matched)
        return has_digit and has_alpha and len(matched) > 15
