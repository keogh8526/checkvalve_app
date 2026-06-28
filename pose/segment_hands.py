"""
손21점(rtmlib) 기반 구간분할 — 손확대 영상 전용(body pose 어깨=0이라 불가).
손중심 위치(posx,posy)·손크기·손속도 채널로 다채널 분할. body의 segment_multi와 동일 철학.

입력 : hands.json (extract_hands_rtm.py)   출력 : segments.json (동일 스키마)
usage:
  python pose/segment_hands.py --hands-json results/all/hand_fast/hands.json --out-dir /tmp/h --n-steps 6
"""
import argparse
import json
from pathlib import Path

import numpy as np
import ruptures as rpt

from segment import smooth


def hand_channels(data, want):
    """hands.json → 채널행렬. 손중심 위치/크기/속도(첫 손 기준)."""
    fps = data["fps"]; stride = data.get("stride", 1); eff = fps / stride
    cx, cy, size = [], [], []
    for fr in data["frames"]:
        if fr["num_hands"] > 0:
            kp = np.array(fr["hands"][0]["kpts"])      # (21,3)
            xy = kp[:, :2]
            cx.append(float(xy[:, 0].mean())); cy.append(float(xy[:, 1].mean()))
            size.append(float(np.hypot(*(xy.max(0) - xy.min(0)))))  # 손 bbox 대각(거리정규화)
        else:
            cx.append(np.nan); cy.append(np.nan); size.append(np.nan)
    cx, cy, size = map(np.array, (cx, cy, size))
    idx = np.arange(len(cx))
    for a in (cx, cy, size):
        m = np.isnan(a)
        if m.any() and (~m).any():
            a[m] = np.interp(idx[m], idx[~m], a[~m])
        elif m.all():
            a[:] = 0.0
    scale = float(np.median(size)) or 1.0
    ch = {}
    ch["posx"] = smooth(cx / scale, eff)[1:]
    ch["posy"] = smooth(cy / scale, eff)[1:]
    sx = smooth(cx / scale, eff); sy = smooth(cy / scale, eff)
    ch["spd"] = smooth(np.sqrt(np.diff(sx) ** 2 + np.diff(sy) ** 2) * eff, eff, 0.5, 0.01)
    ch["size"] = smooth(size / scale, eff)[1:]          # 손 개폐(집기)
    cols = []
    for c in want:
        v = np.nan_to_num(ch[c], nan=0.0)
        v = (v - v.mean()) / (v.std() + 1e-9)
        cols.append(v)
    return np.column_stack(cols), eff, stride, fps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands-json", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--channels", default="spd,posx,posy")
    ap.add_argument("--n-steps", type=int, default=6)
    ap.add_argument("--min-sec", type=float, default=3.0)
    args = ap.parse_args()
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    data = json.loads(Path(args.hands_json).read_text(encoding="utf-8"))
    want = [c.strip() for c in args.channels.split(",")]
    X, eff, stride, fps = hand_channels(data, want)
    ds = max(1, int(eff / 2)); Xd = X[::ds]
    min_size = max(2, int(args.min_sec * (eff / ds)))
    algo = rpt.Dynp(model="rbf", min_size=min_size, jump=1).fit(Xd)
    bkps = [min(len(X), b * ds) for b in algo.predict(n_bkps=args.n_steps - 1)]
    bounds = [0] + bkps
    segs = []
    for i in range(len(bounds) - 1):
        s, e = bounds[i], bounds[i + 1]
        segs.append({"seg": i + 1, "t_start": round(s * stride / fps, 2),
                     "t_end": round(e * stride / fps, 2),
                     "dur_sec": round((e - s) * stride / fps, 2),
                     "mean_speed": round(float(np.mean(X[s:e, 0])), 3)})
    (out / "segments.json").write_text(
        json.dumps({"video": data["video"], "eff_fps": round(eff, 2), "channels": want,
                    "source": "hands21", "n_segments": len(segs), "segments": segs},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] 손21점 {len(segs)}세그 (채널={want}) -> {out/'segments.json'}")
    for s in segs:
        print(f"  {s['t_start']:6.1f}~{s['t_end']:6.1f}s ({s['dur_sec']:5.1f}s)")


if __name__ == "__main__":
    main()
