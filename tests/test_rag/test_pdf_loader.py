"""PdfLoader 回归测试

2026-10-06 语料重建时实测到：旧实现在提取书签之前就 doc_handle.close()，
PyMuPDF 随后抛 "document closed"，导致整个 PDF 加载失败、静默丢文档。
"""

from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz", reason="环境未安装 PyMuPDF")

from src.rag.data_sources import FileInfo  # noqa: E402
from src.rag.loaders.pdf_loader import PdfLoader  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_T90_PDF = _PROJECT_ROOT / "fixtures" / "kb_test" / "thermosense_t90_service_manual.pdf"


def test_pdf_load_does_not_access_closed_handle():
    """完整加载真实 PDF 不抛异常（回归 document closed），且产出非空章节"""
    assert _T90_PDF.exists(), f"测试夹具缺失: {_T90_PDF}"

    info = FileInfo(
        path=_T90_PDF,
        name=_T90_PDF.name,
        ext=".pdf",
        size=_T90_PDF.stat().st_size,
    )
    base_meta = {"source": info.name, "category": "pdf", "doc_format": "pdf"}

    chapters = PdfLoader().load(info, base_meta)

    assert chapters, "PDF 应至少产出一个章节文档"
    for doc in chapters:
        assert doc.page_content.strip(), "章节内容不能为空"
        assert doc.metadata.get("source") == _T90_PDF.name
