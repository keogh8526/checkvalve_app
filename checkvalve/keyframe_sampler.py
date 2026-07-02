"""Stage C — sample JPEG keyframes per candidate segment (cv2), resized for vision.

When a motion signal exists (rows), pick onset/peak/hold by wrist speed; for no-signal
clips (no_keypoints — e.g. the timeline deliverable) pick start/mid/end by TIME so the
frames still cover the clip evenly. Frames are downscaled + capped and fed to the Claude
vision author as the visual content signal.
"""
from __future__ import annotations

import json

import cv2

from .config import OUTPUT
from .paths import video_path

MAX_FRAMES = 36     # global budget per clip (vision token control)
LONG_EDGE = 1024    # downscale long edge


def _picks_time(start_sec, end_sec):
    a, b = float(start_sec), float(max(end_sec, start_sec + 1))
    picks = [("start", a + 0.5 if b - a > 1.5 else a), ("mid", (a + b) / 2), ("end", max(a, b - 0.5))]
    out, seen = [], set()
    for label, sec in picks:
        s = int(round(sec))
        if s not in seen:
            seen.add(s)
            out.append((label, s))
    return out


def _picks_signal(rows, start_sec, end_sec):
    seg = [r for r in rows if start_sec <= r["t"] < max(end_sec, start_sec + 1)]
    if not seg:
        return _picks_time(start_sec, end_sec)
    onset = seg[0]["t"]
    peak = max((r["speed"] if r["speed"] is not None else -1, r["t"]) for r in seg)[1]
    back = seg[len(seg) // 2:] or seg
    hold = min((r["speed"] if r["speed"] is not None else 1e9, r["t"]) for r in back)[1]
    out, seen = [], set()
    for label, sec in (("onset", onset), ("peak", peak), ("hold", hold)):
        if sec not in seen:
            seen.add(sec)
            out.append((label, sec))
    return out


def _resize(img):
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= LONG_EDGE:
        return img
    s = LONG_EDGE / m
    return cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)


def sample(stem: str, digest: dict, max_per_seg: int = 3) -> dict:
    video = video_path(stem)
    if not video:
        raise FileNotFoundError(f"{stem}: source mp4 not found.")
    fps = digest.get("fps") or 29.97
    rows = digest.get("rows", [])
    segs = digest.get("candidate_segments", [])
    per_seg = max_per_seg if len(segs) <= 12 else 2 if len(segs) <= 18 else 1
    kdir = OUTPUT / stem / "keyframes"
    kdir.mkdir(parents=True, exist_ok=True)
    for old in kdir.glob("*.jpg"):        # drop stale frames from a prior run
        old.unlink()

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {video}")   # Exception (not SystemExit) so run_job logs it
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 10**9
    manifest = {"stem": stem, "fps": round(fps, 3), "segments": []}
    written = 0
    try:
        for seg in segs:
            picks = (_picks_signal(rows, seg["start_sec"], seg["end_sec"]) if rows
                     else _picks_time(seg["start_sec"], seg["end_sec"]))[:per_seg]
            frames = []
            for kind, sec in picks:
                if written >= MAX_FRAMES:
                    break
                fi = min(int(round(sec * fps)), total - 1)
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ok, img = cap.read()
                if not ok:
                    continue
                name = f"seg{seg['id']}_{kind}_{fi:06d}.jpg"
                cv2.imwrite(str(kdir / name), _resize(img), [cv2.IMWRITE_JPEG_QUALITY, 82])
                frames.append({"kind": kind, "sec": int(sec), "frame": fi, "path": f"keyframes/{name}"})
                written += 1
            manifest["segments"].append({"id": seg["id"], "start_sec": seg["start_sec"],
                                         "end_sec": seg["end_sec"], "frames": frames})
    finally:
        cap.release()
    (OUTPUT / stem / "keyframes.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    return manifest
