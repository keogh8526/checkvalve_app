"""
정직한 평가 프로토콜 — 기존 ±2s '최근접 매칭'의 중복카운트 부풀림을 제거한다.
멀티에이전트 만장일치 1순위: "부풀린 수치부터 바로잡아야 모든 개선이 의미있다."

개선점:
  (1) Hungarian 1:1 경계매칭 — 예측 1개가 정답 2~3개를 동시매칭하던 중복카운트 제거(scipy)
  (2) ±1s / ±2s 병기 — 관대(±2s)와 엄격(±1s)을 함께 보고
  (3) precision / recall / F1 — recall만 자랑하던 것 교정(여분경계=낮은 precision 노출)
  (4) 라벨 정확도(granularity 공정) — AI 섹터 중앙시각이 속한 정답단계와 라벨 일치

usage:
  python pose/eval_honest.py --gt data/ground_truth.csv --seg results/all/fused_segments.json --video front_fast [--steps results/all/steps.json]
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment


def gt_rows(path, video):
    return [r for r in csv.DictReader(open(path, encoding="utf-8")) if r["video"].strip() == video]


def bounds_of(items, ks="t_start", ke="t_end"):
    b = set()
    for s in items:
        b.add(round(float(s[ks]), 1)); b.add(round(float(s[ke]), 1))
    sb = sorted(b)
    # 전역 시작(≈0)·끝(≈T) 경계는 GT·예측이 항상 공유하는 자명매칭 → 제외(P/R 부풀림 방지)
    return sb[1:-1] if len(sb) >= 2 else []


def hungarian_match(gt, pred, tol):
    """경계를 1:1 매칭하되 'tol 이내 매칭 개수를 최대화'한다.
    주의: 최소비용할당(linear_sum_assignment(거리))은 전체비용 최소화라, tol 밖의
    가까운 쌍에 매칭을 낭비해 유효매칭을 과소계산할 수 있다 → tol내=보상(-1) 행렬로
    최대 카디널리티 매칭을 구한다."""
    if not gt or not pred:
        return 0
    D = np.abs(np.array(gt)[:, None] - np.array(pred)[None, :])
    within = D <= tol
    cost = np.where(within, -1.0, 0.0)        # tol내 매칭 1개당 -1 → 합 최소화=매칭수 최대화
    ri, ci = linear_sum_assignment(cost)
    return int(sum(1 for r, c in zip(ri, ci) if within[r, c]))


def prf(matched, n_gt, n_pred):
    rec = matched / n_gt if n_gt else 0
    pre = matched / n_pred if n_pred else 0
    f1 = 2 * pre * rec / (pre + rec) if (pre + rec) else 0
    return pre, rec, f1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", required=True)
    ap.add_argument("--seg", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--steps", default=None, help="라벨 평가용 steps.json(공정단계 포함)")
    args = ap.parse_args()

    gt = gt_rows(args.gt, args.video)
    if not gt:
        raise SystemExit(f"[err] GT에 video={args.video} 없음")
    segd = json.loads(Path(args.seg).read_text(encoding="utf-8"))
    segs = segd.get("sectors") or segd.get("segments")
    gtb, pb = bounds_of(gt), bounds_of(segs)

    print(f"=== 정직한 평가 [{args.video}] · {Path(args.seg).name} ===")
    print(f"  정답 경계 {len(gtb)}개 / 예측 경계 {len(pb)}개")
    print(f"  {'기준':6} {'매칭(1:1)':10} {'정밀도':7} {'재현율':7} {'F1':6}")
    for tol in (1.0, 2.0):
        m = hungarian_match(gtb, pb, tol)
        pre, rec, f1 = prf(m, len(gtb), len(pb))
        print(f"  ±{tol:.0f}s   {m:>3}/{len(gtb):<3}      {pre*100:5.0f}%  {rec*100:5.0f}%  {f1*100:5.0f}%")
    print("  (기존 '최근접 매칭'은 예측1개가 정답 여러개를 중복매칭 → 위 1:1이 진짜값)")

    # 라벨 정확도(granularity 공정): AI 섹터 중앙 → 정답단계 라벨 일치
    if args.steps and Path(args.steps).exists():
        steps = json.loads(Path(args.steps).read_text(encoding="utf-8"))["steps"]

        def gtlabel(t):
            for g in gt:
                if float(g["t_start"]) <= t < float(g["t_end"]):
                    return g["표준단계"]
            return None
        hit = tot = 0
        for s in steps:
            mid = (s["t_start"] + s["t_end"]) / 2
            truth = gtlabel(mid)
            if truth:
                tot += 1; hit += (truth == s.get("공정단계"))
        if tot:
            print(f"  라벨 정확도(중앙시각 기준): {hit}/{tot} = {hit/tot*100:.0f}%")


if __name__ == "__main__":
    main()
