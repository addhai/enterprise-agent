"""OpenAI GPT-4V 视觉引擎

兼容 OpenAI 格式的视觉理解引擎，支持 GPT-4V、GPT-4o 等模型。
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Optional

from src.rag.vision_engines.base import BaseVisionEngine, VisionResult
from src.rag.vision_engines import VisionEngineRegistry

logger = logging.getLogger(__name__)


@register_vision_engine("openai")
class OpenAIVisionEngine(BaseVisionEngine):
    """OpenAI GPT-4V 视觉理解引擎

    环境变量：
        OPENAI_API_KEY — API Key（必填）
        OPENAI_BASE_URL — API 地址（可选）
        VISION_MODEL — 模型名（可选，默认 gpt-4o）
    """

    @property
    def name(self) -> str:
        return "openai_vision"

    def understand(
        self,
        image_path: str,
        image_type: str,
        prompt: Optional[str] = None,
    ) -> Optional[VisionResult]:
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai package not installed")
            return None

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set")
            return None

        model = os.environ.get("VISION_MODEL", "gpt-4o")
        base_url = os.environ.get("OPENAI_BASE_URL")
        timeout = float(os.environ.get("VISION_TIMEOUT", "10.0"))

        try:
            kwargs: dict = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)

            with open(image_path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")
            mime_type = self._get_mime_type(image_path)
            user_prompt = prompt or self._build_default_prompt(image_type)

            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime_type};base64,{image_b64}",
                            "detail": "high",
                        }},
                    ],
                }],
                max_tokens=2048,
                temperature=0.0,
                timeout=timeout,
            )

            text = response.choices[0].message.content
            return VisionResult(
                content=text,
                confidence=0.93,
                model=model,
                extraction_method="vision_openai",
                metadata={"image_type": image_type},
            )
        except Exception as e:
            logger.warning("OpenAI Vision failed: %s", e)
            return None

    def _build_default_prompt(self, image_type: str) -> str:
        # 复用 Qwen 的默认提示
        from src.rag.vision_engines.qwen_vision_engine import QwenVisionEngine
        return QwenVisionEngine._build_default_prompt(None, image_type)

    def _get_mime_type(self, image_path: str) -> str:
        ext = Path(image_path).suffix.lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        }
        return mime_map.get(ext, "image/png")
