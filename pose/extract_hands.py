"""
Hand/finger-focused keypoint extractor using MediaPipe HolisticLandmarker (Tasks API).

Extracts per frame:
  - body pose: 33 landmarks
  - left hand : 21 landmarks (finger joints)
  - right hand: 21 landmarks (finger joints)

Coordinates are stored as pixel [x, y], plus normalized depth z and visibility.
Also renders an annotated video with the body + both-hand skeletons drawn.

Usage:
  python extract_hands.py --video input.mp4
  python extract_hands.py --video input.mp4 --max-frames 100 --no-video
"""

import argparse
import json
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/holistic_landmarker/"
             "holistic_landmarker/float16/latest/holistic_landmarker.task")

POSE_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner",
    "right_eye", "right_eye_outer", "left_ear", "right_ear", "mouth_left",
    "mouth_right", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky", "left_index",
    "right_index", "left_thumb", "right_thumb", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle", "left_heel",
    "right_heel", "left_foot_index", "right_foot_index",
]

HAND_NAMES = [
    "wrist", "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip",
    "index_mcp", "index_pip", "index_dip", "index_tip",
    "middle_mcp", "middle_pip", "middle_dip", "middle_tip",
    "ring_mcp", "ring_pip", "ring_dip", "ring_tip",
    "pinky_mcp", "pinky_pip", "pinky_dip", "pinky_tip",
]

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),          # index
    (5, 9), (9, 10), (10, 11), (11, 12),     # middle
    (9, 13), (13, 14), (14, 15), (15, 16),   # ring
    (13, 17), (17, 18), (18, 19), (19, 20),  # pinky
    (0, 17),                                  # palm
]

POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (27, 31), (29, 31),
    (24, 26), (26, 28), (28, 30), (28, 32), (30, 32),
]


def ensure_model(path: Path):
    if not path.exists():
        print(f"[info] downloading holistic model -> {path}")
        urllib.request.urlretrieve(MODEL_URL, path)
    return path


def lm_list(landmarks, w, h):
    """Convert a MediaPipe landmark list to compact [x_px, y_px, z, vis] rows."""
    if not landmarks:
        return None
    out = []
    for p in landmarks:
        z = round(float(p.z), 4) if p.z is not None else 0.0
        vis = round(float(p.visibility), 3) if p.visibility is not None else 0.0
        out.append([round(p.x * w, 1), round(p.y * h, 1), z, vis])
    return out


def draw_points(img, rows, connections, color, r=3):
    if not rows:
        return
    pts = [(int(x), int(y)) for x, y, *_ in rows]
    for a, b in connections:
        if a < len(pts) and b < len(pts):
            cv2.line(img, pts[a], pts[b], color, 2, cv2.LINE_AA)
    for x, y in pts:
        cv2.circle(img, (x, y), r, color, -1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-video", default=None)
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--downscale", type=float, default=1.0,
                    help="Downscale factor for inference speed (e.g. 0.6). Output stays full-res.")
    args = ap.parse_args()

    video = Path(args.video)
    model = Path(args.model) if args.model else video.with_name("holistic_landmarker.task")
    ensure_model(model)
    out_json = Path(args.out_json) if args.out_json else video.with_name(video.stem + "_hands.json")
    out_video = Path(args.out_video) if args.out_video else video.with_name(video.stem + "_hands.mp4")

    opts = vision.HolisticLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO,
        min_pose_detection_confidence=0.5,
        min_hand_landmarks_confidence=0.5,
    )
    landmarker = vision.HolisticLandmarker.create_from_options(opts)

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"[info] video: {w}x{h} @ {fps:.2f}fps, {total} frames, downscale={args.downscale}")

    writer = None
    if not args.no_video:
        writer = cv2.VideoWriter(str(out_video), cv2.VideoWriter_fourcc(*"mp4v"),
                                 fps / max(args.stride, 1), (w, h))

    frames_out = []
    idx, processed = -1, 0
    n_left = n_right = n_both = 0
    t0 = time.time()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if args.stride > 1 and idx % args.stride != 0:
            continue

        if args.downscale != 1.0:
            small = cv2.resize(frame, None, fx=args.downscale, fy=args.downscale)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = landmarker.detect_for_video(mp_img, int(idx / fps * 1000))

        pose = lm_list(res.pose_landmarks, w, h)
        lh = lm_list(res.left_hand_landmarks, w, h)
        rh = lm_list(res.right_hand_landmarks, w, h)
        if lh:
            n_left += 1
        if rh:
            n_right += 1
        if lh and rh:
            n_both += 1

        frames_out.append({
            "frame": idx,
            "time_sec": round(idx / fps, 3),
            "pose": pose,
            "left_hand": lh,
            "right_hand": rh,
        })

        if writer is not None:
            draw_points(frame, pose, POSE_CONNECTIONS, (0, 200, 255), r=3)      # body: orange
            draw_points(frame, lh, HAND_CONNECTIONS, (80, 255, 80), r=4)         # left hand: green
            draw_points(frame, rh, HAND_CONNECTIONS, (255, 120, 255), r=4)       # right hand: magenta
            writer.write(frame)

        processed += 1
        if processed % 30 == 0:
            el = time.time() - t0
            sp = processed / el if el else 0
            pct = (idx + 1) / total * 100 if total else 0
            print(f"[prog] {idx + 1}/{total} ({pct:5.1f}%)  "
                  f"L={1 if lh else 0} R={1 if rh else 0}  {sp:.1f} fps", flush=True)

        if args.max_frames and processed >= args.max_frames:
            break

    cap.release()
    if writer is not None:
        writer.release()
    landmarker.close()

    el = time.time() - t0
    summary = {
        "video": str(video), "model": "MediaPipe HolisticLandmarker",
        "resolution": [w, h], "fps": round(fps, 3), "total_frames": total,
        "processed_frames": processed, "stride": args.stride, "downscale": args.downscale,
        "pose_landmark_names": POSE_NAMES, "hand_landmark_names": HAND_NAMES,
        "landmark_format": "[x_pixel, y_pixel, z_relative, visibility]",
        "stats": {
            "left_hand_frames": n_left, "right_hand_frames": n_right, "both_hands_frames": n_both,
        },
        "frames": frames_out,
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")

    print("\n=== DONE ===")
    print(f"[done] {processed} frames in {el:.1f}s ({processed / el:.1f} fps)" if el else "")
    print(f"[done] left-hand frames : {n_left}  right-hand frames: {n_right}  both: {n_both}")
    print(f"[done] keypoints JSON   : {out_json}")
    if writer is not None:
        print(f"[done] annotated video  : {out_video}")


if __name__ == "__main__":
    main()
