"""
Child process — the ONLY place ML (cv2/numpy/scipy via the pipeline) runs.
The Studio server shells this via the 3.13 venv python; it streams progress into
OUTPUT/<stem>/job/status.json. A directly-uploaded clip is preprocessed (keypoints)
first, then Claude analyzes the preprocessing (+ the process-doc PDF) to write the
steps — RAG was removed, so a configured API key (settings.get_client) is required;
without one the author raises and the job reports a clear error.
"""
import argparse
import json
import os
import sys
import threading
import time
import traceback

from .config import OUTPUT
from .pipeline import generate_guide


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write(stem, job, **kw):
    d = OUTPUT / stem / "job"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "status.json"
    cur = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"job_id": job, "stem": stem, "log_tail": []}
    cur.update(kw, pid=os.getpid(), job_id=job, updated_at=_now(), seq=cur.get("seq", 0) + 1)
    t = p.with_suffix(".json.tmp")
    t.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(t, p)


def _build_client():
    from .settings import get_client   # reads ~/.checkvalve/settings.json (never committed)
    return get_client()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stem", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()
    client = _build_client()   # generation is Claude-analysis only (RAG removed); None -> author errors

    def prog(stage, pct):
        _write(a.stem, a.job, state="running", stage=stage, pct=pct)

    # Heartbeat: bump updated_at every 30s through the long blocking sections (extraction,
    # the Claude vision call — which write no intermediate progress). The studio's
    # is_generating() staleness guard trusts updated_at recency; a LIVE child (even one
    # stalled inside a hung API call) keeps refreshing it, so the guard never false-negatives
    # and re-opens the cross-process race. Only a truly dead child stops the heartbeat and
    # eventually goes stale (unblocking edit/approve after a server-restart orphan).
    stop = threading.Event()

    def _heartbeat():
        while not stop.wait(30):
            try:
                _write(a.stem, a.job)   # updated_at/seq only; preserves current state/stage/pct
            except Exception:
                pass

    hb = threading.Thread(target=_heartbeat, daemon=True)
    try:
        # Preprocess a directly-uploaded clip if its keypoints aren't extracted yet
        # (heavy YOLO/hands/QC; skipped instantly when results/<stem>/ already exists).
        _write(a.stem, a.job, state="running", stage="preprocess", pct=5)
        hb.start()
        from .prepare.extract import ensure_extraction
        if ensure_extraction(a.stem, on_progress=prog):
            _write(a.stem, a.job, log_tail=["전처리 완료 — 키포인트 추출됨"])

        _write(a.stem, a.job, state="running", stage="analyze", pct=55)
        r = generate_guide(a.stem, client=client, on_progress=prog)   # Claude analyzes preprocessing (+PDF)
        stop.set(); hb.join(timeout=5)   # stop heartbeat before the terminal write so it can't clobber 'done'
        _write(a.stem, a.job, state="done", stage="done", pct=100,
               bundle_path=r["bundle_path"], guide_url=r["guide_url"], error=None)
    except Exception as e:
        stop.set(); hb.join(timeout=5)
        _write(a.stem, a.job, state="error", stage="generate",
               error=str(e), log_tail=traceback.format_exc().splitlines()[-40:])
        sys.exit(1)


if __name__ == "__main__":
    main()
