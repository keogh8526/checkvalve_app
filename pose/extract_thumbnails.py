"""
대표프레임 썸네일 추출 — steps.json의 각 섹터 중앙 시각에서 영상 프레임 1장을 뽑는다(L-c).
작업지도서에 '시각 근거(사진)'를 넣기 위함. 타이밍 소스(빠른조작영상)에서 추출.

입력 : --steps steps.json (t_start/t_end 보유) --video 타이밍영상
출력 : <out-dir>/sec_<n>.jpg (섹터별 1장) + steps.json에 thumb 경로 주입(--write 시)

usage:
  python pose/extract_thumbnails.py --steps results/all/steps.json \
      --video data/front/KakaoTalk_Video_2026-06-22-17-54-49.mp4 --out-dir results/all/thumbs --write
"""
import argparse
import json
from pathlib import Path

import cv2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--write", action="store_true", help="steps.json에 thumb 상대경로 주입")
    ap.add_argument("--max-w", type=int, default=320, help="썸네일 가로 최대(px)")
    args = ap.parse_args()

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    d = json.loads(Path(args.steps).read_text(encoding="utf-8"))
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"영상 열기 실패: {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    n = 0
    for s in d["steps"]:
        mid = (s.get("t_start", 0) + s.get("t_end", 0)) / 2.0
        fidx = min(total - 1, max(0, int(mid * fps)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        if w > args.max_w:
            nh = int(h * args.max_w / w)
            frame = cv2.resize(frame, (args.max_w, nh))
        fn = out / f"sec_{s['step']}.jpg"
        cv2.imwrite(str(fn), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        s["대표프레임"] = f"thumbs/sec_{s['step']}.jpg"   # html과 같은 폴더 기준 상대경로
        n += 1
    cap.release()

    if args.write:
        Path(args.steps).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] 썸네일 {n}장 -> {out} ({'steps.json 주입' if args.write else '미주입'})")


if __name__ == "__main__":
    main()
