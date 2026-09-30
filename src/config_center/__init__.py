"""配置中心包

对外暴露：
    get_config_center()  —— 进程内单例，供 API 层与消费方订阅使用
    ConfigCenter         —— 类型
    ConfigError 及其子类 —— 校验 / 只读 / 未找到，接口层据此翻译成 400 / 404
"""

from src.config_center.service import (  # noqa: F401
    ConfigCenter,
    ConfigError,
    ConfigNotFoundError,
    ConfigReadOnlyError,
    ConfigValidationError,
    get_config_center,
)

__all__ = [
    "ConfigCenter",
    "ConfigError",
    "ConfigNotFoundError",
    "ConfigReadOnlyError",
    "ConfigValidationError",
    "get_config_center",
]
