"""统一异常层次 —— 让错误"类型化、可观测、对外安全"。

设计原则（资深开发把关）：
    1. 所有业务异常继承自 `EnterpriseAgentError`，禁止在业务层抛裸 `Exception`。
    2. 对外暴露的异常带 `safe_message` —— 给用户/前端的只能是它，绝不带 traceback。
    3. 内部细节（堆栈、参数、第三方报错）只进日志，通过 `request_id` 关联排查。
    4. `SafeError` 用于"已知的可恢复业务错误"（如权限不足、参数非法），
       与"未知系统错误"区分，便于监控与告警分级。
"""

from __future__ import annotations

import uuid
from typing import Optional


class EnterpriseAgentError(Exception):
    """所有业务异常的基类。

    Attributes:
        safe_message: 可对用户/前端暴露的安全文案（不含实现细节）。
        request_id:   本次请求唯一 ID，用于日志关联与用户反馈。
        status_code:  建议的 HTTP 状态码（API 层可直接取用）。
    """

    status_code: int = 500

    def __init__(
        self,
        safe_message: str,
        *,
        request_id: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.safe_message = safe_message
        self.request_id = request_id or uuid.uuid4().hex[:12]
        super().__init__(safe_message)
        # 保留根因，便于 `raise ... from cause` 与日志 `exc_info`
        self.__cause__ = cause

    def __str__(self) -> str:  # pragma: no cover - 调试用
        return f"[{self.request_id}] {self.safe_message}"


class SafeError(EnterpriseAgentError):
    """已知的、可恢复的业务错误（如参数非法、权限不足）。

    这类错误不应触发"系统级"告警，只需正常返回给用户。
    """

    status_code = 400


class ToolError(EnterpriseAgentError):
    """工具调用失败。"""

    status_code = 502


class ToolCallTimeout(ToolError):
    """工具调用超时 —— 属于可重试错误。"""

    status_code = 504


class AgentRuntimeError(EnterpriseAgentError):
    """Agent 推理过程中的未知系统错误。"""

    status_code = 500


class PermissionDeniedError(SafeError):
    """权限不足。"""

    status_code = 403


class InvalidArgumentError(SafeError):
    """参数校验失败。"""

    status_code = 422


def safe_message(exc: BaseException, fallback: str = "服务暂时不可用，请稍后重试") -> str:
    """从异常中提取"对外安全消息"。

    - 若是 `EnterpriseAgentError`，返回其 `safe_message`。
    - 否则（未知异常）返回 `fallback`，绝不泄露内部细节。
    """
    if isinstance(exc, EnterpriseAgentError):
        return exc.safe_message
    return fallback
