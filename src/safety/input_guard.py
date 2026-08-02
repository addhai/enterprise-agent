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
        # 指令覆盖（英文）
        (r"(?i)(ignore|forget|disregard|override).{0,30}(instruction|prompt|rule|setting|role|directive)", 0.9),
        # 角色扮演（英文）
        (r"(?i)(you are now|act as|pretend to be|you are DAN|jailbreak)", 0.9),
        # 系统消息伪造（英文）
        (r"(?i)(system:\s*|<<SYS>>|\[system\]|<\|system\|>)", 0.95),
        # 要求列出指令（英文）
        (r"(?i)(list (all |your )?(instructions|rules|tools|capabilities))", 0.7),
        # 要求输出 Prompt（英文）
        (r"(?i)(tell me (about |)your (prompt|system prompt|instructions))", 0.8),
        # ===== 中文越狱模式（对齐中文客服场景）=====
        # 指令覆盖（中文）
        (r"(忽略|无视|不要遵守|跳过|覆盖).{0,10}(指令|规则|设定|限制|约束|提示词)", 0.9),
        (r"忘记.{0,5}(你的|之前的).{0,5}(指令|规则|身份|设定)", 0.9),
        # 角色扮演（中文）
        (r"你现在?是(DAN|越狱模式|开发者模式|管理员模式|无限制模式)", 0.9),
        (r"假装你是(管理员|开发者|无限制AI|越狱AI)", 0.9),
        (r"扮演.{0,10}(管理员|开发者|黑客|无限制)", 0.85),
        # 系统消息伪造（中文）
        (r"(系统提示|系统消息|管理员指令)[:：].{0,20}(切换|进入|开启|执行)", 0.9),
        (r"\[系统\]|\[管理员\]|【系统】|【管理员】", 0.85),
        # 要求泄露系统提示词（中文）
        (r"(显示|告诉我|输出|打印|复述).{0,5}(你的|系统).{0,5}(提示词|系统提示|指令|规则|prompt)", 0.85),
        (r"你的(系统提示|prompt|指令|规则)是什么", 0.8),
        # 要求执行危险操作（中文）
        (r"(绕过|突破|解除).{0,5}(安全|限制|防护|护栏|审查)", 0.9),
        (r"(关闭|禁用|取消).{0,5}(安全|限制|防护|护栏|审查|过滤)", 0.85),
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
