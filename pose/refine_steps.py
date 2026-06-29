"""
단계 정밀화 — 나레이션 앵커(의미) + 손목속도(운동) 결합으로 분할 정확도를 높이고
쓸데없는 동작(NVA)을 구별한다. (표준동작 추출의 핵심)

전략:
  1) 나레이션 앵커 = 의미적 단계 경계 (무엇을 하는가)
  2) 손목속도 = 각 앵커 구간의 '실제 작업 활동량' 측정 + 경계 스냅
  3) NVA 구별:
       - 앵커 구간인데 활동량 매우 낮음 -> '설명/대기'(작업 아님)
       - 앵커 사이 빈 구간 + 고속 이동 -> '이동(transport, 비부가)'
       - 활동량 충분 + 앵커 있음 -> 'VA(부가가치 작업)'

입력 : --anchors canonical_v2.json(절대시각), --body front_explain_body.json(전체)
출력 : refined_steps.json (VA/NVA 라벨 + 활동량 + 스냅 경계)

usage:
  python pose/refine_steps.py --anchors results/seg_test/canonical_v2.json \
      --body results/full/front_explain_body.json --out-json results/seg_test/refined.json
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np

from segment import smooth, wrist_xy, primary_person


def speed_series(body_json):
    d = json.loads(Path(body_json).read_text(encoding="utf-8"))
    fps = d["fps"]; stride = d.get("stride", 1); eff = fps / stride
    sw = []
    for fr in d["frames"]:
        p = primary_person(fr)
        if p is not None:
            k = p["keypoints"]; ls, rs = k["left_shoulder"], k["right_shoulder"]
            if ls["conf"] > 0.3 and rs["conf"] > 0.3:
                sw.append(math.hypot(ls["x"] - rs["x"], ls["y"] - rs["y"]))
    scale = float(np.median(sw)) if sw else 1.0
    vs = []
    for name in ("left_wrist", "right_wrist"):
        x, y = wrist_xy(d, name)
        xs = smooth(x / scale, eff); ys = smooth(y / scale, eff)
        vs.append(np.sqrt(np.diff(xs) ** 2 + np.diff(ys) ** 2) * eff)
    sp = smooth(np.mean(vs, axis=0), eff, 0.5, 0.01)
    # NaN 가드(M7): 전 구간 결측이면 중앙값이 NaN → 모든 단계 활동량 NaN으로 조용히 오분류됨. segment.py와 동일하게 차단.
    if np.all(np.isnan(sp)):
        raise SystemExit("[err] 손목 신호 전부 결측 — 검출 실패 영상 (refine 불가)")
    sp = np.nan_to_num(sp, nan=float(np.nanmedian(sp)))
    t = np.arange(len(sp)) * stride / fps     # 절대시각(초)
    return t, sp


def mean_speed(t, sp, t0, t1):
    m = (t >= t0) & (t < t1)
    return float(np.mean(sp[m])) if m.any() else 0.0


def snap(t, sp, t_target, win=3.0, after=None):
    """t_target 근처 ±win에서 속도 최저점(정지)으로 경계 스냅.
    after 지정 시 그 시각 이후 구간에서만 탐색(M8: 경계 역전·음수구간 방지)."""
    m = (t >= t_target - win) & (t <= t_target + win)
    if after is not None:
        m &= (t > after)
    if not m.any():
        return round(max(t_target, after) if after is not None else t_target, 1)
    idx = np.where(m)[0]
    return round(float(t[idx[np.argmin(sp[idx])]]), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--body", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--active", type=float, default=0.0, help="활동량 임계(미지정시 중앙값 사용)")
    args = ap.parse_args()

    t, sp = speed_series(args.body)
    anchors = json.loads(Path(args.anchors).read_text(encoding="utf-8"))["anchors"]
    active_th = args.active or float(np.median(sp))   # 전체 중앙값을 작업/비작업 기준

    steps = []
    for a in anchors:
        t0, t1 = a["t_start"], a["t_end"]
        v = mean_speed(t, sp, t0, t1)
        s0 = snap(t, sp, t0); s1 = snap(t, sp, t1, after=s0)   # s1은 s0 이후에서만 → 음수구간 방지(M8)
        # 분류
        if v < active_th * 0.6:
            cls = "설명/대기(저활동)"      # 앵커 있으나 손 거의 안 움직임 = 작업 아님
        else:
            cls = "VA(작업)"               # 실제 부가가치 작업
        steps.append({"step": a["step"], "t_start": s0, "t_end": s1,
                      "표준시간_후보": round(s1 - s0, 1), "활동량": round(v, 3),
                      "분류": cls, "나레이션": a["narration"][:60]})

    # 앵커 사이 빈 구간 = NVA 후보
    nva = []
    anchors_sorted = sorted(anchors, key=lambda x: x["t_start"])
    for i in range(len(anchors_sorted) - 1):
        g0, g1 = anchors_sorted[i]["t_end"], anchors_sorted[i + 1]["t_start"]
        if g1 - g0 >= 3.0:
            v = mean_speed(t, sp, g0, g1)
            kind = "이동(transport,비부가)" if v > active_th else "대기/멈춤"
            nva.append({"t_start": round(g0, 1), "t_end": round(g1, 1),
                        "활동량": round(v, 3), "분류": f"NVA-{kind}"})

    out = {"active_threshold": round(active_th, 3),
           "note": "의미=나레이션앵커, 경계=속도스냅, VA/NVA=활동량. 표준시간=VA구간만 합산 권장.",
           "VA_steps": steps, "NVA_segments": nva}
    Path(args.out_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] 활동량 기준={active_th:.3f}\n--- 단계(나레이션 앵커 + 속도 분류) ---")
    for s in steps:
        print(f"  {s['t_start']:6.1f}~{s['t_end']:6.1f}s ({s['표준시간_후보']:5.1f}s) v={s['활동량']:.2f} "
              f"[{s['분류']}] {s['step']}")
    print(f"--- NVA 후보(앵커 사이 빈 구간) {len(nva)}개 ---")
    for n in nva:
        print(f"  {n['t_start']:6.1f}~{n['t_end']:6.1f}s v={n['활동량']:.2f} [{n['분류']}]")
    print(f"[done] -> {args.out_json}")


if __name__ == "__main__":
    main()
