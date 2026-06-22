"""
파이프라인 오케스트레이터 — 개별 모듈을 하나로 묶어 한 번에 실행한다.

체인: extract_pose(YOLO) -> segment(One-Euro+ruptures) -> [extract_asr(나레이션)] -> build_steps(융합)
출력: <out>/steps.json (단계별 시간+표준시간후보+나레이션+공정단계)

다관점 합의(consensus): 여러 뷰의 segments.json 경계를 ±tol초 내 일치하면 '신뢰 경계'로 병합.

usage (단일 영상 한 번에):
  python pose/pipeline.py --video data/front/XXX.mp4 --out results/run_front [--asr-audio results/_audio/XXX.wav]
다관점 합의:
  python pose/pipeline.py --merge results/seg_test/segments.json results/top60_test/segments.json --tol 2.0
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def run(script, *a):
    print(f"\n>>> {script} {' '.join(map(str,a))}", flush=True)
    subprocess.run([PY, str(HERE / script), *map(str, a)], check=True)


def run_one(video, out, asr_audio=None, pen=12, min_sec=4):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    body = out / "body.json"; segs = out / "segments.json"
    asr = out / "asr.json"; steps = out / "steps.json"
    # 1) 추출
    run("extract_pose.py", "--video", video, "--out-json", body, "--model", "yolo11m-pose.pt",
        "--no-video", "--stride", "2")
    # 2) 분할
    run("segment.py", "--body-json", body, "--out-dir", out, "--pen", pen, "--min-sec", min_sec)
    # 3) 나레이션(있으면)
    asr_arg = []
    if asr_audio:
        run("extract_asr.py", "--audio", asr_audio, "--out-json", asr, "--model", "large-v3")
        asr_arg = ["--asr", str(asr)]
    # 4) 융합
    run("build_steps.py", "--segments", segs, "--out-json", steps, *asr_arg)
    print(f"\n[PIPELINE DONE] -> {steps}")
    return steps


def merge_views(seg_paths, tol=2.0):
    """여러 뷰의 경계를 모아 ±tol초 내 다수 뷰가 합의하는 지점을 신뢰 경계로."""
    all_bounds = []
    for p in seg_paths:
        sgs = json.loads(Path(p).read_text(encoding="utf-8"))["segments"]
        bounds = sorted({s["t_start"] for s in sgs} | {s["t_end"] for s in sgs})
        all_bounds.append((p, bounds))
    flat = [(b, p) for p, bs in all_bounds for b in bs]
    flat.sort()
    consensus, used = [], [False] * len(flat)
    for i, (b, _) in enumerate(flat):
        if used[i]:
            continue
        cluster = [(b, flat[i][1])]
        used[i] = True
        for j in range(i + 1, len(flat)):
            if not used[j] and abs(flat[j][0] - b) <= tol:
                cluster.append((flat[j][0], flat[j][1])); used[j] = True
        views = {p for _, p in cluster}
        if len(views) >= 2:  # 2개 이상 뷰가 합의
            consensus.append(round(sum(c[0] for c in cluster) / len(cluster), 1))
    print(f"\n[MERGE] 뷰 {len(seg_paths)}개 → 합의 경계 {len(consensus)}개 (tol={tol}s):")
    print("  ", consensus)
    return consensus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video")
    ap.add_argument("--out")
    ap.add_argument("--asr-audio", default=None)
    ap.add_argument("--pen", default="12")
    ap.add_argument("--min-sec", default="4")
    ap.add_argument("--merge", nargs="+", help="여러 segments.json 경로")
    ap.add_argument("--tol", type=float, default=2.0)
    args = ap.parse_args()

    if args.merge:
        merge_views(args.merge, args.tol)
    elif args.video and args.out:
        run_one(args.video, args.out, args.asr_audio, args.pen, args.min_sec)
    else:
        ap.error("--video+--out (단일실행) 또는 --merge (합의) 중 하나 필요")


if __name__ == "__main__":
    main()
