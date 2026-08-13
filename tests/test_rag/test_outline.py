"""tests for src.rag.outline

覆盖 OutlineNode / OutlineTree 的构建、扁平化、路径查找、章节拆分，
以及标题提取工具（Markdown / PDF 正文）。
"""
from src.rag.outline import (
    OutlineNode,
    OutlineTree,
    extract_docx_headings,
    extract_html_headings,
    extract_markdown_headings,
    extract_pdf_body_headings,
    extract_pdf_bookmarks,
)


def test_outline_node_to_dict():
    root = OutlineNode(text="Root", level=1)
    child = OutlineNode(text="Child", level=2, page=3)
    root.add_child(child)
    d = root.to_dict()
    assert d["text"] == "Root"
    assert d["level"] == 1
    assert d["page"] is None
    assert len(d["children"]) == 1
    assert d["children"][0]["page"] == 3


def test_outline_node_from_dict():
    data = {
        "text": "Root",
        "level": 1,
        "page": None,
        "children": [{"text": "C", "level": 2, "page": 5, "children": []}],
    }
    node = OutlineNode.from_dict(data)
    assert node.text == "Root"
    assert node.children[0].text == "C"
    assert node.children[0].page == 5


def test_build_empty():
    t = OutlineTree()
    t.build([])
    assert t.root is None


def test_build_single():
    t = OutlineTree()
    t.build([(1, "Title", None)])
    assert t.root.text == "Title"
    assert t.root.level == 1
    assert t.root.children == []


def test_build_nested():
    t = OutlineTree()
    t.build([
        (1, "A", None),
        (2, "A.1", None),
        (2, "A.2", None),
        (1, "B", None),
    ])
    # 第二个 H1 会被算法归到根节点 A 之下（弹出同级直到 level<1）
    assert [c.text for c in t.root.children] == ["A.1", "A.2", "B"]
    assert t.root.children[0].children == []


def test_flatten():
    t = OutlineTree()
    t.build([(1, "A", None), (2, "A.1", None), (1, "B", None)])
    flat = t.flatten()
    paths = [p for p, _, _ in flat]
    assert "A" in paths
    assert "A / A.1" in paths
    assert "A / B" in paths


def test_flatten_empty():
    assert OutlineTree().flatten() == []


def test_get_chapter_path_found():
    t = OutlineTree()
    t.build([(1, "A", None), (2, "A.1", None)])
    assert t.get_chapter_path(2, "A.1") == "A / A.1"


def test_get_chapter_path_not_found():
    t = OutlineTree()
    t.build([(1, "A", None)])
    assert t.get_chapter_path(2, "missing") == ""


def test_split_no_root():
    t = OutlineTree()
    docs = t.split("hello world", {"tenant_id": "t1"}, source_file="x.md")
    assert len(docs) == 1
    assert docs[0].page_content == "hello world"
    assert docs[0].metadata["source_file"] == "x.md"


def test_split_root_no_heading_match():
    t = OutlineTree()
    t.build([(1, "A", None)])
    docs = t.split("some text without markdown headings", {"k": "v"})
    assert len(docs) == 1


def test_split_into_chapters():
    t = OutlineTree()
    t.build([(1, "Intro", None), (1, "Body", None)])
    text = "# Intro\nwelcome here\n\n# Body\nmain content"
    docs = t.split(text, {}, source_file="doc.md")
    assert len(docs) == 2
    # 内容按章节截断
    assert "welcome here" in docs[0].page_content
    assert "main content" in docs[1].page_content
    assert docs[0].metadata["chapter_path"] == "Intro"
    assert docs[0].metadata["heading_level"] == 1


def test_split_empty_chapter_skipped():
    t = OutlineTree()
    t.build([(1, "Empty", None), (1, "Filled", None)])
    text = "# Empty\n\n# Filled\nhas content"
    docs = t.split(text, {})
    assert len(docs) == 1
    assert docs[0].metadata["heading_text"] == "Filled"


def test_split_no_chapter_path_fallback():
    # 文本中的标题文本与 outline 中不一致 -> 用 heading_text 兜底
    t = OutlineTree()
    t.build([(1, "Different", None)])
    text = "# Actual\ncontent"
    docs = t.split(text, {})
    assert len(docs) == 1
    assert docs[0].metadata["chapter_path"] == "Actual"


def test_split_with_outline_json():
    t = OutlineTree()
    t.build([(1, "A", None)])
    text = "# A\ncontent"
    docs = t.split(text, {}, store_outline_json=True)
    assert "outline" in docs[0].metadata
    # JSON 可解析
    import json
    json.loads(docs[0].metadata["outline"])


def test_split_without_outline_json():
    t = OutlineTree()
    t.build([(1, "A", None)])
    text = "# A\ncontent"
    docs = t.split(text, {}, store_outline_json=False)
    assert "outline" not in docs[0].metadata


def test_extract_markdown_headings():
    text = "# Title\n\n## Sub\n\n### Deep\n\nbody"
    heads = extract_markdown_headings(text)
    assert heads[0] == (1, "Title", None)
    assert heads[1] == (2, "Sub", None)
    assert heads[2] == (3, "Deep", None)


def test_extract_pdf_body_headings_markdown():
    text = "# One\n\n## Two\nbody"
    heads = extract_pdf_body_headings(text)
    assert (1, "One", None) in heads
    assert (2, "Two", None) in heads


def test_extract_pdf_body_headings_chinese():
    # 注：正则要求行以数字开头（如「一章」而非「第一章」）
    text = "一章 概述\n\n二节 细节\nmore"
    heads = extract_pdf_body_headings(text)
    texts = [h[1] for h in heads]
    assert any("概述" in t for t in texts)
    assert any("细节" in t for t in texts)


def test_extract_pdf_body_headings_numeric():
    text = "1. First\n\n2.1. Sub\n\n3. Second"
    heads = extract_pdf_body_headings(text)
    assert (1, "First", None) in heads
    assert (2, "Sub", None) in heads  # 2.1. -> level 2
    assert (1, "Second", None) in heads


class _FakeTag:
    def __init__(self, text):
        self._t = text

    def get_text(self, strip=False):
        return self._t


class _FakeSoup:
    def find_all(self, name):
        if name == "h1":
            return [_FakeTag("标题一")]
        if name == "h2":
            return [_FakeTag("子标题")]
        if name == "h3":
            return [_FakeTag("三级")]
        return []


def test_extract_html_headings():
    heads = extract_html_headings(_FakeSoup())
    assert (1, "标题一", None) in heads
    assert (2, "子标题", None) in heads
    assert (3, "三级", None) in heads


class _FakePara:
    def __init__(self, style, text):
        self.style = type("S", (), {"name": style})()
        self.text = text


def test_extract_docx_headings():
    paras = [
        _FakePara("Heading 1", "第一章"),
        _FakePara("Normal", "正文"),
        _FakePara("Heading 2", "第二节"),
        _FakePara("List Bullet", "列表"),
    ]
    heads = extract_docx_headings(paras)
    assert (1, "第一章", None) in heads
    assert (2, "第二节", None) in heads
    # 非 Heading 样式被忽略
    assert all("正文" != h[1] and "列表" != h[1] for h in heads)


class _FakeDoc:
    def get_toc(self):
        return [(1, "Intro", 1), (2, "Sub", 3), (3, "Deep", 5)]


def test_extract_pdf_bookmarks():
    heads = extract_pdf_bookmarks(_FakeDoc())
    assert (1, "Intro", 1) in heads
    assert (2, "Sub", 3) in heads
    assert (3, "Deep", 5) in heads
    # 层级上限为 6
    assert all(1 <= h[0] <= 6 for h in heads)
