"""
DINOv2 프레임특징 + 설명영상 프로토타입 1-shot 라벨링 — 규칙(22%)을 영상내용 기반으로 대체.
근거(리서치 2509.21595): DINOv2는 pose식별 동작에 분리도 6.16x. 1-shot 프로토타입(IJCV/CVPR2025).
로컬 MPS, 학습불필요, API불필요.

원리:
  1) 정답 있는 영상(정답셋 ground_truth)의 각 단계 구간에서 프레임 → DINOv2 임베딩 → 단계별 평균 = 프로토타입
  2) 대상 영상의 각 섹터 중앙프레임 → DINOv2 임베딩 → 프로토타입과 코사인 최근접 = 라벨
  주의: 같은 영상으로 프로토타입+평가하면 과적합 → leave-one-video-out(LOVO) 필수.

usage:
  python pose/label_dinov2.py --gt data/ground_truth.csv --proto-videos front_fast,top60_fast \
      --target hand_fast --target-video data/hand_closeup/IMG_3823.MOV --steps results/all/hand_fast/segments.json
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch
import cv2

_MODEL = None
_PROC = None


def _load():
    global _MODEL, _PROC
    if _MODEL is None:
        from transformers import AutoModel, AutoImageProcessor
        _PROC = AutoImageProcessor.from_pretrained("facebook/dinov2-small")
        _MODEL = AutoModel.from_pretrained("facebook/dinov2-small")
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        _MODEL.to(dev).eval()
    return _MODEL, _PROC


def embed_frame(video, t_sec):
    """영상 t초 프레임 → DINOv2 CLS 임베딩(정규화)."""
    model, proc = _load()
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t_sec * fps))
    ok, fr = cap.read(); cap.release()
    if not ok:
        return None
    fr = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
    dev = next(model.parameters()).device
    inp = proc(images=fr, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model(**inp)
    v = out.last_hidden_state[:, 0].cpu().numpy()[0]   # CLS token
    return v / (np.linalg.norm(v) + 1e-9)


def gt_video_map(gt_path):
    rows = list(csv.DictReader(open(gt_path, encoding="utf-8")))
    vids = {}
    for r in rows:
        vids.setdefault(r["video"], []).append(r)
    return vids


# video 이름 → 실제 파일 경로 (manifest 기반)
VIDEO_PATHS = {
    "front_fast": "data/front/KakaoTalk_Video_2026-06-22-17-54-49.mp4",
    "top60_fast": "data/top60/KakaoTalk_Video_2026-06-22-17-15-48.mp4",
    "hand_fast":  "data/hand_closeup/IMG_3823.MOV",
}


def build_prototypes(gt, proto_videos, root):
    """프로토타입 영상들의 단계별 프레임 임베딩 평균."""
    acc = {}
    for v in proto_videos:
        rows = gt.get(v, [])
        for r in rows:
            t = (float(r["t_start"]) + float(r["t_end"])) / 2
            e = embed_frame(root / VIDEO_PATHS[v], t)
            if e is None:
                continue
            acc.setdefault(r["표준단계"], []).append(e)
    return {k: np.mean(vs, axis=0) for k, vs in acc.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", required=True)
    ap.add_argument("--proto-videos", required=True, help="쉼표: 프로토타입 만들 영상(정답 있는)")
    ap.add_argument("--target", required=True, help="라벨 붙일 영상 이름")
    ap.add_argument("--segs", required=True, help="대상 segments.json")
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent

    gt = gt_video_map(args.gt)
    proto = build_prototypes(gt, args.proto_videos.split(","), root)
    labels = list(proto.keys())
    print(f"[proto] {len(labels)}단계 프로토타입: {labels}")

    segs = json.loads(Path(args.segs).read_text(encoding="utf-8"))["segments"]
    tgt_path = root / VIDEO_PATHS[args.target]
    P = np.stack([proto[l] for l in labels])

    # 정답(평가용)
    gtr = gt.get(args.target, [])
    def gtlabel(t):
        for r in gtr:
            if float(r["t_start"]) <= t < float(r["t_end"]): return r["표준단계"]
        return None

    out, hit, tot = [], 0, 0
    for s in segs:
        mid = (s["t_start"] + s["t_end"]) / 2
        e = embed_frame(tgt_path, mid)
        if e is None:
            continue
        sims = P @ e
        pred = labels[int(np.argmax(sims))]
        truth = gtlabel(mid)
        if truth:
            tot += 1; hit += (pred == truth)
        out.append({"t_start": s["t_start"], "t_end": s["t_end"], "공정단계": pred,
                    "정답": truth, "맞음": pred == truth})
        print(f"  {s['t_start']:5.1f}~{s['t_end']:5.1f}s: DINOv2[{pred[:14]:14}] 정답[{(truth or '-')[:14]:14}] {'O' if pred==truth else 'X'}")
    if tot:
        print(f"[done] DINOv2 라벨 정확도 {hit}/{tot} = {hit/tot*100:.0f}% (규칙 22% 대비)")
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
