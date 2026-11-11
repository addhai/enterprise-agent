"""语义查询改写（HyDE / 多查询）单测（离线，LLM 全部打桩）。"""

import pytest
from src.config import settings
from src.rag import semantic_rewriter as sr


class FakeResult:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, content="", raises=False):
        self._content = content
        self._raises = raises
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        if self._raises:
            raise RuntimeError("ollama busy")
        return FakeResult(self._content)


@pytest.fixture
def fake_llm(monkeypatch):
    holder = {}

    def _factory(**kwargs):
        return holder["llm"]

    monkeypatch.setattr("src.agent.cancellable_llm.make_chat_model", _factory)
    return holder


@pytest.fixture
def enable_semantic(monkeypatch):
    monkeypatch.setattr(settings, "semantic_rewrite_enabled", True)
    monkeypatch.setattr(settings, "semantic_rewrite_variants", 2)


# ---------------------------------------------------------------------------
# HyDE
# ---------------------------------------------------------------------------


def test_hyde_returns_paragraph(fake_llm, enable_semantic):
    fake_llm["llm"] = FakeLLM("设备无法开机通常与电池电量、电源键接触或主板保护有关。")

    text = sr.generate_hyde_document("开不了机怎么办")

    assert "电池" in text
    assert fake_llm["llm"].prompts[0].startswith("你是工业测温设备手册专家")


def test_hyde_failure_returns_blank(fake_llm, enable_semantic):
    fake_llm["llm"] = FakeLLM(raises=True)

    assert sr.generate_hyde_document("任意问题") == ""


# ---------------------------------------------------------------------------
# 多查询
# ---------------------------------------------------------------------------


def test_multi_query_parses_numbered_lines(fake_llm, enable_semantic):
    fake_llm["llm"] = FakeLLM("1. 设备开不了机如何处理\n2. 无法开机的排查步骤\n")

    out = sr.generate_alternative_queries("开不了机怎么办", 2)

    assert out == ["设备开不了机如何处理", "无法开机的排查步骤"]


def test_multi_query_dedups_original_and_repeats(fake_llm, enable_semantic):
    fake_llm["llm"] = FakeLLM("1. 开不了机怎么办\n2. 开机失败排查\n3. 开不了机怎么办\n")

    out = sr.generate_alternative_queries("开不了机怎么办", 3)

    assert out == ["开机失败排查"]


def test_multi_query_respects_cap(fake_llm, enable_semantic):
    fake_llm["llm"] = FakeLLM("1. 问法一\n2. 问法二\n3. 问法三\n4. 问法四\n")

    out = sr.generate_alternative_queries("原始问题", 2)

    assert len(out) == 2


def test_multi_query_failure_returns_empty(fake_llm, enable_semantic):
    fake_llm["llm"] = FakeLLM(raises=True)

    assert sr.generate_alternative_queries("问题", 2) == []


# ---------------------------------------------------------------------------
# 统一入口与开关
# ---------------------------------------------------------------------------


def test_disabled_switch_returns_empty(fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "semantic_rewrite_enabled", False)
    fake_llm["llm"] = FakeLLM("不应被调用")

    assert sr.build_semantic_expansion("问题").is_empty


def test_blank_query_returns_empty(fake_llm, enable_semantic):
    fake_llm["llm"] = FakeLLM("不应被调用")

    assert sr.build_semantic_expansion("   ").is_empty


def test_mode_hyde_only(fake_llm, enable_semantic, monkeypatch):
    monkeypatch.setattr(settings, "semantic_rewrite_mode", "hyde")
    fake_llm["llm"] = FakeLLM("假设性手册段落内容。")

    expansion = sr.build_semantic_expansion("问题")

    assert expansion.hyde_text == "假设性手册段落内容。"
    assert expansion.extra_queries == []


def test_mode_multi_query_only(fake_llm, enable_semantic, monkeypatch):
    monkeypatch.setattr(settings, "semantic_rewrite_mode", "multi_query")
    fake_llm["llm"] = FakeLLM("1. 同义问法甲\n2. 同义问法乙\n")

    expansion = sr.build_semantic_expansion("问题")

    assert expansion.hyde_text == ""
    assert len(expansion.extra_queries) == 2


def test_mode_both(fake_llm, enable_semantic, monkeypatch):
    monkeypatch.setattr(settings, "semantic_rewrite_mode", "both")
    # 同一个假件按调用次序分别响应 hyde 与 multi_query
    llm = FakeLLM("1. 同义问法甲\n2. 同义问法乙\n")
    fake_llm["llm"] = llm

    # 第一次 invoke 是 hyde，换成段落输出；第二次是多查询
    original_invoke = llm.invoke

    def _sequential(prompt):
        if "手册专家" in prompt:
            return FakeResult("HyDE 假设段落。")
        return original_invoke(prompt)

    llm.invoke = _sequential

    expansion = sr.build_semantic_expansion("问题")

    assert expansion.hyde_text == "HyDE 假设段落。"
    assert expansion.extra_queries == ["同义问法甲", "同义问法乙"]


def test_all_failures_degrade_to_empty(fake_llm, enable_semantic, monkeypatch):
    monkeypatch.setattr(settings, "semantic_rewrite_mode", "both")
    fake_llm["llm"] = FakeLLM(raises=True)

    expansion = sr.build_semantic_expansion("问题")

    assert expansion.is_empty
