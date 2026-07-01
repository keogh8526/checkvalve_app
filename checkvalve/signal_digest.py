"""Stage B — per-second activity track + WEAK candidate segments (numpy/scipy)."""
from __future__ import annotations

import json
import math

import numpy as np
from scipy.signal import medfilt, savgol_filter, find_peaks

from .config import OUTPUT
from .paths import resolve_artifacts
from .clip_profile import write_profile
from .qc_helpers import primary_person, yolo_xy, frame_scale, Y

H_WRIST, H_MID_MCP = 0, 9
MIN_SEG_SEC = 3.0
UNIFORM_WIN_SEC = 25.0


def _centroid(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0) if box else None


def _select_primary(frame, prev_c):
    persons = frame.get("persons") or []
    if not persons:
        return None
    if prev_c and len(persons) > 1:
        def d(p):
            c = _centroid(p.get("box"))
            return math.hypot(c[0] - prev_c[0], c[1] - prev_c[1]) if c else 1e9
        return min(persons, key=d)
    return primary_person(frame)


def _per_second(times, vals, agg):
    if len(times) == 0:
        return np.array([]), np.array([])
    secs = np.floor(times).astype(int)
    out_t, out_v = [], []
    for s in range(secs.min(), secs.max() + 1):
        m = secs == s
        sub = vals[m]
        out_t.append(s)
        out_v.append(agg(sub) if (m.any() and not np.isnan(sub).all()) else np.nan)
    return np.array(out_t), np.array(out_v)


def _smooth(v):
    if len(v) < 5:
        return v
    x = v.copy()
    nans = np.isnan(x)
    if nans.all():
        return x
    idx = np.arange(len(x))
    x[nans] = np.interp(idx[nans], idx[~nans], x[~nans], left=0.0, right=0.0)
    x = medfilt(x, 3)
    if len(x) >= 9:
        x = savgol_filter(x, 9, 2)
    return x


def _body_series(body, fps):
    times, speeds, two = [], [], []
    prev_xy, prev_c = None, None
    for f in body.get("frames", []):
        t = f.get("time_sec", f["frame"] / fps)
        p = _select_primary(f, prev_c)
        if p is None:
            times.append(t); speeds.append(np.nan); two.append(False); prev_xy = None
            continue
        prev_c = _centroid(p.get("box"))
        rw, lw = yolo_xy(p, Y["r_wri"], 0.3), yolo_xy(p, Y["l_wri"], 0.3)
        wrist = rw or lw
        two.append(bool(rw and lw))
        scale = frame_scale(p)
        if wrist is None or prev_xy is None or not scale:
            speeds.append(np.nan)
        else:
            speeds.append(math.hypot(wrist[0] - prev_xy[0], wrist[1] - prev_xy[1]) / scale * fps)
        times.append(t); prev_xy = wrist
    return np.array(times), np.array(speeds), np.array(two, dtype=bool)


def _hand_xy(hand, idx):
    return (hand[idx][0], hand[idx][1]) if (hand and len(hand) > idx and hand[idx]) else None


def _hand_series(hands, fps):
    times, speeds, two = [], [], []
    prev_xy = None
    for f in hands.get("frames", []):
        t = f.get("time_sec", f["frame"] / fps)
        rh, lh = f.get("right_hand"), f.get("left_hand")
        two.append(bool(rh and lh))
        hand = rh or lh
        wrist, mid = _hand_xy(hand, H_WRIST), _hand_xy(hand, H_MID_MCP)
        span = math.hypot(wrist[0] - mid[0], wrist[1] - mid[1]) if (wrist and mid) else None
        if wrist is None or prev_xy is None or not span or span < 1:
            speeds.append(np.nan)
        else:
            speeds.append(math.hypot(wrist[0] - prev_xy[0], wrist[1] - prev_xy[1]) / span * fps)
        times.append(t); prev_xy = wrist
    return np.array(times), np.array(speeds), np.array(two, dtype=bool)


def _states(speed_sec):
    valid = speed_sec[~np.isnan(speed_sec)]
    if valid.size == 0:
        return ["unknown"] * len(speed_sec)
    p30, p60 = np.percentile(valid, 30), np.percentile(valid, 60)
    out = []
    for s in speed_sec:
        out.append("unknown" if np.isnan(s) else "idle" if s < p30 else "manipulate" if s > p60 else "reach")
    return out


def _uniform(duration):
    n = max(1, int(round(duration / UNIFORM_WIN_SEC)))
    e = np.linspace(0, duration, n + 1)
    return [[float(e[i]), float(e[i + 1])] for i in range(n)]


def _segments(t_sec, speed_sec, duration):
    if speed_sec.size == 0 or np.isnan(speed_sec).all():
        return _uniform(duration), []
    valleys, _ = find_peaks(-np.nan_to_num(speed_sec, nan=np.nanmax(speed_sec)), distance=4)
    hints = sorted({0, *[int(t_sec[v]) for v in valleys], int(round(duration))})
    segs = [[float(a), float(b)] for a, b in zip(hints, hints[1:]) if b - a >= MIN_SEG_SEC]
    if not segs:
        segs = _uniform(duration)
    if len(segs) >= 2 and segs[-1][1] - segs[-1][0] < MIN_SEG_SEC:
        segs[-2][1] = segs[-1][1]; segs.pop()
    return segs, [h for h in hints if 0 < h < round(duration)]


def build_digest(stem: str) -> dict:
    arts = resolve_artifacts(stem)
    prof_path = OUTPUT / stem / "clip_profile.json"
    prof = json.loads(prof_path.read_text(encoding="utf-8")) if prof_path.exists() else write_profile(stem)
    duration = prof.get("duration_sec") or 0.0
    fps = prof.get("fps") or 29.97

    if prof["body_trust"] and arts["body"]:
        source = "body"
        body = json.loads(arts["body"].read_text(encoding="utf-8"))
        fps = body.get("fps", fps)
        times, speeds, two = _body_series(body, fps)
    elif prof["hand_trust"] and arts["hands"]:
        source = "hands"
        hands = json.loads(arts["hands"].read_text(encoding="utf-8"))
        fps = hands.get("fps", fps)
        times, speeds, two = _hand_series(hands, fps)
    else:
        source = "none"
        times, speeds, two = np.array([]), np.array([]), np.array([], dtype=bool)

    t_sec, speed_sec = _per_second(times, speeds, np.nanmean)
    _, two_sec = _per_second(times, two.astype(float), np.nanmean)
    speed_sec = _smooth(speed_sec)
    states = _states(speed_sec)
    segs, hints = _segments(t_sec, speed_sec, duration) if source != "none" else (_uniform(duration), [])

    rows = [{"t": int(s), "two_hands": bool(two_sec[i] >= 0.5) if two_sec.size else False,
             "speed": None if np.isnan(speed_sec[i]) else round(float(speed_sec[i]), 3),
             "state": states[i]} for i, s in enumerate(t_sec)]

    return {
        "stem": stem, "shot_type": prof["shot_type"], "signal_source": source,
        "fps": round(fps, 3), "duration_sec": duration, "rows": rows,
        "boundary_hints_sec": hints,
        "candidate_segments": [{"id": i, "start_sec": round(a, 2), "end_sec": round(b, 2),
                                "source": "valley" if source != "none" else "uniform"}
                               for i, (a, b) in enumerate(segs)],
    }


def write_digest(stem: str) -> dict:
    d = build_digest(stem)
    out = OUTPUT / stem
    out.mkdir(parents=True, exist_ok=True)
    (out / "digest.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return d
