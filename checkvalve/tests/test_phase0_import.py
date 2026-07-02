"""Phase-0 gate: (1) the Studio import path pulls ZERO ML/heavy deps; (2) authoring is
Claude-analysis only — with no client it refuses (RAG removed). Run from REPO w/ 3.13 venv."""
import sys


def test_studio_is_ml_free():
    for m in ("cv2", "numpy", "scipy", "torch", "ultralytics", "pdfplumber"):
        sys.modules.pop(m, None)
    import checkvalve.app.services  # noqa: F401  (drags the studio router's deps)
    for banned in ("cv2", "torch", "numpy", "scipy", "pdfplumber", "anthropic"):
        assert banned not in sys.modules, f"studio path must not import {banned}"


def test_author_requires_client():
    """RAG/gold pool removed — author_steps needs a Claude client; without one it raises
    a clear ValueError (no silent RAG fallback). Cheap: never touches the ML pipeline."""
    from checkvalve.step_author import author_steps
    digest = {"fps": 30.0, "duration_sec": 60, "candidate_segments": [], "boundary_hints_sec": []}
    try:
        author_steps("KakaoTalk_20260606_171834495", digest, {"segments": []},
                     {"shot_type": "timeline", "roles": ["timeline"]}, client=None)
    except ValueError as e:
        assert "키" in str(e), f"unexpected message: {e}"
    else:
        raise AssertionError("author_steps(client=None) must raise ValueError (RAG removed)")


if __name__ == "__main__":
    test_studio_is_ml_free()
    test_author_requires_client()
    print("phase0 OK")
