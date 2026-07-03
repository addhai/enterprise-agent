"""Tesseract OCR 引擎"""
from __future__ import annotations

import logging
from typing import Optional

from src.rag.vision_engines.base import BaseOCREngine
from src.rag.vision_engines import VisionEngineRegistry

logger = logging.getLogger(__name__)


@register_ocr("tesseract")
class TesseractOCREngine(BaseOCREngine):
    """Tesseract OCR 文字识别引擎

    英文识别效果好，中文需安装 chi_sim 语言包。
    """

    @property
    def name(self) -> str:
        return "tesseract_ocr"

    def recognize(self, image_path: str) -> Optional[str]:
        try:
            import pytesseract
            text = pytesseract.image_to_string(image_path, lang="chi_sim+eng")
            return text.strip() or None
        except FileNotFoundError:
            logger.debug("Tesseract executable not found")
            return None
        except ImportError:
            logger.debug("pytesseract not installed")
        except Exception as e:
            logger.warning("Tesseract OCR failed: %s", e)
        return None
