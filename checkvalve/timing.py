"""
Phase 2 — standard-time (작업표준시간) estimate.

Only one clip (170526928, 12.8 min) repeats the cycle, so this is effectively
n=1: we estimate the dominant cycle period by autocorrelating its per-second
activity signal and report it WITH a single-source caveat. We never fabricate a
median+range that implies many timed trials (the gold doc's "38~45초" implies
trials this dataset lacks).
"""
from __future__ import annotations

import json

import numpy as np

from .config import OUTPUT
from .signal_digest import build_digest

TIMING_CLIP = "KakaoTalk_20260606_170526928"
MIN_CYCLE_SEC, MAX_CYCLE_SEC = 15, 150


def estimate(clip: str = TIMING_CLIP) -> dict:
    cache = OUTPUT / "timing.json"
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("source_clip") == clip:   # never trust a cache built for a different clip
            return cached

    out = {"source_clip": clip, "method": "autocorrelation",
           "caveat": "단일 출처(n=1) 추정 · 다회 측정 필요"}
    try:
        digest = build_digest(clip)
        sp = np.array([r["speed"] if r["speed"] is not None else np.nan for r in digest["rows"]])
        sp = sp[~np.isnan(sp)]
        if sp.size >= 2 * MAX_CYCLE_SEC:
            sp = sp - sp.mean()
            ac = np.correlate(sp, sp, mode="full")[sp.size - 1:]
            ac = ac / (ac[0] or 1)
            lo, hi = MIN_CYCLE_SEC, min(MAX_CYCLE_SEC + 1, ac.size)   # inclusive of MAX_CYCLE_SEC
            peak = lo + int(np.argmax(ac[lo:hi]))
            out.update(estimate_sec=int(peak), strength=round(float(ac[peak]), 3),
                       display=f"약 {peak}초 (자동추정)")
        else:
            out.update(estimate_sec=None, display="[측정 부족]")
    except Exception as e:  # extraction missing etc. — stay honest, don't fabricate
        out.update(estimate_sec=None, display="[측정 불가]", error=str(e))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
