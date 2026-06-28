"""
[6] 융합 — 정밀화 단계열(refined.json) 또는 동작구간(segments.json)+나레이션(asr.json)을
'최종 작업지도서 단계열(steps.json)'로 확정한다. (멀티모달 융합의 종착점)

두 입력 경로:
  (A) --refined refined.json  [권장]  : 앵커(의미)+속도(경계/활동) 정밀화 결과를 그대로 단계열로.
  (B) --segments + --asr      [대체]  : 앵커 없는 영상(무설명 등) — 속도구간에 나레이션 겹침으로 라벨.

원칙(환각방지): 시간·구간=측정값, 설명문=나레이션 원문(용어교정만), 공정단계=공통 taxonomy 키워드.
                LLM은 이 단계 이후 '문장 다듬기'에만. 용어교정(terms)·단계정의(canonical)=공통모듈.

출력 steps.json 스키마(고정 — generate_html이 소비):
  {step, 공정단계, t_start, t_end, 표준시간_후보_초, 분류, 활동량, 나레이션}

usage:
  python pose/build_steps.py --refined results/run_front_full/refined.json \
      --out-json results/run_front_full/steps.json
  python pose/build_steps.py --segments seg.json --asr asr.json --out-json steps.json
"""
import argparse
import json
from pathlib import Path

from terms import normalize_terms
from canonical import classify, UNCLASSIFIED, CANONICAL_ORDER, NON_WORK_STEPS


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def from_refined(refined_path, include_nva):
    """경로 A: 정밀화 결과(VA_steps[+NVA])를 최종 단계열로."""
    d = json.loads(Path(refined_path).read_text(encoding="utf-8"))
    rows = []
    for s in d.get("VA_steps", []):
        rows.append({"공정단계": s["step"], "t_start": s["t_start"], "t_end": s["t_end"],
                     "표준시간_후보_초": s.get("표준시간_후보", round(s["t_end"] - s["t_start"], 1)),
                     "분류": s.get("분류", "VA(작업)"), "활동량": s.get("활동량"),
                     "나레이션": normalize_terms(s.get("나레이션", "")) or "(나레이션 없음)"})
    if include_nva:
        for n in d.get("NVA_segments", []):
            rows.append({"공정단계": "(비부가)", "t_start": n["t_start"], "t_end": n["t_end"],
                         "표준시간_후보_초": round(n["t_end"] - n["t_start"], 1),
                         "분류": n.get("분류", "NVA"), "활동량": n.get("활동량"),
                         "나레이션": "(이동/대기 — 표준시간 제외 권장)"})
    rows.sort(key=lambda r: r["t_start"])
    return rows


def from_segments(seg_path, asr_path):
    """경로 B: 속도구간 + 나레이션 겹침으로 라벨(앵커 없는 영상용)."""
    segs = json.loads(Path(seg_path).read_text(encoding="utf-8"))["segments"]
    asr = []
    if asr_path and Path(asr_path).exists():
        asr = json.loads(Path(asr_path).read_text(encoding="utf-8")).get("segments", [])
    rows = []
    for sg in segs:
        t0, t1 = sg["t_start"], sg["t_end"]
        narr = [a for a in asr if overlap(t0, t1, a["start"], a["end"]) > 0.3]
        text = normalize_terms(" ".join(a["text"] for a in narr).strip())
        label, _ = classify(text) if text else (UNCLASSIFIED, 0)
        rows.append({"공정단계": label, "t_start": t0, "t_end": t1,
                     "표준시간_후보_초": sg["dur_sec"], "분류": "VA(작업)" if text else "미상",
                     "활동량": sg.get("mean_speed"),
                     "나레이션": text or "(이 구간 나레이션 없음)"})
    return rows


def aggregate_standard(rows, min_sec=2.0):
    """시간순 단편 → 표준 작업지도서: canonical 단계별로 VA시간 합산, 표준 순서 정렬.
    설명(비작업)·0초 퇴화·잡담은 제외. 같은 단계가 흩어져 있어도 하나의 표준단계로 모은다."""
    agg = {}
    for r in rows:
        label = r["공정단계"]
        if label in NON_WORK_STEPS or label == UNCLASSIFIED or label == "(비부가)":
            continue
        if not str(r.get("분류", "")).startswith("VA"):
            continue
        dur = r["t_end"] - r["t_start"]
        if dur < min_sec:                       # 0초/너무 짧은 퇴화 단편 제외
            continue
        a = agg.setdefault(label, {"공정단계": label, "표준시간_후보_초": 0.0,
                                   "출현_횟수": 0, "first_t": r["t_start"], "나레이션들": []})
        a["표준시간_후보_초"] += dur
        a["출현_횟수"] += 1
        a["first_t"] = min(a["first_t"], r["t_start"])
        if r.get("나레이션") and not r["나레이션"].startswith("("):
            a["나레이션들"].append((dur, r["나레이션"]))
    # 표준 공정 순서로 정렬(목록에 없으면 첫 출현시각 순)
    def order_key(label):
        return (CANONICAL_ORDER.index(label) if label in CANONICAL_ORDER else 99,
                agg[label]["first_t"])
    out = []
    for label in sorted(agg, key=order_key):
        a = agg[label]
        narr = max(a["나레이션들"], default=(0, "(나레이션 없음)"))[1]   # 가장 긴 구간의 설명 대표
        # C1 정직화: 흩어진 단편 합산을 '가짜 연속구간(first_t~first_t+합계)'으로 만들지 않는다.
        # t_start/t_end 대신 누적시간임을 명시. 실제 연속 작업시간은 빠른조작영상(fuse_views)에서 측정.
        out.append({"공정단계": label,
                    "누적발화시간_초": round(a["표준시간_후보_초"], 1),
                    "출현_횟수": a["출현_횟수"], "첫출현_초": round(a["first_t"], 1),
                    "분류": "VA(작업)", "시간성격": "누적·비연속(설명영상 발화기준, 표준시간 아님)",
                    "나레이션": narr})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refined", default=None, help="[권장] refine_steps.py 출력")
    ap.add_argument("--segments", default=None, help="[대체] segment.py 출력")
    ap.add_argument("--asr", default=None, help="[대체] extract_asr.py 출력 (segments와 함께)")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--include-nva", action="store_true", help="비부가(NVA) 구간도 표에 표기")
    ap.add_argument("--standard", action="store_true",
                    help="표준집계: canonical 단계별 VA시간 합산·표준순서(시간순 덤프 대신 표준작업지도서)")
    args = ap.parse_args()

    if args.refined:
        rows = from_refined(args.refined, args.include_nva)
        src = {"refined": args.refined}
    elif args.segments:
        rows = from_segments(args.segments, args.asr)
        src = {"segments": args.segments, "asr": args.asr}
    else:
        ap.error("--refined (권장) 또는 --segments (대체) 중 하나 필요")

    mode = "timeline"
    if args.standard:
        rows = aggregate_standard(rows)
        mode = "standard"

    steps = []
    for i, r in enumerate(rows, 1):
        steps.append({"step": i, **r})

    note = ("표준집계: canonical 단계별 VA시간 합산·표준순서(설명/잡담 제외, 사람검수 필요)" if mode == "standard"
            else "시간순: 측정구간 그대로(감사/근거용). 설명=나레이션(용어교정), 공정단계=공통taxonomy")
    out = {"n_steps": len(steps), "mode": mode, "source": src, "note": note, "steps": steps}
    Path(args.out_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] {len(steps)} steps (mode={mode}) -> {args.out_json}\n")
    for s in steps:
        if "누적발화시간_초" in s:      # 표준집계(누적·비연속)
            print(f"  [단계{s['step']}] 누적 {s['누적발화시간_초']:5.1f}s (출현{s.get('출현_횟수','?')}회) "
                  f"[{s.get('분류','-')}] {s['공정단계']}")
        else:                          # 시간순
            print(f"  [단계{s['step']}] {s['t_start']:6.1f}~{s['t_end']:6.1f}s "
                  f"({s.get('표준시간_후보_초', s['t_end']-s['t_start']):5.1f}s) "
                  f"[{s.get('분류','-')}] {s['공정단계']}")
        print(f"        나레이션: {s['나레이션'][:80]}")


if __name__ == "__main__":
    main()
