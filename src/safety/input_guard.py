"""输入护栏：检测 Prompt 注入和恶意输入"""
import re
from dataclasses import dataclass


@dataclass
class SafetyResult:
    blocked: bool
    reason: str = ""
    confidence: float = 0.0


class InputGuard:
    """输入安全检查"""

    # 高风险注入模式（正则）
    INJECTION_PATTERNS = [
        # 指令覆盖
        (r"(?i)(ignore|forget|disregard|override).{0,30}(instruction|prompt|rule|setting|role|directive)", 0.9),
        # 角色扮演
        (r"(?i)(you are now|act as|pretend to be|you are DAN|jailbreak)", 0.9),
        # 系统消息伪造
        (r"(?i)(system:\s*|<<SYS>>|\[system\]|<\|system\|>)", 0.95),
        # 要求列出指令
        (r"(?i)(list (all |your )?(instructions|rules|tools|capabilities))", 0.7),
        # 要求输出 Prompt
        (r"(?i)(tell me (about |)your (prompt|system prompt|instructions))", 0.8),
    ]

    def check(self, message: str) -> SafetyResult:
        """检查用户输入是否安全"""
        # 长度检查
        if len(message) > 10000:
            return SafetyResult(blocked=True, reason="message_too_long", confidence=1.0)

        # 注入模式检查
        for pattern, confidence in self.INJECTION_PATTERNS:
            if re.search(pattern, message):
                return SafetyResult(
                    blocked=True,
                    reason=f"injection_pattern_match:{pattern[:50]}",
                    confidence=confidence
                )

        # 空消息
        if not message.strip():
            return SafetyResult(blocked=True, reason="empty_message", confidence=1.0)

        return SafetyResult(blocked=False, reason="ok", confidence=0.0)
