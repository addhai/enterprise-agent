"""DocxLoader 单元测试

阶段 2 开门周补齐：CI 口径 docx_loader.py 行覆盖率仅 14%。
用 python-docx 在 tmp_path 现场生成 docx，不依赖二进制夹具。

顺带覆盖两处本次修复的潜伏缺陷：
1. 第 4 行补 import json（原文件在 outline_store_full_json=True 时 NameError）
2. settings 导入路径由不存在的 src.rag.config 修正为 src.config
"""

import json

import pytest

docx = pytest.importorskip("docx", reason="环境未安装 python-docx")

from src.rag.data_sources import FileInfo  # noqa: E402
from src.rag.loaders.docx_loader import DocxLoader  # noqa: E402


def _info(path) -> FileInfo:
    return FileInfo(path=path, name=path.name, ext=".docx", size=path.stat().st_size)


def _make_docx(path, *, headed: bool, author: str = "", title: str = ""):
    doc = docx.Document()
    if author:
        doc.core_properties.author = author
    if title:
        doc.core_properties.title = title
    if headed:
        doc.add_heading("第一章 设备概述", level=1)
        doc.add_paragraph("本章介绍设备的用途、适用场景与基本组成结构。")
        doc.add_heading("1.1 技术参数", level=2)
        doc.add_paragraph("量程为零下五十摄氏度到零上五百五十摄氏度。")
    else:
        doc.add_paragraph(
            "这是一份没有任何标题样式的纯正文文档，内容长度足以通过清洗。"
        )
        doc.add_paragraph("第二段补充说明设备日常维护的基本注意事项与清洁要求。")
    doc.save(str(path))
    return path


def test_docx_loader_without_headings_single_document(tmp_path):
    p = _make_docx(tmp_path / "plain.docx", headed=False)

    docs = DocxLoader().load(_info(p), {"source": "plain.docx", "doc_format": "docx"})

    assert len(docs) == 1
    assert "纯正文文档" in docs[0].page_content
    assert docs[0].metadata["source_file"] == "plain.docx"


def test_docx_loader_with_headings_splits_and_keeps_properties(tmp_path):
    p = _make_docx(
        tmp_path / "headed.docx", headed=True, author="张工", title="测温设备手册"
    )

    docs = DocxLoader().load(_info(p), {"source": "headed.docx"})

    assert len(docs) >= 2
    # chapter_path / heading 元数据齐全，正文保留
    paths = [d.metadata.get("chapter_path", "") for d in docs]
    assert any("设备概述" in path for path in paths)
    joined = "\n".join(d.page_content for d in docs)
    assert "五百五十摄氏度" in joined
    # 文档属性透传到基础元数据
    assert docs[0].metadata.get("author") == "张工"
    assert docs[0].metadata.get("title") == "测温设备手册"


def test_docx_loader_corrupt_file_returns_empty(tmp_path):
    # 内容不是合法 zip/docx，python-docx 打开失败应安全降级 []
    p = tmp_path / "broken.docx"
    p.write_text("这根本不是一个 docx 文件，只是纯文本伪装的扩展名。", encoding="utf-8")

    assert DocxLoader().load(_info(p), {"source": "broken.docx"}) == []


def test_docx_loader_empty_body_returns_empty(tmp_path):
    # 只有空段落、没有正文，清洗后为空 → []
    p = tmp_path / "empty.docx"
    doc = docx.Document()
    doc.add_paragraph("   ")
    doc.save(str(p))

    assert DocxLoader().load(_info(p), {"source": "empty.docx"}) == []


def test_docx_loader_outline_json_when_enabled(tmp_path, monkeypatch):
    # 打开 outline_store_full_json：修复 import json 与错误 settings 路径后，
    # metadata 应携带可解析的 outline JSON
    from src.config import settings

    monkeypatch.setattr(settings, "outline_store_full_json", True, raising=False)
    p = _make_docx(tmp_path / "outline.docx", headed=True)

    docs = DocxLoader().load(_info(p), {"source": "outline.docx"})

    assert docs, "带标题文档应产出章节"
    outlined = [d for d in docs if d.metadata.get("outline")]
    assert outlined, "store_full_json=True 时章节 metadata 必须带 outline"
    parsed = json.loads(outlined[0].metadata["outline"])
    assert isinstance(parsed, dict)
