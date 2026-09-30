"""结构化 JSON 日志配置

每条日志含：timestamp, level, message, request_id, session_id,
duration_ms, status_code, error。
不输出敏感信息（密钥、token），ERROR 日志只在真正异常时打。

用法：
    from src.utils.logging import setup_logging
    setup_logging()  # 在 main.py startup 中调用

    # 业务节点打日志
    import logging
    logger = logging.getLogger(__name__)
    logger.info("chat_started", extra={"session_id": "xxx", "user_id": "yyy"})
"""

import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """JSON 格式日志格式化器

    输出格式：
        {"timestamp":"2026-09-12T19:00:00","level":"INFO",
         "message":"chat_started","request_id":"abc123",
         "session_id":"xxx","duration_ms":42,"status_code":200}
    """

    # 不输出的字段（敏感信息）
    _REDACT_KEYS = {"token", "password", "secret", "api_key", "authorization"}

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": (
                f"{record.created:.0f}"
                if not hasattr(record, "timestamp")
                else record.timestamp
            ),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # ISO8601 时间戳
        from datetime import datetime

        log_data["timestamp"] = datetime.fromtimestamp(record.created).isoformat()

        # 附加字段（从 extra 传入）
        # 白名单式收集：只放行已知字段，避免把任意 extra 塞进日志造成体量失控
        # 或意外泄露。method / path 由 src/api/metrics.py 的访问日志使用。
        for attr in [
            "request_id",
            "session_id",
            "duration_ms",
            "status_code",
            "user_id",
            "intent",
            "hit_count",
            "model",
            "tokens",
            "method",
            "path",
            # top_k：来自配置中心且可热更，落日志后才能在线上判断
            # 「某次回答差是检索条数被改坏了，还是知识库缺内容」
            "top_k",
        ]:
            val = getattr(record, attr, None)
            if val is not None:
                log_data[attr] = val

        # 异常信息（不含堆栈，只含 type 和 message）
        if record.exc_info and record.exc_info[1]:
            log_data["error"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # 脱敏：不输出密钥类字段
        for key in list(log_data.keys()):
            for redact in self._REDACT_KEYS:
                if redact in key.lower():
                    log_data[key] = "[REDACTED]"

        return json.dumps(log_data, ensure_ascii=False, default=str)


def _build_file_handler(formatter: logging.Formatter) -> logging.Handler | None:
    """按需创建 JSON 日志文件 handler（离线环境的日志可查方案）

    背景：内网/离线部署里没有 Loki（镜像本地缺失且不允许联网拉取），
    日志聚合只能退化为「落文件 + 运维直接查看」。
    落盘目录默认取环境变量 LOG_DIR，缺省 /app/logs —— 该路径在
    deploy/prod 的 compose 里是具名卷（prod-agent-logs），容器重建后日志仍在。

    任何一步失败（目录不存在且创建失败、权限不足）都返回 None 并降级为
    仅标准输出，日志能力缺失不应阻断服务启动。
    """
    log_dir = os.getenv("LOG_DIR", "/app/logs")
    # 显式关闭开关：本地开发默认不落盘，避免在仓库里生成 log 文件
    if os.getenv("LOG_TO_FILE", "1").lower() in ("0", "false", "no", "off"):
        return None

    try:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        # 轮转策略：默认单文件 5MB、保留 2 份历史轮转；可用环境变量覆盖，
        # 便于在离线生产环境不改代码直接调整磁盘占用。
        max_bytes = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
        backup_count = int(os.getenv("LOG_BACKUP_COUNT", "2"))
        handler = RotatingFileHandler(
            path / "app.jsonl",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        return handler
    except Exception:
        return None


def setup_logging(level: str = "INFO"):
    """初始化结构化日志（在 main.py startup 中调用）

    覆盖 uvicorn 默认日志格式，统一为 JSON 输出。
    同时按需把同样的 JSON 行写入 LOG_DIR/app.jsonl，供无 Loki 的离线环境查日志。
    """
    formatter = JSONFormatter()

    # 根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除已有 handler，避免重复输出
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # 文件落盘（尽力而为，失败即降级）
    file_handler = _build_file_handler(formatter)
    if file_handler is not None:
        root_logger.addHandler(file_handler)

    # uvicorn 日志也用同一格式
    for uv_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        uv_logger = logging.getLogger(uv_name)
        uv_logger.handlers.clear()
        uv_handler = logging.StreamHandler(sys.stdout)
        uv_handler.setFormatter(formatter)
        uv_logger.addHandler(uv_handler)
        uv_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        uv_logger.propagate = False

    # 访问日志专用 logger：与业务日志同格式，便于按 logger 名区分
    access_logger = logging.getLogger("src.access")
    access_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if file_handler is not None and file_handler not in access_logger.handlers:
        access_logger.addHandler(file_handler)

    # httpx 日志降级到 WARNING（避免每条请求一条日志）
    logging.getLogger("httpx").setLevel(logging.WARNING)


def generate_request_id() -> str:
    """生成唯一 request_id"""
    return uuid.uuid4().hex[:12]


class RequestTiming:
    """请求计时上下文管理器

    用法：
        with RequestTiming() as t:
            # ... do work ...
        logger.info("request_done", extra={
            "request_id": t.request_id,
            "duration_ms": t.elapsed_ms,
        })
    """

    def __init__(self, request_id: str | None = None):
        self.request_id = request_id or generate_request_id()
        self._start = None
        self.elapsed_ms = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = round((time.perf_counter() - self._start) * 1000, 1)
