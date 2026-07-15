import io, os
from PIL import Image
from app.tools import image_gen


def _png():
    b = io.BytesIO(); Image.new("RGB", (400, 300), (120, 150, 200)).save(b, "PNG"); return b.getvalue()


def test_image_tool_mock(monkeypatch, tmp_path):
    monkeypatch.setattr(image_gen, "_call_gemini", lambda p: _png())
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("FINBRIEF_IMAGE_STUB", raising=False)
    asset = image_gen.generate_image("prompt, no text", str(tmp_path), "x")
    assert asset and os.path.exists(asset.path) and asset.model == image_gen.IMAGE_MODEL


def test_image_disabled_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert image_gen.generate_image("p", str(tmp_path), "x") is None
