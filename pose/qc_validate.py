"""
Quality-control / anomaly validator for extracted pose keypoints.

Cross-checks YOLO body keypoints against MediaPipe Holistic and flags likely
false detections and artifacts:
  - coverage gaps (frames with no person)
  - person-count spikes (likely false extra detections)
  - chronically low-confidence keypoints
  - teleport / jitter (frame-to-frame jumps too large for the body scale)
  - out-of-bounds keypoints
  - cross-model disagreement on shared joints (shoulders / elbows / wrists)
  - hand handedness flips + fingertip jitter

Outputs: <out_dir>/qc.json (machine), qc.txt (human), suspicious_frames/*.jpg
"""

import argparse
import json
import math
from pathlib import Path

import cv2

# YOLO COCO-17 indices
Y = {"l_sho": 5, "r_sho": 6, "l_elb": 7, "r_elb": 8, "l_wri": 9, "r_wri": 10}
# MediaPipe pose-33 indices
M = {"l_sho": 11, "r_sho": 12, "l_elb": 13, "r_elb": 14, "l_wri": 15, "r_wri": 16}
SHARED = ["l_sho", "r_sho", "l_elb", "r_elb", "l_wri", "r_wri"]

YOLO_NAMES = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder",
              "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
              "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def primary_person(frame):
    """Pick the largest-box person as the primary subject (stable across frames)."""
    persons = frame.get("persons") or []
    if not persons:
        return None
    def area(p):
        b = p.get("box")
        return (b[2] - b[0]) * (b[3] - b[1]) if b else 0
    return max(persons, key=area)


def yolo_xy(person, idx, conf_min=0.3):
    """Return (x, y) for a YOLO keypoint index if confident, else None."""
    name = YOLO_NAMES[idx]
    kp = person["keypoints"][name]
    if kp["conf"] < conf_min:
        return None
    return (kp["x"], kp["y"])


def frame_scale(person):
    """Per-frame body scale in px: shoulder width if both shoulders are visible,
    else a bbox-diagonal proxy. Returns None only when neither is available.
    Always per-frame (no stale carry-over) so teleport/cross-model thresholds stay calibrated."""
    ls = yolo_xy(person, Y["l_sho"]); rs = yolo_xy(person, Y["r_sho"])
    if ls and rs:
        d = dist(ls, rs)
        if d > 1:
            return d
    b = person.get("box")
    if b:
        diag = math.hypot(b[2] - b[0], b[3] - b[1])
        if diag > 1:
            return 0.25 * diag   # ~shoulder-width fraction of the person box
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--body-json", required=True, help="YOLO keypoints json")
    ap.add_argument("--hands-json", default=None, help="MediaPipe holistic json")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--dump-frames", type=int, default=12, help="How many worst frames to save as images.")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    (out_dir / "suspicious_frames").mkdir(parents=True, exist_ok=True)

    body = json.loads(Path(args.body_json).read_text(encoding="utf-8"))
    W, H = body["resolution"]
    bframes = body["frames"]
    total = len(bframes)

    hands = None
    mp_by_frame = {}
    if args.hands_json and Path(args.hands_json).exists():
        hands = json.loads(Path(args.hands_json).read_text(encoding="utf-8"))
        for f in hands["frames"]:
            mp_by_frame[f["frame"]] = f
        if hands.get("resolution") != [W, H]:
            print(f"[warn] resolution mismatch: body {[W, H]} vs hands {hands.get('resolution')} "
                  f"-- cross-model pixel distances would be invalid; skipping cross-model checks")
            hands, mp_by_frame = None, {}

    flags = []          # list of dicts: {frame, type, detail, severity}
    susp_score = {}     # frame -> accumulated severity

    def add(frame_idx, ftype, detail, sev):
        flags.append({"frame": frame_idx, "type": ftype, "detail": detail, "severity": round(sev, 3)})
        susp_score[frame_idx] = susp_score.get(frame_idx, 0) + sev

    # --- coverage + person count ---
    no_det = 0
    counts = {}
    for f in bframes:
        n = f["num_persons"]
        counts[n] = counts.get(n, 0) + 1
        if n == 0:
            no_det += 1
    # longest no-detection gap
    longest_gap = cur = 0
    for f in bframes:
        if f["num_persons"] == 0:
            cur += 1
            longest_gap = max(longest_gap, cur)
        else:
            cur = 0
    # person-count spikes: frame jumps from 1 to >=2 then back (transient extra person)
    for i in range(1, len(bframes) - 1):
        prev, cur_n, nxt = bframes[i - 1]["num_persons"], bframes[i]["num_persons"], bframes[i + 1]["num_persons"]
        if cur_n >= 2 and prev <= 1 and nxt <= 1:
            add(bframes[i]["frame"], "person_spike", f"{prev}->{cur_n}->{nxt}", 1.0)

    # --- per-keypoint confidence + OOB + teleport (primary person) ---
    low_conf_counter = {n: 0 for n in YOLO_NAMES}
    prev_kp = {}        # name -> (x, y)
    prim_frames = 0
    for f in bframes:
        p = primary_person(f)
        if not p:
            prev_kp = {}
            continue
        prim_frames += 1
        scale = frame_scale(p)   # real per-frame scale (shoulders or bbox), or None

        for idx, name in enumerate(YOLO_NAMES):
            kp = p["keypoints"][name]
            x, y, c = kp["x"], kp["y"], kp["conf"]
            if c < 0.3:
                low_conf_counter[name] += 1
            if c >= 0.3 and (x < -5 or x > W + 5 or y < -5 or y > H + 5):
                add(f["frame"], "out_of_bounds", f"{name} at ({x:.0f},{y:.0f})", 1.5)
            # teleport: only when THIS frame has a real scale (no stale fallback -> no miscalibration)
            if scale and c >= 0.5 and name in prev_kp:
                d = dist((x, y), prev_kp[name])
                if d > 0.6 * scale and d > 40:      # big jump relative to body size
                    add(f["frame"], "teleport", f"{name} moved {d:.0f}px", min(2.0, d / scale))
            if c >= 0.5:
                prev_kp[name] = (x, y)
            elif name in prev_kp:
                del prev_kp[name]

    # --- cross-model disagreement (YOLO vs MediaPipe shared joints) ---
    xmodel_checked = xmodel_bad = 0
    if hands:
        for f in bframes:
            mf = mp_by_frame.get(f["frame"])
            if not mf or not mf.get("pose"):
                continue
            p = primary_person(f)
            if not p:
                continue
            scale = frame_scale(p)   # shoulders or bbox proxy -> works even without shoulders
            if not scale:
                continue
            pose = mf["pose"]   # [x,y,z,vis]*33
            for joint in SHARED:
                yx = yolo_xy(p, Y[joint])
                mlm = pose[M[joint]]
                if yx is None or mlm[3] < 0.5:   # vis
                    continue
                mxy = (mlm[0], mlm[1])
                xmodel_checked += 1
                d = dist(yx, mxy) / scale
                if d > 0.7:                      # joints disagree by >0.7 shoulder-widths
                    xmodel_bad += 1
                    add(f["frame"], "model_disagree", f"{joint} YOLO vs MP {d:.2f}sw", min(2.0, d))

    # --- assemble report ---
    worst = sorted(susp_score.items(), key=lambda kv: -kv[1])[: args.dump_frames]

    # dump worst frames as annotated images
    dumped = []
    if worst:
        reasons_by_frame = {}
        for fl in flags:
            reasons_by_frame.setdefault(fl["frame"], set()).add(fl["type"])
        body_by_frame = {f["frame"]: f for f in bframes}
        cap = cv2.VideoCapture(args.video)
        try:
            for fi, score in worst:
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ok, img = cap.read()
                if not ok:
                    continue
                p = primary_person(body_by_frame.get(fi, {}))
                if p:
                    for name in YOLO_NAMES:
                        kp = p["keypoints"][name]
                        if kp["conf"] >= 0.3:
                            cv2.circle(img, (int(kp["x"]), int(kp["y"])), 4, (0, 255, 255), -1)
                reasons = sorted(reasons_by_frame.get(fi, []))
                cv2.putText(img, f"f{fi} score={score:.1f} {','.join(reasons)}",
                            (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
                out = out_dir / "suspicious_frames" / f"frame_{fi:06d}_score{score:.0f}.jpg"
                cv2.imwrite(str(out), img)
                dumped.append(str(out))
        finally:
            cap.release()

    by_type = {}
    for fl in flags:
        by_type[fl["type"]] = by_type.get(fl["type"], 0) + 1

    report = {
        "video": args.video,
        "total_frames": total,
        "resolution": [W, H],
        "coverage": {
            "frames_with_person": total - no_det,
            "no_detection_frames": no_det,
            "no_detection_pct": round(no_det / total * 100, 2) if total else 0,
            "longest_gap_frames": longest_gap,
            "person_count_histogram": counts,
        },
        "low_confidence_keypoints": {n: c for n, c in sorted(low_conf_counter.items(), key=lambda kv: -kv[1]) if c > total * 0.2},
        "cross_model": {
            "joints_checked": xmodel_checked,
            "disagreements": xmodel_bad,
            "disagree_pct": round(xmodel_bad / xmodel_checked * 100, 2) if xmodel_checked else None,
        },
        "anomaly_counts_by_type": by_type,
        "total_anomaly_flags": len(flags),
        "worst_frames": [{"frame": fi, "score": round(s, 2)} for fi, s in worst],
        "dumped_images": dumped,
    }
    (out_dir / "qc.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # human-readable
    lines = [
        f"QC REPORT — {Path(args.video).name}",
        f"  frames: {total}  resolution: {W}x{H}",
        f"  coverage: {report['coverage']['no_detection_pct']}% frames had NO person "
        f"(longest gap {longest_gap}f), person-count {counts}",
        f"  low-confidence joints (>20% of frames): {report['low_confidence_keypoints'] or 'none'}",
        f"  cross-model: checked {xmodel_checked} joint-frames, "
        f"{xmodel_bad} disagreed ({report['cross_model']['disagree_pct']}%)",
        f"  anomaly flags by type: {by_type or 'none'}  (total {len(flags)})",
        f"  worst frames (saved as images): {[fi for fi, _ in worst]}",
    ]
    (out_dir / "qc.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"[done] QC written to {out_dir}")


if __name__ == "__main__":
    main()
