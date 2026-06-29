"""
파이프라인 검증 테스트 스위트 — 모듈별 기능테스트 + 단계간 연결(handoff) + 전체 end-to-end.

목적: "입력→출력이 신뢰도 높게 나오는가"를 정의된 합격기준으로 판별한다.
원칙(정직): 두 단계로 나눈다.
  Tier 1 (구조/기능 검증, 지금 측정 가능): 모듈 실행·스키마 유효·값 정상범위·연결 일치 → PASS/FAIL
  Tier 2 (정확도/신뢰도): 정답셋(ground truth)이 없으면 경계오차·분류정확도는 '수치화 불가'.
          → 측정 가능한 것만 측정하고, 불가한 것은 명시적으로 'UNMEASURED(한계)'로 보고.

usage: python tests/verify_pipeline.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_FULL = ROOT / "results/run_front_full"     # 설명영상 풀체인(의미 소스)
FAST = {"front": ROOT / "results/fast_front", "top60": ROOT / "results/fast_top60"}
FUSED = ROOT / "results/fused/fused_segments.json"

P = F = U = 0          # pass / fail / unmeasured
LOG = []


def chk(name, cond, detail=""):
    global P, F
    ok = bool(cond)
    P += ok; F += (not ok)
    LOG.append(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def unmeasured(name, why):
    global U
    U += 1
    LOG.append(f"  [UNMEASURED] {name} — {why}")


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sane_segments(segs, key_s="t_start", key_e="t_end"):
    """구간이 단조·비음수·연속(겹침/공백 없음)인지."""
    issues = []
    prev_e = None
    for i, s in enumerate(segs):
        if s[key_e] < s[key_s]:
            issues.append(f"seg{i} 역전({s[key_s]}>{s[key_e]})")
        if prev_e is not None and abs(s[key_s] - prev_e) > 0.51:
            issues.append(f"seg{i} 불연속(gap {s[key_s]-prev_e:.1f}s)")
        prev_e = s[key_e]
    return issues


def main():
    print("=" * 64)
    print(" 체크밸브 파이프라인 검증 스위트")
    print("=" * 64)

    # ── M1 extract_pose ──────────────────────────────────────────
    LOG.append("\n■ M1 extract_pose (포즈추출)")
    for name, d in {"run_front_full": RUN_FULL, **FAST}.items():
        bp = (d if isinstance(d, Path) and d.name.endswith(".json") else Path(d) / "body.json")
        if not bp.exists():
            chk(f"{name}/body.json 존재", False); continue
        b = load(bp); fr = b["frames"]; n = len(fr)
        det = sum(1 for f in fr if f["num_persons"] > 0)
        has17 = all(len(f["persons"][0]["keypoints"]) == 17 for f in fr if f["num_persons"] > 0)
        chk(f"{name} body 스키마(17키포인트)", has17)
        chk(f"{name} 검출률>=90%", det / n >= 0.90, f"{det/n*100:.1f}%")

    # ── M2 segment ───────────────────────────────────────────────
    LOG.append("\n■ M2 segment (단계분할)")
    for name in ("front", "top60"):
        sp = FAST[name] / "segments.json"
        if not chk(f"{name}/segments.json 존재", sp.exists()):
            continue
        sg = load(sp); segs = sg["segments"]
        chk(f"{name} 섹터>=1", len(segs) >= 1, f"{len(segs)}섹터")
        iss = sane_segments(segs)
        chk(f"{name} 구간 연속·비역전", not iss, "; ".join(iss[:3]))
        # eff_fps 일치(=pose fps/stride)
        b = load(FAST[name] / "body.json")
        chk(f"{name} eff_fps 일치", abs(sg["eff_fps"] - b["fps"] / b.get("stride", 1)) < 0.1)

    # ── M3 fuse_views (다시점 합의) ───────────────────────────────
    LOG.append("\n■ M3 fuse_views (DTW 다시점 합의분할)")
    if chk("fused_segments.json 존재", FUSED.exists()):
        fu = load(FUSED)
        chk("DTW 정렬거리<0.5(정렬성공)", fu["alignment"][0]["dtw_distance"] < 0.5,
            f"거리 {fu['alignment'][0]['dtw_distance']}")
        iss = sane_segments(fu["sectors"])
        chk("합의 섹터 연속·비역전", not iss, "; ".join(iss[:3]))
        # 합의가 단일시점보다 섹터를 늘렸는가(과소분할 보정 증거)
        f6 = len(load(FAST["front"] / "segments.json")["segments"])
        chk("합의>=단일시점 front(과소분할 보정)", fu["n_sectors"] >= f6,
            f"front {f6} → 합의 {fu['n_sectors']}")

    # ── M4 extract_asr ───────────────────────────────────────────
    LOG.append("\n■ M4 extract_asr (나레이션)")
    ap = RUN_FULL / "asr.json"
    if chk("asr.json 존재", ap.exists()):
        a = load(ap); segs = a["segments"]
        chk("ASR 문장>=10", len(segs) >= 10, f"{len(segs)}문장")
        chk("ASR start<end·텍스트존재", all(s["start"] <= s["end"] and s["text"] for s in segs))
        chk("ASR 모델=large-v3", a.get("model") == "large-v3", a.get("model"))

    # ── M5 anchor_steps ──────────────────────────────────────────
    LOG.append("\n■ M5 anchor_steps (표준단계 앵커)")
    anp = RUN_FULL / "anchors.json"
    if chk("anchors.json 존재", anp.exists()):
        an = load(anp); sp = an["anchors"]
        chk("앵커>=1", len(sp) >= 1, f"{len(sp)}앵커")
        chk("앵커 t_start<=t_end", all(s["t_start"] <= s["t_end"] for s in sp))

    # ── M6 refine_steps ──────────────────────────────────────────
    LOG.append("\n■ M6 refine_steps (정밀화·VA/NVA)")
    rp = RUN_FULL / "refined.json"
    if chk("refined.json 존재", rp.exists()):
        r = load(rp); va = r["VA_steps"]
        neg = [s for s in va if s["t_end"] < s["t_start"]]
        chk("음수구간 없음(M8 snap 수정)", not neg, f"{len(neg)}개 역전")
        import math
        nan_act = [s for s in va if s.get("활동량") is None or
                   (isinstance(s.get("활동량"), float) and math.isnan(s["활동량"]))]
        chk("활동량 NaN 없음(M7 가드)", not nan_act, f"{len(nan_act)}개 NaN")

    # ── M7 build_steps ───────────────────────────────────────────
    LOG.append("\n■ M7 build_steps (융합 → steps.json)")
    stp = RUN_FULL / "steps.json"
    if chk("steps.json 존재", stp.exists()):
        st = load(stp)
        chk("steps 스키마(n_steps==len)", st["n_steps"] == len(st["steps"]))
        chk("mode 명시", "mode" in st, st.get("mode"))

    # ── M8 generate_html ─────────────────────────────────────────
    LOG.append("\n■ M8 generate_html (작업지도서 렌더)")
    hp = RUN_FULL / "work_instruction.html"
    if chk("work_instruction.html 존재", hp.exists()):
        h = hp.read_text(encoding="utf-8")
        chk("HTML 테이블 존재", "<table>" in h)
        # 데이터행만 카운트(헤더 th·tfoot 제외) — 각 데이터행은 <td class="no"> 셀을 가짐
        import re
        data_rows = len(re.findall(r'<td class="no">', h))
        chk("데이터행 수==steps", data_rows == load(stp)["n_steps"],
            f"{data_rows}행 vs {load(stp)['n_steps']}단계")

    # ── 전체 연결(handoff) ───────────────────────────────────────
    LOG.append("\n■ E2E 연결(handoff)")
    chk("설명영상 풀체인 산출물 7종 모두 존재",
        all((RUN_FULL / f).exists() for f in
            ["body.json", "segments.json", "asr.json", "anchors.json",
             "refined.json", "steps.json", "work_instruction.html"]))

    # ── Tier 2 신뢰도(정답셋 없으면 측정불가) ─────────────────────
    LOG.append("\n■ Tier 2 신뢰도/정확도 (정직한 한계)")
    gt = ROOT / "data/ground_truth.json"
    if gt.exists():
        unmeasured("경계오차/분류정확도", "정답셋 발견 — 별도 평가 스크립트 필요(미구현)")
    else:
        unmeasured("단계경계 오차(초)", "정답셋(data/ground_truth.json) 없음 → 정확도 수치화 불가")
        unmeasured("단계 분류 정확도", "정답셋 없음 → 키워드 분류 정/오 판별 불가")
        unmeasured("표준시간 신뢰도", "단일 작업자·단일 회차 → 통계(중앙값±범위) 불가, '참고시간'")

    print("\n".join(LOG))
    print("\n" + "=" * 64)
    print(f" 결과: PASS {P} · FAIL {F} · UNMEASURED {U}")
    print("=" * 64)
    if F:
        print(" ⚠ FAIL 존재 — 구조/기능 결함. 위 FAIL 항목 확인.")
    else:
        print(" ✅ Tier1(구조/기능) 전부 PASS. 단, Tier2(정확도)는 정답셋 부재로 UNMEASURED.")
        print("    → '파이프라인은 신뢰도 높게 완주하나, 출력 정확도는 정답셋 라벨링 전까지 미검증'이 정직한 판정.")
    sys.exit(1 if F else 0)


if __name__ == "__main__":
    main()
