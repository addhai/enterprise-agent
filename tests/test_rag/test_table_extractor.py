"""PDF 表格提取单测（离线）。

三层覆盖：
    1. render_tables_markdown 纯函数：Markdown 结构、噪声过滤、异常隔离
    2. extract_page_tables 鸭子类型页面对象：空表与异常降级
    3. PdfLoader 接线：开关开启时表格块随页文本注入（monkeypatch 确定性）
"""

import pytest

fitz = pytest.importorskip("fitz", reason="环境未安装 PyMuPDF")

from src.rag import table_extractor as te  # noqa: E402
from src.rag.data_sources import FileInfo  # noqa: E402
from src.rag.loaders.pdf_loader import PdfLoader  # noqa: E402


class FakeTable:
    def __init__(self, rows, raises=False):
        self._rows = rows
        self._raises = raises

    def extract(self):
        if self._raises:
            raise RuntimeError("boom")
        return self._rows


class FakeFinder:
    def __init__(self, tables):
        self.tables = tables


class FakePage:
    def __init__(self, tables=None, raises=False):
        self._tables = tables or []
        self._raises = raises

    def find_tables(self):
        if self._raises:
            raise RuntimeError("finder unavailable")
        return FakeFinder(self._tables)


# ---------------------------------------------------------------------------
# 1. render_tables_markdown
# ---------------------------------------------------------------------------


def test_render_basic_markdown_structure():
    table = FakeTable(
        [
            ["参数", "规格"],
            ["测温范围", "-50~550℃"],
            ["精度", "±1.5℃"],
        ]
    )

    md = te.render_tables_markdown([table])

    assert "【表格 1】" in md
    lines = md.split("\n")
    assert lines[1] == "| 参数 | 规格 |"
    assert lines[2] == "| --- | --- |"
    assert "| 测温范围 | -50~550℃ |" in md
    assert "| 精度 | ±1.5℃ |" in md


def test_render_normalizes_none_and_newlines():
    table = FakeTable([["A", "B"], ["x\n换行", None]])

    md = te.render_tables_markdown([table])

    assert "| x 换行 |  |" in md


def test_render_pads_ragged_rows():
    table = FakeTable([["H1", "H2", "H3"], ["only-one"]])

    md = te.render_tables_markdown([table])

    assert "| only-one |  |  |" in md


def test_render_filters_single_cell_noise():
    table = FakeTable([["孤零零一个单元格"]])

    assert te.render_tables_markdown([table]) == ""


def test_render_skips_empty_and_failed_tables():
    bad = FakeTable([], raises=True)
    good = FakeTable([["K", "V"], ["发射率", "0.10~1.00"]])

    md = te.render_tables_markdown([bad, good])

    # 失败表跳过且不占输出序号位，成功表保留页内原始编号 2
    assert "【表格 2】" in md
    assert "发射率" in md
    assert "【表格 1】" not in md


def test_render_multiple_tables_numbered():
    t1 = FakeTable([["A", "B"], ["1", "2"]])
    t2 = FakeTable([["C", "D"], ["3", "4"]])

    md = te.render_tables_markdown([t1, t2])

    assert "【表格 1】" in md
    assert "【表格 2】" in md


# ---------------------------------------------------------------------------
# 2. extract_page_tables 降级语义
# ---------------------------------------------------------------------------


def test_extract_page_tables_happy_path():
    page = FakePage([FakeTable([["K", "V"], ["保修", "12个月"]])])

    md = te.extract_page_tables(page)

    assert "【表格 1】" in md
    assert "12个月" in md


def test_extract_page_tables_empty_returns_blank():
    assert te.extract_page_tables(FakePage(tables=[])) == ""


def test_extract_page_tables_finder_exception_degrades():
    assert te.extract_page_tables(FakePage(raises=True)) == ""


# ---------------------------------------------------------------------------
# 3. PdfLoader 接线（monkeypatch 保证确定性，不依赖识别引擎版本）
# ---------------------------------------------------------------------------


def test_loader_injects_table_markdown_when_enabled(tmp_path, monkeypatch):
    pdf_path = tmp_path / "plain.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Thermal device manual body text for loading.")
    doc.save(str(pdf_path))
    doc.close()

    injected = "【表格 1】\n| 参数 | 值 |\n| --- | --- |\n| 精度 | ±1.5℃ |"
    monkeypatch.setattr(te, "extract_page_tables", lambda page: injected)

    info = FileInfo(
        path=pdf_path, name="plain.pdf", ext=".pdf", size=pdf_path.stat().st_size
    )
    chapters = PdfLoader().load(
        info, {"source": "plain.pdf", "category": "pdf", "doc_format": "pdf"}
    )

    full_text = "\n".join(c.page_content for c in chapters)
    assert "±1.5℃" in full_text
    assert "【表格 1】" in full_text


def test_loader_skips_tables_when_disabled(tmp_path, monkeypatch):
    pdf_path = tmp_path / "plain2.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Another body paragraph for the disabled case.")
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr(
        "src.config.settings.pdf_table_extract_enabled", False, raising=True
    )
    called = {"n": 0}

    def _should_not_run(page):
        called["n"] += 1
        return "不该出现的表格"

    monkeypatch.setattr(te, "extract_page_tables", _should_not_run)

    info = FileInfo(
        path=pdf_path, name="plain2.pdf", ext=".pdf", size=pdf_path.stat().st_size
    )
    chapters = PdfLoader().load(
        info, {"source": "plain2.pdf", "category": "pdf", "doc_format": "pdf"}
    )

    full_text = "\n".join(c.page_content for c in chapters)
    assert called["n"] == 0
    assert "不该出现的表格" not in full_text
    assert chapters, "关闭表格提取不应影响正文加载"


# ---------------------------------------------------------------------------
# 4. 真实合成 PDF 冒烟：线条网格 + 单元格文字
# ---------------------------------------------------------------------------


def test_real_pdf_grid_table_smoke(tmp_path):
    pdf_path = tmp_path / "grid.pdf"
    doc = fitz.open()
    page = doc.new_page()

    # 2x2 线条网格（坐标：左上 72,72，列宽 120，行高 36）
    x0, y0, col_w, row_h = 72, 72, 120, 36
    for i in range(3):
        page.draw_line((x0 + i * col_w, y0), (x0 + i * col_w, y0 + 2 * row_h))
    for j in range(3):
        page.draw_line((x0, y0 + j * row_h), (x0 + 2 * col_w, y0 + j * row_h))
    page.insert_text((x0 + 8, y0 + 22), "K")
    page.insert_text((x0 + col_w + 8, y0 + 22), "V")
    page.insert_text((x0 + 8, y0 + row_h + 22), "range")
    page.insert_text((x0 + col_w + 8, y0 + row_h + 22), "550C")
    doc.save(str(pdf_path))
    doc.close()

    info = FileInfo(
        path=pdf_path, name="grid.pdf", ext=".pdf", size=pdf_path.stat().st_size
    )
    chapters = PdfLoader().load(
        info, {"source": "grid.pdf", "category": "pdf", "doc_format": "pdf"}
    )

    assert chapters, "带表格 PDF 必须正常加载"
    full_text = "\n".join(c.page_content for c in chapters)
    # 引擎识别成功则 Markdown 必须成块；识别不到时正文文字仍应在，链路不崩
    if "【表格 1】" in full_text:
        assert "| ---" in full_text
    assert "550C" in full_text or "range" in full_text
