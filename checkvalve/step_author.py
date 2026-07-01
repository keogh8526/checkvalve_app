"""
Stage E — step author. The only stage that will call Claude.

Two modes:
  - client given  -> real claude-opus-4-8 vision call (STEP_SCHEMA). Wired once an
                     API key exists; raises NotImplementedError until then.
  - client=None   -> RAG mode (this demo): retrieve the validated gold pool and map
                     it onto the clip's candidate segments. On the gold clip itself
                     this reproduces the known-good guide (grounded); on other clips
                     it is an honest draft (grounded=False -> blocks sign-off, needs
                     vision to confirm the step actually occurs there).

pts (중점 관리 항목) are NEVER invented — they come from the validated pool or a human.
Numeric specs are never fabricated. Every step carries evidence frames.
"""
from __future__ import annotations

from .store import get_validated_steps, get_gold
from .config import PART_ID

STEP_SCHEMA = {  # for the real claude-opus-4-8 structured-output call
    "type": "object", "additionalProperties": False,
    "properties": {
        "badge": {"type": "string"}, "text": {"type": "string"}, "sub": {"type": "string"},
        "pts": {"type": "array", "items": {"type": "string"}},
        "insp": {"type": "integer", "enum": [1, 2, 3]},
        "cap": {"type": "string"}, "evidence_frames": {"type": "array", "items": {"type": "integer"}},
        "grounded": {"type": "boolean"},
    },
    "required": ["badge", "text", "sub", "pts", "insp", "cap", "evidence_frames", "grounded"],
}


def _mmss(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def _placeholder(stem, seg, frames, fps):
    start = seg["start_sec"]
    return {
        "badge": "미정", "text": f"[자동초안] {_mmss(start)}~ 구간 — Claude 비전 분석 대기",
        "sub": f"신호원={seg.get('source', '?')}", "pts": [], "insp": 1,
        "cap": f"[초안] {_mmss(start)}~{_mmss(seg['end_sec'])} (영상 {_mmss(start)}~)",
        "at": int(round(start)),
        "evidence": {"clip": stem, "frames": frames or [int(round(start * fps))]},
        "provenance": "stub", "grounded": False, "reviewed": False,
    }


def author_steps(stem: str, digest: dict, keyframes: dict, profile: dict, *, client=None) -> dict:
    if client is not None:  # pragma: no cover - real path wired with an API key
        raise NotImplementedError(
            "Real claude-opus-4-8 vision authoring: send keyframes (Files API) + the "
            "per-second signal summary + the retrieved pool, constrained by STEP_SCHEMA.")

    pool = get_validated_steps(PART_ID)
    gold = get_gold(PART_ID)
    is_gold_clip = bool(gold and stem == gold.get("source_clip"))
    fps = digest["fps"]
    kf = {s["id"]: s.get("frames", []) for s in keyframes.get("segments", [])}

    steps, dropped = [], 0
    segs = digest.get("candidate_segments", [])
    for i, seg in enumerate(segs):
        frames = [f["frame"] for f in kf.get(seg["id"], [])]
        if i < len(pool):
            g = pool[i]
            steps.append({
                "badge": g["badge"], "text": g["text"], "sub": g["sub"], "pts": list(g["pts"]),
                "insp": g["insp"], "cap": g["cap"], "at": int(round(seg["start_sec"])),
                "evidence": {"clip": stem, "frames": frames or [int(round(seg["start_sec"] * fps))]},
                "provenance": "rag:gold" if is_gold_clip else "rag",
                "grounded": is_gold_clip, "reviewed": False,
            })
        else:
            steps.append(_placeholder(stem, seg, frames, fps))
    if len(pool) > len(segs):
        dropped = len(pool) - len(segs)

    return {
        "steps": steps,
        "pool_size": len(pool),
        "mode": "rag",
        "is_gold_clip": is_gold_clip,
        "dropped_pool_steps": dropped,
        "gold": gold,
    }
