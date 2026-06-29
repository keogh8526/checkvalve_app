"""
[융합조립] 다시점 합의 섹터(타이밍) + 설명영상 앵커(단계 의미)를 결합해 최종 작업지도서 단계열을 만든다.

설계(리서치 근거):
  - 타이밍·섹터  = fuse_views.py 결과(빠른조작영상 다시점 합의, 실측)  ← '측정=비전'
  - 단계명·근거설명 = anchor_steps.py 결과(설명영상 나레이션→canonical)  ← '의미=언어'
  - 매핑 = 두 촬영본을 '절차 진행도 0~1'로 정규화해 대응(서로 다른 take라 절대시각 매칭 불가).
           → 빠른영상 섹터의 정규화 위치에 해당하는 설명영상 표준단계를 라벨로.
  - 라벨은 '순서기반 매핑(검수확정)'으로 명시. 표준시간은 실측이라 신뢰.

입력 : --fused fused_segments.json  --anchors anchors.json
출력 : steps.json (fused 타이밍 + 매핑 라벨 + 근거발화)

usage:
  python pose/assemble_fused.py --fused results/fused/fused_segments.json \
      --anchors results/run_front_full/anchors.json --out-json results/fused/steps.json
"""
import argparse
import json
from pathlib import Path

from canonical import NON_WORK_STEPS, UNCLASSIFIED, CANONICAL_ORDER, parts_for, desc_for, control_for


def step_durations_and_narr(anchor_sets):
    """다중경로 앵커 → 작업단계별 {총시간(가중치), 대표 근거발화}.
    시간순서가 아니라 '어떤 단계가 얼마나 등장했나'만 모은다(시간순은 Q&A라 신뢰불가)."""
    if isinstance(anchor_sets, dict):
        anchor_sets = [anchor_sets]
    durs, narr = {}, {}
    for anchors in anchor_sets:
        for a in anchors:
            st = a["step"]
            if st in NON_WORK_STEPS or st == UNCLASSIFIED:
                continue
            durs[st] = durs.get(st, 0.0) + max(0.1, a.get("dur_sec", a["t_end"] - a["t_start"]))
            if len(a.get("narration", "")) > len(narr.get(st, "")):
                narr[st] = a["narration"]
    return durs, narr


def canonical_bands(durs):
    """작업단계를 '공정 표준순서(canonical)'로 정렬하고, 설명영상 등장시간을 가중치로
    정규화 누적경계(0~1)를 만든다. → 빠른영상 섹터를 단조증가로 매핑하기 위한 띠."""
    present = [s for s in CANONICAL_ORDER if s in durs]      # 표준 공정순서 강제
    if not present:
        return []
    total = sum(durs[s] for s in present)
    bands, acc = [], 0.0
    for s in present:
        acc += durs[s] / total
        bands.append({"step": s, "end": acc})               # 누적 진행도 끝점
    return bands


def assign_label(progress, bands):
    """정규화 진행도(0~1) → 누적 띠에서 해당 단계(공정순서 단조)."""
    for b in bands:
        if progress <= b["end"] + 1e-9:
            return b["step"]
    return bands[-1]["step"]


def label_by_rule(sectors):
    """섹터 길이 규칙 라벨(도메인지식, ASR발화시간 의존 폐기).
    공정8~11 빠른영상 순서: 부품준비 → HINGE PIN(최장,핀삽입) → 정렬 → GUIDE → BODY-GUIDE → SET SCREW(종단).
    근거: 핀삽입이 가장 오래(공정 상식), 마지막 장구간=세트스크류 체결. HINGE PIN/정렬은 동시진행이라 분리상한 존재."""
    n = len(sectors)
    durs = [s["t_end"] - s["t_start"] for s in sectors]
    labels = [None] * n
    fill = ["정렬(SPRING·SPACER)", "GUIDE 결합", "BODY-GUIDE 결합", "검사/측정"]
    if n == 0:
        return labels
    if n < 3:
        # 섹터가 너무 적으면 준비/핀/세트스크류 특수규칙이 서로 덮어써 충돌 → 공정서 순서로 단순 채움
        base = ["부품 준비"] + fill
        return [base[min(len(base) - 1, i)] for i in range(n)]
    labels[0] = "부품 준비"                                  # 첫 섹터 = 준비
    # HINGE PIN = 준비(0) 제외한 최장 (longest==0이 '부품 준비'를 덮어쓰지 않도록)
    longest = max(range(1, n), key=lambda i: durs[i])
    labels[longest] = "HINGE PIN 조립"
    # SET SCREW = HINGE PIN 이후 미배정 중 최장(없으면 미배정 전체 중 최장) — HINGE PIN 덮어쓰기 방지
    tail = [i for i in range(longest + 1, n) if labels[i] is None] \
        or [i for i in range(n) if labels[i] is None]
    if tail:
        labels[max(tail, key=lambda i: durs[i])] = "SET SCREW 결합"
    # 나머지를 공정서 순서(정렬→GUIDE→BODY-GUIDE→검사)로 채움
    fi = 0
    for i in range(n):
        if labels[i] is None:
            labels[i] = fill[min(len(fill) - 1, fi)]; fi += 1
    return labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fused", required=True, help="fuse_views.py 결과(타이밍)")
    ap.add_argument("--anchors", required=True, action="append",
                    help="anchor_steps.py 결과(단계 의미). 반복 지정 시 다중경로(여러 설명영상) 결합")
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()

    fu = json.loads(Path(args.fused).read_text(encoding="utf-8"))
    sectors = fu["sectors"]
    total = fu["ref_dur"]
    # 다중경로 앵커 → 단계별 대표 근거발화(라벨용 아님, 설명용)
    anchor_sets = [json.loads(Path(p).read_text(encoding="utf-8"))["anchors"] for p in args.anchors]
    _, narr = step_durations_and_narr(anchor_sets)
    # ★ 라벨 = ASR 발화시간 매핑 폐기 → 섹터 길이 규칙(도메인지식). 근본원인1 제거.
    rule_labels = label_by_rule(sectors)

    steps = []
    for i, s in enumerate(sectors, 1):
        label = rule_labels[i - 1]
        steps.append({
            "step": i,
            "공정단계": label,
            "라벨_근거": "순서기반 매핑(설명영상 표준단계, 검수확정 필요)",
            "t_start": s["t_start"], "t_end": s["t_end"],
            "표준시간_후보_초": s["dur_sec"],          # 실측(빠른영상 다시점 합의)
            "분류": "VA(작업)",
            "지지시점": s.get("start_support_views", 1),
            "근거발화": narr.get(label, "(설명영상에 해당 발화 없음)")[:120],
            "작업설명": desc_for(label),                  # 공정서 작업순서(문서 출처, LLM 불필요)
            "중점관리항목": control_for(label),           # 공정서/멘토양식 기준
            "부품표": [{"부품명": n, "수량": q} for n, q in parts_for(label)],  # 공정서 BOM(재료)
        })

    out = {"n_steps": len(steps), "mode": "fused_multiview",
           "source": {"timing": args.fused, "labels": args.anchors},
           "note": "표준시간=빠른조작영상 다시점합의 실측 / 단계명=설명영상 진행도매핑(검수확정) / 작업설명=빈칸+LLM초안",
           "steps": steps}
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] 다시점 융합 단계열 {len(steps)}개 -> {args.out_json}")
    for s in steps:
        print(f"  [단계{s['step']}] {s['t_start']:5.1f}~{s['t_end']:5.1f}s ({s['표준시간_후보_초']:4.1f}s) "
              f"지지{s['지지시점']}시점 | {s['공정단계']}")


if __name__ == "__main__":
    main()
