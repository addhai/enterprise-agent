"""多模态视觉引擎插件包

通过 @register_vision_engine 和 @register_ocr 装饰器注册引擎实现。
所有引擎实现导入此包时自动注册。
"""
from src.rag.vision_engines.base import (
    BaseOCREngine,
    BaseVisionEngine,
    VisionCircuitBreaker,
    VisionResult,
)
from src.rag.vision_engines.registry import VisionEngineRegistry


def register_vision_engine(name: str):
    """装饰器：注册视觉引擎"""
    return VisionEngineRegistry.register_vision(name)


def register_ocr(name: str):
    """装饰器：注册 OCR 引擎"""
    return VisionEngineRegistry.register_ocr(name)


__all__ = [
    "BaseVisionEngine",
    "BaseOCREngine",
    "VisionResult",
    "VisionCircuitBreaker",
    "VisionEngineRegistry",
    "register_vision_engine",
    "register_ocr",
]
