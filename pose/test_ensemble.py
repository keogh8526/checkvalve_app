"""테스팅C: 다신호 앙상블 투표 라벨링.
신호: (1) DINOv2 프로토타입 유사도 (2) 시간순서 prior(공정 단조) (3) 섹터길이 prior
투표(점수합)로 공정5 라벨 → 단일(DINOv2 50%) 대비 비교. 경계=정답 고정(라벨 천장 조건).
usage: python pose/test_ensemble.py
"""
import csv
from pathlib import Path
import numpy as np
from label_superlabel import VIDEO_PATHS, SUPER, SUPER_ORDER, embed, gt_map, prototypes


def main():
    root = Path(".")
    gt = gt_map("data/ground_truth.csv")
    print("=== 테스팅C: 다신호 앙상블 투표 (공정5, 경계=정답) ===")
    agg = {"dino_only": [], "ensemble": []}
    for tgt in [v for v in VIDEO_PATHS if v in gt]:
        proto_vids = [v for v in VIDEO_PATHS if v != tgt and v in gt]   # LOVO
        rows = gt[tgt]
        proto = prototypes(gt, proto_vids, root, super_label=True)
        labels = [l for l in SUPER_ORDER if l in proto]
        P = np.stack([proto[l] for l in labels])
        embs, truth, mids, durs = [], [], [], []
        for r in rows:
            t = (float(r["t_start"]) + float(r["t_end"])) / 2
            e = embed(root / VIDEO_PATHS[tgt], t)
            if e is None:
                continue
            embs.append(e); truth.append(SUPER[r["표준단계"]])
            mids.append(t); durs.append(float(r["t_end"]) - float(r["t_start"]))
        E = np.array(embs); n = len(E)
        dino = E @ P.T                        # 신호1: DINOv2 유사도 [n×K]
        dino = (dino - dino.mean(0)) / (dino.std(0) + 1e-9)
        # 신호2: 시간순서 prior — 섹터 진행도(0~1)를 공정순서 위치에 맞춤
        total = max(mids) if mids else 1
        order_prior = np.zeros((n, len(labels)))
        for i, t in enumerate(mids):
            prog = t / total                  # 0~1
            for k in range(len(labels)):
                center = (k + 0.5) / len(labels)
                order_prior[i, k] = -abs(prog - center)   # 진행도-순서위치 가까울수록 +
        order_prior = (order_prior - order_prior.mean(0)) / (order_prior.std(0) + 1e-9)
        # 신호3: 길이 prior — 공정8이 보통 최장
        len_prior = np.zeros((n, len(labels)))
        if "공정8(DISC·SPACER·HINGE PIN 조립)" in labels:
            k8 = labels.index("공정8(DISC·SPACER·HINGE PIN 조립)")
            dn = np.array(durs); dn = (dn - dn.mean()) / (dn.std() + 1e-9)
            len_prior[:, k8] = dn             # 긴 섹터일수록 공정8 가점

        for name, score in [("dino_only", dino),
                            ("ensemble", dino + 0.7 * order_prior + 0.5 * len_prior)]:
            pred = [labels[i] for i in np.argmax(score, axis=1)]
            hit = sum(1 for p, t in zip(pred, truth) if p == t)
            acc = hit / n * 100
            agg[name].append(acc)
            print(f"  [{tgt:10} {name:9}] {hit}/{n} = {acc:.0f}%")
    print("\n=== 평균(3영상) ===")
    for k, v in agg.items():
        print(f"  {k:10}: {np.mean(v):.0f}%")


if __name__ == "__main__":
    main()
