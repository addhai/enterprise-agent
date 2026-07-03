"""加载器工具函数（编码检测等）

从原 loader.py 中提取的工具函数独立成模块，
避免循环导入。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def detect_encoding(file_path: str) -> str:
    """自动检测文件编码

    优先级：chardet > 内置 open 试探 > 默认 UTF-8
    支持：UTF-8 / UTF-8-BOM / GBK / GB2312 / Latin-1
    """
    # 优先用 chardet
    try:
        import chardet as _chardet
        with open(file_path, "rb") as f:
            raw = f.read(10000)  # 只检测前 10KB
            result = _chardet.detect(raw)
            encoding = result.get("encoding", "utf-8") or "utf-8"
            confidence = result.get("confidence", 0)
            if confidence > 0.7:
                logger.debug("Encoding detected: %s (confidence=%.2f) for %s",
                             encoding, confidence, file_path)
                return encoding
    except ImportError:
        logger.debug("chardet not installed, skipping encoding detection")
    except Exception:
        pass

    # 降级：尝试常见编码
    for enc in ["utf-8-sig", "utf-8", "gbk", "gb2312", "latin-1"]:
        try:
            with open(file_path, "r", encoding=enc) as f:
                f.read(1000)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue

    return "utf-8"
