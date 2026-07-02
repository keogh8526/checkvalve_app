"""
Pipeline orchestrator: one clip -> a draft 표준 작업 지도서, end to end.

  profile -> digest (keypoint-derived motion) -> keyframes
          -> author (Claude analyzes the preprocessing + process-doc PDF)
          -> standard-time -> assemble -> render -> ingest the draft (audit).

No RAG / gold pool — the Claude API is the analyst. A key is required; see step_author.
The store is kept only as an audit log of drafts, not a retrieval source.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

from .config import OUTPUT, REPO, PART_ID
from .paths import video_path, list_stems
from . import store as store
from .clip_profile import write_profile
from .step_author import author_steps
from .assembler import assemble
from .render import render
from .store import ingest_document, delete_drafts
# signal_digest/keyframe_sampler/timing pull cv2/numpy/scipy — imported LAZILY inside run()
# so the ML-free Studio process can import this module just for the edit/approve helpers.


def run(stem: str, client=None, ingest: bool = True) -> dict:
    from .signal_digest import write_digest   # lazy (ML) — only when actually generating
    from .keyframe_sampler import sample
    from .timing import estimate
    profile = write_profile(stem)
    digest = write_digest(stem)
    keyframes = sample(stem, digest)
    author_result = author_steps(stem, digest, keyframes, profile, client=client)
    timing = estimate()

    vid = video_path(stem)
    video_rel = vid.relative_to(REPO).as_posix() if vid else f"data/{stem}.mp4"   # POSIX sep (Windows-safe)
    bundle = assemble(stem, author_result, video_rel, profile, timing)
    (OUTPUT / stem / "steps_bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    # Fresh authoring invalidates any prior per-step review — clear the review_state so a
    # regenerated bundle never inherits stale "reviewed"/signed flags on freshly-written steps.
    _rs_path(stem).unlink(missing_ok=True)

    out = render(stem, bundle)

    if ingest:
        delete_drafts(PART_ID, stem)   # re-run replaces this clip's draft, not accumulates
        steps_for_store = [{**s, "provenance": s.get("provenance", "llm")} for s in bundle["STEPS"]]
        ingest_document(PART_ID, stem, "draft", bundle["meta"], steps_for_store,
                        bundle["SEQ"], bundle["SELF"], origin="pipeline")

    return {"profile": profile, "digest": digest, "author": author_result,
            "bundle": bundle, "render": out}


# ─────────────────────────── GUI-facing helpers (Phase 4) ───────────────────────────
# The Studio calls these (ML-free): generate is the FAST per-clip path; edit/review/approve
# mutate the bundle + review_state.json and re-render via the SAME render() path as preview/export.
EDITABLE = {"badge", "text", "sub", "pts", "insp", "cap"}   # label channel only (tag/at/standard_time protected)
PROTECTED = {"at", "no", "tag", "standard_time", "evidence"}

# Per-stem lock — serializes the read-modify-write-render sequences (edit/review/approve)
# and preview/export renders for one clip. Shared across services/preview/export.
_STEM_LOCKS = {}
_STEM_GUARD = threading.Lock()


def _stem_lock(stem):
    with _STEM_GUARD:
        return _STEM_LOCKS.setdefault(stem, threading.Lock())


def _now():
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(p, o):
    t = p.with_suffix(p.suffix + ".tmp")
    t.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(t, p)


def _rs_path(stem):
    return OUTPUT / stem / "review_state.json"


def _load_rs(stem):
    p = _rs_path(stem)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}   # a corrupt review_state must not crash edit/review/approve or the library


def _require_keys(b):
    for k in ("video", "review", "standard_time", "stem", "shot_type", "roles", "STEPS", "CHAPTERS", "SEQ", "SELF"):
        if k not in b:
            raise KeyError(f"bundle missing '{k}' — refusing to render")


def _merged_review(b, rs):
    r = dict(b["review"])
    r["signed_off"] = bool(b["STEPS"]) and all(rs.get(str(s["no"]), {}).get("reviewed") for s in b["STEPS"])
    return r


def generate_guide(stem, client=None, on_progress=None):
    """FAST per-clip path the /api/run job calls. Wraps run(); never prepare/fuse."""
    if stem not in list_stems():
        raise ValueError(f"unknown stem: {stem}")
    if on_progress:
        on_progress("generate", 10)
    res = run(stem, client=client, ingest=True)
    if on_progress:
        on_progress("done", 100)
    b = res["bundle"]
    return {"stem": stem, "bundle": b, "bundle_path": str(OUTPUT / stem / "steps_bundle.json"),
            "guide_url": f"/output/{stem}/guide/index.html", "review": b["review"]}


def _reingest_draft(b, rs):
    prov = {str(s["no"]): (rs.get(str(s["no"]), {}).get("provenance") or s.get("provenance", "llm"))
            for s in b["STEPS"]}
    steps = [{**s, "provenance": prov[str(s["no"])]} for s in b["STEPS"]]
    store.delete_drafts(PART_ID, b["stem"])
    store.ingest_document(PART_ID, b["stem"], "draft", b["meta"], steps, b["SEQ"], b["SELF"], origin="pipeline")


def edit_step(stem, no, fields):
    bad = set(fields) - EDITABLE
    if bad:
        raise ValueError(f"protected/unknown fields: {sorted(bad)}")
    bp = OUTPUT / stem / "steps_bundle.json"
    b = json.loads(bp.read_text(encoding="utf-8"))
    tgt = next((s for s in b["STEPS"] if s["no"] == no), None)
    if tgt is None:
        raise ValueError(f"no step {no}")
    tgt.update({k: fields[k] for k in fields})
    tgt["provenance"] = "manual"
    rs = _load_rs(stem)
    # editing content invalidates the operator's prior sign-off: the edited step must be
    # re-reviewed and the whole guide re-approved (a signature can't cover changed content).
    rs[str(no)] = {**rs.get(str(no), {}), "provenance": "manual", "reviewed": False}
    if b["review"].get("approved") or b["review"].get("signed_off"):
        b["review"].update(approved=False, signed_off=False, signed_by=None, signed_at=None)
    _atomic_json(_rs_path(stem), rs)
    _require_keys(b)
    _atomic_json(bp, b)
    render(stem, b)
    _reingest_draft(b, rs)
    return {"ok": True, "step": tgt, "review": _merged_review(b, rs)}


def mark_reviewed(stem, no):
    b = json.loads((OUTPUT / stem / "steps_bundle.json").read_text(encoding="utf-8"))
    # trust gate: a step with a real evidence gap (blocked) cannot be signed off — the client
    # disables its button, but enforce server-side too so a direct API call can't bypass it.
    if no in (b.get("review", {}).get("blocked") or []):
        raise ValueError(f"step {no}: 근거 미충족(blocked) — 검수할 수 없습니다")
    rs = _load_rs(stem)
    rs[str(no)] = {**rs.get(str(no), {}), "reviewed": True}
    _atomic_json(_rs_path(stem), rs)
    return {"ok": True, "review": _merged_review(b, rs)}


def approve(stem, signed_by):
    bp = OUTPUT / stem / "steps_bundle.json"
    b = json.loads(bp.read_text(encoding="utf-8"))
    rs = _load_rs(stem)
    r = b["review"]
    if not r.get("evidence_ok"):
        return False, {"error": "근거 미충족 — 승인 불가", "review": _merged_review(b, rs)}
    if not (b["STEPS"] and all(rs.get(str(s["no"]), {}).get("reviewed") for s in b["STEPS"])):
        return False, {"error": "모든 단계 검수 필요", "review": _merged_review(b, rs)}
    # Record the signed doc in the DB FIRST. If the DB write fails we must NOT leave an
    # approved=True guide on disk with no audit record — so promote before persisting.
    store.promote_to_validated(PART_ID, stem, signed_by)   # audit: marks the validated doc + signer
    r.update(signed_off=True, approved=True, signed_by=signed_by, signed_at=_now())
    _require_keys(b)
    _atomic_json(bp, b)
    render(stem, b)
    return True, {"ok": True, "approved": True, "review": _merged_review(b, rs)}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="sopgen pipeline: draft a 작업지도서 for one clip.")
    ap.add_argument("--stem", required=True)
    ap.add_argument("--no-ingest", action="store_true")
    args = ap.parse_args()
    res = run(args.stem, ingest=not args.no_ingest)
    r = res["bundle"]["review"]
    state = ("APPROVED" if r["approved"]
             else "GROUNDED·서명대기" if r.get("evidence_ok")
             else "DRAFT·검수필요")
    print(f"[sopgen] {args.stem}: {r['total_steps']} steps · grounded {r['grounded']} · "
          f"provenance {r['provenance']} · {state}")
    print(f"         -> {res['render']['index']}")


if __name__ == "__main__":
    main()
