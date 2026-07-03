"""VisionEngineRegistry 注册表

独立模块，避免循环导入。
"""
from __future__ import annotations

from typing import Dict, Optional, Type


class VisionEngineRegistry:
    """引擎注册表"""

    _vision_engines: Dict[str, Type] = {}
    _ocr_engines: Dict[str, Type] = {}

    @classmethod
    def register_vision(cls, name: str):
        def decorator(engine_cls):
            cls._vision_engines[name] = engine_cls
            return engine_cls
        return decorator

    @classmethod
    def register_ocr(cls, name: str):
        def decorator(ocr_cls):
            cls._ocr_engines[name] = ocr_cls
            return ocr_cls
        return decorator

    @classmethod
    def get_vision(cls, name: str):
        return cls._vision_engines.get(name)

    @classmethod
    def get_ocr(cls, name: str):
        return cls._ocr_engines.get(name)

    @classmethod
    def list_vision(cls):
        return list(cls._vision_engines.keys())

    @classmethod
    def list_ocr(cls):
        return list(cls._ocr_engines.keys())
