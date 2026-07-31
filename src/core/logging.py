"""结构化日志工具 —— 让每条日志都带 request_id / tenant_id，便于线上排查。

用法：
    from src.core.logging import get_logger
    log = get_logger(__name__)
    log.warning("tool failed", extra={"request_id": rid, "tenant_id": tid})

注意：本项目已有 `logging.getLogger(__name__)` 的散点用法，这里不替换既有 logger，
只提供带上下文的便捷封装与统一的 `request_id` 注入约定。
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

# 统一字段名，便于 Grafana / Loki 提取
REQUEST_ID_KEY = "request_id"
TENANT_ID_KEY = "tenant_id"


def new_request_id() -> str:
    """生成短的请求 ID（12 位 hex），用于错误关联与用户反馈。"""
    return uuid.uuid4().hex[:12]


def get_logger(name: str) -> logging.Logger:
    """返回带统一命名空间的 logger（与项目现有约定一致）。"""
    return logging.getLogger(name)


class RequestContextFilter(logging.Filter):
    """自动为日志补上 request_id / tenant_id（若调用方通过 extra 传入）。

    这样业务代码只需 `log.warning("msg", extra={"request_id": rid})`，
    缺失时显示 '-'，保证日志格式稳定、可被采集系统解析。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, REQUEST_ID_KEY):
            setattr(record, REQUEST_ID_KEY, "-")
        if not hasattr(record, TENANT_ID_KEY):
            setattr(record, TENANT_ID_KEY, "-")
        return True


def attach_context_filter(logger: Optional[logging.Logger] = None) -> None:
    """给指定 logger（默认 root）挂上上下文 filter，幂等。"""
    target = logger or logging.getLogger()
    if not any(isinstance(f, RequestContextFilter) for f in target.filters):
        target.addFilter(RequestContextFilter())
