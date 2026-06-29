"""
슈퍼라벨(공정5) + 강제단조 DP 라벨링 — 최종 점검에서 도출된 '비용0 최고가치' 수.

핵심(멀티에이전트 최종판정):
  1) 슈퍼라벨: 정답셋 비고열(공정8/9/10/11)로 7세부단계 → 공정5(설명/공정8/공정9/공정10/공정11) 묶음.
     → 부품준비·정렬·HINGE PIN이 전부 '공정8'이라, 못풀던 'HINGE PIN↔정렬 동시진행' 난제가 정의상 소멸.
     → 6영상 전부 '설명→공정8→9→10→11' 완전 단조열이 됨.
  2) 강제단조 DP: DINOv2 프레임유사도 행렬 위에서 '왼→오 단조 + skip허용' 누적유사 최대 경로를
     한 번에 디코딩 → 경계·라벨 동시. 시간순서상 불가능한 라벨(역행)을 구조적으로 차단.
  3) 비교: fine7(세부) vs 공정5(슈퍼) 병기. LOVO로 과적합 정직검증.

usage:
  python pose/label_superlabel.py --gt data/ground_truth.csv --target front_fast
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch
import cv2

VIDEO_PATHS = {
    "front_fast": "data/front/KakaoTalk_Video_2026-06-22-17-54-49.mp4",
    "top60_fast": "data/top60/KakaoTalk_Video_2026-06-22-17-15-48.mp4",
    "hand_fast":  "data/hand_closeup/IMG_3823.MOV",
}
# 세부단계 → 공정 슈퍼라벨 (정답셋 비고열 기준). 공정8 안에 준비/정렬/HINGE PIN.
SUPER = {
    "부품 준비": "공정8(DISC·SPACER·HINGE PIN 조립)",
    "정렬(SPRING·SPACER)": "공정8(DISC·SPACER·HINGE PIN 조립)",
    "HINGE PIN 조립": "공정8(DISC·SPACER·HINGE PIN 조립)",
    "GUIDE 결합": "공정9(GUIDE 결합)",
    "BODY-GUIDE 결합": "공정10(BODY-GUIDE 결합)",
    "SET SCREW 결합": "공정11(SET SCREW 결합)",
    "검사/측정": "공정11(SET SCREW 결합)",   # 검사는 영상 말미, 공정11에 흡수
}
SUPER_ORDER = ["공정8(DISC·SPACER·HINGE PIN 조립)", "공정9(GUIDE 결합)",
               "공정10(BODY-GUIDE 결합)", "공정11(SET SCREW 결합)"]

_M = _P = None


def _load():
    global _M, _P
    if _M is None:
        from transformers import AutoModel, AutoImageProcessor
        _P = AutoImageProcessor.from_pretrained("facebook/dinov2-small")
        _M = AutoModel.from_pretrained("facebook/dinov2-small")
        _M.to("mps" if torch.backends.mps.is_available() else "cpu").eval()
    return _M, _P


def embed(video, t):
    m, p = _load()
    cap = cv2.VideoCapture(str(video)); fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps)); ok, fr = cap.read(); cap.release()
    if not ok:
        return None
    fr = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
    dev = next(m.parameters()).device
    with torch.no_grad():
        v = m(**p(images=fr, return_tensors="pt").to(dev)).last_hidden_state[:, 0].cpu().numpy()[0]
    return v / (np.linalg.norm(v) + 1e-9)


def gt_map(path):
    vids = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        vids.setdefault(r["video"], []).append(r)
    return vids


def prototypes(gt, proto_vids, root, super_label=True):
    """프로토타입 영상들의 (슈퍼)단계별 임베딩 평균."""
    acc = {}
    for v in proto_vids:
        for r in gt.get(v, []):
            t = (float(r["t_start"]) + float(r["t_end"])) / 2
            e = embed(root / VIDEO_PATHS[v], t)
            if e is None:
                continue
            key = SUPER[r["표준단계"]] if super_label else r["표준단계"]
            acc.setdefault(key, []).append(e)
    return {k: np.mean(vs, axis=0) for k, vs in acc.items()}


def monotonic_decode(sims, order):
    """sims[프레임×단계] + 단계순서 → 강제단조(머무르기/다음/skip) 최대 경로 DP. 라벨열 반환."""
    T, K = sims.shape
    NEG = -1e9
    dp = np.full((T, K), NEG); bk = np.zeros((T, K), int)
    dp[0, 0] = sims[0, 0]                       # 첫 프레임은 첫 단계에서 시작
    for t in range(1, T):
        for k in range(K):
            best, arg = NEG, k
            for pk in range(0, k + 1):          # 같은단계 유지 또는 이전 단계들에서 전이(skip 허용)
                if dp[t - 1, pk] + sims[t, k] > best:
                    best, arg = dp[t - 1, pk] + sims[t, k], pk
            dp[t, k] = best; bk[t, k] = arg
    k = int(np.argmax(dp[T - 1])); path = [k]
    for t in range(T - 1, 0, -1):
        k = bk[t, k]; path.append(k)
    path.reverse()
    return [order[i] for i in path]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--stride-sec", type=float, default=2.0)
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    gt = gt_map(args.gt)
    proto_vids = [v for v in VIDEO_PATHS if v != args.target and v in gt]  # LOVO
    tgt = root / VIDEO_PATHS[args.target]

    # 대상 영상 프레임 샘플 임베딩
    cap = cv2.VideoCapture(str(tgt)); fps = cap.get(cv2.CAP_PROP_FPS) or 30
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps; cap.release()
    times = list(np.arange(0, dur, args.stride_sec))
    embs = [embed(tgt, t) for t in times]
    keep = [(t, e) for t, e in zip(times, embs) if e is not None]
    times = [t for t, _ in keep]; E = np.array([e for _, e in keep])

    def gtlabel(t, super_label):
        for r in gt[args.target]:
            if float(r["t_start"]) <= t < float(r["t_end"]):
                return SUPER[r["표준단계"]] if super_label else r["표준단계"]
        return None

    print(f"=== {args.target} · LOVO(proto={proto_vids}) ===")
    for super_label, order, name in [
            (False, ["부품 준비", "정렬(SPRING·SPACER)", "HINGE PIN 조립", "GUIDE 결합",
                     "BODY-GUIDE 결합", "SET SCREW 결합", "검사/측정"], "fine7"),
            (True, SUPER_ORDER, "공정5")]:
        proto = prototypes(gt, proto_vids, root, super_label)
        labels = [l for l in order if l in proto]            # 프로토타입 있는 단계만
        P = np.stack([proto[l] for l in labels])
        sims = E @ P.T                                        # [프레임×단계]
        # (a) 독립 argmax  (b) 강제단조 DP
        for mode in ["argmax", "monotonic"]:
            if mode == "argmax":
                pred = [labels[i] for i in np.argmax(sims, axis=1)]
            else:
                pred = monotonic_decode(sims, labels)
            hit = tot = 0
            for t, pr in zip(times, pred):
                tr = gtlabel(t, super_label)
                if tr:
                    tot += 1; hit += (pr == tr)
            print(f"  [{name:5} · {mode:9}] {hit}/{tot} = {hit/tot*100:4.0f}%")


if __name__ == "__main__":
    main()
