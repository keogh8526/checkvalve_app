"""
손 키포인트 추출 (rtmlib RTMPose-Hand, ONNX) — MediaPipe 대체 (Python 3.13 호환).
손확대 60fps 영상에서 손가락 21점을 추출해 정밀 미세동작(스프링 끼움·핀 삽입) 분석.

입력 : 손확대 영상 (.MOV/.mp4)
출력 : hands.json (프레임별 손 21점 [x,y,score])

usage:
  python pose/extract_hands_rtm.py --video data/hand_closeup/IMG_3823.MOV \
      --out-json results/hand_test/hands.json --stride 3 --max-frames 60
"""
import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--max-frames", type=int, default=0)
    args = ap.parse_args()

    import onnxruntime as ort
    from rtmlib import Hand
    # mac: CoreML 가능시 사용, 아니면 CPU
    eps = ort.get_available_providers()
    backend = "onnxruntime"
    device = "cpu"
    print(f"[info] onnxruntime EPs: {eps}")

    hand = Hand(mode="lightweight", backend=backend, device=device)  # rtmlib는 현재 lightweight만 지원

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"[info] video {w}x{h} @ {fps:.1f}fps, {total}f")

    out = []
    idx = -1; proc = 0; det = 0; t0 = time.time()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if args.stride > 1 and idx % args.stride != 0:
            continue
        keypoints, scores = hand(frame)   # (N,21,2), (N,21)
        hands_f = []
        if keypoints is not None and len(keypoints) > 0:
            det += 1
            for kp, sc in zip(keypoints, scores):
                hands_f.append({"kpts": [[round(float(x), 1), round(float(y), 1),
                                          round(float(s), 3)] for (x, y), s in zip(kp, sc)]})
        out.append({"frame": idx, "time_sec": round(idx / fps, 3),
                    "num_hands": len(hands_f), "hands": hands_f})
        proc += 1
        if proc % 20 == 0:
            print(f"[prog] {idx+1}/{total} hands={len(hands_f)} {proc/(time.time()-t0):.1f}fps", flush=True)
        if args.max_frames and proc >= args.max_frames:
            break
    cap.release()

    el = time.time() - t0
    res = {"video": args.video, "model": "rtmlib RTMPose-Hand", "resolution": [w, h],
           "fps": round(fps, 3), "stride": args.stride, "processed": proc,
           "frames_with_hand": det, "hand_landmark_count": 21,
           "landmark_format": "[x, y, score]", "frames": out}
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"\n[done] {proc}프레임 {el:.1f}s ({proc/el:.1f}fps), 손검출 {det}/{proc}")
    print(f"[done] -> {args.out_json}")


if __name__ == "__main__":
    main()
