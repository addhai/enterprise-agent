"""全局限流熔断 + 并发加载

统一管控所有外部 API（视觉引擎、OCR、内容安全等）的限流和熔断，
并提供并发文件加载能力。

组件：
    RateLimiter: 令牌桶限流器
    CircuitBreaker: 熔断器
    ConcurrentLoader: 并发文件加载器
"""
from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from src.config import settings

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 令牌桶限流器
# ---------------------------------------------------------------------------


class RateLimiter:
    """令牌桶限流器

    原理：固定速率产生令牌放入桶中，请求到达时消耗令牌。
    桶满则丢弃新令牌，令牌不足则等待或拒绝。

    Attributes:
        rate: 每秒产生的令牌数（QPS）
        burst: 桶容量（允许的最大突发请求数）
    """

    def __init__(self, rate: float = None, burst: int = None) -> None:
        self.rate = rate or settings.rate_limit_qps
        self.burst = burst or settings.rate_limit_burst
        self._tokens = float(self.burst)  # 初始桶满
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """补充令牌"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * self.rate
        self._tokens = min(self.burst, self._tokens + new_tokens)
        self._last_refill = now

    def acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """获取令牌

        Args:
            tokens: 需要消耗的令牌数
            timeout: 等待超时秒数，None 表示不等待

        Returns:
            True 表示获取成功，False 表示超时或令牌不足
        """
        deadline = time.monotonic() + timeout if timeout else None

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True

            # 令牌不足，等待或放弃
            if deadline and time.monotonic() >= deadline:
                return False

            # 等待下一批令牌产生
            wait_time = (tokens - self._tokens) / self.rate
            time.sleep(min(wait_time, 0.01))

    def __enter__(self) -> "RateLimiter":
        return self

    def __exit__(self, *args) -> None:
        pass

    @property
    def available_tokens(self) -> float:
        """当前可用令牌数"""
        with self._lock:
            self._refill()
            return self._tokens


# ---------------------------------------------------------------------------
# 熔断器
# ---------------------------------------------------------------------------


class CircuitBreakerOpenError(Exception):
    """熔断器打开时抛出的异常"""
    pass


class CircuitBreaker:
    """熔断器（状态机：CLOSED → OPEN → HALF_OPEN → CLOSED）

    连续失败 N 次后打开熔断，等待恢复时间后进入半开状态，
    允许一次探测请求。成功则关闭，失败则重新打开。

    Attributes:
        failure_threshold: 连续失败多少次后熔断
        recovery_timeout: 熔断后等待多少秒恢复（半开状态）
    """

    STATUS_CLOSED = "closed"
    STATUS_OPEN = "open"
    STATUS_HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = None,
        recovery_timeout: int = None,
        name: str = "default",
    ) -> None:
        self.failure_threshold = failure_threshold or settings.circuit_breaker_threshold
        self.recovery_timeout = recovery_timeout or settings.circuit_breaker_recovery
        self.name = name

        self._status = self.STATUS_CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    @property
    def status(self) -> str:
        """当前状态"""
        with self._lock:
            if self._status == self.STATUS_OPEN:
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self.recovery_timeout:
                    self._status = self.STATUS_HALF_OPEN
                    logger.info("CircuitBreaker '%s': OPEN → HALF_OPEN", self.name)
            return self._status

    def is_open(self) -> bool:
        """熔断器是否打开（拒绝请求）"""
        return self.status == self.STATUS_OPEN

    def record_success(self) -> None:
        """记录成功调用"""
        with self._lock:
            self._failure_count = 0
            self._success_count += 1
            if self._status == self.STATUS_HALF_OPEN:
                self._status = self.STATUS_CLOSED
                logger.info(
                    "CircuitBreaker '%s': HALF_OPEN → CLOSED (success)", self.name,
                )

    def record_failure(self) -> None:
        """记录失败调用"""
        with self._lock:
            self._failure_count += 1
            if self._status == self.STATUS_HALF_OPEN:
                self._status = self.STATUS_OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "CircuitBreaker '%s': HALF_OPEN → OPEN (probe failed)", self.name,
                )
            elif self._failure_count >= self.failure_threshold:
                self._status = self.STATUS_OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "CircuitBreaker '%s': CLOSED → OPEN after %d failures",
                    self.name, self.failure_threshold,
                )

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """包装函数调用，自动熔断

        Args:
            func: 要调用的函数
            *args, **kwargs: 传递给函数的参数

        Returns:
            函数返回值

        Raises:
            CircuitBreakerOpenError: 熔断器打开时
        """
        if self.is_open():
            raise CircuitBreakerOpenError(
                f"CircuitBreaker '{self.name}' is OPEN, request rejected"
            )
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except CircuitBreakerOpenError:
            raise
        except Exception as e:
            self.record_failure()
            raise

    def reset(self) -> None:
        """手动重置熔断器"""
        with self._lock:
            self._status = self.STATUS_CLOSED
            self._failure_count = 0
            self._success_count = 0
            logger.info("CircuitBreaker '%s': manual reset", self.name)


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------


class GlobalLimits:
    """全局限流熔断管理器

    为不同外部 API 提供独立的 RateLimiter 和 CircuitBreaker。
    单例模式，全局共享。
    """

    _instance: Optional["GlobalLimits"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "GlobalLimits":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = object.__new__(cls)
                    instance._init()
                    cls._instance = instance
        return cls._instance

    def _init(self) -> None:
        # 视觉 API
        self.vision_limiter = RateLimiter()
        self.vision_breaker = CircuitBreaker(name="vision")
        # OCR API
        self.ocr_limiter = RateLimiter(rate=20.0)  # OCR 通常更快
        self.ocr_breaker = CircuitBreaker(name="ocr")
        # 内容安全 API
        self.safety_limiter = RateLimiter(rate=5.0)
        self.safety_breaker = CircuitBreaker(name="safety")

    def get_limiter(self, name: str) -> RateLimiter:
        """获取指定名称的限流器"""
        mapping = {
            "vision": self.vision_limiter,
            "ocr": self.ocr_limiter,
            "safety": self.safety_limiter,
        }
        return mapping.get(name, self.vision_limiter)

    def get_breaker(self, name: str) -> CircuitBreaker:
        """获取指定名称的熔断器"""
        mapping = {
            "vision": self.vision_breaker,
            "ocr": self.ocr_breaker,
            "safety": self.safety_breaker,
        }
        return mapping.get(name, self.vision_breaker)


# ---------------------------------------------------------------------------
# 并发加载器
# ---------------------------------------------------------------------------


class ConcurrentLoader:
    """并发文件加载器

    使用 ThreadPoolExecutor 并发加载目录下的文件，
    每个文件的加载受全局限流熔断保护。

    Usage::

        loader = DocumentLoader()
        concurrent = ConcurrentLoader(loader, max_workers=4)
        docs = concurrent.load_directory("/path/to/docs")
    """

    def __init__(
        self,
        loader: "DocumentLoader",
        max_workers: int = None,
    ) -> None:
        self.loader = loader
        self.max_workers = max_workers or settings.loader_max_workers
        self.global_limits = GlobalLimits()

    def load_directory(self, dir_path: str) -> List["_Doc"]:
        """并发加载目录下的所有文件"""
        from src.rag.data_sources import LocalDirectoryDataSource
        from src.rag.loader import DocumentLoader as DL

        # 获取文件列表
        source = LocalDirectoryDataSource(dir_path)
        file_infos = source.list_files()

        if not file_infos:
            return []

        logger.info(
            "ConcurrentLoader: loading %d files with %d workers",
            len(file_infos), self.max_workers,
        )

        all_docs: List["_Doc"] = []
        errors: List[str] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_info = {
                executor.submit(self._load_one, info): info
                for info in file_infos
            }

            for future in as_completed(future_to_info):
                info = future_to_info[future]
                try:
                    docs = future.result()
                    all_docs.extend(docs)
                except Exception as e:
                    error_msg = f"{info.path}: {e}"
                    errors.append(error_msg)
                    logger.error("Concurrent load failed: %s", error_msg)

        if errors:
            logger.warning(
                "ConcurrentLoader: %d/%d files failed",
                len(errors), len(file_infos),
            )

        logger.info(
            "ConcurrentLoader: %d files → %d docs (%d errors)",
            len(file_infos), len(all_docs), len(errors),
        )
        return all_docs

    def _load_one(self, info) -> List["_Doc"]:
        """加载单个文件（受限流熔断保护）"""
        # 限流
        limiter = self.global_limits.get_limiter("vision")
        limiter.acquire()

        # 构建基础元数据
        from src.rag.loader import (
            _build_base_meta,
            detect_encoding,
            _get_category,
        )
        encoding = detect_encoding(str(info.path))
        base_meta = _build_base_meta(info, encoding, "")
        base_meta["encoding"] = encoding

        # 查找加载器
        from src.rag.loaders import LoaderRegistry
        loader_cls = LoaderRegistry.get(info.ext)
        if not loader_cls:
            logger.warning("No loader for %s", info.ext)
            return []

        # 加载
        loader = loader_cls()
        docs = loader.load(info, base_meta)

        # 管道处理
        pipeline = self.loader._build_pipeline()
        ctx = pipeline.run(docs, file_info=info)
        return list(ctx)
