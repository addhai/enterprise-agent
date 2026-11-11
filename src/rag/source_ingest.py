"""多知识源摄取：网页 URL + 纯文本 → 统一 Document 列表

设计原则：
    - 复用 src.rag.loader.DocumentLoader 的解析 / 清洗 / 分块管线，
      保证 URL / 文本来源与文件上传"同源"（同一套 metadata、同一套分块策略）。
    - 不引入新依赖：网页抓取用 httpx（已在 requirements），正文提取用
      beautifulsoup4（已在 requirements），零新增第三方包。
    - 仅做"文本类"来源的摄取（document 仍走原文件上传路径）。

数据流：
    URL  → httpx 抓取 → BeautifulSoup 提取正文 → 临时 .txt → DocumentLoader.load_file
    文本 → 直接写入临时 .txt → DocumentLoader.load_file
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class WebIngestDisabledError(RuntimeError):
    """内网形态下网页摄取被策略关闭时抛出。

    与普通网络错误区分：这是确定性的配置拒绝，调用方应返回明确的
    「功能禁用」提示，而不是伪装成抓取失败重试。
    """


def _ensure_web_ingest_enabled() -> None:
    """网页抓取前置守卫（P2-15）。

    全离线内网默认 web_ingest_enabled=False，任何 URL 摄取路径在发起
    httpx 请求前先在此被拦截，保证不产生外网连接。
    """
    from src.config import settings

    if not getattr(settings, "web_ingest_enabled", False):
        raise WebIngestDisabledError(
            "网页 URL 知识源摄取已被内网策略禁用"
            "（web_ingest_enabled=false）；如需启用请由管理员显式配置"
        )


def fetch_url_text(url: str, timeout: float = 15.0) -> str:
    """抓取网页并提取正文纯文本

    Args:
        url: 目标网页地址（需以 http:// 或 https:// 开头）
        timeout: 请求超时（秒）

    Returns:
        去噪后的正文文本（多行），失败时抛异常由调用方处理
    """
    # 底层防御：即便有调用方绕过 url_to_documents 直接抓网页，也先过开关
    _ensure_web_ingest_enabled()
    import httpx
    from bs4 import BeautifulSoup

    resp = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; EnterpriseAgent/1.0)"},
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    # 移除无正文价值的标签
    for tag in soup(
        ["script", "style", "noscript", "header", "footer", "nav", "aside", "iframe"]
    ):
        tag.decompose()

    main = soup.find("article") or soup.find("main") or soup.body
    text = (
        main.get_text(separator="\n", strip=True)
        if main
        else soup.get_text(separator="\n", strip=True)
    )
    # 合并多余空行
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _load_text_via_loader(text: str, title: str, tenant_id: str) -> list[Document]:
    """把纯文本写入临时 .txt，复用 DocumentLoader 的分块 / 清洗管线"""
    from src.rag.loader import DocumentLoader

    # 注意：DocumentLoader 未注册 .txt 加载器，但 .md 加载器兼容纯文本，故用 .md
    fd, tmp_path = tempfile.mkstemp(suffix=".md", prefix="kb_src_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        loader = DocumentLoader(default_tenant_id=tenant_id)
        docs = loader.load_file(tmp_path)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
    for d in docs:
        d.metadata["source"] = title or "text"
        d.metadata["category"] = "text"
    return docs


def text_to_documents(text: str, title: str, tenant_id: str = "") -> list[Document]:
    """纯文本 → Document 列表（已分块、清洗、标注元数据）

    用于"手动录入 / FAQ / 产品问答"等结构化文本知识源。
    """
    if not text or not text.strip():
        return []
    return _load_text_via_loader(text, title or "文本片段", tenant_id)


def url_to_documents(url: str, title: str, tenant_id: str = "") -> list[Document]:
    """网页 URL → Document 列表（已分块、清洗、标注元数据）

    用于"官网帮助中心 / 文档站 / 博客"等网页知识源。
    内网形态受 web_ingest_enabled 开关约束，关闭时抛 WebIngestDisabledError。
    """
    # 主入口守卫：与 fetch_url_text 内的底层防御互为冗余，确保即便
    # 测试或未来调用方替换了抓取函数，策略开关仍然生效。
    _ensure_web_ingest_enabled()
    text = fetch_url_text(url)
    docs = _load_text_via_loader(text, title or url, tenant_id)
    for d in docs:
        d.metadata["source"] = title or url
        d.metadata["source_url"] = url
        d.metadata["category"] = "web"
    return docs
