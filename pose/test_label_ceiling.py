"""
테스팅A: 경계를 정답으로 고정하고 라벨만 측정 → 라벨/경계 병목 분리.
경계가 완벽(정답)할 때 DINOv2 라벨이 얼마나 나오는가 = 라벨의 순수 천장.
이게 낮으면 라벨 자체가 한계(경계 고쳐도 소용X), 높으면 경계가 병목(경계 투자 가치).

usage: python pose/test_label_ceiling.py --gt data/ground_truth.csv
"""
import csv
from pathlib import Path
import numpy as np

from label_superlabel import (VIDEO_PATHS, SUPER, SUPER_ORDER, embed, gt_map,
                              prototypes, monotonic_decode)

FINE = ["부품 준비", "정렬(SPRING·SPACER)", "HINGE PIN 조립", "GUIDE 결합",
        "BODY-GUIDE 결합", "SET SCREW 결합", "검사/측정"]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default="data/ground_truth.csv")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    gt_path = args.gt if Path(args.gt).is_absolute() else str(root / args.gt)  # CWD 아닌 root 기준
    gt = gt_map(gt_path)
    print("=== 테스팅A: 경계=정답 고정, 라벨만 측정 (LOVO) ===")
    print("  영상별: [라벨단위 · 디코딩] 정확도")
    agg = {}
    for tgt in [v for v in VIDEO_PATHS if v in gt]:
        proto_vids = [v for v in VIDEO_PATHS if v != tgt and v in gt]   # LOVO
        rows = gt[tgt]
        # 정답 구간 중앙 프레임 임베딩
        embs, fine_truth, super_truth = [], [], []
        for r in rows:
            t = (float(r["t_start"]) + float(r["t_end"])) / 2
            e = embed(root / VIDEO_PATHS[tgt], t)
            if e is None:
                continue
            embs.append(e); fine_truth.append(r["표준단계"]); super_truth.append(SUPER[r["표준단계"]])
        E = np.array(embs)
        for super_label, order, truth, name in [
                (False, FINE, fine_truth, "fine7"),
                (True, SUPER_ORDER, super_truth, "공정5")]:
            proto = prototypes(gt, proto_vids, root, super_label)
            labels = [l for l in order if l in proto]
            P = np.stack([proto[l] for l in labels])
            sims = E @ P.T
            for mode in ["argmax", "monotonic"]:
                pred = ([labels[i] for i in np.argmax(sims, axis=1)] if mode == "argmax"
                        else monotonic_decode(sims, labels))
                hit = sum(1 for p, t in zip(pred, truth) if p == t)
                acc = hit / len(truth) * 100
                print(f"  [{tgt:10} {name:5} {mode:9}] {hit}/{len(truth)} = {acc:4.0f}%")
                agg.setdefault(f"{name}/{mode}", []).append(acc)
    print("\n=== 평균(3영상) ===")
    for k, v in agg.items():
        print(f"  {k:18}: {np.mean(v):4.0f}%")


if __name__ == "__main__":
    main()
