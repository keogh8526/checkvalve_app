"""
정확도 평가 — 사용자 정답셋(ground_truth.csv) vs 파이프라인 산출(steps.json)을 대조해
(1) 경계오차(초) (2) 단계 분류 정확도를 숫자로 낸다. (L-e 측정: UNMEASURED → 측정)

정답셋 양식: data/ground_truth.template.csv 참고. '#'·'예시' 행은 무시.
컬럼: video,t_start,t_end,표준단계,사용재료_부품,행위_동작,공구,비고

usage:
  python pose/evaluate_accuracy.py --gt data/ground_truth.csv \
      --steps results/all/steps.json --video front_fast
"""
import argparse
import csv
import json
from pathlib import Path


def load_gt(path, video=None):
    rows = []
    for r in csv.DictReader(l for l in Path(path).read_text(encoding="utf-8").splitlines()
                            if not l.strip().startswith("#") and l.strip()):
        if (r.get("비고") or "").strip() == "예시":
            continue
        if video and r.get("video", "").strip() != video:
            continue
        try:
            rows.append({"t_start": float(r["t_start"]), "t_end": float(r["t_end"]),
                         "step": r["표준단계"].strip()})
        except (ValueError, KeyError):
            continue
    return sorted(rows, key=lambda x: x["t_start"])


def boundaries(items):
    b = set()
    for s in items:
        b.add(round(s["t_start"], 1)); b.add(round(s["t_end"], 1))
    return sorted(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", required=True)
    ap.add_argument("--steps", required=True)
    ap.add_argument("--video", default=None, help="GT에서 이 video 행만 사용")
    args = ap.parse_args()

    gt = load_gt(args.gt, args.video)
    if not gt:
        raise SystemExit("[err] 정답셋이 비었습니다. data/ground_truth.csv를 채우세요(예시행 제외).")
    pred = json.loads(Path(args.steps).read_text(encoding="utf-8"))["steps"]

    # (1) 경계오차: GT 경계마다 가장 가까운 예측 경계까지 거리(초)
    gb, pb = boundaries(gt), boundaries(pred)
    errs = [min(abs(g - p) for p in pb) for g in gb]
    mean_err = sum(errs) / len(errs)
    within2 = sum(1 for e in errs if e <= 2.0) / len(errs) * 100

    # (2) 단계 분류 정확도: 예측 섹터 중앙시각이 속한 GT 단계명과 일치?
    def gt_label(t):
        for g in gt:
            if g["t_start"] <= t < g["t_end"]:
                return g["step"]
        return None
    hit = tot = 0
    detail = []
    for s in pred:
        mid = (s["t_start"] + s["t_end"]) / 2
        truth = gt_label(mid)
        got = s.get("공정단계")
        if truth is None:
            continue
        tot += 1; ok = (truth == got); hit += ok
        detail.append((s["step"], round(mid, 1), got, truth, ok))
    acc = hit / tot * 100 if tot else 0

    print(f"=== 정확도 평가 (GT {len(gt)}단계 vs 예측 {len(pred)}섹터) ===")
    print(f"[경계오차] 평균 {mean_err:.2f}s | ±2s 이내 {within2:.0f}%")
    print(f"[단계 분류 정확도] {acc:.0f}% ({hit}/{tot})")
    print("--- 섹터별 (예측 vs 정답) ---")
    for st, mid, got, truth, ok in detail:
        print(f"  섹터{st} @{mid:5.1f}s: 예측 [{got}] vs 정답 [{truth}] {'✓' if ok else '✗'}")


if __name__ == "__main__":
    main()
