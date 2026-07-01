"""
Pipeline orchestrator: one clip -> a draft 표준 작업 지도서, end to end.

  seed gold -> profile -> digest -> (gold-align segments on the timeline clip)
            -> keyframes -> author(RAG) -> standard-time -> assemble -> render
            -> ingest the draft into the store.

The author stage is RAG (gold pool) here; pass a Claude client to switch stage E
to claude-opus-4-8 vision once an API key exists.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .config import OUTPUT, REPO, PART_ID
from .paths import video_path, list_stems
from . import store as store
from .clip_profile import write_profile
from .step_author import author_steps
from .assembler import assemble
from .render import render
from .store import seed_gold, get_gold, get_validated_steps, ingest_document, delete_drafts
# signal_digest/keyframe_sampler/timing pull cv2/numpy/scipy — imported LAZILY inside run()
# so the ML-free Studio process can import this module just for the edit/approve helpers.


def _gold_aligned_segments(digest, pool):
    """For the timeline clip, replace the weak uniform windows with the gold step
    boundaries so keyframes + steps line up 1:1 with the validated guide."""
    dur = digest["duration_sec"] or (pool[-1]["at"] + 30)
    ats = [p["at"] for p in pool]
    segs = []
    for i, a in enumerate(ats):
        b = ats[i + 1] if i + 1 < len(ats) else dur
        segs.append({"id": i, "start_sec": float(a), "end_sec": float(b), "source": "gold"})
    return segs


def run(stem: str, client=None, ingest: bool = True) -> dict:
    from .signal_digest import write_digest   # lazy (ML) — only when actually generating
    from .keyframe_sampler import sample
    from .timing import estimate
    seed_gold()
    profile = write_profile(stem)
    digest = write_digest(stem)

    gold = get_gold(PART_ID)
    pool = get_validated_steps(PART_ID)
    if gold and stem == gold.get("source_clip") and pool:
        digest["candidate_segments"] = _gold_aligned_segments(digest, pool)
        (OUTPUT / stem / "digest.json").write_text(
            json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")

    keyframes = sample(stem, digest)
    author_result = author_steps(stem, digest, keyframes, profile, client=client)
    timing = estimate()

    vid = video_path(stem)
    video_rel = vid.relative_to(REPO).as_posix() if vid else f"data/{stem}.mp4"   # POSIX sep (Windows-safe)
    bundle = assemble(stem, author_result, video_rel, profile, timing)
    (OUTPUT / stem / "steps_bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    out = render(stem, bundle)

    if ingest:
        delete_drafts(PART_ID, stem)   # re-run replaces this clip's draft, not accumulates
        steps_for_store = [{**s, "provenance": author_result["steps"][i].get("provenance", "rag")}
                           for i, s in enumerate(bundle["STEPS"])]
        ingest_document(PART_ID, stem, "draft", bundle["meta"], steps_for_store,
                        bundle["SEQ"], bundle["SELF"], origin="pipeline")

    return {"profile": profile, "digest": digest, "author": author_result,
            "bundle": bundle, "render": out}


# ─────────────────────────── GUI-facing helpers (Phase 4) ───────────────────────────
# The Studio calls these (ML-free): generate is the FAST per-clip path; edit/review/approve
# mutate the bundle + review_state.json and re-render via the SAME render() path as preview/export.
EDITABLE = {"badge", "text", "sub", "pts", "insp", "cap"}   # label channel only (tag/at/standard_time protected)
PROTECTED = {"at", "no", "tag", "standard_time", "evidence"}


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
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


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
    prov = {str(s["no"]): (rs.get(str(s["no"]), {}).get("provenance") or s.get("provenance", "rag"))
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
    rs[str(no)] = {**rs.get(str(no), {}), "provenance": "manual"}
    _atomic_json(_rs_path(stem), rs)
    _require_keys(b)
    _atomic_json(bp, b)
    render(stem, b)
    _reingest_draft(b, rs)
    return {"ok": True, "step": tgt, "review": _merged_review(b, rs)}


def mark_reviewed(stem, no):
    rs = _load_rs(stem)
    rs[str(no)] = {**rs.get(str(no), {}), "reviewed": True}
    _atomic_json(_rs_path(stem), rs)
    b = json.loads((OUTPUT / stem / "steps_bundle.json").read_text(encoding="utf-8"))
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
    r.update(signed_off=True, approved=True, signed_by=signed_by, signed_at=_now())
    _require_keys(b)
    _atomic_json(bp, b)
    render(stem, b)
    store.promote_to_validated(PART_ID, stem, signed_by)   # closes the RAG feedback loop
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
