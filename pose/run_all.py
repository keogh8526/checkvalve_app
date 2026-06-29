"""
★ 최상위 다영상 오케스트레이터 — 다시점 영상들을 받아 '하나의 표준작업지도서'를 만든다.

다각도(다시점)이므로 입력은 여러 영상이다. 역할 분담(리서치 근거):
  - 빠른조작영상(무설명) × 여러 시점  → 타이밍·섹터(다시점 DTW 합의, 실측)   [측정=비전]
  - 설명영상 × 1시점                  → 단계명·근거설명(나레이션→canonical)   [의미=언어]
  - 손확대영상                        → body pose 불가(머리·어깨 화면밖) → 타이밍 제외,
                                        손 미세동작은 rtmlib(extract_hands_rtm) 별도 트랙(선택)

흐름:
  [A] 각 빠른시점: extract_pose → segment
  [B] fuse_views: 빠른시점들 DTW 합의 → fused_segments.json (실측 표준시간)
  [C] 설명시점: extract_pose → extract_asr → anchor_steps (단계 의미 순서)
  [D] assemble_fused: 합의섹터(타이밍) + 앵커(라벨) → steps.json
  [E] generate_html → 작업지도서

usage:
  python pose/run_all.py --out results/all
  (영상 경로는 아래 VIEWS 기본값 — manifest 기반. 필요시 수정)
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = sys.executable

# 기본 입력(manifest.csv 기준). fast=무설명(타이밍), exp=설명(라벨)
VIEWS = {
    "front": {
        "fast": "data/front/KakaoTalk_Video_2026-06-22-17-54-49.mp4",
        "exp":  "data/front/KakaoTalk_Video_2026-06-22-17-54-39.mp4",
        "exp_audio": "results/_audio/KakaoTalk_Video_2026-06-22-17-54-39.wav",
    },
    "top60": {
        "fast": "data/top60/KakaoTalk_Video_2026-06-22-17-15-48.mp4",
        "exp":  "data/top60/KakaoTalk_Video_2026-06-22-17-15-54.mp4",
        "exp_audio": "results/_audio/KakaoTalk_Video_2026-06-22-17-15-54.wav",
    },
    # hand_closeup: body pose 불가(어깨0) → 손21점(rtmlib)으로 분할(hand=True 분기)
    "hand": {
        "fast": "data/hand_closeup/IMG_3823.MOV",
        "exp":  "data/hand_closeup/IMG_3822.MOV",
        "exp_audio": "results/_audio/IMG_3822.wav",
        "hand": True,    # 손21점 분할 분기
    },
}
LABEL_VIEW = "front"   # 단계 라벨(설명) 소스 시점(다중경로에 top60·hand exp도 결합)


def run(script, *a):
    print(f"\n>>> [{script}] {' '.join(map(str, a))}", flush=True)
    subprocess.run([PY, str(HERE / script), *map(str, a)], check=True)


def ensure_pose(video, body, model="yolo11m-pose.pt"):
    if body.exists() and body.stat().st_size > 0:
        print(f">>> extract_pose SKIP (재사용: {body})"); return
    run("extract_pose.py", "--video", video, "--out-json", body, "--model", model, "--no-video", "--stride", "2")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/all")
    ap.add_argument("--pen", default="12")
    ap.add_argument("--min-sec", default="3")
    ap.add_argument("--n-steps", default="6", help="공정서 작업단계 수(빠른영상 K). 다채널 분할에 사용")
    ap.add_argument("--channels", default="spd,posx,posy",
                    help="분할 채널(손위치 포함이 정확). spd,posx,posy,dist,hgt,elb")
    args = ap.parse_args()
    out = (ROOT / args.out); out.mkdir(parents=True, exist_ok=True)

    # ── [A] 빠른시점 각각: 분할 (body 손위치 / hand 손21점). body 시점만 타이밍 합의에 사용 ──
    fast_views = []     # body 시점(front/top60) — fused 합의용
    hand_track = None   # 손확대 — 손21점 별도 트랙(미세동작)
    for name, v in VIEWS.items():
        if not v.get("fast"):
            continue
        d = out / f"{name}_fast"; d.mkdir(parents=True, exist_ok=True)
        if v.get("hand"):
            # 손확대: rtmlib 손21점 → segment_hands (body pose 불가, 검증 75%)
            hands = d / "hands.json"
            if not hands.exists() or hands.stat().st_size == 0:
                run("extract_hands_rtm.py", "--video", ROOT / v["fast"], "--out-json", hands, "--stride", "3")
            run("segment_hands.py", "--hands-json", hands, "--out-dir", d,
                "--channels", args.channels, "--n-steps", args.n_steps, "--min-sec", args.min_sec)
            hand_track = (name, hands, d / "segments.json")
        else:
            body = d / "body.json"
            ensure_pose(ROOT / v["fast"], body)
            # 다채널(손위치 포함) 분할 — 속도단독 대비 정확도 2배 검증(50→83%). 공정서 K=6 강제.
            run("segment_multi.py", "--body-json", body, "--out-dir", d,
                "--channels", args.channels, "--n-steps", args.n_steps, "--min-sec", args.min_sec)
            fast_views.append((name, body, d / "segments.json"))
    if len(fast_views) < 1:
        raise SystemExit("body 빠른시점 영상이 없습니다.")

    # ── [B] 다시점 합의 분할(DTW) → fused_segments (실측 표준시간) ──
    fused = out / "fused_segments.json"
    if len(fast_views) >= 2:
        ref = fast_views[0]; others = fast_views[1:]
        view_args = []
        for _, b, s in others:
            view_args += ["--view", str(b), "--view-segs", str(s)]
        run("fuse_views.py", "--ref", ref[1], "--ref-segs", ref[2], *view_args,
            "--out-json", fused, "--tol", "2.0", "--min-sec", args.min_sec, "--min-support", "1")
    else:
        # 시점 1개뿐이면 그 segments를 fused 형식으로 변환
        segs = json.loads((fast_views[0][2]).read_text(encoding="utf-8"))["segments"]
        sectors = [{"sector": i + 1, "t_start": s["t_start"], "t_end": s["t_end"],
                    "dur_sec": s["dur_sec"], "start_support_views": 1} for i, s in enumerate(segs)]
        fused.write_text(json.dumps({"ref_dur": segs[-1]["t_end"], "n_sectors": len(sectors),
                                     "alignment": [], "sectors": sectors}, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        print(f">>> 시점 1개 → fused 변환 {len(sectors)}섹터")

    # ── [C] 설명시점 다중경로: 모든 설명영상 → asr → anchor (라벨 견고성↑) ──
    pre = ROOT / "results/run_front_full"
    anchor_paths = []
    for name, v in VIEWS.items():
        if not v.get("exp_audio"):
            continue
        ld = out / f"{name}_exp"; ld.mkdir(parents=True, exist_ok=True)
        easr = ld / "asr.json"; anchors = ld / "anchors.json"
        # front는 기존 run_front_full 앵커 재사용(무거운 ASR 절약)
        if name == "front" and (pre / "anchors.json").exists():
            anchor_paths.append(pre / "anchors.json")
            print(f">>> [C] {name} 설명 앵커 재사용: {pre/'anchors.json'}")
            continue
        if not easr.exists() or easr.stat().st_size == 0:
            run("extract_asr.py", "--audio", ROOT / v["exp_audio"], "--out-json", easr, "--model", "large-v3")
        run("anchor_steps.py", "--asr", easr, "--out-json", anchors, "--offset", "0")
        anchor_paths.append(anchors)
    if not anchor_paths:
        raise SystemExit("설명영상(라벨 소스)이 없습니다.")

    # ── [D] 융합조립: 합의섹터(타이밍) + 다중경로 앵커(라벨) → steps.json ──
    steps = out / "steps.json"
    anc_args = []
    for p in anchor_paths:
        anc_args += ["--anchors", str(p)]
    run("assemble_fused.py", "--fused", fused, *anc_args, "--out-json", steps)

    # ── [E] 대표프레임 썸네일(타이밍 영상=기준 빠른시점) + 렌더 ──
    ref_fast_video = ROOT / VIEWS[list(VIEWS)[0]]["fast"]
    run("extract_thumbnails.py", "--steps", steps, "--video", ref_fast_video,
        "--out-dir", out / "thumbs", "--write")
    html = out / "work_instruction.html"
    run("generate_html.py", "--steps", steps, "--out", html)

    # ── [F] 팀 양식 작업지도서(app/check_valve.html 템플릿)에 파이프라인 데이터 주입 ──
    #     + 포즈 스켈레톤 오버레이 영상(분석 시각화)을 좌측 영상으로 표시.
    import shutil
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    app = ROOT / "app"
    ref_body = out / (list(VIEWS)[0] + "_fast") / "body.json"
    skel_final = app / "front_skeleton.mp4"
    if Path(ffmpeg).exists() and ref_body.exists():
        skel_raw = out / "front_skeleton_raw.mp4"
        run("render_overlay.py", "--video", ref_fast_video,
            "--body-json", ref_body, "--out", skel_raw)
        subprocess.run([ffmpeg, "-y", "-i", str(skel_raw), "-vf", "scale=640:-2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", "-an", str(skel_final)], check=True)
        skel_raw.unlink(missing_ok=True)
        vid_name = "front_skeleton.mp4"
    else:
        print(">>> [F] ffmpeg/ body.json 없음 → 스켈레톤 생략, 원본 영상 사용")
        vid_name = "front_fast.mp4"
    team_html = app / "work_instruction_auto.html"
    run("render_workinstruction.py", "--steps", steps,
        "--template", app / "check_valve.html", "--video", vid_name, "--out", team_html)

    print(f"\n[RUN_ALL DONE] 기본양식 -> {html}\n               팀 양식(자동) -> {team_html}")


if __name__ == "__main__":
    main()
