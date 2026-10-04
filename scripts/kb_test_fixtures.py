#!/usr/bin/env python
"""生成知识库 RAG 全链路测试素材（DOCX / PDF）

用法（宿主机，生成 DOCX）：
    python scripts/kb_test_fixtures.py docx

用法（容器内，生成含中文的 PDF，需要 PyMuPDF）：
    python scripts/kb_test_fixtures.py pdf

说明：
    DOCX 用 python-docx 生成；PDF 用 PyMuPDF(fitz) + 内置 CJK 字体生成，
    避免依赖 reportlab 等外部库，也不需要下载字体文件。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 输出目录：默认仓库内 fixtures/kb_test。
# 容器内运行时用 KB_FIXTURE_DIR 覆盖（容器里的脚本路径与仓库结构不同）。
FIXTURE_DIR = Path(
    os.environ.get("KB_FIXTURE_DIR")
    or (Path(__file__).resolve().parent.parent / "fixtures" / "kb_test")
)

# 与 kb_md_manual.md 中的独有事实保持一致的测试内容。
# 独有数字（192 摄氏度 / 47 分钟 / 26 分钟）与 markdown/txt 版本刻意不同，
# 用于判断命中的到底是哪一份文档，从而验证引用溯源是否精确。
DOCX_PARAGRAPHS = [
    ("XG-9000 真空镀膜机 升级说明（DOCX 格式测试）", "title"),
    ("一、腔体预热参数调整", "h1"),
    (
        "XG-9000 型真空镀膜机在 V3 固件后的腔体预热温度调整为 192 摄氏度，"
        "预热时长为 47 分钟。此变更仅适用于 2026 年 7 月以后出厂的机型。",
        "body",
    ),
    ("升级后需在首次开机时执行一次温度自校准，自校准耗时 26 分钟。", "body"),
    ("二、兼容性说明", "h1"),
    ("V3 固件不兼容旧版 TC-K-31 热电偶，必须更换为 TC-K-32。", "body"),
    ("三、报警代码变更", "h1"),
    ("原 E-2071 报警拆分为 E-2071A（流量不足）与 E-2071B（水温过高）两条。", "body"),
]

PDF_TEXT = """XG-9000 真空镀膜机 安全操作规范（PDF 格式测试）

第一条 启动前检查
操作人员在启动 XG-9000 前，必须确认腔体门锁紧销已插入到位。
未插入到位时启动，联锁装置会在 8 秒内切断主电源。

第二条 高温防护
腔体预热期间，外壁温度最高可达 74 摄氏度，禁止徒手接触。
检修作业必须佩戴耐温 200 摄氏度以上的隔热手套。

第三条 真空维持
设备停机后需维持分子泵运行 21 分钟，使腔内压力缓慢回升。
直接破真空会导致靶材表面产生微裂纹。

第四条 应急处置
发生冷却水泄漏时，立即按下红色急停按钮，位置在设备右侧下方 1.1 米处。
急停后 3 分钟内不得重新上电。
"""


def build_docx() -> Path:
    """生成 DOCX 测试文档（宿主机可运行）"""
    from docx import Document

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    out = FIXTURE_DIR / "kb_docx_upgrade.docx"

    doc = Document()
    for text, kind in DOCX_PARAGRAPHS:
        if kind == "title":
            doc.add_heading(text, level=0)
        elif kind == "h1":
            doc.add_heading(text, level=1)
        else:
            doc.add_paragraph(text)
    doc.save(str(out))
    print(f"[OK] DOCX generated: {out} ({out.stat().st_size} bytes)")
    return out


def build_pdf() -> Path:
    """生成含中文的 PDF 测试文档（需 PyMuPDF，容器内可运行）"""
    import fitz  # PyMuPDF

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    out = FIXTURE_DIR / "kb_pdf_safety.pdf"

    doc = fitz.open()
    page = doc.new_page()
    # 使用 PyMuPDF 内置简体中文字体，避免依赖外部字体文件
    y = 60.0
    for line in PDF_TEXT.split("\n"):
        if line.strip():
            page.insert_text(
                (56, y),
                line,
                fontname="china-s",  # 内置简体中文字体
                fontsize=12,
            )
        y += 22.0
    doc.save(str(out))
    doc.close()
    print(f"[OK] PDF generated: {out} ({out.stat().st_size} bytes)")
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "docx"
    if mode == "docx":
        build_docx()
    elif mode == "pdf":
        build_pdf()
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        sys.exit(2)
