"""多模态视觉引擎抽象基类

定义统一的视觉理解和 OCR 接口，具体实现（Qwen-VL、OpenAI GPT-4V、
PaddleOCR、Tesseract）各自独立实现，可灵活切换。

数据流：
    图片 → VisionEngine.understand() → VisionResult
         → OCREngine.recognize() → str
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VisionResult — 视觉引擎返回结果
# ---------------------------------------------------------------------------


@dataclass
class VisionResult:
    """视觉理解引擎的返回结果"""

    content: str               # 模型生成的描述文本
    confidence: float          # 置信度 (0.0 ~ 1.0)
    model: str                 # 使用的模型名
    extraction_method: str     # 提取方式标识
    metadata: Dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 熔断器
# ---------------------------------------------------------------------------


class VisionCircuitBreaker:
    """视觉引擎熔断器

    高并发保护：连续失败 N 次后自动熔断（不再调用 vision engine），
    等待指定时间后自动恢复（半开状态，允许一次重试）。

    Attributes:
        threshold: 连续失败多少次后熔断（默认 5）
        reset_seconds: 熔断后等待多少秒恢复（默认 60）
    """

    def __init__(
        self,
        threshold: int = 5,
        reset_seconds: int = 60,
    ) -> None:
        self._fail_count = 0
        self._threshold = threshold
        self._reset_seconds = reset_seconds
        self._opened_at = 0.0
        self._opened = False

    def record_success(self) -> None:
        """记录一次成功调用，重置失败计数"""
        self._fail_count = 0
        self._opened = False

    def record_failure(self) -> None:
        """记录一次失败调用，达到阈值后熔断"""
        self._fail_count += 1
        if self._fail_count >= self._threshold:
            self._opened = True
            self._opened_at = time.time()
            logger.warning(
                "Vision circuit breaker OPENED after %d consecutive failures. "
                "Switching to OCR for %d seconds.",
                self._threshold, self._reset_seconds,
            )

    def is_open(self) -> bool:
        """熔断器是否打开（拒绝请求）"""
        if not self._opened:
            return False

        elapsed = time.time() - self._opened_at
        if elapsed >= self._reset_seconds:
            # 熔断时间到，关闭熔断器（半开状态）
            self._opened = False
            self._fail_count = 0
            logger.info("Vision circuit breaker CLOSED (recovered)")
            return False

        return True

    def attempt_request(self) -> bool:
        """尝试发起请求（半开状态探测）

        Returns:
            True 表示允许请求，False 表示拒绝
        """
        if self.is_open():
            return False
        return True


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------


class BaseVisionEngine(ABC):
    """视觉理解引擎抽象基类

    所有视觉理解引擎（Qwen-VL、GPT-4V 等）必须实现此接口。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎名称（用于日志和注册）"""
        ...

    @abstractmethod
    def understand(
        self,
        image_path: str,
        image_type: str,
        prompt: Optional[str] = None,
    ) -> Optional[VisionResult]:
        """理解图片内容

        Args:
            image_path: 图片文件路径
            image_type: 图片类型（screenshot/error_screenshot/diagram 等）
            prompt: 自定义理解提示（可选，使用引擎默认提示）

        Returns:
            VisionResult 或 None（失败）
        """
        ...


class BaseOCREngine(ABC):
    """OCR 引擎抽象基类

    所有 OCR 引擎（PaddleOCR、Tesseract 等）必须实现此接口。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎名称"""
        ...

    @abstractmethod
    def recognize(self, image_path: str) -> Optional[str]:
        """识别图片中的文字

        Args:
            image_path: 图片文件路径

        Returns:
            提取的文字内容，或 None（失败）
        """
        ...
