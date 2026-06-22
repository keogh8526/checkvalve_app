"""
Pose estimation keypoint extractor using Ultralytics YOLO11-pose.

- Runs a high-accuracy pose model on a video (GPU-accelerated when available).
- Extracts COCO 17 keypoints (x, y, confidence) per detected person per frame.
- Saves results to JSON and writes an annotated skeleton-overlay video.

Usage:
    python extract_pose.py --video "KakaoTalk_20260606_170526928.mp4"
    python extract_pose.py --video input.mp4 --model yolo11x-pose.pt --conf 0.5
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO

# COCO-17 keypoint names, in the order YOLO returns them.
KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]


def parse_args():
    p = argparse.ArgumentParser(description="Extract pose keypoints from a video.")
    p.add_argument("--video", required=True, help="Path to the input video.")
    p.add_argument("--model", default="yolo11x-pose.pt",
                   help="Ultralytics pose model (auto-downloaded). "
                        "Accuracy: yolo11x > l > m > s > n.")
    p.add_argument("--conf", type=float, default=0.5, help="Detection confidence threshold.")
    p.add_argument("--out-json", default=None, help="Output JSON path (default: <video>_keypoints.json).")
    p.add_argument("--out-video", default=None, help="Annotated video path (default: <video>_pose.mp4).")
    p.add_argument("--no-video", action="store_true", help="Skip writing the annotated video.")
    p.add_argument("--stride", type=int, default=1, help="Process every Nth frame (1 = all frames).")
    p.add_argument("--max-frames", type=int, default=0, help="Stop after N processed frames (0 = no limit).")
    return p.parse_args()


def main():
    args = parse_args()
    video_path = Path(args.video)
    if not video_path.exists():
        raise SystemExit(f"Video not found: {video_path}")

    out_json = Path(args.out_json) if args.out_json else video_path.with_name(video_path.stem + "_keypoints.json")
    out_video = Path(args.out_video) if args.out_video else video_path.with_name(video_path.stem + "_pose.mp4")

    if torch.cuda.is_available():
        device, gpu_name = "cuda", torch.cuda.get_device_name(0)
    elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        device, gpu_name = "mps", "Apple MPS"
    else:
        device, gpu_name = "cpu", "CPU"
    print(f"[info] device   : {device} ({gpu_name})")
    print(f"[info] model    : {args.model}")

    model = YOLO(args.model)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"[info] video    : {width}x{height} @ {fps:.2f}fps, {total} frames")

    writer = None
    if not args.no_video:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out_fps = fps / max(args.stride, 1)
        writer = cv2.VideoWriter(str(out_video), fourcc, out_fps, (width, height))

    frames_data = []
    frame_idx = -1
    processed = 0
    t0 = time.time()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        if args.stride > 1 and frame_idx % args.stride != 0:
            continue

        results = model.predict(frame, conf=args.conf, device=device, verbose=False)
        r = results[0]

        persons = []
        if r.keypoints is not None and r.keypoints.data is not None and len(r.keypoints.data) > 0:
            kpts = r.keypoints.data.cpu().numpy()  # [N, 17, 3] -> x, y, conf
            boxes = r.boxes.xyxy.cpu().numpy() if r.boxes is not None else None
            box_conf = r.boxes.conf.cpu().numpy() if r.boxes is not None else None
            for i, person_kpts in enumerate(kpts):
                keypoints = {
                    name: {
                        "x": round(float(person_kpts[j][0]), 2),
                        "y": round(float(person_kpts[j][1]), 2),
                        "conf": round(float(person_kpts[j][2]), 4),
                    }
                    for j, name in enumerate(KEYPOINT_NAMES)
                }
                persons.append({
                    "person_id": i,
                    "box": [round(float(v), 2) for v in boxes[i]] if boxes is not None else None,
                    "box_conf": round(float(box_conf[i]), 4) if box_conf is not None else None,
                    "keypoints": keypoints,
                })

        frames_data.append({
            "frame": frame_idx,
            "time_sec": round(frame_idx / fps, 3),
            "num_persons": len(persons),
            "persons": persons,
        })

        if writer is not None:
            writer.write(r.plot())

        processed += 1
        if processed % 30 == 0:
            elapsed = time.time() - t0
            speed = processed / elapsed if elapsed > 0 else 0
            pct = (frame_idx + 1) / total * 100 if total else 0
            print(f"[prog] frame {frame_idx + 1}/{total} ({pct:5.1f}%)  "
                  f"persons={len(persons)}  {speed:.1f} fps", flush=True)

        if args.max_frames and processed >= args.max_frames:
            break

    cap.release()
    if writer is not None:
        writer.release()

    elapsed = time.time() - t0
    summary = {
        "video": str(video_path),
        "model": args.model,
        "device": device,
        "gpu": gpu_name,
        "resolution": [width, height],
        "fps": round(fps, 3),
        "total_frames": total,
        "processed_frames": processed,
        "stride": args.stride,
        "keypoint_names": KEYPOINT_NAMES,
        "frames": frames_data,
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== DONE ===")
    print(f"[done] processed {processed} frames in {elapsed:.1f}s "
          f"({processed / elapsed:.1f} fps avg)" if elapsed > 0 else "")
    print(f"[done] keypoints JSON : {out_json}")
    if writer is not None:
        print(f"[done] annotated video: {out_video}")


if __name__ == "__main__":
    main()
