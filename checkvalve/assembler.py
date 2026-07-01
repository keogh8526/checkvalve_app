"""
Stage F — document assembler (pure Python). Phase 1+2.

Collects the authored steps, assigns no/tag/at, runs verification + the mandatory
review gate, attaches provenance, the gold checklists, and the standard-time
estimate. Produces the bundle the renderer turns into steps_data.js.

Approval rule: a doc is APPROVED only when every step is grounded AND there are no
warnings AND a human has reviewed. Until then it renders as a clearly-marked draft.
"""
from __future__ import annotations


def _ev_frames(s):
    if s.get("evidence_frames"):
        return list(s["evidence_frames"])
    return list((s.get("evidence") or {}).get("frames", []))


def _chapters(steps):
    """One jump-chip per step using its badge (cap at 6, evenly sampled)."""
    n = len(steps)
    if n == 0:
        return []
    if n <= 6:
        idxs = list(range(n))
    else:
        idxs = sorted({round(i * (n - 1) / 5) for i in range(6)})
    out = []
    for j, idx in enumerate(idxs):
        label = steps[idx].get("badge") or f"구간 {idx + 1}"
        out.append([f"① {label}" if j == 0 else label, idx])
    return out


def assemble(stem, author_result, video_rel, profile, timing):
    steps_in = author_result["steps"]
    gold = author_result.get("gold")
    warnings, needs_review, STEPS, prov_counts = [], [], [], {}
    prev_at = -1

    for i, s in enumerate(steps_in):
        no = i + 1
        at = int(s.get("at", i))
        if at <= prev_at:
            at = prev_at + 1
            warnings.append(f"step {no}: 비단조 'at' -> {at}s 로 보정")
        prev_at = at
        frames = _ev_frames(s)
        if not frames:
            warnings.append(f"step {no}: 근거 프레임 없음")
        if not s.get("grounded", False):
            needs_review.append(no)
        prov = s.get("provenance", "stub")
        prov_counts[prov] = prov_counts.get(prov, 0) + 1
        STEPS.append({"no": no, "tag": s.get("tag", f"1-{no}"), "at": at,
                      "insp": int(s.get("insp", 1)), "badge": s.get("badge", "미정"),
                      "text": s.get("text", ""), "sub": s.get("sub", ""),
                      "pts": list(s.get("pts", [])), "cap": s.get("cap", ""),
                      "provenance": prov})   # per-step provenance so GUI chips render

    # checklists: prefer the part's validated SEQ/SELF; else derive from pts by insp
    if gold:
        seq, self_ = list(gold.get("seq", [])), list(gold.get("self", []))
    else:
        seq = sorted({p for st in steps_in if st.get("insp") == 1 for p in st.get("pts", [])})
        self_ = sorted({p for st in steps_in if st.get("insp") in (2, 3) for p in st.get("pts", [])})

    meta = dict((gold or {}).get("meta", {})) or {
        "품명": "체크밸브", "도번": "GMT-CV-008", "공정명": "DISC·SPACER·HINGE PIN 조립",
        "관리번호": "8", "개정": "Rev.0 · 자동초안"}
    st_display = timing.get("display", "[측정 불가]")
    meta["작업표준시간"] = st_display

    evidence_ok = not needs_review and not warnings        # all steps grounded, no warnings
    signed_off = bool(steps_in) and all(s.get("reviewed") for s in steps_in)
    review = {
        "total_steps": len(STEPS), "grounded": len(STEPS) - len(needs_review),
        "needs_review": needs_review, "warnings": warnings,
        "provenance": prov_counts,
        "evidence_ok": evidence_ok, "signed_off": signed_off,
        "approved": evidence_ok and signed_off,            # green ONLY after a human signs off
        "dropped_pool_steps": author_result.get("dropped_pool_steps", 0),
        "mode": author_result.get("mode"), "is_gold_clip": author_result.get("is_gold_clip", False),
    }

    return {
        "stem": stem, "video": video_rel, "shot_type": profile["shot_type"],
        "roles": profile["roles"], "meta": meta,
        "standard_time": timing, "STEPS": STEPS, "CHAPTERS": _chapters(steps_in),
        "SEQ": seq, "SELF": self_, "review": review,
    }
