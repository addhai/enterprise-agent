"""图片格式加载器（多模态视觉管线：Vision Engine + OCR 降级）

改造后：
    - 视觉理解和 OCR 各自独立为 Engine 实现
    - Engine 通过构造函数注入或配置自动实例化
    - 熔断器抽离为独立类
    - 图片上下文关联预留接口
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from src.rag.data_sources import FileInfo
from src.rag.image_context import ImageContext, infer_image_type
from src.rag.loaders.base import BaseLoader, register_loader
from src.rag.vision_engines.base import (
    BaseOCREngine,
    BaseVisionEngine,
    VisionCircuitBreaker,
    VisionResult,
)

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


@register_loader(".png")
@register_loader(".jpg")
@register_loader(".jpeg")
@register_loader(".gif")
@register_loader(".webp")
@register_loader(".bmp")
class ImageLoader(BaseLoader):
    """加载图片文件并进行多模态理解

    三级降级策略（ABC）：
        A. Vision Engine 多模态理解 → 结构化 Markdown 描述（首选）
        B. 主 OCR Engine → 纯文字提取（降级）
        C. 备用 OCR Engine → 纯文字提取（最终降级）
        D. 两者都失败 → 返回空列表

    高并发保护：
        - 熔断器：Vision Engine 连续失败 N 次后自动切 OCR
        - 大图保护：>1024px 的图片先缩放再识别

    引擎注入方式（优先级：构造函数 > settings 自动实例化）：
        - vision_engine: 传入 BaseVisionEngine 实例，或留空自动创建
        - ocr_engine: 传入 BaseOCREngine 实例，或留空自动创建
        - fallback_ocr: 同上，用于第二 OCR 降级
    """

    def __init__(
        self,
        vision_engine: Optional[BaseVisionEngine] = None,
        ocr_engine: Optional[BaseOCREngine] = None,
        fallback_ocr: Optional[BaseOCREngine] = None,
        circuit_threshold: int = 5,
        circuit_reset_seconds: int = 60,
        ocr_max_image_size: int = 1024,
    ) -> None:
        self.circuit_breaker = VisionCircuitBreaker(
            threshold=circuit_threshold,
            reset_seconds=circuit_reset_seconds,
        )
        self.ocr_max_image_size = ocr_max_image_size

        # 构造函数注入优先，未设置则从 settings 自动实例化
        self.vision_engine = vision_engine or self._auto_create_vision_engine()
        self.ocr_engine = ocr_engine or self._auto_create_primary_ocr()
        self.fallback_ocr = fallback_ocr or self._auto_create_fallback_ocr()

    # ------------------------------------------------------------------
    # BaseLoader 接口
    # ------------------------------------------------------------------

    def load(self, info: FileInfo, base_meta: dict) -> List["_Doc"]:
        """加载图片文件，返回 Document 列表"""
        from langchain_core.documents import Document

        # 确定图片类型
        img_type = infer_image_type(str(info.path))
        meta = {**base_meta, "image_type": img_type}

        # ===== 方案 A: Vision Engine（首选） =====
        vision_result: Optional[VisionResult] = None
        if self.circuit_breaker.attempt_request():
            vision_result = self._call_vision_engine(info.path, img_type)
            if vision_result:
                self.circuit_breaker.record_success()
                meta["confidence"] = vision_result.confidence
                meta["image_type"] = img_type
                meta["extraction_method"] = vision_result.extraction_method
                meta["model"] = vision_result.model
                return [Document(page_content=vision_result.content, metadata=meta)]
            else:
                self.circuit_breaker.record_failure()

        # ===== 方案 B: 主 OCR Engine（降级） =====
        ocr_text = self._ocr_safe(str(info.path))
        if ocr_text and len(ocr_text.strip()) > 10:
            meta["image_type"] = img_type
            if vision_result is None:
                # Vision 失败，OCR 是唯一结果
                meta["warning"] = (
                    "图片理解服务不可用，以下为 OCR 提取的文字碎片，"
                    "可能缺少布局和功能描述。"
                )
                meta["confidence"] = 0.3
            else:
                meta["warning"] = None
                meta["confidence"] = 0.6
                meta["extraction_method"] = "ocr_backup"
                meta["vision_available"] = True

            meta["extraction_method"] = meta.get("extraction_method", self.ocr_engine.name)
            return [Document(page_content=ocr_text, metadata=meta)]

        # ===== 方案 C: 备用 OCR Engine（最终降级） =====
        if self.fallback_ocr:
            fallback_text = self._ocr_safe_with_engine(self.fallback_ocr, str(info.path))
            if fallback_text and len(fallback_text.strip()) > 10:
                meta["image_type"] = img_type
                meta["warning"] = "主 OCR 不可用，已使用备用 OCR 引擎"
                meta["confidence"] = 0.25
                meta["extraction_method"] = self.fallback_ocr.name
                return [Document(page_content=fallback_text, metadata=meta)]

        # ===== 全部失败 =====
        logger.warning(
            "Vision + OCR both failed for %s (img_type=%s)",
            info.path, img_type,
        )
        return []

    # ------------------------------------------------------------------
    # 引擎调用
    # ------------------------------------------------------------------

    def _call_vision_engine(
        self, image_path: str, image_type: str
    ) -> Optional[VisionResult]:
        """调用视觉引擎，带超时保护"""
        try:
            return self.vision_engine.understand(image_path, image_type)
        except Exception as e:
            logger.warning("Vision engine %s failed: %s", self.vision_engine.name, e)
            return None

    def _ocr_safe(self, image_path: str) -> Optional[str]:
        """安全调用主 OCR，带大图保护"""
        return self._ocr_safe_with_engine(self.ocr_engine, image_path)

    def _ocr_safe_with_engine(
        self, engine: BaseOCREngine, image_path: str
    ) -> Optional[str]:
        """安全调用指定 OCR 引擎，带大图保护"""
        resized_path, need_cleanup = self._maybe_resize_image(image_path)
        try:
            return engine.recognize(resized_path)
        finally:
            if need_cleanup:
                try:
                    os.remove(resized_path)
                except Exception:
                    pass

    def _maybe_resize_image(self, image_path: str) -> tuple:
        """大图保护：检查并缩放"""
        try:
            from PIL import Image
        except ImportError:
            return image_path, False

        try:
            img = Image.open(image_path)
            width, height = img.size
            if width > self.ocr_max_image_size or height > self.ocr_max_image_size:
                ratio = self.ocr_max_image_size / max(width, height)
                new_w = int(width * ratio)
                new_h = int(height * ratio)
                img_resized = img.resize((new_w, new_h), Image.LANCZOS)
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    temp_path = f.name
                img_resized.save(temp_path)
                return temp_path, True
        except Exception:
            pass
        return image_path, False

    # ------------------------------------------------------------------
    # 自动实例化工厂（从 settings 读取配置）
    # ------------------------------------------------------------------

    def _auto_create_vision_engine(self) -> Optional[BaseVisionEngine]:
        """从 settings 自动实例化视觉引擎"""
        from src.config import settings

        engine_name = getattr(settings, "vision_engine_name", "qwen")
        engine_cls = None

        # 尝试注册表查找
        from src.rag.vision_engines import VisionEngineRegistry
        engine_cls = VisionEngineRegistry.get_vision(engine_name)

        # 如果注册表中没有，尝试直接导入
        if engine_cls is None:
            if engine_name == "qwen":
                from src.rag.vision_engines.qwen_vision_engine import QwenVisionEngine
                engine_cls = QwenVisionEngine
            elif engine_name == "openai":
                from src.rag.vision_engines.openai_vision_engine import OpenAIVisionEngine
                engine_cls = OpenAIVisionEngine

        if engine_cls:
            return engine_cls()

        logger.warning("Unknown vision engine: %s, returning None", engine_name)
        return None

    def _auto_create_primary_ocr(self) -> Optional[BaseOCREngine]:
        """从 settings 自动实例化主 OCR 引擎"""
        from src.config import settings

        engine_name = getattr(settings, "ocr_engine_name", "paddle")
        engine_cls = None

        from src.rag.vision_engines import VisionEngineRegistry
        engine_cls = VisionEngineRegistry.get_ocr(engine_name)

        if engine_cls is None:
            if engine_name == "paddle":
                from src.rag.vision_engines.paddle_ocr_engine import PaddleOCREngine
                engine_cls = PaddleOCREngine
            elif engine_name == "tesseract":
                from src.rag.vision_engines.tesseract_ocr_engine import TesseractOCREngine
                engine_cls = TesseractOCREngine

        if engine_cls:
            return engine_cls()

        logger.warning("Unknown OCR engine: %s, returning None", engine_name)
        return None

    def _auto_create_fallback_ocr(self) -> Optional[BaseOCREngine]:
        """从 settings 自动实例化备用 OCR 引擎"""
        from src.config import settings

        engine_name = getattr(settings, "fallback_ocr_name", "tesseract")
        # 如果主 OCR 和备用相同，返回 None（不重复）
        from src.config import settings as s2
        primary = getattr(s2, "ocr_engine_name", "paddle")
        if engine_name == primary:
            return None

        engine_cls = None

        from src.rag.vision_engines import VisionEngineRegistry
        engine_cls = VisionEngineRegistry.get_ocr(engine_name)

        if engine_cls is None:
            if engine_name == "tesseract":
                from src.rag.vision_engines.tesseract_ocr_engine import TesseractOCREngine
                engine_cls = TesseractOCREngine
            elif engine_name == "paddle":
                from src.rag.vision_engines.paddle_ocr_engine import PaddleOCREngine
                engine_cls = PaddleOCREngine

        if engine_cls:
            return engine_cls()

        return None
