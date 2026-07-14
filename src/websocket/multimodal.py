"""多模态消息处理器

职责：
    接收前端传来的 base64 图片/音频，通过视觉引擎或语音引擎处理后，
    将结果转换为文本注入到 Agent 的消息中。

数据流：
    前端 base64 图片 → 保存到临时文件 → Qwen-VL 理解 → 文本注入 Agent
    前端 base64 音频 → 保存到临时文件 → Whisper 转录 → 文本注入 Agent
"""
from __future__ import annotations

import base64
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from src.config import settings

logger = logging.getLogger(__name__)

# 临时文件目录
_TEMP_DIR = Path(tempfile.gettempdir()) / "enterprise_agent_multimodal"
_TEMP_DIR.mkdir(parents=True, exist_ok=True)


def _save_base64_image(base64_data: str, suffix: str = ".png") -> Optional[str]:
    """保存 base64 图片到临时文件，返回文件路径"""
    try:
        # 处理 data:image/png;base64,... 格式
        if "," in base64_data:
            base64_data = base64_data.split(",", 1)[1]

        data = base64.b64decode(base64_data)
        filename = f"image_{int(time.time())}{suffix}"
        filepath = _TEMP_DIR / filename
        filepath.write_bytes(data)
        logger.info("Saved image to %s (%d bytes)", filepath, len(data))
        return str(filepath)
    except Exception as e:
        logger.error("Failed to save image: %s", e)
        return None


def _save_base64_audio(base64_data: str, suffix: str = ".webm") -> Optional[str]:
    """保存 base64 音频到临时文件，返回文件路径"""
    try:
        if "," in base64_data:
            base64_data = base64_data.split(",", 1)[1]

        data = base64.b64decode(base64_data)
        filename = f"audio_{int(time.time())}{suffix}"
        filepath = _TEMP_DIR / filename
        filepath.write_bytes(data)
        logger.info("Saved audio to %s (%d bytes)", filepath, len(data))
        return str(filepath)
    except Exception as e:
        logger.error("Failed to save audio: %s", e)
        return None


def _clean_temp_files(max_age_hours: int = 1):
    """清理超过指定时间的临时文件"""
    try:
        for f in _TEMP_DIR.iterdir():
            if f.is_file() and (time.time() - f.stat().st_mtime) > max_age_hours * 3600:
                f.unlink()
    except Exception:
        pass


def process_image(image_base64: str) -> str:
    """处理图片消息

    1. 保存图片到临时文件
    2. 调用 Qwen-VL 视觉引擎理解图片
    3. 将理解结果拼接到消息中

    Returns:
        包含图片理解结果的文本
    """
    if not image_base64:
        return ""

    # 保存临时文件
    image_path = _save_base64_image(image_base64)
    if not image_path:
        return "[图片上传失败]"

    try:
        # 尝试调用 Qwen-VL 视觉引擎
        from src.rag.vision_engines.qwen_vision_engine import QwenVisionEngine
        engine = QwenVisionEngine()
        result = engine.understand(image_path, "generic")

        if result and result.content:
            logger.info("Vision engine understood image: %s", result.content[:100])
            return {
                "display": f"🖼️ 图片识别结果：{result.content}",
                "agent_input": f"[用户发送了一张图片，AI 识别结果：{result.content}]",
            }
        else:
            logger.warning("Vision engine returned no content")
            return {
                "display": "🖼️ 图片消息",
                "agent_input": "[图片消息]",
            }
    except ImportError:
        logger.warning("Qwen-VL engine not available, skipping image understanding")
        return {
            "display": "🖼️ 图片消息",
            "agent_input": "[图片消息]",
        }
    except Exception as e:
        logger.error("Vision engine failed: %s", e)
        return {
            "display": "🖼️ 图片消息",
            "agent_input": "[图片消息]",
        }
    finally:
        # 清理临时文件
        try:
            Path(image_path).unlink(missing_ok=True)
        except Exception:
            pass


def process_audio(audio_base64: str) -> str:
    """处理语音消息

    1. 保存音频到临时文件
    2. 调用阿里百炼 Whisper 转录（兼容 OpenAI 格式）
    3. 返回转录文本

    Returns:
        语音转录的文本
    """
    if not audio_base64:
        return ""

    # 保存临时文件
    audio_path = _save_base64_audio(audio_base64, suffix=".webm")
    if not audio_path:
        return ""

    try:
        # 尝试调用阿里百炼语音转录（兼容 OpenAI 格式）
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set, cannot transcribe audio")
            return ""

        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        with open(audio_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
                language="zh",
            )

        text = response.text.strip()
        logger.info("Audio transcribed: %s", text[:50])
        return f"[语音消息，转录为：{text}]"
    except ImportError:
        logger.warning("openai package not installed, cannot transcribe audio")
        return ""
    except Exception as e:
        logger.error("Audio transcription failed: %s", e)
        return ""
    finally:
        try:
            Path(audio_path).unlink(missing_ok=True)
        except Exception:
            pass


def process_multimodal_message(
    text: str,
    image_base64: str = "",
    audio_base64: str = "",
) -> tuple[str, str]:
    """处理多模态消息

    将图片/音频转换为文本描述，拼接到原始消息中。

    Args:
        text: 用户输入的文本
        image_base64: base64 编码的图片
        audio_base64: base64 编码的音频

    Returns:
        (display_text, agent_input)
        - display_text: 展示给用户看的（包含图片识别结果）
        - agent_input: 传给 Agent 的完整上下文
    """
    display_parts = []
    agent_parts = []

    if image_base64:
        image_result = process_image(image_base64)
        if isinstance(image_result, dict):
            display_parts.append(image_result.get("display", ""))
            agent_input = image_result.get("agent_input", "")
            if agent_input:
                agent_parts.append(agent_input)
        else:
            display_parts.append(image_result)
            agent_parts.append(image_result)

    if audio_base64:
        audio_desc = process_audio(audio_base64)
        if audio_desc:
            display_parts.append(f"🎤 语音消息：{audio_desc}")
            agent_parts.append(audio_desc)

    if text:
        display_parts.append(text)
        agent_parts.append(text)

    return (
        "\n\n".join(display_parts),
        "\n\n".join(agent_parts),
    )


# 启动时清理过期临时文件
_clean_temp_files()
