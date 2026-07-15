import io, os
from datetime import date
from PIL import Image
from app.tools import image_gen
from app.agents.graph import graph


def _png():
    b = io.BytesIO(); Image.new("RGB", (600, 400), (120, 150, 200)).save(b, "PNG"); return b.getvalue()


def test_pipeline_with_image(monkeypatch, tmp_path):
    monkeypatch.setattr(image_gen, "_call_gemini", lambda p: _png())
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("FINBRIEF_IMAGE_STUB", raising=False)
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    monkeypatch.setenv("FINBRIEF_OUT", str(tmp_path))
    monkeypatch.setenv("FINBRIEF_IMG_OUT", str(tmp_path))   # 실제 out_llm 안 건드리게
    final = graph.invoke({"run_id": "t", "run_date": "2026-07-09",
                          "status": "queued", "cards": [], "deliveries": [], "errors": []})
    assert final["status"] == "completed"
    assert all(c["image_url"] and os.path.exists(c["image_url"]) for c in final["cards"])
