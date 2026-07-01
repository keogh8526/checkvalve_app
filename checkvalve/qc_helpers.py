"""
Primary-person / wrist / body-scale helpers.

Inlined (not imported) from the repo's qc_validate.py so this folder is fully
self-contained. The logic is identical, so the speed numbers stay calibrated to
the same subject and scale the QC report used.
"""
import math

# YOLO COCO-17 indices used here
Y = {"l_sho": 5, "r_sho": 6, "l_elb": 7, "r_elb": 8, "l_wri": 9, "r_wri": 10}
YOLO_NAMES = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder",
              "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
              "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def primary_person(frame):
    """Largest-bbox person as the primary subject."""
    persons = frame.get("persons") or []
    if not persons:
        return None

    def area(p):
        b = p.get("box")
        return (b[2] - b[0]) * (b[3] - b[1]) if b else 0
    return max(persons, key=area)


def yolo_xy(person, idx, conf_min=0.3):
    """(x, y) for a YOLO keypoint index if confident, else None."""
    kp = person["keypoints"][YOLO_NAMES[idx]]
    if kp["conf"] < conf_min:
        return None
    return (kp["x"], kp["y"])


def frame_scale(person):
    """Per-frame body scale in px: shoulder width if visible, else bbox-diagonal
    proxy. None when neither is available (e.g. close-ups)."""
    ls = yolo_xy(person, Y["l_sho"])
    rs = yolo_xy(person, Y["r_sho"])
    if ls and rs:
        d = dist(ls, rs)
        if d > 1:
            return d
    b = person.get("box")
    if b:
        diag = math.hypot(b[2] - b[0], b[3] - b[1])
        if diag > 1:
            return 0.25 * diag
    return None
