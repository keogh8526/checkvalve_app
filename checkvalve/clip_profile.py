"""Stage A — clip profiler. Decides which keypoints to trust + the clip's role."""
from __future__ import annotations

import json
import re

from .config import OUTPUT, CLIP_ROLES
from .paths import resolve_artifacts

DISAGREE_BODY_DEAD = 40.0
HAND_TRUST_COV = 0.30
SPARSE_NODET = 30.0
TIMING_MIN_SEC = 300.0


def _num(m):
    return float(m.group(1)) if m else None


def hands_meta(path) -> dict:
    """fps / total_frames / both-hands count from the hands JSON head only (the
    metadata precedes the multi-MB frames array, so we never load it)."""
    if not path or not path.exists():
        return {}
    head = path.read_bytes()[:65536].decode("utf-8", "ignore")
    cut = head.find('"frames"')
    if cut == -1:
        txt = path.read_text(encoding="utf-8")
        c = txt.find('"frames"')
        head = txt[:c] if c != -1 else txt
    else:
        head = head[:cut]
    sm = re.search(r'"stats"\s*:\s*(\{[^}]*\})', head)
    stats = json.loads(sm.group(1)) if sm else {}
    return {
        "fps": _num(re.search(r'"fps"\s*:\s*([0-9.]+)', head)),
        "total_frames": _num(re.search(r'"total_frames"\s*:\s*([0-9]+)', head)),
        "both_hands_frames": stats.get("both_hands_frames"),
    }


def classify_shot(disagree_pct, no_detection_pct, hand_cov) -> str:
    if disagree_pct is None:
        return "unknown"
    if disagree_pct >= DISAGREE_BODY_DEAD:
        return "hand_closeup" if hand_cov >= HAND_TRUST_COV else "no_keypoints"
    if no_detection_pct is not None and no_detection_pct > SPARSE_NODET:
        return "sparse"
    return "body_reliable"


def suggest_role(shot_type, duration_sec, hand_trust) -> list:
    roles = []
    if shot_type == "body_reliable":
        roles.append("body_evidence")
        if duration_sec and duration_sec > TIMING_MIN_SEC:
            roles.append("timing")
    if hand_trust and shot_type in ("hand_closeup", "body_reliable"):
        roles.append("hand_evidence")
    if shot_type in ("no_keypoints", "sparse", "unknown"):
        roles.append("review")
    return roles or ["review"]


def build_profile(stem: str) -> dict:
    arts = resolve_artifacts(stem)
    if not arts["qc"]:
        raise FileNotFoundError(f"No qc.json for {stem} (run extraction first).")
    qc = json.loads(arts["qc"].read_text(encoding="utf-8"))
    hm = hands_meta(arts["hands"])

    disagree = (qc.get("cross_model") or {}).get("disagree_pct")
    cov = qc.get("coverage") or {}
    nodet = cov.get("no_detection_pct")
    total = qc.get("total_frames") or hm.get("total_frames")
    fps = hm.get("fps")
    duration = round(total / fps, 1) if (total and fps) else None
    both = hm.get("both_hands_frames")
    hand_cov = (both / total) if (both is not None and total) else 0.0

    shot = classify_shot(disagree, nodet, hand_cov)
    hand_trust = hand_cov >= HAND_TRUST_COV
    ov = CLIP_ROLES.get(stem)
    if ov:
        roles, src, note = ov["role"], "override", ov.get("note", "")
    else:
        roles, src, note = suggest_role(shot, duration, hand_trust), "auto", ""

    return {
        "stem": stem, "duration_sec": duration, "fps": round(fps, 3) if fps else None,
        "total_frames": int(total) if total else None, "resolution": qc.get("resolution"),
        "disagree_pct": disagree, "no_detection_pct": nodet,
        "hand_both_frames": int(both) if both is not None else None,
        "hand_cov": round(hand_cov, 4), "shot_type": shot,
        "body_trust": shot == "body_reliable", "hand_trust": hand_trust,
        "roles": roles, "role_source": src,
        "needs_manual_role": src == "auto" and shot in ("no_keypoints", "sparse", "unknown"),
        "note": note,
    }


def write_profile(stem: str) -> dict:
    p = build_profile(stem)
    out = OUTPUT / stem
    out.mkdir(parents=True, exist_ok=True)
    (out / "clip_profile.json").write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
