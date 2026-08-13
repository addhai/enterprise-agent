"""tests for src.websocket.multimodal

覆盖图片/音频保存、视觉引擎理解、语音转录、多模态拼接，以及各类异常分支。
全部使用 fake 引擎 / fake openai 客户端，不触网。
"""
import sys

import pytest

import src.websocket.multimodal as mm


# ---------------------------------------------------------------------------
# Fake 视觉引擎
# ---------------------------------------------------------------------------
class FakeVisionResult:
    def __init__(self, content):
        self.content = content


class FakeVisionEngine:
    def __init__(self, content="一只猫"):
        self._content = content

    def understand(self, image_path, mode):
        return FakeVisionResult(self._content)


class BoomVisionEngine:
    def understand(self, image_path, mode):
        raise RuntimeError("vision boom")


# ---------------------------------------------------------------------------
# Fake openai 客户端
# ---------------------------------------------------------------------------
class FakeTranscription:
    def __init__(self, text):
        self.text = text


class FakeTranscriptions:
    def create(self, **kwargs):
        return FakeTranscription("你好世界")


class FakeAudio:
    def __init__(self):
        self.transcriptions = FakeTranscriptions()


class FakeOpenAIClient:
    def __init__(self, **kwargs):
        self.audio = FakeAudio()


# ---------------------------------------------------------------------------
# _save_base64_* 正常 / 异常
# ---------------------------------------------------------------------------
def test_save_base64_image_ok():
    data = "data:image/png;base64," + "A" * 100
    path = mm._save_base64_image(data)
    assert path and path.endswith(".png")
    import os

    assert os.path.exists(path)
    os.unlink(path)


def test_save_base64_image_without_prefix():
    # 无 data: 前缀，直接 b64
    import base64, os

    raw = base64.b64encode(b"hello").decode()
    path = mm._save_base64_image(raw, suffix=".bin")
    assert path
    assert os.path.exists(path)
    os.unlink(path)


def test_save_base64_image_decode_error(monkeypatch):
    import base64

    def _boom(*a, **k):
        raise base64.binascii.Error("bad")

    monkeypatch.setattr(base64, "b64decode", _boom)
    assert mm._save_base64_image("not-valid") is None


def test_save_base64_audio_ok():
    import os

    data = "data:audio/webm;base64," + "B" * 100
    path = mm._save_base64_audio(data)
    assert path and path.endswith(".webm")
    assert os.path.exists(path)
    os.unlink(path)


def test_save_base64_audio_decode_error(monkeypatch):
    import base64

    def _boom(*a, **k):
        raise base64.binascii.Error("bad")

    monkeypatch.setattr(base64, "b64decode", _boom)
    assert mm._save_base64_audio("not-valid") is None


def test_clean_temp_files_runs():
    # 不应抛异常
    mm._clean_temp_files()


# ---------------------------------------------------------------------------
# process_image
# ---------------------------------------------------------------------------
def test_process_image_empty():
    assert mm.process_image("") == ""


def test_process_image_save_failed(monkeypatch):
    monkeypatch.setattr(mm, "_save_base64_image", lambda x: None)
    assert mm.process_image("abc") == "[图片上传失败]"


def test_process_image_happy(monkeypatch):
    eng = FakeVisionEngine("一只猫在睡觉")
    fake_mod = type(sys)("src.rag.vision_engines.qwen_vision_engine")
    fake_mod.QwenVisionEngine = lambda: eng
    monkeypatch.setitem(sys.modules, "src.rag.vision_engines.qwen_vision_engine", fake_mod)
    res = mm.process_image("data:image/png;base64,AAAA")
    assert isinstance(res, dict)
    assert "一只猫在睡觉" in res["display"]
    assert "一只猫在睡觉" in res["agent_input"]


def test_process_image_empty_content(monkeypatch):
    eng = FakeVisionEngine("")
    fake_mod = type(sys)("src.rag.vision_engines.qwen_vision_engine")
    fake_mod.QwenVisionEngine = lambda: eng
    monkeypatch.setitem(sys.modules, "src.rag.vision_engines.qwen_vision_engine", fake_mod)
    res = mm.process_image("data:image/png;base64,AAAA")
    # 无内容 -> 回退 dict
    assert res["agent_input"] == "[图片消息]"


def test_process_image_engine_exception(monkeypatch):
    fake_mod = type(sys)("src.rag.vision_engines.qwen_vision_engine")
    fake_mod.QwenVisionEngine = BoomVisionEngine
    monkeypatch.setitem(sys.modules, "src.rag.vision_engines.qwen_vision_engine", fake_mod)
    res = mm.process_image("data:image/png;base64,AAAA")
    assert res["agent_input"] == "[图片消息]"


def test_process_image_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "src.rag.vision_engines.qwen_vision_engine", None)
    res = mm.process_image("data:image/png;base64,AAAA")
    assert res["agent_input"] == "[图片消息]"


# ---------------------------------------------------------------------------
# process_audio
# ---------------------------------------------------------------------------
def test_process_audio_empty():
    assert mm.process_audio("") == ""


def test_process_audio_save_failed(monkeypatch):
    monkeypatch.setattr(mm, "_save_base64_audio", lambda x, **k: None)
    assert mm.process_audio("abc") == ""


def test_process_audio_no_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    import openai

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAIClient)
    # 无 key -> 直接返回空
    assert mm.process_audio("data:audio/webm;base64,BBBB") == ""


def test_process_audio_happy(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    import openai

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAIClient)
    res = mm.process_audio("data:audio/webm;base64,BBBB")
    assert "你好世界" in res


def test_process_audio_transcribe_exception(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class BoomClient:
        def __init__(self, **k):
            pass

        @property
        def audio(self):
            raise RuntimeError("boom")

    import openai

    monkeypatch.setattr(openai, "OpenAI", BoomClient)
    assert mm.process_audio("data:audio/webm;base64,BBBB") == ""


def test_process_audio_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)
    assert mm.process_audio("data:audio/webm;base64,BBBB") == ""


# ---------------------------------------------------------------------------
# process_multimodal_message
# ---------------------------------------------------------------------------
def test_multimodal_only_text():
    d, a = mm.process_multimodal_message("你好")
    assert d == "你好"
    assert a == "你好"


def test_multimodal_empty():
    d, a = mm.process_multimodal_message("")
    assert d == ""
    assert a == ""


def test_multimodal_only_image(monkeypatch):
    eng = FakeVisionEngine("一张发票")
    fake_mod = type(sys)("src.rag.vision_engines.qwen_vision_engine")
    fake_mod.QwenVisionEngine = lambda: eng
    monkeypatch.setitem(sys.modules, "src.rag.vision_engines.qwen_vision_engine", fake_mod)
    d, a = mm.process_multimodal_message("", image_base64="data:image/png;base64,AAAA")
    assert "一张发票" in d
    assert "一张发票" in a


def test_multimodal_only_audio(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    import openai

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAIClient)
    d, a = mm.process_multimodal_message("", audio_base64="data:audio/webm;base64,BBBB")
    assert "你好世界" in d
    assert "你好世界" in a


def test_multimodal_text_and_image(monkeypatch):
    eng = FakeVisionEngine("一张发票")
    fake_mod = type(sys)("src.rag.vision_engines.qwen_vision_engine")
    fake_mod.QwenVisionEngine = lambda: eng
    monkeypatch.setitem(sys.modules, "src.rag.vision_engines.qwen_vision_engine", fake_mod)
    d, a = mm.process_multimodal_message("帮我看下", image_base64="data:image/png;base64,AAAA")
    assert "帮我看下" in d and "一张发票" in d
    assert "帮我看下" in a and "一张发票" in a


def test_multimodal_image_save_failed(monkeypatch):
    # 图片保存失败 -> 返回字符串 "[图片上传失败]"，走非 dict 分支
    monkeypatch.setattr(mm, "_save_base64_image", lambda x, **k: None)
    d, a = mm.process_multimodal_message("文本", image_base64="x")
    assert "[图片上传失败]" in d
    assert "[图片上传失败]" in a
    assert "文本" in d
