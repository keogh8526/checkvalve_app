"""
ML-free 전처리 확인 데이터: clip profile + digest summary + keyframes + per-keyframe body
keypoints (COCO-17, original video coords + resolution) so the ② preprocessing screen can
draw a skeleton overlay and show what was extracted. Reads JSON only — no cv2.
"""
from __future__ import annotations

import json

from .config import OUTPUT
from .paths import resolve_artifacts


def _load(p):
    """Parse a JSON file to a dict. A missing/corrupt/non-dict payload degrades to {} —
    prep() must never 500 on a partial or wrong-version artifact (single-operator UI)."""
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else {}
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


def _num(v, nd):
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return 0.0


def _primary(persons):
    return max(persons, key=lambda p: p.get("box_conf", 0)) if persons else None


def prep(stem: str) -> dict:
    prof = _load(OUTPUT / stem / "clip_profile.json")
    digest = _load(OUTPUT / stem / "digest.json")
    kfman = _load(OUTPUT / stem / "keyframes.json")
    arts = resolve_artifacts(stem)
    qc = _load(arts.get("qc"))

    # keyframe manifest — keep only well-formed frames; a truncated/partial file degrades
    # to fewer (or zero) frames instead of raising KeyError/TypeError up to the router.
    frames = []
    try:
        for seg in (kfman.get("segments") or []):
            for f in (seg.get("frames") or []) if isinstance(seg, dict) else []:
                if isinstance(f, dict) and f.get("frame") is not None and f.get("path"):
                    frames.append(f)
    except Exception:
        frames = []

    want = {f["frame"]: None for f in frames}
    resolution = qc.get("resolution") or [1920, 1080]
    body = arts.get("body")
    if body and want:
        try:
            bj = json.loads(body.read_text(encoding="utf-8"))
            resolution = bj.get("resolution", resolution)
            for fr in bj.get("frames", []):
                fi = fr.get("frame")
                if fi in want and want[fi] is None:
                    p = _primary(fr.get("persons") or [])
                    if p:
                        want[fi] = {k: [_num(v.get("x"), 1), _num(v.get("y"), 1), _num(v.get("conf"), 3)]
                                    for k, v in (p.get("keypoints") or {}).items() if isinstance(v, dict)}
        except Exception:
            pass

    kfs = [{"path": f["path"], "sec": f.get("sec"), "frame": f["frame"], "kp": want.get(f["frame"])} for f in frames]
    cov = qc.get("coverage") if isinstance(qc.get("coverage"), dict) else {}
    cm = qc.get("cross_model") if isinstance(qc.get("cross_model"), dict) else {}
    cand = digest.get("candidate_segments")
    hints = digest.get("boundary_hints_sec")
    return {
        "stem": stem,
        "profile": {"shot_type": prof.get("shot_type"), "body_trust": prof.get("body_trust"),
                    "hand_trust": prof.get("hand_trust"), "roles": prof.get("roles"),
                    "duration_sec": prof.get("duration_sec"), "fps": prof.get("fps")},
        "digest": {"signal_source": digest.get("signal_source"),
                   "n_segments": len(cand) if isinstance(cand, list) else 0,
                   "boundary_hints_sec": hints[:40] if isinstance(hints, list) else []},
        "qc": {"disagree_pct": cm.get("disagree_pct"), "no_detection_pct": cov.get("no_detection_pct"),
               "resolution": resolution},
        "resolution": resolution, "keyframes": kfs,
    }
