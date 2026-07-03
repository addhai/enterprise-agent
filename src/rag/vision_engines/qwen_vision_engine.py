"""阿里百炼 Qwen-VL 视觉引擎

兼容 OpenAI 格式 API，支持百炼 DashScope 和任何 OpenAI 兼容后端。
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Optional

from src.rag.vision_engines.base import BaseVisionEngine, VisionResult
from src.rag.vision_engines import register_vision_engine

logger = logging.getLogger(__name__)


@register_vision_engine("qwen")
class QwenVisionEngine(BaseVisionEngine):
    """阿里百炼 Qwen-VL 视觉理解引擎

    环境变量：
        OPENAI_API_KEY — API Key（必填）
        VISION_MODEL — 模型名（可选，默认 qwen-vl-plus）
        VISION_BASE_URL — API 地址（可选，默认百炼 DashScope）
    """

    @property
    def name(self) -> str:
        return "qwen_vision"

    def understand(
        self,
        image_path: str,
        image_type: str,
        prompt: Optional[str] = None,
    ) -> Optional[VisionResult]:
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai package not installed, cannot use vision API")
            return None

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set, skipping vision API")
            return None

        model = os.environ.get("VISION_MODEL", "qwen-vl-plus")
        base_url = os.environ.get(
            "VISION_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        timeout = float(os.environ.get("VISION_TIMEOUT", "10.0"))

        try:
            client = OpenAI(api_key=api_key, base_url=base_url)

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
                confidence=0.95,
                model=model,
                extraction_method="vision_dashscope",
                metadata={"image_type": image_type},
            )
        except Exception as e:
            logger.warning("Qwen-VL failed: %s", e)
            return None

    def _build_default_prompt(self, image_type: str) -> str:
        base = (
            "你是一个企业客服知识库的文档处理器。请仔细观察这张图片，"
            "并以 Markdown 格式输出以下内容：\n\n"
        )
        prompts = {
            "screenshot": (
                base +
                "1. **界面描述**：这是什么软件/页面的截图？\n"
                "2. **关键元素**：列出所有可见的按钮、输入框、菜单项\n"
                "3. **文字内容**：提取界面上所有可读的文字\n"
                "4. **操作流程**：如果图中显示了操作步骤，请按顺序描述\n"
                "5. **注意事项**：任何警告、提示、错误信息\n\n"
                "用中文回答，保持简洁准确。"
            ),
            "error_screenshot": (
                base +
                "1. **错误类型**：这是什么错误？\n"
                "2. **错误信息**：完整提取错误文字和堆栈跟踪\n"
                "3. **可能原因**：根据错误信息分析可能的根因\n"
                "4. **解决建议**：给出针对性的排查建议\n\n"
                "务必准确提取所有错误信息。"
            ),
            "scanned_document": (
                base +
                "1. **文档类型**：这是什么类型的文档？\n"
                "2. **全文提取**：逐字提取所有文字内容\n"
                "3. **关键信息**：提取日期、金额、编号等关键字段\n"
                "4. **表格还原**：如果有表格，用 Markdown 表格格式还原\n\n"
                "这是扫描件，可能存在模糊或倾斜，请尽力准确识别。"
            ),
            "diagram": (
                base +
                "1. **图表类型**：这是什么图？\n"
                "2. **结构描述**：描述图中的主要组件及其连接关系\n"
                "3. **文字标注**：提取图中所有文字标签\n"
                "4. **流程说明**：如果是流程图，描述完整的流程步骤\n\n"
                "请用清晰的层次结构描述。"
            ),
            "table_image": (
                base +
                "1. **表格描述**：这个表格的主题是什么？\n"
                "2. **表头**：提取所有列名\n"
                "3. **数据内容**：用 Markdown 表格格式还原所有数据行\n"
                "4. **备注说明**：表注、单位、数据来源等\n\n"
                "请务必准确还原表格结构。"
            ),
            "generic": (
                base +
                "1. **内容概述**：这张图片展示了什么？\n"
                "2. **文字提取**：提取所有可读文字\n"
                "3. **结构描述**：描述图片的布局和结构\n"
                "4. **关键信息**：提取有帮助的关键信息\n\n"
                "用中文回答，保持简洁准确。"
            ),
        }
        return prompts.get(image_type, prompts["generic"])

    def _get_mime_type(self, image_path: str) -> str:
        ext = Path(image_path).suffix.lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        }
        return mime_map.get(ext, "image/png")
