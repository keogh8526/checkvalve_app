"""
파이프라인 오케스트레이터 — 개별 기술블록을 '한 명령'으로 단계별 연결한다.

데이터 플로우(설명영상 = ASR 있음):
  [입력] 영상(mp4) + 오디오(wav)
    [1] extract_pose   영상      -> body.json      (프레임별 17키포인트, YOLO11m)
    [2] segment        body.json -> segments.json  (손목속도 변화점=운동경계, ruptures) + velocity.png
    [3] extract_asr    wav       -> asr.json       (문장별 나레이션+시각, whisper large-v3)
    [4] anchor_steps   asr.json  -> anchors.json   (용어교정->표준단계 의미 타임라인)
    [5] refine_steps   anchors+body -> refined.json(경계 속도스냅 + VA/NVA 활동량)
    [6] build_steps    refined   -> steps.json     (최종 단계열: 순서·표준시간·공정단계·나레이션)
    [7] generate_html  steps.json -> work_instruction.html   <- 작업지도서 초안
  [게이트] 사람 검수

오디오가 없으면(무설명 반복영상) [3~5] 건너뛰고 [6]은 segments+나레이션 대체경로(B)로 단계열 생성.

usage (단일 영상 풀체인):
  python pose/pipeline.py --video data/front/XXX.mp4 --out results/run_front_full \
      --asr-audio results/_audio/XXX.wav [--offset 0]

다관점/회차 합의(보조 — 표준시간 통계 보강):
  python pose/pipeline.py --merge resultsA/segments.json resultsB/segments.json --tol 2.0
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def run(script, *a):
    print(f"\n>>> [{script}] {' '.join(map(str, a))}", flush=True)
    subprocess.run([PY, str(HERE / script), *map(str, a)], check=True)


def run_one(video, out, asr_audio=None, offset=0.0, pen=12, min_sec=4, model="yolo11m-pose.pt"):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    body = out / "body.json"; segs = out / "segments.json"
    asr = out / "asr.json"; anchors = out / "anchors.json"
    refined = out / "refined.json"
    steps = out / "steps.json"; steps_tl = out / "steps_timeline.json"
    html = out / "work_instruction.html"; html_tl = out / "work_instruction_timeline.html"

    # [1] 포즈 추출 (이미 있으면 재사용 — 무거운 단계)
    if body.exists() and body.stat().st_size > 0:
        print(f"\n>>> [1] extract_pose SKIP (재사용: {body})")
    else:
        run("extract_pose.py", "--video", video, "--out-json", body,
            "--model", model, "--no-video", "--stride", "2")

    # [2] 분할 (운동경계 + 속도곡선 시각화)
    run("segment.py", "--body-json", body, "--out-dir", out, "--pen", pen, "--min-sec", min_sec)

    if asr_audio:
        # [3] 나레이션 (이미 있으면 재사용 — 무거운 단계)
        if asr.exists() and asr.stat().st_size > 0:
            print(f"\n>>> [3] extract_asr SKIP (재사용: {asr})")
        else:
            run("extract_asr.py", "--audio", asr_audio, "--out-json", asr, "--model", "large-v3")
        # [4] 앵커링 (나레이션 -> 표준단계 의미 타임라인)
        run("anchor_steps.py", "--asr", asr, "--out-json", anchors, "--offset", offset)
        # [5] 정밀화 (앵커 의미 + 속도 경계스냅 + VA/NVA)
        run("refine_steps.py", "--anchors", anchors, "--body", body, "--out-json", refined)
        # [6] 융합 — 표준 작업지도서(메인) + 시간순 상세(감사 근거용)
        run("build_steps.py", "--refined", refined, "--standard", "--out-json", steps)
        run("build_steps.py", "--refined", refined, "--out-json", steps_tl)
    else:
        # 무설명 영상: 속도구간 단독 -> 단계열(대체경로 B)
        run("build_steps.py", "--segments", segs, "--out-json", steps_tl)
        steps = steps_tl

    # [7] 렌더 (작업지도서 HTML)
    run("generate_html.py", "--steps", steps, "--out", html)
    if steps_tl != steps and Path(steps_tl).exists():
        run("generate_html.py", "--steps", steps_tl, "--out", html_tl)

    print(f"\n[PIPELINE DONE] 표준 작업지도서 -> {html}")
    return html


def merge_views(seg_paths, tol=2.0):
    """여러 뷰/회차의 경계를 모아 ±tol초 내 다수가 합의하는 지점을 신뢰 경계로(보조)."""
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
        cluster = [(b, flat[i][1])]; used[i] = True
        for j in range(i + 1, len(flat)):
            if not used[j] and abs(flat[j][0] - b) <= tol:
                cluster.append((flat[j][0], flat[j][1])); used[j] = True
        if len({p for _, p in cluster}) >= 2:
            consensus.append(round(sum(c[0] for c in cluster) / len(cluster), 1))
    print(f"\n[MERGE] 뷰 {len(seg_paths)}개 → 합의 경계 {len(consensus)}개 (tol={tol}s): {consensus}")
    return consensus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video")
    ap.add_argument("--out")
    ap.add_argument("--asr-audio", default=None)
    ap.add_argument("--offset", type=float, default=0.0, help="클립 시작 오프셋(원본 절대시각 환산, L9)")
    ap.add_argument("--pen", default="12")
    ap.add_argument("--min-sec", default="4")
    ap.add_argument("--model", default="yolo11m-pose.pt")
    ap.add_argument("--merge", nargs="+", help="여러 segments.json 경로(합의 보조)")
    ap.add_argument("--tol", type=float, default=2.0)
    args = ap.parse_args()

    if args.merge:
        merge_views(args.merge, args.tol)
    elif args.video and args.out:
        run_one(args.video, args.out, args.asr_audio, args.offset, args.pen, args.min_sec, args.model)
    else:
        ap.error("--video+--out (풀체인) 또는 --merge (합의) 중 하나 필요")


if __name__ == "__main__":
    main()
