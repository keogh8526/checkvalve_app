"""Artifact + video path resolution (reads the repo's pre-extracted keypoints)."""
from pathlib import Path

from .config import RESULTS, DATA, REPO


def resolve_artifacts(stem: str) -> dict:
    """{'body','hands','qc': Path|None}. results/<stem>/ first, then the repo-root
    legacy names used only by clip #1 (170526928)."""
    rd = RESULTS / stem
    cands = {
        "body": [rd / "body_yolo.json", REPO / f"{stem}_keypoints.json"],
        "hands": [rd / "hands_mediapipe.json", REPO / f"{stem}_hands.json"],
        "qc": [rd / "qc.json", REPO / f"{stem}_qc.json"],
    }
    return {k: next((p for p in ps if p.exists()), None) for k, ps in cands.items()}


def video_path(stem: str) -> Path | None:
    for p in (DATA / f"{stem}.mp4", REPO / f"{stem}.mp4"):
        if p.exists():
            return p
    return None


def list_stems() -> list[str]:
    return sorted(p.stem for p in DATA.glob("*.mp4")) if DATA.exists() else []
