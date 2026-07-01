"""
sopgen — self-contained demo of the full video -> 표준 작업 지도서 pipeline (Phase 0..4).

Everything lives under this one folder. It READS pre-extracted keypoints from the
repo's results/ (produced once by extract_pose/extract_hands/qc_validate) and the
frozen template, and WRITES every generated artifact under sopgen/output/ + sop.db.
No file outside sopgen/ is modified.
"""
from pathlib import Path

PKG = Path(__file__).resolve().parent          # checkvalve/
REPO = PKG.parent                              # project root (venv/data/results live here)
DATA = REPO / "data"                           # source mp4s
RESULTS = REPO / "results"                     # pre-extracted keypoints (read-only input)
TEMPLATE = PKG / "app" / "check_valve.html"    # frozen template (re-anchored into the package)
OUTPUT = REPO / "output"                        # generated guides -> /output/<stem>/* (web-served, guarded)
DB_PATH = PKG / "sop.db"                        # SQLite catalog / RAG store (not web-served)
VENV_PY = REPO / "venv" / "Scripts" / "python.exe"   # the 3.13 ML venv the runner shells
STATIC = PKG / "app" / "static"                      # SPA asset root

PART_ID = "GMT-CV-008"                         # the check-valve part this demo covers

# Role of each clip in the doc. shot_type (keypoint trust) is auto-derived; the
# ROLE — especially which clip the deliverable plays (timeline) vs which to drop —
# is a human decision the QC numbers can't make. Edit freely.
CLIP_ROLES = {
    "KakaoTalk_20260606_171834495": {"role": ["timeline"],
        "note": "Deliverable plays this clip; keypoints dead -> vision-only + mandatory review."},
    "KakaoTalk_20260606_171639759": {"role": ["body_evidence", "hand_evidence"],
        "note": "Cleanest keypoints; early assembly only, flat single take."},
    "KakaoTalk_20260606_171942873": {"role": ["hand_evidence"],
        "note": "Top-down close-up; hands good, body dead -> finger detail + measure/press."},
    "KakaoTalk_20260606_170526928": {"role": ["timing", "body_evidence"],
        "note": "Only multi-cycle clip -> standard-time source."},
    "KakaoTalk_20260606_171535893": {"role": ["drop"],
        "note": "Person absent ~47% -> unusable."},
}


def is_timeline(stem: str) -> bool:
    """The deliverable clip (the one the guide's video plays)."""
    return "timeline" in (CLIP_ROLES.get(stem, {}).get("role", []))


assert OUTPUT.is_relative_to(REPO)   # /output/<stem>/* must resolve under REPO for the static guard
