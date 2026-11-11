"""PDF 表格轻量结构化提取（PyMuPDF 内置能力，零新增依赖）。

背景：DeepDoc 重型栈默认关闭，旧链路把参数表、对照表抽成散文本，
跨列关系在切块后丢失（GS11 类检索边界的部分根因）。PyMuPDF 1.23+
自带 ``page.find_tables()``，基于线条/间距识别表格区域，无需引入
pdfplumber、onnxruntime 等重型依赖，契合全离线 CPU 生产环境。

输出 Markdown 表格：对切块器与 7B 生成都友好，且能作为普通文本
随页边标记走完整的页码传播链路，不需要新增 metadata 通道。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _row_to_markdown(row: list) -> str:
    cells = [("" if c is None else str(c)).replace("\n", " ").strip() for c in row]
    return "| " + " | ".join(cells) + " |"


def render_tables_markdown(tables) -> str:
    """把 PyMuPDF TableFinder.tables 渲染成 Markdown 文本。

    纯函数，入参用鸭子类型（只需 ``table.extract() -> list[list]``），
    便于单测构造假件，不绑定具体 PyMuPDF 版本对象。
    """
    blocks: list[str] = []
    for idx, table in enumerate(tables, start=1):
        try:
            rows = table.extract()
        except Exception as e:  # noqa: BLE001 - 单表失败不影响其他表与正文
            logger.warning("PDF table %d extract failed, skipped: %s", idx, e)
            continue

        # 噪声过滤：无行、单行单列、整表无实质字符的识别结果直接丢弃
        rows = [r for r in rows if r]
        if not rows:
            continue
        non_empty = [c for r in rows for c in r if c and str(c).strip()]
        if len(non_empty) < 2:
            continue

        lines = [f"【表格 {idx}】"]
        header = rows[0]
        lines.append(_row_to_markdown(header))
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for row in rows[1:]:
            # 列数不齐时补齐，避免 Markdown 表格断裂
            if len(row) < len(header):
                row = list(row) + [""] * (len(header) - len(row))
            lines.append(_row_to_markdown(row))
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def extract_page_tables(page) -> str:
    """提取单页表格，返回 Markdown 文本；无表格或异常时返回空字符串。

    任何异常都降级为空串，保证 PDF 正文加载这条主链路永不因
    表格识别而失败（表格提取是增强能力，不是硬依赖）。
    """
    try:
        finder = page.find_tables()
        tables = getattr(finder, "tables", None)
        if not tables:
            return ""
        return render_tables_markdown(tables)
    except Exception as e:  # noqa: BLE001
        logger.debug("find_tables unavailable on this page, skipped: %s", e)
        return ""
