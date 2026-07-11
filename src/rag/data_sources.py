"""数据源抽象层

将"从哪里读取文件"与"如何解析文件"解耦。
后续可扩展 OSS、飞书文档、企业微信、Confluence 等数据源。

数据流：
    原始文件 → 数据源提供 FileInfo → 加载器读取 → 解析为 Document
"""
from __future__ import annotations

import logging
import mimetypes
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 文件信息
# ---------------------------------------------------------------------------


@dataclass
class FileInfo:
    """文件元信息，数据源产出的统一中间表示"""

    path: Path
    name: str
    ext: str
    size: int
    mime_type: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.mime_type:
            self.mime_type = mimetypes.guess_type(str(self.path))[0] or "application/octet-stream"
        # 补充时间元数据
        if not self.metadata.get("created_time"):
            self.metadata["created_time"] = datetime.fromtimestamp(
                self.path.stat().st_ctime
            ).isoformat()
        if not self.metadata.get("modified_time"):
            self.metadata["modified_time"] = datetime.fromtimestamp(
                self.path.stat().st_mtime
            ).isoformat()


# ---------------------------------------------------------------------------
# 数据源抽象
# ---------------------------------------------------------------------------


class BaseDataSource:
    """数据源抽象基类

    约定两个核心方法：
        list_files()  → 列出所有可加载的文件
        read_file()   → 读取指定文件的原始字节
    """

    def list_files(self) -> List[FileInfo]:
        """列出数据源中所有可加载的文件"""
        raise NotImplementedError

    def read_file(self, info: FileInfo) -> Union[bytes, str]:
        """读取文件的原始内容"""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 本地目录数据源
# ---------------------------------------------------------------------------


class LocalDirectoryDataSource(BaseDataSource):
    """本地目录数据源

    将现有的 glob 扫描逻辑封装为数据源实现。
    支持递归扫描子目录。
    """

    # 支持的扩展名集合
    SUPPORTED_EXTS = {
        ".md", ".pdf", ".html", ".htm", ".docx",
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    }

    def __init__(self, root_path: str, recursive: bool = True) -> None:
        self.root_path = Path(root_path).resolve()
        self.recursive = recursive

    def list_files(self) -> List[FileInfo]:
        """扫描目录下所有支持的文件"""
        if not self.root_path.is_dir():
            logger.warning("Data source path does not exist: %s", self.root_path)
            return []

        pattern = "**/*" if self.recursive else "*"
        files: List[FileInfo] = []

        for ext in sorted(self.SUPPORTED_EXTS):
            for path in self.root_path.glob(pattern):
                if path.suffix.lower() == ext and path.is_file():
                    stat = path.stat()
                    files.append(FileInfo(
                        path=path,
                        name=path.name,
                        ext=path.suffix.lower(),
                        size=stat.st_size,
                    ))

        logger.info("LocalDirectoryDataSource: found %d files in %s", len(files), self.root_path)
        return files

    def read_file(self, info: FileInfo) -> bytes:
        """读取文件原始字节"""
        with open(info.path, "rb") as f:
            return f.read()
