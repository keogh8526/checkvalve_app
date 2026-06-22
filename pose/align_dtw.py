"""
M4 DTW 정렬 — 같은 작업의 서로 다른 관점/회차 영상을 시간축으로 정렬한다.
(다각도 융합의 핵심 연결고리: 관점마다 분할이 달라도 '같은 표준단계'로 묶음)

원리: 두 영상의 손목속도 프로파일을 DTW(시간왜곡)로 정렬 -> 한 영상의 단계경계를
      다른 영상 타임라인으로 변환. 학습 불필요(저데이터 OK).

입력 : --ref body.json (기준뷰, 예: 위60°), --tgt body.json (정렬대상, 예: 정면)
출력 : align.json (정렬 품질 + ref경계->tgt시각 매핑) + align.png

usage:
  python pose/align_dtw.py --ref results/top60_test/body.json --tgt results/seg_test/body_full.json \
      --ref-segs results/top60_test/segments.json --out-dir results/align
"""
import argparse
import json
from pathlib import Path

import numpy as np

from segment import smooth, wrist_xy   # 모듈 재사용 (One-Euro 평활, 손목좌표)


def speed_profile(body_json, N=400):
    d = json.loads(Path(body_json).read_text(encoding="utf-8"))
    fps = d["fps"]; stride = d.get("stride", 1); eff = fps / stride
    import math
    sw = []
    for fr in d["frames"]:
        if fr["num_persons"] > 0:
            k = fr["persons"][0]["keypoints"]
            ls, rs = k["left_shoulder"], k["right_shoulder"]
            if ls["conf"] > 0.3 and rs["conf"] > 0.3:
                sw.append(math.hypot(ls["x"] - rs["x"], ls["y"] - rs["y"]))
    scale = float(np.median(sw)) if sw else 1.0
    vs = []
    for name in ("left_wrist", "right_wrist"):
        x, y = wrist_xy(d, name)
        xs = smooth(x / scale, eff); ys = smooth(y / scale, eff)
        vs.append(np.sqrt(np.diff(xs) ** 2 + np.diff(ys) ** 2) * eff)
    sp = smooth(np.mean(vs, axis=0), eff, 0.5, 0.01)
    dur = len(sp) * stride / fps
    # 고정길이 N으로 리샘플(정렬 속도/안정)
    t = np.linspace(0, 1, len(sp)); tn = np.linspace(0, 1, N)
    spN = np.interp(tn, t, sp)
    spN = (spN - spN.mean()) / (spN.std() + 1e-9)   # z-정규화(관점 무관)
    return spN, dur


def dtw(a, b):
    n, m = len(a), len(b)
    D = np.full((n + 1, m + 1), np.inf); D[0, 0] = 0.0
    for i in range(1, n + 1):
        ai = a[i - 1]
        for j in range(1, m + 1):
            c = abs(ai - b[j - 1])
            D[i, j] = c + min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
    # 백트래킹
    path = []; i, j = n, m
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        s = np.argmin([D[i - 1, j - 1], D[i - 1, j], D[i, j - 1]])
        if s == 0: i, j = i - 1, j - 1
        elif s == 1: i -= 1
        else: j -= 1
    path.reverse()
    return D[n, m] / (n + m), path     # 정규화 거리, 정렬경로


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--tgt", required=True)
    ap.add_argument("--ref-segs", default=None)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--N", type=int, default=400)
    args = ap.parse_args()
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)

    rs, rdur = speed_profile(args.ref, args.N)
    ts, tdur = speed_profile(args.tgt, args.N)
    dist, path = dtw(rs, ts)

    # ref 인덱스 -> tgt 인덱스 매핑(평균)
    ref2tgt = {}
    for ri, tj in path:
        ref2tgt.setdefault(ri, []).append(tj)
    ref2tgt = {ri: np.mean(tj) for ri, tj in ref2tgt.items()}

    def ref_time_to_tgt(t_ref):
        ri = int(round(t_ref / rdur * (args.N - 1)))
        ri = max(0, min(args.N - 1, ri))
        tj = ref2tgt.get(ri, ri)
        return round(tj / (args.N - 1) * tdur, 1)

    mapped = []
    if args.ref_segs and Path(args.ref_segs).exists():
        segs = json.loads(Path(args.ref_segs).read_text(encoding="utf-8"))["segments"]
        for s in segs:
            mapped.append({"ref_t": s["t_start"], "tgt_t": ref_time_to_tgt(s["t_start"])})

    quality = "양호(잘 정렬됨)" if dist < 0.5 else ("보통" if dist < 1.0 else "낮음(정렬 어려움)")
    res = {"ref": args.ref, "tgt": args.tgt, "ref_dur": round(rdur, 1), "tgt_dur": round(tdur, 1),
           "dtw_distance_normalized": round(float(dist), 3), "alignment_quality": quality,
           "ref_boundary_to_tgt": mapped}
    (out / "align.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    # 시각화
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        plt.figure(figsize=(11, 4))
        plt.plot(np.linspace(0, rdur, args.N), rs, label="ref (위60°)", lw=0.9)
        plt.plot(np.linspace(0, tdur, args.N), ts, label="tgt (정면)", lw=0.9, alpha=0.8)
        plt.title(f"DTW 정렬 — 정규화거리 {dist:.3f} ({quality})")
        plt.xlabel("time (s)"); plt.ylabel("z-정규화 손목속도"); plt.legend()
        plt.tight_layout(); plt.savefig(out / "align.png", dpi=90); plt.close()
    except Exception as e:
        print("[warn] plot skip:", e)

    print(f"[done] DTW 정규화거리 = {dist:.3f} ({quality})")
    print(f"  ref({rdur:.0f}s) <-> tgt({tdur:.0f}s)")
    for m in mapped:
        print(f"  위60° {m['ref_t']:5.1f}s  ->  정면 {m['tgt_t']:5.1f}s")
    print(f"[done] -> {out/'align.json'}, {out/'align.png'}")


if __name__ == "__main__":
    main()
