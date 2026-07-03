"""PaddleOCR 引擎"""
from __future__ import annotations

import logging
from typing import Optional

from src.rag.vision_engines.base import BaseOCREngine
from src.rag.vision_engines import VisionEngineRegistry

logger = logging.getLogger(__name__)


@register_ocr("paddle")
class PaddleOCREngine(BaseOCREngine):
    """PaddleOCR 文字识别引擎

    中文识别效果好，适合扫描件、截图等场景。
    """

    @property
    def name(self) -> str:
        return "paddle_ocr"

    def recognize(self, image_path: str) -> Optional[str]:
        try:
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(use_angle_cls=True, lang="ch")
            result = ocr.ocr(image_path, cls=True)
            if result and result[0]:
                lines = [line[1][0] for line in result[0]]
                return "\n".join(lines)
        except MemoryError:
            logger.warning("PaddleOCR OOM")
            return None
        except ImportError:
            logger.debug("PaddleOCR not installed")
        except Exception as e:
            logger.warning("PaddleOCR failed: %s", e)
        return None
