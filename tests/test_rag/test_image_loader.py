"""ImageLoader 三级降级链单元测试

阶段 2 开门周补齐：CI 口径 image_loader.py 行覆盖率仅 18%。
真实 Vision/OCR 引擎依赖外部模型与 paddle/tesseract（requirements 中已注释），
因此全部通过构造函数注入 Fake 引擎，离线确定性地覆盖：
A 视觉成功 / B 视觉失败降级主 OCR / C 主 OCR 无效降级备用 OCR / 全失败 / 熔断器。
"""

import pytest
from src.rag.data_sources import FileInfo
from src.rag.loaders.image_loader import ImageLoader
from src.rag.vision_engines.base import (
    BaseOCREngine,
    BaseVisionEngine,
    VisionResult,
)


class FakeVision(BaseVisionEngine):
    def __init__(
        self, result=None, raise_exc: Exception | None = None, engine_name="fake-vision"
    ):
        self._result = result
        self._raise = raise_exc
        self._name = engine_name
        self.calls = 0

    @property
    def name(self):
        return self._name

    def understand(self, image_path, image_type, prompt=None):
        self.calls += 1
        if self._raise:
            raise self._raise
        return self._result


class FakeOCR(BaseOCREngine):
    def __init__(self, text=None, engine_name="fake-ocr"):
        self._text = text
        self._name = engine_name
        self.calls = 0

    @property
    def name(self):
        return self._name

    def recognize(self, image_path):
        self.calls += 1
        return self._text


def _info(tmp_path, name="device_photo.png"):
    p = tmp_path / name
    # 只需要路径存在可 stat；Fake 引擎不会真正解码图片
    p.write_bytes(b"\x89PNG\r\n\x1a\n-fake-bytes-")
    return FileInfo(path=p, name=name, ext=".png", size=p.stat().st_size)


def _vision_result(content="设备面板截图，显示屏读数正常，无报警指示灯。"):
    return VisionResult(
        content=content,
        confidence=0.92,
        model="fake-vl",
        extraction_method="vision",
    )


def test_path_a_vision_success_returns_vision_doc(tmp_path):
    vision = FakeVision(_vision_result())
    loader = ImageLoader(
        vision_engine=vision, ocr_engine=FakeOCR(None), fallback_ocr=FakeOCR(None)
    )

    docs = loader.load(_info(tmp_path), {"source": "device_photo.png"})

    assert len(docs) == 1
    assert "面板截图" in docs[0].page_content
    assert docs[0].metadata["extraction_method"] == "vision"
    assert docs[0].metadata["confidence"] == pytest.approx(0.92)
    assert vision.calls == 1


def test_path_b_vision_none_falls_back_to_primary_ocr(tmp_path):
    ocr = FakeOCR("这是 OCR 提取出的足够长的面板文字内容片段")
    loader = ImageLoader(
        vision_engine=FakeVision(None), ocr_engine=ocr, fallback_ocr=FakeOCR(None)
    )

    docs = loader.load(_info(tmp_path), {"source": "device_photo.png"})

    assert len(docs) == 1
    assert "OCR 提取" in docs[0].page_content
    # vision 无结果时 OCR 是唯一来源，带降级告警与低置信度
    assert docs[0].metadata["confidence"] == pytest.approx(0.3)
    assert docs[0].metadata["extraction_method"] == "fake-ocr"
    assert ocr.calls == 1


def test_vision_exception_is_swallowed_and_ocr_used(tmp_path):
    # 视觉引擎抛异常由 _call_vision_engine 吞掉，链路继续走 OCR 而不是整体失败
    vision = FakeVision(raise_exc=RuntimeError("model backend down"))
    ocr = FakeOCR("视觉异常场景下由 OCR 提供的足够长的备用文字内容")
    loader = ImageLoader(
        vision_engine=vision, ocr_engine=ocr, fallback_ocr=FakeOCR(None)
    )

    docs = loader.load(_info(tmp_path), {"source": "device_photo.png"})

    assert len(docs) == 1
    assert "备用文字" in docs[0].page_content
    assert vision.calls == 1
    assert ocr.calls == 1


def test_path_c_short_primary_ocr_falls_back_to_secondary(tmp_path):
    # 主 OCR 只给 10 字以内的碎片，视为无效，转备用 OCR
    primary = FakeOCR("短", engine_name="primary-ocr")
    fallback = FakeOCR(
        "备用 OCR 引擎识别出的足够长的有效文本内容", engine_name="backup-ocr"
    )
    loader = ImageLoader(
        vision_engine=FakeVision(None), ocr_engine=primary, fallback_ocr=fallback
    )

    docs = loader.load(_info(tmp_path), {"source": "scan.png"})

    assert len(docs) == 1
    assert "备用 OCR" in docs[0].page_content
    assert docs[0].metadata["confidence"] == pytest.approx(0.25)
    assert docs[0].metadata["extraction_method"] == "backup-ocr"
    assert fallback.calls == 1


def test_all_engines_fail_returns_empty(tmp_path):
    loader = ImageLoader(
        vision_engine=FakeVision(None),
        ocr_engine=FakeOCR(None),
        fallback_ocr=None,
    )

    assert loader.load(_info(tmp_path), {"source": "device_photo.png"}) == []


def test_circuit_breaker_blocks_vision_after_threshold(tmp_path):
    # threshold=1：第一次视觉失败即熔断；同实例第二次 load 不应再调视觉
    vision = FakeVision(None)
    ocr = FakeOCR("熔断后由 OCR 直接提供的足够长的文字内容")
    loader = ImageLoader(
        vision_engine=vision,
        ocr_engine=ocr,
        fallback_ocr=None,
        circuit_threshold=1,
        circuit_reset_seconds=300,
    )
    meta = {"source": "device_photo.png"}

    first = loader.load(_info(tmp_path, "a.png"), meta)
    assert first and vision.calls == 1
    assert loader.circuit_breaker.is_open()

    second = loader.load(_info(tmp_path, "b.png"), meta)
    assert second, "熔断后 OCR 仍应正常产出"
    assert vision.calls == 1, "熔断打开期间不得再次调用视觉引擎"
    assert ocr.calls == 2


def test_maybe_resize_passthrough_for_small_image(tmp_path):
    loader = ImageLoader(
        vision_engine=FakeVision(None),
        ocr_engine=FakeOCR(None),
        fallback_ocr=None,
    )
    p = _info(tmp_path).path

    returned, need_cleanup = loader._maybe_resize_image(str(p))

    # 假字节无法被 PIL 打开，异常被吞，安全返回原路径且不需要清理
    assert returned == str(p)
    assert need_cleanup is False


def test_maybe_resize_shrinks_oversized_image(tmp_path):
    pytest.importorskip("PIL", reason="环境未安装 Pillow")
    from PIL import Image

    p = tmp_path / "big.png"
    Image.new("RGB", (2000, 1000), color=(120, 120, 120)).save(p)
    loader = ImageLoader(
        vision_engine=FakeVision(None),
        ocr_engine=FakeOCR("大尺寸图片缩放后 OCR 识别出的足够长文本内容"),
        fallback_ocr=None,
        ocr_max_image_size=1024,
    )

    resized, need_cleanup = loader._maybe_resize_image(str(p))

    assert need_cleanup is True
    assert resized != str(p)
    with Image.open(resized) as im:
        assert max(im.size) <= 1024

    docs = loader.load(
        FileInfo(path=p, name="big.png", ext=".png", size=p.stat().st_size),
        {"source": "big.png"},
    )
    assert docs and "缩放后 OCR" in docs[0].page_content


# ---------------------------------------------------------------------------
# 自动实例化工厂（不注入引擎时从 settings + 注册表创建）
# ---------------------------------------------------------------------------


def _loader_without_factories_called():
    # 三个引擎全注入，构造过程不碰工厂，再手动调用工厂方法做分支测试
    return ImageLoader(
        vision_engine=FakeVision(None),
        ocr_engine=FakeOCR(None),
        fallback_ocr=FakeOCR(None),
    )


def test_auto_create_vision_registry_hit_and_unknown(monkeypatch):
    from src.config import settings
    from src.rag.vision_engines import VisionEngineRegistry

    loader = _loader_without_factories_called()

    # 注册表命中：直接返回注册的引擎类实例
    monkeypatch.setitem(VisionEngineRegistry._vision_engines, "fake-v", FakeVision)
    monkeypatch.setattr(settings, "vision_engine_name", "fake-v", raising=False)
    engine = loader._auto_create_vision_engine()
    assert isinstance(engine, FakeVision)

    # 名称既不在注册表也不匹配内置 qwen/openai：安全返回 None
    monkeypatch.setattr(
        settings, "vision_engine_name", "totally-unknown", raising=False
    )
    assert loader._auto_create_vision_engine() is None


def test_auto_create_primary_ocr_registry_hit_and_unknown(monkeypatch):
    from src.config import settings
    from src.rag.vision_engines import VisionEngineRegistry

    loader = _loader_without_factories_called()

    monkeypatch.setitem(VisionEngineRegistry._ocr_engines, "fake-ocr-engine", FakeOCR)
    monkeypatch.setattr(settings, "ocr_engine_name", "fake-ocr-engine", raising=False)
    engine = loader._auto_create_primary_ocr()
    assert isinstance(engine, FakeOCR)

    monkeypatch.setattr(settings, "ocr_engine_name", "totally-unknown", raising=False)
    assert loader._auto_create_primary_ocr() is None


def test_auto_create_fallback_none_when_same_as_primary(monkeypatch):
    # 备用 OCR 与主 OCR 同名时不重复实例化，返回 None
    from src.config import settings

    loader = _loader_without_factories_called()
    monkeypatch.setattr(settings, "ocr_engine_name", "paddle", raising=False)
    monkeypatch.setattr(settings, "fallback_ocr_name", "paddle", raising=False)

    assert loader._auto_create_fallback_ocr() is None


def test_vision_engine_modules_are_importable():
    # 回归：四个引擎模块的注册装饰器曾写错（未导入的名字 / 错误函数名），
    # 模块一导入就 NameError，导致自动工厂的内置分支永远不可达。
    import importlib

    for mod in (
        "src.rag.vision_engines.tesseract_ocr_engine",
        "src.rag.vision_engines.paddle_ocr_engine",
        "src.rag.vision_engines.openai_vision_engine",
        "src.rag.vision_engines.qwen_vision_engine",
    ):
        importlib.import_module(mod)
