"""HtmlLoader 单元测试

阶段 2 开门周补齐：CI 口径 html_loader.py 行覆盖率仅 29%。
BeautifulSoup 为 requirements 已声明依赖，测试全程离线确定性。
"""

from src.rag.data_sources import FileInfo
from src.rag.loaders.base import LoaderRegistry
from src.rag.loaders.html_loader import HtmlLoader


def _info(path) -> FileInfo:
    return FileInfo(
        path=path, name=path.name, ext=path.suffix, size=path.stat().st_size
    )


def test_html_and_htm_extensions_registered():
    # 两个扩展名都应注册到同一个 loader
    assert LoaderRegistry.get(".html") is HtmlLoader
    assert LoaderRegistry.get(".htm") is HtmlLoader


def test_html_loader_extracts_body_and_drops_boilerplate(tmp_path):
    p = tmp_path / "page.html"
    p.write_text(
        """
        <html><head>
          <title>设备手册页</title>
          <style>.x { color: red; }</style>
          <script>var secret_token = "不应进入正文的脚本内容";</script>
        </head><body>
          <nav>导航首页 产品 关于</nav>
          <header>站点页眉文字</header>
          <h1>第一章 安装指南</h1>
          <p>安装前请确认环境温度在零上四十摄氏度以内，并保持通风。</p>
          <h2>1.1 接线说明</h2>
          <ul><li>端子 A 接电源正极</li><li>端子 B 接信号地</li></ul>
          <footer>版权所有翻印必究</footer>
        </body></html>
        """,
        encoding="utf-8",
    )

    docs = HtmlLoader().load(_info(p), {"source": "page.html", "doc_format": "html"})

    assert docs, "正文非空的 HTML 必须产出文档"
    joined = "\n".join(d.page_content for d in docs)
    assert "安装前请确认环境温度" in joined
    assert "端子 A 接电源正极" in joined
    # script/style/nav/header/footer 的噪声文本不得进入正文
    assert "secret_token" not in joined
    assert "导航首页" not in joined
    assert "站点页眉文字" not in joined
    assert "版权所有翻印必究" not in joined
    # 章节元数据齐全
    assert all(d.metadata.get("source_file") == "page.html" for d in docs)


def test_html_loader_only_boilerplate_returns_empty(tmp_path):
    # 只有脚本样式导航、没有正文，清洗后为空 → []
    p = tmp_path / "empty.html"
    p.write_text(
        "<html><head><script>alert(1)</script><style>a{}</style></head>"
        "<body><nav>菜单</nav></body></html>",
        encoding="utf-8",
    )

    assert HtmlLoader().load(_info(p), {"source": "empty.html"}) == []
