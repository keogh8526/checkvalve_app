"""Phase-0 gate: (1) the Studio import path pulls ZERO ML; (2) generate_guide
produces a real guide for the timeline clip. Run from REPO with the 3.13 venv."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TIMELINE = "KakaoTalk_20260606_171834495"


def test_studio_is_ml_free():
    for m in ("cv2", "numpy", "scipy", "torch", "ultralytics"):
        sys.modules.pop(m, None)
    import checkvalve.app.services  # noqa: F401  (drags studio's deps)
    assert "cv2" not in sys.modules, "studio path must not import cv2"
    assert "torch" not in sys.modules, "studio path must not import torch"


def test_generate_timeline_guide():
    from checkvalve import pipeline
    r = pipeline.generate_guide(TIMELINE)
    guide = REPO / "output" / TIMELINE / "guide"
    assert (guide / "index.html").is_file()
    assert (guide / "clip.mp4").is_file()
    assert (guide / "steps_data.js").is_file()
    assert r["review"]["is_gold_clip"] is True
    assert 'src="clip.mp4"' in (guide / "index.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    test_studio_is_ml_free()
    test_generate_timeline_guide()
    print("phase0 OK")
