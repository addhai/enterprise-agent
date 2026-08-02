"""DeepDoc 文档解析器 — 扫描件 PDF / 复杂版面 增强

参考：RAGFlow 的 deepdoc/parser/pdf_parser.py + deepdoc/vision/
对齐阿里云百炼：扫描件 PDF 可解析、复杂版面可识别

设计思路（轻量级，不引入重依赖）：
    RAGFlow 的 DeepDoc 完整版依赖 onnxruntime/xgboost/sklearn/pdfplumber 等重型库。
    本项目采用轻量级适配方案，复用现有的 vision_engines + OCR 引擎：

    1. 检测 PDF 类型：
       - 文字型 PDF（原生 PDF）：PyMuPDF 直接提取文字（现有流程，快）
       - 扫描件 PDF（图片型）：每页渲染为图片 → 复用 ImageLoader 管线（Vision+OCR）
    2. 混合型 PDF：部分页有文字、部分页是扫描图 → 逐页判断，分别处理
    3. 表格识别：复用 Qwen-VL 视觉理解（已支持表格 Markdown 输出）

工作流程：
    PDF → 逐页检测 → [文字页: PyMuPDF] + [扫描页: 渲染图片→Vision/OCR] → 合并

配置（在 .env 中）：
    DEEPDOC_ENABLED=true              # 启用 DeepDoc 增强（默认 false，避免影响性能）
    DEEPDOC_SCAN_THRESHOLD=50         # 扫描件判定阈值（每页最少字符数，低于此值视为扫描页）
    DEEPDOC_RENDER_DPI=150            # 扫描页渲染 DPI（越高越清晰，但越慢）
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

from src.config import settings
from src.rag.data_sources import FileInfo

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


class DeepDocParser:
    """DeepDoc 文档解析器 — 扫描件 PDF / 复杂版面增强

    用法：
        parser = DeepDocParser()
        if parser.is_scanned_pdf(pdf_path):
            docs = parser.parse_scanned_pdf(pdf_path, base_meta)
        else:
            docs = []  # 走原有 PyMuPDF 流程

    或用统一入口：
        docs = parser.parse_pdf(pdf_path, base_meta)  # 自动判断并路由
    """

    def __init__(
        self,
        scan_threshold: int = None,
        render_dpi: int = None,
        enabled: bool = None,
    ):
        self.scan_threshold = scan_threshold or getattr(
            settings, "deepdoc_scan_threshold", 50
        )
        self.render_dpi = render_dpi or getattr(
            settings, "deepdoc_render_dpi", 150
        )
        self.enabled = enabled if enabled is not None else getattr(
            settings, "deepdoc_enabled", False
        )
        self._image_loader = None  # 懒加载 ImageLoader

    @property
    def image_loader(self):
        """懒加载 ImageLoader（复用其 Vision+OCR 管线）"""
        if self._image_loader is not None:
            return self._image_loader
        from src.rag.loaders.image_loader import ImageLoader
        self._image_loader = ImageLoader()
        return self._image_loader

    # ------------------------------------------------------------------
    # PDF 类型检测
    # ------------------------------------------------------------------

    def is_scanned_pdf(self, pdf_path: str) -> bool:
        """检测 PDF 是否为扫描件（图片型）

        判定规则：
            - 统计每页可提取的文字字符数
            - 如果超过 50% 的页文字字符数 < scan_threshold，视为扫描件

        Args:
            pdf_path: PDF 文件路径

        Returns:
            True 如果是扫描件 PDF
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.warning("PyMuPDF not installed, cannot detect PDF type")
            return False

        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            if total_pages == 0:
                return False

            scanned_pages = 0
            for page in doc:
                text = page.get_text().strip()
                if len(text) < self.scan_threshold:
                    scanned_pages += 1

            doc.close()

            # 超过 50% 的页是扫描页 → 判定为扫描件
            is_scanned = scanned_pages > total_pages * 0.5
            if is_scanned:
                logger.info(
                    "Scanned PDF detected: %s (%d/%d pages are image-only)",
                    pdf_path, scanned_pages, total_pages,
                )
            return is_scanned

        except Exception as e:
            logger.warning("PDF type detection failed: %s", e)
            return False

    def detect_page_types(self, pdf_path: str) -> List[str]:
        """逐页检测 PDF 页面类型

        Returns:
            每页类型列表：["text", "scanned", "text", ...]
        """
        try:
            import fitz
        except ImportError:
            return []

        doc = fitz.open(pdf_path)
        page_types = []
        for page in doc:
            text = page.get_text().strip()
            page_types.append("scanned" if len(text) < self.scan_threshold else "text")
        doc.close()
        return page_types

    # ------------------------------------------------------------------
    # 解析入口
    # ------------------------------------------------------------------

    def parse_pdf(
        self,
        info: FileInfo,
        base_meta: dict,
    ) -> List["_Doc"]:
        """统一 PDF 解析入口 — 自动判断并路由

        - 文字型 PDF：返回空列表，由调用方走原有 PyMuPDF 流程
        - 扫描件 PDF：每页渲染图片 → Vision/OCR 提取
        - 混合型 PDF：逐页分别处理

        Args:
            info: 文件信息
            base_meta: 基础元数据

        Returns:
            Document 列表（文字型 PDF 返回空，由调用方处理）
        """
        if not self.enabled:
            return []

        pdf_path = str(info.path)

        # 检测页面类型
        page_types = self.detect_page_types(pdf_path)
        if not page_types:
            return []

        scanned_count = sum(1 for t in page_types if t == "scanned")
        if scanned_count == 0:
            # 纯文字 PDF，走原有流程
            logger.debug("PDF is text-based, using PyMuPDF: %s", pdf_path)
            return []

        logger.info(
            "DeepDoc parsing PDF: %s (%d text pages, %d scanned pages)",
            pdf_path, len(page_types) - scanned_count, scanned_count,
        )

        return self._parse_mixed_pdf(info, base_meta, page_types)

    def _parse_mixed_pdf(
        self,
        info: FileInfo,
        base_meta: dict,
        page_types: List[str],
    ) -> List["_Doc"]:
        """解析混合型 PDF（文字页 + 扫描页）

        文字页：PyMuPDF 提取
        扫描页：渲染为图片 → ImageLoader 管线（Vision+OCR）
        """
        from langchain_core.documents import Document

        try:
            import fitz
        except ImportError:
            return []

        docs: List[_Doc] = []
        doc = fitz.open(str(info.path))

        try:
            for page_num, page_type in enumerate(page_types):
                page = doc[page_num]
                page_meta = {
                    **base_meta,
                    "page_number": page_num + 1,
                    "page_type": page_type,  # text / scanned
                    "deepdoc_processed": True,
                }

                if page_type == "text":
                    # 文字页：PyMuPDF 提取
                    text = page.get_text().strip()
                    if text:
                        docs.append(Document(
                            page_content=text,
                            metadata=page_meta,
                        ))
                else:
                    # 扫描页：渲染为图片 → ImageLoader
                    page_docs = self._parse_scanned_page(page, page_meta, info.name, page_num)
                    docs.extend(page_docs)
        finally:
            doc.close()

        return docs

    def _parse_scanned_page(
        self,
        page,
        page_meta: dict,
        source_name: str,
        page_num: int,
    ) -> List["_Doc"]:
        """将扫描页渲染为图片，复用 ImageLoader 管线提取内容

        Args:
            page: fitz.Page 对象
            page_meta: 页面元数据
            source_name: 源文件名
            page_num: 页码（0-based）

        Returns:
            Document 列表
        """
        from langchain_core.documents import Document

        # 渲染页面为图片
        temp_img_path = self._render_page_to_image(page, page_num)
        if not temp_img_path:
            return []

        try:
            # 构造 FileInfo 给 ImageLoader
            from src.rag.data_sources import FileInfo
            img_info = FileInfo(
                path=Path(temp_img_path),
                name=f"{source_name}_p{page_num + 1}.png",
                ext=".png",
                size=os.path.getsize(temp_img_path),
            )

            # 调用 ImageLoader（复用 Vision+OCR 管线）
            docs = self.image_loader.load(img_info, page_meta)

            # 标记来源为扫描页
            for doc in docs:
                doc.metadata["source"] = source_name
                doc.metadata["extraction_method"] = f"deepdoc_{doc.metadata.get('extraction_method', 'unknown')}"

            return docs

        except Exception as e:
            logger.warning(
                "DeepDoc: failed to parse scanned page %d: %s", page_num + 1, e
            )
            return []
        finally:
            # 清理临时图片
            try:
                os.remove(temp_img_path)
            except Exception:
                pass

    def _render_page_to_image(self, page, page_num: int) -> Optional[str]:
        """将 PDF 页面渲染为 PNG 图片

        Args:
            page: fitz.Page 对象
            page_num: 页码（用于临时文件命名）

        Returns:
            临时图片路径，失败返回 None
        """
        try:
            import fitz
            # 渲染矩阵：DPI 控制
            zoom = self.render_dpi / 72.0  # 72 是 PDF 默认 DPI
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # 保存为临时 PNG
            temp_path = os.path.join(
                tempfile.gettempdir(),
                f"deepdoc_page_{page_num}_{os.getpid()}.png",
            )
            pix.save(temp_path)
            return temp_path

        except Exception as e:
            logger.warning("Failed to render page %d: %s", page_num + 1, e)
            return None

    # ------------------------------------------------------------------
    # 表格识别（预留，复用 Qwen-VL）
    # ------------------------------------------------------------------

    def extract_tables(self, pdf_path: str) -> List[str]:
        """提取 PDF 中的表格（返回 Markdown 格式）

        预留接口：当前依赖 Qwen-VL 视觉理解，后续可接入专门的表格识别模型。
        RAGFlow 用 TableStructureRecognizer（onnx 模型）识别表格结构。

        Returns:
            Markdown 格式表格列表
        """
        # TODO: 接入 TableStructureRecognizer 或调用 Qwen-VL 表格识别 prompt
        logger.info("Table extraction not yet implemented (placeholder)")
        return []
