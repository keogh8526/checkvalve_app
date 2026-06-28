"""
구간분할 평가 — AI 분할(segment/fuse) 경계 vs 사람 정답(ground_truth) 경계를 영상별로 대조.
"AI가 공정 구간을 얼마나 잘 나누는가"를 숫자로 (경계오차·과소/과분할·매칭율).

입력 : --gt data/ground_truth.csv  --seg <segments.json 또는 fused_segments.json>  --video <이름>
출력 : 경계오차(평균/중앙), ±tol초 매칭율, 정답경계수 vs 예측경계수(과소/과분할)

usage:
  python pose/eval_segmentation.py --gt data/ground_truth.csv --seg results/all/front_fast/segments.json --video front_fast
  python pose/eval_segmentation.py --gt data/ground_truth.csv --seg results/all/fused_segments.json --video front_fast
"""
import argparse
import csv
import json
from pathlib import Path


def gt_boundaries(path, video):
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8"))
            if r["video"].strip() == video]
    b = set()
    for r in rows:
        b.add(round(float(r["t_start"]), 1)); b.add(round(float(r["t_end"]), 1))
    return sorted(b), rows


def seg_boundaries(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    segs = d.get("sectors") or d.get("segments")
    b = set()
    for s in segs:
        b.add(round(s["t_start"], 1)); b.add(round(s["t_end"], 1))
    return sorted(b)


def match(gt, pred, tol):
    """정답 경계마다 가장 가까운 예측까지 거리 + tol내 매칭/누락."""
    errs, matched = [], 0
    for g in gt:
        e = min(abs(g - p) for p in pred)
        errs.append(e); matched += (e <= tol)
    # 과분할: 정답 경계와 멀리 떨어진 예측 경계(여분)
    spurious = sum(1 for p in pred if min(abs(p - g) for g in gt) > tol)
    return errs, matched, spurious


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", required=True)
    ap.add_argument("--seg", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--tol", type=float, default=2.0)
    args = ap.parse_args()

    gt, gtrows = gt_boundaries(args.gt, args.video)
    if not gt:
        raise SystemExit(f"[err] 정답에 video={args.video} 없음")
    pred = seg_boundaries(args.seg)
    errs, matched, spurious = match(gt, pred, args.tol)
    mean_e = sum(errs) / len(errs)
    med_e = sorted(errs)[len(errs) // 2]

    print(f"=== 구간분할 평가 [{args.video}] ===")
    print(f"  소스: {Path(args.seg).name}")
    print(f"  정답 경계 {len(gt)}개 / 예측 경계 {len(pred)}개", end="")
    print(f"  → {'과분할' if len(pred) > len(gt)+1 else ('과소분할' if len(pred) < len(gt)-1 else '적정')}")
    print(f"  경계오차: 평균 {mean_e:.2f}s · 중앙 {med_e:.2f}s")
    print(f"  ±{args.tol}s 매칭율: {matched}/{len(gt)} = {matched/len(gt)*100:.0f}%")
    print(f"  여분(과분할) 경계: {spurious}개")
    print(f"  정답경계: {gt}")
    print(f"  예측경계: {pred}")


if __name__ == "__main__":
    main()
