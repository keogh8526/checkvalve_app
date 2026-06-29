"""
[3.5] 다시점 합의 분할 (Multi-view Consensus Segmentation) — "영상을 어떻게 단계로 나눌 것인가"의 해법.

단일 시점 ruptures는 분할이 들쭉날쭉하다(한 각도에서 안 보이는 경계를 놓침).
예: front 빠른조작은 앞 70초를 1덩어리로(과소분할), top60는 같은 구간을 5섹터로 쪼갬.
→ DTW로 두 시점을 같은 타임라인에 정렬하고, 각 시점의 경계를 기준시점 시각으로 투영해
   '합의 경계'를 만든다. 한 시점이 놓친 경계를 다른 시점이 채워 정확한 섹터가 나온다.

타이밍 소스 = 잡담 없는 '빠른조작(무설명) 영상'. 표준시간은 여기서 실측한다.

입력 : --ref (기준시점 body.json, 예: front-fast) --ref-segs (그 segments.json)
        --view (다른시점 body.json, 반복가능) [--view-segs 대응 segments.json, 반복가능]
출력 : fused_segments.json — 합의 섹터(t_start/t_end/dur_sec) + 각 경계 지지 시점 수

usage:
  python pose/fuse_views.py --ref results/fast_front/body.json --ref-segs results/fast_front/segments.json \
      --view results/fast_top60/body.json --view-segs results/fast_top60/segments.json \
      --out-json results/fused/fused_segments.json
"""
import argparse
import json
from pathlib import Path

import numpy as np

from align_dtw import speed_profile, dtw


def seg_bounds(seg_path):
    sgs = json.loads(Path(seg_path).read_text(encoding="utf-8"))["segments"]
    return sorted({s["t_start"] for s in sgs} | {s["t_end"] for s in sgs})


def map_time_via_dtw(view_body, ref_body, N=400):
    """view 시각 → ref 시각 변환함수 (DTW 정렬). 반환: (fn, dtw_거리)."""
    rs, rdur = speed_profile(ref_body, N)
    vs, vdur = speed_profile(view_body, N)
    dist, path = dtw(vs, rs)               # view를 ref에 정렬
    v2r = {}
    for vi, ri in path:
        v2r.setdefault(vi, []).append(ri)
    v2r = {vi: float(np.mean(ri)) for vi, ri in v2r.items()}

    def fn(t_view):
        vi = int(round(t_view / vdur * (N - 1))) if vdur > 0 else 0
        vi = max(0, min(N - 1, vi))
        ri = v2r.get(vi, vi)
        return round(ri / (N - 1) * rdur, 1)
    return fn, round(float(dist), 3), rdur


def cluster(bounds_with_src, tol):
    """(시각, 시점이름) 목록 → ±tol 군집. 각 군집: 평균시각 + 지지 시점 수."""
    flat = sorted(bounds_with_src)
    used = [False] * len(flat)
    out = []
    for i, (b, _) in enumerate(flat):
        if used[i]:
            continue
        members = [flat[i]]; used[i] = True
        for j in range(i + 1, len(flat)):
            if not used[j] and abs(flat[j][0] - b) <= tol:
                members.append(flat[j]); used[j] = True
        t = round(sum(m[0] for m in members) / len(members), 1)
        views = {m[1] for m in members}
        out.append((t, len(views)))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="기준시점 body.json (예: front-fast)")
    ap.add_argument("--ref-segs", required=True)
    ap.add_argument("--view", action="append", default=[], help="다른시점 body.json (반복)")
    ap.add_argument("--view-segs", action="append", default=[], help="대응 segments.json (반복)")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--tol", type=float, default=2.0, help="경계 합의 군집 허용오차(초)")
    ap.add_argument("--min-sec", type=float, default=2.5, help="너무 짧은 섹터 병합 임계")
    ap.add_argument("--min-support", type=int, default=1,
                    help="경계 채택 최소 지지 시점 수(1=union, 2=2시점합의)")
    args = ap.parse_args()
    if len(args.view) != len(args.view_segs):
        ap.error("--view 와 --view-segs 개수가 같아야 함")

    ref_name = "ref"
    bounds = [(b, ref_name) for b in seg_bounds(args.ref_segs)]
    ref_dur = None
    align_info = []

    for vb, vs in zip(args.view, args.view_segs):
        fn, dist, ref_dur = map_time_via_dtw(vb, args.ref)
        vname = Path(vb).parent.name
        mapped = [fn(b) for b in seg_bounds(vs)]
        bounds += [(b, vname) for b in mapped]
        align_info.append({"view": vname, "dtw_distance": dist, "n_bounds": len(mapped)})

    # ref 길이로 끝 경계 확정
    if ref_dur is None:
        ref_dur = max(b for b, _ in bounds)
    clustered = cluster(bounds, args.tol)
    # min-support 필터(끝점 0·ref_dur는 항상 유지)
    kept = [t for t, sup in clustered if sup >= args.min_support or t <= 0.1 or t >= ref_dur - 0.1]
    kept = sorted(set([0.0] + kept + [round(ref_dur, 1)]))

    # 너무 짧은 섹터 병합
    merged = [kept[0]]
    for t in kept[1:]:
        if t - merged[-1] < args.min_sec:
            continue
        merged.append(t)
    if merged[-1] < ref_dur - 0.1:
        merged.append(round(ref_dur, 1))

    sectors = []
    for i in range(len(merged) - 1):
        t0, t1 = merged[i], merged[i + 1]
        # 이 경계 지지 시점 수(가장 가까운 군집)
        sup = max((s for t, s in clustered if abs(t - t0) <= args.tol), default=1)
        sectors.append({"sector": i + 1, "t_start": round(t0, 1), "t_end": round(t1, 1),
                        "dur_sec": round(t1 - t0, 1), "start_support_views": sup})

    out = {"ref": args.ref, "ref_dur": round(ref_dur, 1), "tol": args.tol,
           "min_support": args.min_support, "n_views_total": 1 + len(args.view),
           "alignment": align_info, "n_sectors": len(sectors),
           "note": "다시점 DTW 합의 분할. 표준시간=빠른조작영상 실측. 경계=시점 합의(과/미분할 보정).",
           "sectors": sectors}
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] 합의 섹터 {len(sectors)}개 (시점 {1+len(args.view)}개, tol={args.tol}s) -> {args.out_json}")
    for a in align_info:
        print(f"  정렬: {a['view']} DTW거리 {a['dtw_distance']} (경계 {a['n_bounds']}개)")
    for s in sectors:
        print(f"  섹터{s['sector']}: {s['t_start']:5.1f}~{s['t_end']:5.1f}s ({s['dur_sec']:4.1f}s) 지지{s['start_support_views']}시점")


if __name__ == "__main__":
    main()
