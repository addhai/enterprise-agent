"""纯文本（.txt）格式加载器

背景：
    知识库上传接口的扩展名白名单允许 .txt，但加载器注册表里没有 .txt，
    导致 ``DocumentLoader.load_file`` 走 ``No loader registered for extension``
    分支返回空列表，最终表现为「上传成功、入库 0 个切片」的静默失败。

处理流程：
    1. 按探测到的编码读取全文（UTF-8 / GBK / Latin-1 自动识别）
    2. 文本规范化 + 噪声段落过滤（复用与 markdown 相同的清洗管道）
    3. 若正文里存在 Markdown 风格标题，按章节边界拆分；否则整篇作为单个文档
    4. 注入 source_file / doc_format 等元数据，与其它格式保持一致
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.rag.data_sources import FileInfo
from src.rag.loaders.base import BaseLoader, register_loader
from src.rag.outline import OutlineTree, extract_markdown_headings

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


@register_loader(".txt")
class TextLoader(BaseLoader):
    """加载纯文本文件（.txt）

    .txt 与 .md 的差别只在于「不保证有结构」：
    有 Markdown 标题就按章节切，没有就整篇作为一个文档交给下游分块器。
    """

    def load(self, info: FileInfo, base_meta: dict) -> list[_Doc]:
        from langchain_community.document_loaders import TextLoader as LcTextLoader

        from src.rag.loader import _filter_noise_paragraphs, normalize_text

        encoding = base_meta.get("encoding", "utf-8")
        try:
            loader = LcTextLoader(str(info.path), encoding=encoding)
            docs = loader.load()
        except Exception as e:
            # 编码探测偶尔会猜错（例如把 GBK 判成 Latin-1），回退到 utf-8 再试一次，
            # 两次都失败才认为文件不可读。
            logger.warning(
                "TextLoader failed with encoding=%s: %s, retry utf-8", encoding, e
            )
            try:
                loader = LcTextLoader(str(info.path), encoding="utf-8", errors="ignore")
                docs = loader.load()
            except Exception as e2:
                logger.warning("TextLoader retry failed for %s: %s", info.path, e2)
                return []

        if not docs:
            return []

        full_text = "\n\n".join(d.page_content for d in docs)
        full_text = normalize_text(full_text)
        full_text = _filter_noise_paragraphs(full_text)
        if not full_text.strip():
            return []

        source_name = info.name

        # 有 Markdown 标题则按章节拆分，否则整篇一个文档。
        # 纯文本没有结构保证，硬拆只会切碎语义，故此处只做「有结构才用结构」。
        headings = extract_markdown_headings(full_text)
        if headings:
            outline_tree = OutlineTree()
            outline_tree.build(headings)
            from src.config import settings

            store_json = getattr(settings, "outline_store_full_json", False)
            chapters = outline_tree.split(
                full_text,
                base_meta,
                source_file=source_name,
                store_outline_json=store_json,
            )
        else:
            from langchain_core.documents import Document

            chapters = [
                Document(
                    page_content=full_text,
                    metadata={**base_meta, "source_file": source_name},
                )
            ]

        for doc in chapters:
            doc.metadata = {**base_meta, **doc.metadata}

        logger.info("TXT loaded: %s → %d section(s)", source_name, len(chapters))
        return chapters
