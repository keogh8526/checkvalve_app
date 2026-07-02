"""
Preprocessing — run the repo's keypoint extraction (YOLO body -> hands -> QC) for a
clip whose artifacts don't exist yet, so a directly-uploaded video flows through the
same pipeline as the pre-extracted demo clips. Adapted from run_one.ensure_extraction.

Heavy ML runs in the shelled extract_pose.py / extract_hands.py / qc_validate.py — this
module itself imports nothing heavy and is only ever called from the run_job child.
Produces results/<stem>/{body_yolo.json, hands_mediapipe.json, qc.json}.
"""
from __future__ import annotations

import subprocess
import sys

from ..config import RESULTS, REPO
from ..paths import resolve_artifacts, video_path

PY = sys.executable   # run_job is launched by the venv python, so this IS the ML venv


def _run(cmd):
    subprocess.run(cmd, check=True, cwd=str(REPO))


def ensure_extraction(stem: str, on_progress=None) -> bool:
    """Extract only the missing artifacts. Returns True if extraction ran, False if the
    clip was already fully extracted. Raises FileNotFoundError if no source mp4 exists."""
    arts = resolve_artifacts(stem)
    if arts["qc"] and arts["body"] and arts["hands"]:
        return False                              # already fully preprocessed
    video = video_path(stem)
    if not video:
        raise FileNotFoundError(f"{stem}: 원본 mp4가 없어 전처리할 수 없습니다.")
    out = RESULTS / stem
    out.mkdir(parents=True, exist_ok=True)
    body = out / "body_yolo.json"
    hands = out / "hands_mediapipe.json"

    if not arts["body"]:
        if on_progress:
            on_progress("extract:pose", 15)
        _run([PY, str(REPO / "extract_pose.py"), "--video", str(video),
              "--out-json", str(body), "--no-video"])
        arts["body"] = body

    if not arts["hands"]:
        if on_progress:
            on_progress("extract:hands", 30)
        _run([PY, str(REPO / "extract_hands.py"), "--video", str(video),
              "--out-json", str(hands), "--no-video"])
        arts["hands"] = hands

    if not arts["qc"]:
        if on_progress:
            on_progress("extract:qc", 45)
        cmd = [PY, str(REPO / "qc_validate.py"), "--video", str(video),
               "--body-json", str(arts["body"]), "--out-dir", str(out)]
        if arts["hands"]:
            cmd += ["--hands-json", str(arts["hands"])]
        _run(cmd)
    return True
