"""Stage C — sample onset/peak/hold JPEG keyframes per candidate segment (cv2)."""
from __future__ import annotations

import json

import cv2

from .config import OUTPUT
from .paths import video_path


def _seconds_of_interest(rows, start_sec, end_sec):
    seg = [r for r in rows if start_sec <= r["t"] < max(end_sec, start_sec + 1)]
    if not seg:
        return [("onset", int(start_sec))]
    onset = seg[0]["t"]
    peak = max((r["speed"] if r["speed"] is not None else -1, r["t"]) for r in seg)[1]
    back = seg[len(seg) // 2:] or seg
    hold = min((r["speed"] if r["speed"] is not None else 1e9, r["t"]) for r in back)[1]
    seen, picks = set(), []
    for label, sec in (("onset", onset), ("peak", peak), ("hold", hold)):
        if sec not in seen:
            seen.add(sec); picks.append((label, sec))
    return picks


def sample(stem: str, digest: dict, max_per_seg: int = 3) -> dict:
    video = video_path(stem)
    if not video:
        raise FileNotFoundError(f"{stem}: source mp4 not found.")
    fps = digest.get("fps") or 29.97
    rows = digest.get("rows", [])
    kdir = OUTPUT / stem / "keyframes"
    kdir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"Could not open {video}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 10**9
    manifest = {"stem": stem, "fps": round(fps, 3), "segments": []}
    try:
        for seg in digest.get("candidate_segments", []):
            frames = []
            for kind, sec in _seconds_of_interest(rows, seg["start_sec"], seg["end_sec"])[:max_per_seg]:
                fi = min(int(round(sec * fps)), total - 1)
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ok, img = cap.read()
                if not ok:
                    continue
                name = f"seg{seg['id']}_{kind}_{fi:06d}.jpg"
                cv2.imwrite(str(kdir / name), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
                frames.append({"kind": kind, "sec": int(sec), "frame": fi, "path": f"keyframes/{name}"})
            manifest["segments"].append({"id": seg["id"], "start_sec": seg["start_sec"],
                                         "end_sec": seg["end_sec"], "frames": frames})
    finally:
        cap.release()
    (OUTPUT / stem / "keyframes.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    return manifest
