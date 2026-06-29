"""
다채널 키포인트 분할 — "손이 얼마나 빨리(속도)"만이 아니라 "어디서 무엇을(위치)"을 본다.
속도 단일채널의 한계(의미경계≠속도변화점)를 위치/자세 채널로 보완.

채널(각 z정규화):
  spd  양손목 속도        (기존)
  posx 손중심 x (정규화)   ← 손이 좌우 어디
  posy 손중심 y (정규화)   ← 손이 상하 어디 (부품영역 이동)
  dist 양손목 거리         ← 모으기/벌리기(조립 vs 분리)
  hgt  손높이(손목y-어깨y)  ← 들어올림/내려놓음
  elb  팔꿈치각도          ← 자세 변화

입력 : body.json   출력 : segments.json (segment.py와 동일 스키마)
usage:
  python pose/segment_multi.py --body-json results/all/front_fast/body.json --out-dir /tmp/x \
      --channels spd,posy,dist --n-steps 6 --min-sec 3
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import ruptures as rpt

from segment import smooth, wrist_xy, primary_person


def scale_of(data):
    def width(a, b):
        out = []
        for fr in data["frames"]:
            p = primary_person(fr)
            if p:
                k = p["keypoints"]
                if k[a]["conf"] > 0.3 and k[b]["conf"] > 0.3:
                    out.append(math.hypot(k[a]["x"] - k[b]["x"], k[a]["y"] - k[b]["y"]))
        return out
    sw = width("left_shoulder", "right_shoulder") or width("left_hip", "right_hip")
    if sw:
        return float(np.median(sw))
    return float(data.get("resolution", [1920])[0]) * 0.2


def kp_series(data, name):
    """키포인트 x,y 시계열 (저신뢰 보간)."""
    xs, ys = [], []
    for fr in data["frames"]:
        p = primary_person(fr)
        if p and p["keypoints"][name]["conf"] >= 0.3:
            xs.append(p["keypoints"][name]["x"]); ys.append(p["keypoints"][name]["y"])
        else:
            xs.append(np.nan); ys.append(np.nan)
    xs, ys = np.array(xs), np.array(ys)
    idx = np.arange(len(xs))
    for a in (xs, ys):
        m = np.isnan(a)
        if m.any() and (~m).any():
            a[m] = np.interp(idx[m], idx[~m], a[~m])
        elif m.all():
            a[:] = 0.0
    return xs, ys


def angle_series(data, sh, el, wr):
    """팔꿈치각도(어깨-팔꿈치-손목) 시계열."""
    sx, sy = kp_series(data, sh); ex, ey = kp_series(data, el); wx, wy = kp_series(data, wr)
    ang = []
    for i in range(len(sx)):
        v1 = np.array([sx[i] - ex[i], sy[i] - ey[i]])
        v2 = np.array([wx[i] - ex[i], wy[i] - ey[i]])
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        c = np.dot(v1, v2) / (n1 * n2 + 1e-9)
        ang.append(math.acos(max(-1, min(1, c))))
    return np.array(ang)


def build_channels(data, want, eff_fps, scale):
    lwx, lwy = kp_series(data, "left_wrist"); rwx, rwy = kp_series(data, "right_wrist")
    ch = {}
    # 속도
    spds = []
    for x, y in ((lwx, lwy), (rwx, rwy)):
        xs = smooth(x / scale, eff_fps); ys = smooth(y / scale, eff_fps)
        spds.append(np.sqrt(np.diff(xs) ** 2 + np.diff(ys) ** 2) * eff_fps)
    ch["spd"] = smooth(np.mean(spds, axis=0), eff_fps, 0.5, 0.01)
    # 위치(손중심), 거리, 높이, 각도 — diff로 길이 맞춤(속도와 동일 N-1)
    cx = ((lwx + rwx) / 2) / scale; cy = ((lwy + rwy) / 2) / scale
    ch["posx"] = smooth(cx, eff_fps)[1:]
    ch["posy"] = smooth(cy, eff_fps)[1:]
    ch["dist"] = smooth(np.hypot((lwx - rwx) / scale, (lwy - rwy) / scale), eff_fps)[1:]
    shy = kp_series(data, "left_shoulder")[1]
    ch["hgt"] = smooth((cy - shy / scale), eff_fps)[1:]
    ch["elb"] = smooth((angle_series(data, "left_shoulder", "left_elbow", "left_wrist")
                        + angle_series(data, "right_shoulder", "right_elbow", "right_wrist")) / 2,
                       eff_fps)[1:]
    cols = []
    for c in want:
        v = ch[c]
        v = np.nan_to_num(v, nan=float(np.nanmedian(v)) if not np.all(np.isnan(v)) else 0.0)
        v = (v - v.mean()) / (v.std() + 1e-9)      # z정규화
        cols.append(v)
    return np.column_stack(cols)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-json", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--channels", default="spd,posy,dist", help="쉼표: spd,posx,posy,dist,hgt,elb")
    ap.add_argument("--n-steps", type=int, default=6, help="공정서 단계 수 K (정확히 K세그)")
    ap.add_argument("--min-sec", type=float, default=3.0)
    ap.add_argument("--pen", type=float, default=0.0, help=">0이면 Pelt(pen), else Dynp(n_steps)")
    args = ap.parse_args()

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    data = json.loads(Path(args.body_json).read_text(encoding="utf-8"))
    fps = data["fps"]; stride = data.get("stride", 1); eff_fps = fps / stride
    scale = scale_of(data)
    want = [c.strip() for c in args.channels.split(",")]
    X = build_channels(data, want, eff_fps, scale)
    # 다운샘플(속도): 너무 길면 Dynp 느림 → 2Hz로
    ds = max(1, int(eff_fps / 2))
    Xd = X[::ds]
    min_size = max(2, int(args.min_sec * (eff_fps / ds)))

    if args.pen > 0:
        algo = rpt.Pelt(model="rbf", min_size=min_size).fit(Xd)
        bkps_d = algo.predict(pen=args.pen)
    else:
        algo = rpt.Dynp(model="rbf", min_size=min_size, jump=1).fit(Xd)
        bkps_d = algo.predict(n_bkps=args.n_steps - 1)
    # 다운샘플 인덱스 → 원 인덱스
    bkps = [min(len(X), b * ds) for b in bkps_d]

    bounds = [0] + bkps
    segs = []
    for i in range(len(bounds) - 1):
        s_idx, e_idx = bounds[i], bounds[i + 1]
        t0 = s_idx * stride / fps; t1 = e_idx * stride / fps
        segs.append({"seg": i + 1, "t_start": round(t0, 2), "t_end": round(t1, 2),
                     "dur_sec": round(t1 - t0, 2),
                     "mean_speed": round(float(np.mean(X[s_idx:e_idx, 0])), 3)})
    (out / "segments.json").write_text(
        json.dumps({"video": data["video"], "eff_fps": round(eff_fps, 2),
                    "channels": want, "scale_px": round(scale, 1), "n_segments": len(segs),
                    "segments": segs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {len(segs)}세그 (채널={want}, scale={scale:.0f}) -> {out/'segments.json'}")
    for s in segs:
        print(f"  {s['t_start']:6.1f}~{s['t_end']:6.1f}s ({s['dur_sec']:5.1f}s)")


if __name__ == "__main__":
    main()
