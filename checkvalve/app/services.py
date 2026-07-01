"""ML-free helpers the Studio router calls. Imports NO cv2/numpy — pure stdlib +
pipeline edit helpers + store. Keeps the server process small and crash-isolated."""
import json
import os

from ..config import OUTPUT, PART_ID, CLIP_ROLES, is_timeline
from ..paths import list_stems
from .. import pipeline, store
from .export import build_export, ExportBlocked   # noqa: F401 (re-exported for the router)
from .preview import ensure_rendered              # noqa: F401


def api_parts():
    parts = []
    for stem in list_stems():
        role = CLIP_ROLES.get(stem, {}).get("role", [])
        sp = OUTPUT / stem / "job" / "status.json"
        last = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else None
        parts.append({"stem": stem, "shot_type": _shot(stem), "roles": role,
                      "is_timeline": is_timeline(stem), "needs_manual_role": False,
                      "role_source": "config",
                      "has_guide": (OUTPUT / stem / "guide" / "index.html").is_file(),
                      "last_job": last})
    llm = bool(os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("CHECKVALVE_LLM") == "1")
    return {"part_id": PART_ID, "llm_available": llm, "parts": parts}


def _shot(stem):
    p = OUTPUT / stem / "clip_profile.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("shot_type", "?")
        except Exception:
            pass
    return "?"


def get_bundle(stem):
    b = json.loads((OUTPUT / stem / "steps_bundle.json").read_text(encoding="utf-8"))
    rs = pipeline._load_rs(stem)
    for s in b["STEPS"]:
        s["reviewed"] = bool(rs.get(str(s["no"]), {}).get("reviewed"))
        if rs.get(str(s["no"]), {}).get("provenance"):
            s["provenance"] = rs[str(s["no"])]["provenance"]
    b["review"] = pipeline._merged_review(b, rs)
    b["is_timeline"] = is_timeline(stem)
    return b


# thin pass-throughs (router validates stem ∈ list_stems()) — held under the per-stem lock
# so concurrent PUT/review/approve for one clip don't lose each other's read-modify-write.
def edit_step(stem, no, fields):
    with pipeline._stem_lock(stem):
        return pipeline.edit_step(stem, no, fields)


def mark_reviewed(stem, no):
    with pipeline._stem_lock(stem):
        return pipeline.mark_reviewed(stem, no)


def approve(stem, signed_by):
    with pipeline._stem_lock(stem):
        return pipeline.approve(stem, signed_by)
