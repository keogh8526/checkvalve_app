"""
ML-free library index over generated instructions (OUTPUT/<stem>/steps_bundle.json).
Powers the Home screen: lists every generated work-instruction with a name, status
(draft / review / approved), step + review counts, updated time, signer, and a thumbnail
(first keyframe). Names live in the bundle meta; the name write is guarded + locked.
"""
from __future__ import annotations

import json

from .config import OUTPUT, PART_ID
from . import pipeline


def _one(bp):
    stem = bp.parent.name
    try:
        b = json.loads(bp.read_text(encoding="utf-8"))
        r = b.get("review", {}) or {}
        meta = b.get("meta", {}) or {}
        steps = b.get("STEPS", []) or []
        rs = pipeline._load_rs(stem)
        reviewed = sum(1 for s in steps if rs.get(str(s.get("no")), {}).get("reviewed"))
        status = "approved" if r.get("approved") else ("review" if reviewed else "draft")
        kdir = OUTPUT / stem / "keyframes"
        kfs = sorted(kdir.glob("*.jpg")) if kdir.is_dir() else []
    except Exception:
        return None                      # a bad row is skipped, never crashes the whole list
    return {
        "stem": stem,
        "name": (meta.get("name") or f"{meta.get('품명', '작업지도서')} · {stem[-9:]}"),
        "part": meta.get("도번", PART_ID),
        "n_steps": len(steps), "reviewed": reviewed, "status": status,
        "signer": r.get("signed_by"), "updated": int(bp.stat().st_mtime),
        "thumb": (f"keyframes/{kfs[0].name}" if kfs else None),
    }


def list_instructions() -> list[dict]:
    if not OUTPUT.exists():
        return []
    out = [i for i in (_one(bp) for bp in OUTPUT.glob("*/steps_bundle.json")) if i]
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def set_name(stem: str, name: str) -> dict:
    name = str(name or "").strip()[:80]
    with pipeline._stem_lock(stem):
        bp = OUTPUT / stem / "steps_bundle.json"
        b = json.loads(bp.read_text(encoding="utf-8"))
        b.setdefault("meta", {})["name"] = name
        pipeline._atomic_json(bp, b)
    return {"ok": True, "name": name}
