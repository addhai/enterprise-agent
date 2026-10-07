"""TextLoader 单元测试

阶段 2 开门周补齐：CI 口径 text_loader.py 行覆盖率仅 22%。
全部使用 tmp_path 现场写文件，确定性、无外部依赖。
"""

from src.rag.data_sources import FileInfo
from src.rag.loaders.text_loader import TextLoader


def _info(path) -> FileInfo:
    return FileInfo(path=path, name=path.name, ext=".txt", size=path.stat().st_size)


def _base_meta() -> dict:
    return {"source": "sample.txt", "category": "text", "doc_format": "txt"}


def test_text_loader_plain_file_single_document(tmp_path):
    # 无 Markdown 标题：整篇作为单个文档，不硬切
    p = tmp_path / "plain.txt"
    p.write_text(
        "这是一段没有任何标题结构的纯文本正文，长度足够通过清洗与最小可读长度校验。",
        encoding="utf-8",
    )

    docs = TextLoader().load(_info(p), _base_meta())

    assert len(docs) == 1
    assert "纯文本正文" in docs[0].page_content
    assert docs[0].metadata["source_file"] == "plain.txt"


def test_text_loader_with_headings_splits_chapters(tmp_path):
    # 含 Markdown 标题：outline 按章节拆，metadata 带 chapter_path
    p = tmp_path / "headed.txt"
    p.write_text(
        "# 第一章 概述\n\n概述章节的正文内容，介绍设备基本情况。\n\n"
        "## 1.1 技术参数\n\n技术参数章节的正文内容，列出量程与精度。\n",
        encoding="utf-8",
    )

    docs = TextLoader().load(_info(p), _base_meta())

    assert len(docs) >= 2
    paths = [d.metadata.get("chapter_path", "") for d in docs]
    assert any("概述" in path for path in paths)
    assert all(d.page_content.strip() for d in docs)


def test_text_loader_empty_after_cleaning_returns_empty(tmp_path):
    # 纯噪声 / 空白文件清洗后为空，返回空列表而不是吐空文档
    p = tmp_path / "blank.txt"
    p.write_text("   \n\n\t\n", encoding="utf-8")

    assert TextLoader().load(_info(p), _base_meta()) == []


def test_text_loader_encoding_fallback_retries_utf8(tmp_path):
    # 首次用非法编码名读取必然抛 LookupError，应回退 utf-8(errors=ignore)
    # 仍能读到正文，而不是直接返回空列表
    p = tmp_path / "enc.txt"
    p.write_text("编码回退验证正文，确保第二次读取成功返回内容。", encoding="utf-8")

    meta = _base_meta()
    meta["encoding"] = "definitely-not-a-real-encoding"
    docs = TextLoader().load(_info(p), meta)

    assert len(docs) == 1
    assert "编码回退" in docs[0].page_content


def test_text_loader_unreadable_file_returns_empty(tmp_path):
    # 目录可以被 stat（FileInfo 能构造），但当文件打开两次都失败，
    # loader 应安全返回空列表，不抛异常
    info = FileInfo(path=tmp_path, name="dir", ext=".txt", size=0)

    assert TextLoader().load(info, _base_meta()) == []
