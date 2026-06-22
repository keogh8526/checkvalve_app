"""
M6 융합 — 동작 구간(segment) × 나레이션(asr) × 공정지침서(QMS)를 시간축으로 합쳐
'단계별 라벨 + 설명 + 표준시간 후보'를 만든다. (멀티모달 융합의 핵심)

입력 : segments.json (segment.py), asr.json (extract_asr.py)
출력 : steps.json — 각 단계: 시각/표준시간후보/나레이션/공정단계 추정

원칙(환각방지): 시간·구간은 측정값(segment), 설명문은 나레이션 원문, 공정단계는 키워드 매핑.
                LLM은 이 단계 이후 '문장 다듬기'에만 쓰고 수치·단계는 여기서 확정.

usage:
  python pose/build_steps.py --segments results/seg_test/segments.json \
      --asr results/seg_test/asr.json --out-json results/seg_test/steps.json
"""
import argparse
import json
from pathlib import Path

# 공정지침서 GMT-QI-700-4 기반 키워드 -> 공정8 단계(및 개요) 매핑
QMS_KEYWORDS = [
    ("개요/원리설명", ["역류", "물이", "물을", "배관", "유수", "열려", "닫혀", "체크", "원리", "보통"]),
    ("부품준비",       ["준비", "가공", "주물", "샤프트", "스프링", "디스크", "디스플로드", "바디", "세 개"]),
    ("정렬(스프링·스페이서)", ["정렬", "맞춰", "스페이서", "사이", "1자", "일자"]),
    ("힌지핀 삽입",     ["핀", "힌지", "hinge", "삽입", "끼"]),
    ("검사/측정",       ["검사", "측정", "확인", "캘리퍼", "회전", "복귀", "작동"]),
]


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def guess_step(text):
    """나레이션 텍스트 -> 공정단계 추정 (키워드 점수)."""
    best, score = "미분류", 0
    for label, kws in QMS_KEYWORDS:
        s = sum(text.count(k) for k in kws)
        if s > score:
            best, score = label, s
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", required=True)
    ap.add_argument("--asr", default=None, help="없으면 구간만으로 단계 골격 생성")
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()

    segs = json.loads(Path(args.segments).read_text(encoding="utf-8"))["segments"]
    asr = []
    if args.asr and Path(args.asr).exists():
        asr = json.loads(Path(args.asr).read_text(encoding="utf-8")).get("segments", [])

    steps = []
    for i, sg in enumerate(segs, 1):
        t0, t1 = sg["t_start"], sg["t_end"]
        # 이 동작구간과 시간이 겹치는 나레이션 문장 수집
        narr = [a for a in asr if overlap(t0, t1, a["start"], a["end"]) > 0.3]
        text = " ".join(a["text"] for a in narr).strip()
        step = {
            "step": i,
            "t_start": t0, "t_end": t1,
            "표준시간_후보_초": sg["dur_sec"],     # 측정값(동작구간 길이)
            "평균손목속도": sg.get("mean_speed"),
            "나레이션": text or "(이 구간 나레이션 없음)",
            "공정단계_추정": guess_step(text) if text else "미분류",
        }
        steps.append(step)

    out = {"n_steps": len(steps), "source": {"segments": args.segments, "asr": args.asr},
           "note": "표준시간/구간=측정값, 설명=나레이션원문, 공정단계=키워드추정(사람검수 필요)",
           "steps": steps}
    Path(args.out_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] {len(steps)} steps -> {args.out_json}\n")
    for s in steps:
        print(f"  [단계{s['step']}] {s['t_start']:5.1f}~{s['t_end']:5.1f}s ({s['표준시간_후보_초']:4.1f}s) "
              f"| {s['공정단계_추정']}")
        print(f"        나레이션: {s['나레이션'][:80]}")


if __name__ == "__main__":
    main()
