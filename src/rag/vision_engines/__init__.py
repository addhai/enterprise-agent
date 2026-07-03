"""视觉引擎注册表 + 工厂

通过 @register_vision_engine 装饰器注册引擎实现，
ImageLoader 通过名称查找并自动实例化。
"""
from __future__ import annotations

from typing import Dict, Optional, Type

from src.rag.vision_engines.base import BaseOCREngine, BaseVisionEngine


class VisionEngineRegistry:
    """视觉引擎注册表"""

    _vision_engines: Dict[str, Type[BaseVisionEngine]] = {}
    _ocr_engines: Dict[str, Type[BaseOCREngine]] = {}

    @classmethod
    def register_vision(cls, name: str):
        """注册视觉引擎"""
        def decorator(engine_cls: Type[BaseVisionEngine]) -> Type[BaseVisionEngine]:
            cls._vision_engines[name] = engine_cls
            return engine_cls
        return decorator

    @classmethod
    def register_ocr(cls, name: str):
        """注册 OCR 引擎"""
        def decorator(ocr_cls: Type[BaseOCREngine]) -> Type[BaseOCREngine]:
            cls._ocr_engines[name] = ocr_cls
            return ocr_cls
        return decorator

    @classmethod
    def get_vision(cls, name: str) -> Optional[Type[BaseVisionEngine]]:
        """根据名称查找视觉引擎类"""
        return cls._vision_engines.get(name)

    @classmethod
    def get_ocr(cls, name: str) -> Optional[Type[BaseOCREngine]]:
        """根据名称查找 OCR 引擎类"""
        return cls._ocr_engines.get(name)

    @classmethod
    def list_vision(cls) -> list:
        return list(cls._vision_engines.keys())

    @classmethod
    def list_ocr(cls) -> list:
        return list(cls._ocr_engines.keys())
