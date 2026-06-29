"""
DINOv2 프레임변화 경계신호 — 손위치(운동) 채널이 못 잡는 '외형/장면 변화' 경계를 보강.
근거(리서치 2509.21595): DINOv2 프레임특징은 pose식별 동작 분리도 6.16x. 속도무변 정밀단계 경계 포착.

원리: 영상을 일정 간격 프레임 → DINOv2 임베딩 → 인접프레임 코사인거리 시계열 = '변화신호'.
      이 신호의 피크가 단계 전환 후보(부품 바뀜/도구 바뀜 = 외형 점프).
출력: dino_signal.json {times[], change[]} → segment에 채널로 합류 가능.

usage:
  python pose/dino_boundary.py --video data/front/...49.mp4 --out-json results/all/front_fast/dino.json --stride-sec 1.0
"""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
import cv2

_M = _P = None


def _load():
    global _M, _P
    if _M is None:
        from transformers import AutoModel, AutoImageProcessor
        _P = AutoImageProcessor.from_pretrained("facebook/dinov2-small")
        _M = AutoModel.from_pretrained("facebook/dinov2-small")
        _M.to("mps" if torch.backends.mps.is_available() else "cpu").eval()
    return _M, _P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--stride-sec", type=float, default=1.0, help="샘플 간격(초)")
    args = ap.parse_args()

    model, proc = _load()
    dev = next(model.parameters()).device
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(args.stride_sec * fps))

    times, embs = [], []
    for f in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, fr = cap.read()
        if not ok:
            break
        fr = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
        inp = proc(images=fr, return_tensors="pt").to(dev)
        with torch.no_grad():
            v = model(**inp).last_hidden_state[:, 0].cpu().numpy()[0]
        embs.append(v / (np.linalg.norm(v) + 1e-9))
        times.append(round(f / fps, 2))
    cap.release()

    embs = np.array(embs)
    # 인접 코사인거리 = 변화신호 (1 - 유사도)
    change = [0.0] + [float(1 - np.dot(embs[i], embs[i - 1])) for i in range(1, len(embs))]
    Path(args.out_json).write_text(json.dumps(
        {"video": args.video, "stride_sec": args.stride_sec,
         "times": times, "change": change}, ensure_ascii=False), encoding="utf-8")
    # 변화 피크(상위) = 경계후보
    arr = np.array(change)
    thr = float(np.mean(arr) + np.std(arr))
    peaks = [times[i] for i in range(len(arr)) if arr[i] > thr]
    print(f"[done] DINOv2 변화신호 {len(times)}샘플 -> {args.out_json}")
    print(f"  변화피크(경계후보, >평균+1σ): {[round(p) for p in peaks]}")


if __name__ == "__main__":
    main()
