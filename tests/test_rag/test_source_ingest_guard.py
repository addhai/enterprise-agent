"""网页摄取内网隔离开关专项测试（P2-15，全离线）。

锁定四条契约：
    1. web_ingest_enabled 默认关闭，url_to_documents 确定性抛禁用异常且不触网
    2. 底层 fetch_url_text 同样受开关保护，防止调用方绕过主入口直接抓取
    3. 显式开启后，配合本地 HTML 替身，整条 URL 摄取管线恢复正常
    4. 纯文本 text_to_documents 不联网，开关关闭时仍可正常使用
"""

import pytest
from src.config import settings
from src.rag import source_ingest
from src.rag.source_ingest import WebIngestDisabledError


def test_url_ingest_blocked_when_switch_off(monkeypatch):
    """开关关闭时主入口抛禁用异常，且被替换的抓取函数不会被调用（不触网）。"""
    monkeypatch.setattr(settings, "web_ingest_enabled", False)

    def _network_sentinel(*args, **kwargs):
        raise AssertionError("守卫失效：禁用态不应发起任何网页抓取")

    monkeypatch.setattr(source_ingest, "fetch_url_text", _network_sentinel)

    with pytest.raises(WebIngestDisabledError):
        source_ingest.url_to_documents("https://example.com/x", "标题")


def test_fetch_url_text_blocked_at_low_level(monkeypatch):
    """底层抓取函数自带守卫，绕过 url_to_documents 直接调用也被拦截。"""
    monkeypatch.setattr(settings, "web_ingest_enabled", False)
    with pytest.raises(WebIngestDisabledError):
        source_ingest.fetch_url_text("https://example.com/raw")


def test_url_ingest_works_when_switch_on(monkeypatch):
    """显式开启后，本地 HTML 替身驱动整条管线，元数据带 source_url。"""
    monkeypatch.setattr(settings, "web_ingest_enabled", True)
    html = (
        "<html><body><h1>隔离开关验证标题</h1>"
        "<p>这是开关开启后经本地替身抓取的网页正文内容。</p>"
        "</body></html>"
    )
    monkeypatch.setattr(source_ingest, "fetch_url_text", lambda url, timeout=15.0: html)

    docs = source_ingest.url_to_documents(
        "https://example.com/enabled", "开启态网页", tenant_id="t1"
    )
    assert docs
    assert all(d.metadata.get("category") == "web" for d in docs)
    assert all(
        d.metadata.get("source_url") == "https://example.com/enabled" for d in docs
    )


def test_text_ingest_unaffected_by_switch(monkeypatch):
    """纯文本摄取不联网，开关关闭时依旧可用，不被网页策略误伤。"""
    monkeypatch.setattr(settings, "web_ingest_enabled", False)
    long_text = "纯文本知识源不受网页抓取开关约束。" * 20
    docs = source_ingest.text_to_documents(long_text, "文本片段", tenant_id="t1")
    assert docs
    assert all(d.metadata.get("category") == "text" for d in docs)
