"""
[LEGACY · 본선 아님] QC 검증 전용 드라이버. 작업지도서 본선은 pose/pipeline.py 를 쓴다.
이 스크립트는 extract_hands.py(MediaPipe, Python 3.13 미지원)를 호출하므로 3.13 환경에서는
손 추출 단계가 실패한다. 손 키포인트가 필요하면 extract_hands_rtm.py(rtmlib)를 별도 사용.

Portable driver: run the full keypoint pipeline on every .mp4 in a folder.

For each video it runs, in order:
  1. extract_pose.py   - YOLO11-pose body keypoints (17) -> body_yolo.json
  2. extract_hands.py  - MediaPipe Holistic body+hands   -> hands_mediapipe.json
  3. qc_validate.py    - cross-model QC / anomaly report  -> qc.json, qc.txt, suspicious_frames/
  4. render_overlay.py - annotated skeleton video         -> <stem>_overlay.mp4  (unless --no-render)

Outputs go to <out-dir>/<video_stem>/.

Example:
  python run_pipeline.py --data-dir ../data --out-dir ../results
  python run_pipeline.py --data-dir ./videos --out-dir ./out --no-render
"""
import argparse
import glob
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def run(script, *a):
    subprocess.run([PY, str(HERE / script), *map(str, a)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True, help="Folder containing input .mp4 videos.")
    ap.add_argument("--out-dir", required=True, help="Output root; one subfolder is created per video.")
    ap.add_argument("--model", default="yolo11m-pose.pt",
                   help="확정=yolo11m(본선 pipeline.py와 동일). 이전 기본 yolo11x는 레포 미포함.")
    ap.add_argument("--no-render", action="store_true", help="Skip the annotated overlay video.")
    args = ap.parse_args()

    data, out = Path(args.data_dir), Path(args.out_dir)
    videos = sorted(glob.glob(str(data / "*.mp4")))
    if not videos:
        raise SystemExit(f"No .mp4 files found in {data}")

    print(f"[pipeline] {len(videos)} video(s) to process")
    for v in videos:
        stem = Path(v).stem
        d = out / stem
        d.mkdir(parents=True, exist_ok=True)
        body, hands = d / "body_yolo.json", d / "hands_mediapipe.json"
        print(f"\n=== {stem} ===", flush=True)
        run("extract_pose.py", "--video", v, "--out-json", body, "--no-video", "--model", args.model)
        run("extract_hands.py", "--video", v, "--out-json", hands, "--no-video")
        run("qc_validate.py", "--video", v, "--body-json", body, "--hands-json", hands, "--out-dir", d)
        if not args.no_render:
            run("render_overlay.py", "--video", v, "--body-json", body,
                "--hands-json", hands, "--out", d / f"{stem}_overlay.mp4")
    print("\n[pipeline] DONE")


if __name__ == "__main__":
    main()
