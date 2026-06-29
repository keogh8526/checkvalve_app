"""
[4] 표준단계 앵커링 — 나레이션(ASR)을 공정지침서(GMT-QI-700-4) 표준 단계에 시간 매핑한다.
(다관점 병합의 공통 좌표계: 각 영상이 '표준 단계가 몇 초에 있나'를 공유)

입력 : asr.json (extract_asr.py)
출력 : anchors.json — [{step, t_start, t_end, dur_sec, narration}]
처리 : 용어교정 → 문장별 표준단계 분류 → 연속 같은 단계 병합 → 단계별 시간 span → offset 환산

용어교정(terms.py)·단계정의(canonical.py)는 공통 모듈을 사용한다(build_steps와 동일 기준).

usage:
  python pose/anchor_steps.py --asr results/run_front_full/asr.json \
      --out-json results/run_front_full/anchors.json [--offset 0]
"""
import argparse
import json
from pathlib import Path

from terms import normalize_terms
from canonical import classify, UNCLASSIFIED


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asr", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--offset", type=float, default=0.0,
                    help="클립이 원본영상의 X초부터 잘린 것이면 X 입력 → 절대시각 환산(L9)")
    args = ap.parse_args()

    asr = json.loads(Path(args.asr).read_text(encoding="utf-8"))["segments"]

    # 문장별 분류 (용어교정은 classify 내부에서 수행)
    tagged = []
    for a in asr:
        label, score = classify(a["text"])
        tagged.append({"start": a["start"], "end": a["end"],
                       "text": normalize_terms(a["text"]), "step": label, "score": score})

    # 연속 같은 단계 병합 → 표준단계 span
    spans = []
    for t in tagged:
        if t["step"] == UNCLASSIFIED:
            if spans:                                  # 직전 span에 흡수(설명 연속성)
                spans[-1]["end"] = t["end"]; spans[-1]["narration"] += " " + t["text"]
            continue
        if spans and spans[-1]["step"] == t["step"]:
            spans[-1]["end"] = t["end"]; spans[-1]["narration"] += " " + t["text"]
        else:
            spans.append({"step": t["step"], "t_start": t["start"], "end": t["end"],
                          "narration": t["text"]})
    for s in spans:
        s["t_end"] = round(s.pop("end") + args.offset, 1)
        s["t_start"] = round(s["t_start"] + args.offset, 1)   # 절대시각 환산(L9)
        s["dur_sec"] = round(s["t_end"] - s["t_start"], 1)
        s["narration"] = s["narration"].strip()

    out = {"source": args.asr, "n_anchors": len(spans), "offset": args.offset,
           "note": "나레이션→공정지침서 표준단계 시각 앵커. 용어교정/단계정의=공통모듈. 다관점/반복은 DTW로 정렬.",
           "anchors": spans}
    Path(args.out_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] {len(spans)} 표준단계 앵커 -> {args.out_json}\n")
    for s in spans:
        print(f"  [{s['t_start']:6.1f}~{s['t_end']:6.1f}s] {s['step']}")
        print(f"        \"{s['narration'][:70]}\"")


if __name__ == "__main__":
    main()
