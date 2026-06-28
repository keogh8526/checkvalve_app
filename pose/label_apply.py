"""
본선 라벨 적용 — fused 섹터에 DINOv2 공정5 슈퍼라벨(검증 최선, 평균67%)을 붙인다.
규칙라벨(22%) 대비 검증된 최선 방법. 프로토타입=정답 있는 빠른영상(LOVO 권장).

usage:
  python pose/label_apply.py --fused results/all/fused_segments.json \
      --target-video data/front/...49.mp4 --gt data/ground_truth.csv \
      --proto front_fast,top60_fast,hand_fast --self front_fast --out-json results/all/sector_labels.json
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

from label_superlabel import SUPER, SUPER_ORDER, embed, gt_map, prototypes, VIDEO_PATHS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fused", required=True)
    ap.add_argument("--target-video", required=True, help="섹터 타이밍의 기준(빠른) 영상 파일")
    ap.add_argument("--gt", required=True)
    ap.add_argument("--proto", required=True, help="프로토타입 영상 이름들(쉼표)")
    ap.add_argument("--self", default=None, help="LOVO: 프로토타입에서 제외할 자기 영상")
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent

    gt = gt_map(args.gt)
    proto_vids = [v for v in args.proto.split(",") if v != args.self and v in gt]
    proto = prototypes(gt, proto_vids, root, super_label=True)
    labels = [l for l in SUPER_ORDER if l in proto]
    P = np.stack([proto[l] for l in labels])

    fu = json.loads(Path(args.fused).read_text(encoding="utf-8"))
    sectors = fu["sectors"]
    out = []
    for s in sectors:
        mid = (s["t_start"] + s["t_end"]) / 2
        e = embed(args.target_video, mid)
        if e is None:
            out.append({"t_start": s["t_start"], "t_end": s["t_end"], "공정": "미상", "신뢰도": 0.0}); continue
        sims = P @ e
        k = int(np.argmax(sims))
        # 신뢰도 = softmax 최댓값(검수 라우팅용)
        ex = np.exp(sims - sims.max()); conf = float(ex[k] / ex.sum())
        out.append({"t_start": s["t_start"], "t_end": s["t_end"],
                    "공정": labels[k], "신뢰도": round(conf, 2)})
    Path(args.out_json).write_text(json.dumps(
        {"proto": proto_vids, "method": "DINOv2 공정5 슈퍼라벨", "labels": out},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] DINOv2 슈퍼라벨 {len(out)}섹터 -> {args.out_json}")
    for o in out:
        print(f"  {o['t_start']:5.1f}~{o['t_end']:5.1f}s [{o['공정']}] 신뢰{o['신뢰도']}")


if __name__ == "__main__":
    main()
