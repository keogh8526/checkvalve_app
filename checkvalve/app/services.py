"""ML-free helpers the Studio router calls. Imports NO cv2/numpy — pure stdlib +
pipeline edit helpers + store. Keeps the server process small and crash-isolated."""
import json
import os
import re
import shutil
import tempfile

from ..config import OUTPUT, DATA, RESULTS, PART_ID, CLIP_ROLES, is_timeline
from ..paths import list_stems
from .. import pipeline, settings, library, prep_view
from . import runner                                # is_generating() job-state guard (ML-free)
from ..prepare.doc_stub import doc_status          # ML-free (pdfplumber only on upload)
from .export import build_export, ExportBlocked   # noqa: F401 (re-exported for the router)
from .preview import ensure_rendered              # noqa: F401

STEM_RE = re.compile(r"[A-Za-z0-9_\-]+")          # upload filename -> safe stem


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
    return {"part_id": PART_ID, "llm_available": settings.configured(),
            "model": settings.model(), "doc": doc_status(PART_ID), "parts": parts}


def prep(stem):
    return prep_view.prep(stem)


def list_instructions():
    return {"instructions": library.list_instructions()}


def save_instruction(stem, name):
    _guard(stem)                     # refuse while generating; no _stem_lock here — set_name takes it
    return library.set_name(stem, name)


def get_settings():
    return settings.public()


def set_settings(model=None, api_key=None):
    settings.save(model=model, api_key=api_key)   # raises ValueError on a bad model
    return settings.public()


def save_upload(filename, data):
    """Save an uploaded mp4 into DATA/<stem>.mp4 so list_stems() picks it up. The stem is
    the sanitized filename; extraction runs later in the run_job child. Returns the stem."""
    stem = os.path.splitext(os.path.basename(filename or ""))[0].strip()
    if not stem or not STEM_RE.fullmatch(stem):
        raise ValueError("파일명은 영문/숫자/_/- 만 사용할 수 있습니다")
    _guard(stem)                     # refuse to overwrite a clip's source while it is generating
    DATA.mkdir(parents=True, exist_ok=True)
    dest = (DATA / f"{stem}.mp4").resolve()
    if not dest.is_relative_to(DATA.resolve()):
        raise ValueError("invalid filename")
    existed = dest.is_file()
    fd, tmpname = tempfile.mkstemp(suffix=".part", dir=str(DATA))   # unique tmp — no concurrent-upload clash
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmpname, dest)
    except Exception:
        try:
            os.unlink(tmpname)
        except OSError:
            pass
        raise
    if existed:
        # a re-upload replaced the source video under the same name: drop BOTH the stale
        # keypoints/QC (so the next run re-extracts against the NEW video instead of
        # silently reusing the previous clip's motion) AND the stale guide/bundle/review
        # (so the old video's document can't be edited/approved/exported under this stem
        # until it is regenerated). stem passed STEM_RE — these paths are safe.
        shutil.rmtree(RESULTS / stem, ignore_errors=True)
        shutil.rmtree(OUTPUT / stem, ignore_errors=True)
    return {"stem": stem, "bytes": dest.stat().st_size, "replaced": existed}


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
# ALSO guarded by is_generating(): the in-process _stem_lock cannot exclude the run_job CHILD
# process, which rewrites steps_bundle.json/review_state.json/guide while generating — so these
# trust-model writes refuse (409 Busy) while a generation for the stem is in flight.
def _guard(stem):
    if runner.is_generating(stem):
        raise runner.Busy(f"{stem}.generating")


def edit_step(stem, no, fields):
    with pipeline._stem_lock(stem):
        _guard(stem)
        return pipeline.edit_step(stem, no, fields)


def mark_reviewed(stem, no):
    with pipeline._stem_lock(stem):
        _guard(stem)
        return pipeline.mark_reviewed(stem, no)


def approve(stem, signed_by):
    with pipeline._stem_lock(stem):
        _guard(stem)
        return pipeline.approve(stem, signed_by)
