"""
Render an annotated skeleton video from already-extracted keypoint JSONs
(no re-inference). Overlays YOLO body (cyan) + MediaPipe hands (green/magenta).

Usage:
  python render_overlay.py --video in.mp4 --body-json body.json --hands-json hands.json --out out.mp4
"""
import argparse, json
from pathlib import Path
import cv2

YOLO_NAMES = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder",
              "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
              "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]

COCO_CONNECTIONS = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12),
                    (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]

HAND_CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
                    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15),
                    (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]


def draw_body(img, person):
    pts, ok = [], []
    for name in YOLO_NAMES:
        kp = person["keypoints"][name]
        pts.append((int(kp["x"]), int(kp["y"])))
        ok.append(kp["conf"] >= 0.3)
    for a, b in COCO_CONNECTIONS:
        if ok[a] and ok[b]:
            cv2.line(img, pts[a], pts[b], (255, 255, 0), 2, cv2.LINE_AA)
    for i, p in enumerate(pts):
        if ok[i]:
            cv2.circle(img, p, 4, (255, 255, 0), -1, cv2.LINE_AA)


def draw_hand(img, rows, color):
    if not rows:
        return
    pts = [(int(x), int(y)) for x, y, *_ in rows]
    for a, b in HAND_CONNECTIONS:
        cv2.line(img, pts[a], pts[b], color, 2, cv2.LINE_AA)
    for p in pts:
        cv2.circle(img, p, 3, color, -1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--body-json", required=True)
    ap.add_argument("--hands-json", default=None, help="없으면 몸 스켈레톤만 그림")
    ap.add_argument("--out", required=True)
    ap.add_argument("--debug-text", action="store_true", help="프레임번호 디버그 텍스트 표시")
    args = ap.parse_args()

    body = json.loads(Path(args.body_json).read_text(encoding="utf-8"))
    body_by = {f["frame"]: f for f in body["frames"]}
    hands_by = {}
    if args.hands_json and Path(args.hands_json).exists():
        hands = json.loads(Path(args.hands_json).read_text(encoding="utf-8"))
        hands_by = {f["frame"]: f for f in hands["frames"]}

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    print(f"[render] {Path(args.video).name}: {w}x{h} {total}f -> {args.out}", flush=True)

    idx = 0
    try:
        while True:
            ok, img = cap.read()
            if not ok:
                break
            bf = body_by.get(idx)
            if bf:
                for person in bf.get("persons", []):
                    draw_body(img, person)
            hf = hands_by.get(idx)
            if hf:
                draw_hand(img, hf.get("left_hand"), (80, 255, 80))     # green
                draw_hand(img, hf.get("right_hand"), (255, 120, 255))  # magenta
            if args.debug_text:
                cv2.putText(img, f"f{idx}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                            (0, 0, 255), 2, cv2.LINE_AA)
            writer.write(img)
            idx += 1
            if idx % 500 == 0:
                print(f"[render]   {idx}/{total}", flush=True)
    finally:
        cap.release()
        writer.release()
    print(f"[render] DONE {args.out} ({idx} frames)", flush=True)


if __name__ == "__main__":
    main()
