"""
단계 자동분할 — 손목 키포인트 속도의 변화점(changepoint)으로 작업 단계 경계를 검출한다.

입력 : extract_pose.py 가 만든 body json (keypoints[name]={x,y,conf})
처리 : 손목 좌표 -> One-Euro 평활 -> 속도 -> ruptures(Pelt, rbf) 변화점
출력 : <out>/segments.json (단계 경계 시각) + <out>/velocity.png (속도곡선+경계 시각화)

usage:
  python pose/segment.py --body-json results/seg_test/body_full.json --out-dir results/seg_test --pen 8
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import ruptures as rpt


# ---------- One-Euro Filter (포즈 jitter 표준 해법) ----------
class OneEuro:
    def __init__(self, freq, mincutoff=1.0, beta=0.02, dcutoff=1.0):
        self.freq, self.mincutoff, self.beta, self.dcutoff = freq, mincutoff, beta, dcutoff
        self.x_prev = None
        self.dx_prev = 0.0

    def _alpha(self, cutoff):
        te = 1.0 / self.freq
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / te)

    def __call__(self, x):
        if self.x_prev is None:
            self.x_prev = x
            return x
        dx = (x - self.x_prev) * self.freq
        a_d = self._alpha(self.dcutoff)
        dx_hat = a_d * dx + (1 - a_d) * self.dx_prev
        cutoff = self.mincutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff)
        x_hat = a * x + (1 - a) * self.x_prev
        self.x_prev, self.dx_prev = x_hat, dx_hat
        return x_hat


def smooth(arr, freq, mincutoff=1.0, beta=0.02):
    f = OneEuro(freq, mincutoff, beta)
    return np.array([f(v) for v in arr])


def wrist_xy(data, name, conf_min=0.3):
    """손목 좌표 시계열. 저신뢰/미검출은 NaN -> 선형보간."""
    xs, ys = [], []
    for fr in data["frames"]:
        if fr["num_persons"] > 0:
            kp = fr["persons"][0]["keypoints"][name]
            if kp["conf"] >= conf_min:
                xs.append(kp["x"]); ys.append(kp["y"]); continue
        xs.append(np.nan); ys.append(np.nan)
    xs, ys = np.array(xs), np.array(ys)
    # 선형보간 (짧은 결측만 자연 보간)
    idx = np.arange(len(xs))
    for a in (xs, ys):
        m = np.isnan(a)
        if m.any() and (~m).any():
            a[m] = np.interp(idx[m], idx[~m], a[~m])
    return xs, ys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-json", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--pen", type=float, default=8.0, help="ruptures penalty (클수록 경계 적음)")
    ap.add_argument("--min-sec", type=float, default=2.0, help="최소 단계 길이(초)")
    args = ap.parse_args()

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    data = json.loads(Path(args.body_json).read_text(encoding="utf-8"))
    fps = data["fps"]; stride = data.get("stride", 1)
    eff_fps = fps / stride                      # 처리된 프레임의 실효 fps
    scale_px = 1.0

    # 어깨너비로 정규화(카메라 거리 무관) — 가능할 때
    sw = []
    for fr in data["frames"]:
        if fr["num_persons"] > 0:
            k = fr["persons"][0]["keypoints"]
            ls, rs = k["left_shoulder"], k["right_shoulder"]
            if ls["conf"] > 0.3 and rs["conf"] > 0.3:
                sw.append(math.hypot(ls["x"] - rs["x"], ls["y"] - rs["y"]))
    if sw:
        scale_px = float(np.median(sw))

    # 양손목 속도 (정규화 -> One-Euro -> 속도) 합성
    speeds = []
    for name in ("left_wrist", "right_wrist"):
        x, y = wrist_xy(data, name)
        xs = smooth(x / scale_px, eff_fps)
        ys = smooth(y / scale_px, eff_fps)
        v = np.sqrt(np.diff(xs) ** 2 + np.diff(ys) ** 2) * eff_fps  # 정규화속도/초
        speeds.append(v)
    speed = np.mean(speeds, axis=0)
    speed = smooth(speed, eff_fps, mincutoff=0.5, beta=0.01)        # 속도자체도 평활
    # NaN 가드(L12): 전 프레임 결측 등으로 남은 NaN을 0으로 -> ruptures 크래시 방지
    if np.all(np.isnan(speed)):
        raise SystemExit("[err] 손목 신호 전부 결측 — 검출 실패 영상")
    speed = np.nan_to_num(speed, nan=float(np.nanmedian(speed)))

    # ruptures 변화점 검출
    min_size = max(2, int(args.min_sec * eff_fps))
    algo = rpt.Pelt(model="rbf", min_size=min_size).fit(speed.reshape(-1, 1))
    bkps = algo.predict(pen=args.pen)            # 끝 인덱스 목록(마지막=N)

    # 경계 -> 세그먼트 시각
    bounds = [0] + bkps
    segs = []
    for i in range(len(bounds) - 1):
        s_idx, e_idx = bounds[i], bounds[i + 1]
        t0 = s_idx * stride / fps
        t1 = e_idx * stride / fps
        segs.append({"seg": i + 1, "t_start": round(t0, 2), "t_end": round(t1, 2),
                     "dur_sec": round(t1 - t0, 2),
                     "mean_speed": round(float(np.mean(speed[s_idx:e_idx])), 3)})

    (out / "segments.json").write_text(
        json.dumps({"video": data["video"], "eff_fps": round(eff_fps, 2),
                    "scale_px": round(scale_px, 1), "pen": args.pen,
                    "n_segments": len(segs), "segments": segs},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # 시각화
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        t = np.arange(len(speed)) * stride / fps
        plt.figure(figsize=(12, 4))
        plt.plot(t, speed, lw=0.8, color="#1f77b4", label="wrist speed (norm/s)")
        for b in bkps[:-1]:
            plt.axvline(b * stride / fps, color="red", ls="--", lw=1)
        plt.title(f"Wrist-speed segmentation — {len(segs)} steps detected (pen={args.pen})")
        plt.xlabel("time (s)"); plt.ylabel("speed"); plt.legend()
        plt.tight_layout(); plt.savefig(out / "velocity.png", dpi=90); plt.close()
    except Exception as e:
        print("[warn] plot skipped:", e)

    print(f"[done] {len(segs)} segments  (eff_fps={eff_fps:.1f}, scale={scale_px:.0f}px, pen={args.pen})")
    for s in segs:
        print(f"  seg{s['seg']}: {s['t_start']:6.1f}s ~ {s['t_end']:6.1f}s  ({s['dur_sec']:5.1f}s)  v={s['mean_speed']}")
    print(f"[done] -> {out/'segments.json'} , {out/'velocity.png'}")


if __name__ == "__main__":
    main()
