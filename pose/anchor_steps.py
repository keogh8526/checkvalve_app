"""
표준단계 앵커링 — 나레이션(ASR)을 공정지침서(GMT-QI-700-4) 표준 단계에 시간 매핑한다.
(다관점 병합의 공통 좌표계: 각 영상이 '표준 단계가 몇 초에 있나'를 공유)

입력 : asr.json (extract_asr.py)
출력 : canonical_steps.json — [{step, t_start, t_end, narration}]
처리 : 나레이션 문장별 QMS 단계 분류 -> 연속 같은 단계 병합 -> 단계별 시간 span

usage:
  python pose/anchor_steps.py --asr results/seg_test/asr_large.json --out-json results/seg_test/canonical.json
"""
import argparse
import json
from pathlib import Path

# 작업자 구어 -> 공정관리지침서 GMT-QI-700-4 표준 용어 매핑 (L4)
TERM_MAP = {
    "테프론": "스페이서", "베프론": "스페이서", "데프론": "스페이서",
    "서포트": "가이드", "디스켓": "디스크", "디스플로드": "디스크",
    "바이드": "비드", "차속": "디스크",
}


def normalize_terms(text):
    for spoken, std in TERM_MAP.items():
        text = text.replace(spoken, std)
    return text


# 공정지침서 GMT-QI-700-4 공정8~11 표준 단계 키워드 (정밀, L5 보강)
CANONICAL = [
    ("개요/원리",        ["역류", "물이", "물을", "배관", "유수", "열려", "닫혀", "체크", "원리", "보통", "세요"]),
    ("부품 준비",        ["준비", "가공", "주물", "샤프트", "세 개", "들어오"]),
    ("정렬(스프링·스페이서)", ["정렬", "맞춰", "스페이서", "스프링", "사이", "1자", "일자", "올려", "넣고", "꼽"]),
    ("힌지핀 삽입",      ["핀", "힌지", "hinge", "삽입", "끼", "관통", "꽂"]),
    ("디스크 체결",      ["디스크", "체결"]),
    ("GUIDE 결합",       ["가이드", "guide", "양쪽", "결합", "바디"]),
    ("SET SCREW 체결",   ["볼트", "스크류", "스크루", "탭", "나사"]),
    ("검사/측정",        ["검사", "측정", "확인", "캘리퍼", "버니어", "회전", "복귀", "작동", "눌러"]),
]


def classify(text):
    text = normalize_terms(text)
    best, score = "미분류", 0
    for label, kws in CANONICAL:
        s = sum(text.count(k) for k in kws)
        if s > score:
            best, score = label, s
    return best, score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asr", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--offset", type=float, default=0.0,
                    help="클립이 원본영상의 X초부터 잘린 것이면 X 입력 → 절대시각 환산(L9)")
    args = ap.parse_args()

    asr = json.loads(Path(args.asr).read_text(encoding="utf-8"))["segments"]

    # 문장별 분류
    tagged = []
    for a in asr:
        label, score = classify(a["text"])
        tagged.append({"start": a["start"], "end": a["end"], "text": normalize_terms(a["text"]),
                       "step": label, "score": score})

    # 연속 같은 단계 병합 -> 표준단계 span
    spans = []
    for t in tagged:
        if t["step"] == "미분류":
            # 직전 span에 흡수(설명 연속성)
            if spans:
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

    out = {"source": args.asr, "n_anchors": len(spans),
           "note": "나레이션→공정지침서 표준단계 시각 앵커. 다관점/반복은 DTW로 이 좌표계에 정렬.",
           "anchors": spans}
    Path(args.out_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] {len(spans)} 표준단계 앵커 -> {args.out_json}\n")
    for s in spans:
        print(f"  [{s['t_start']:5.1f}~{s['t_end']:5.1f}s] {s['step']}")
        print(f"        \"{s['narration'][:70]}\"")


if __name__ == "__main__":
    main()
