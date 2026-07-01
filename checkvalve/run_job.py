"""
Child process — the ONLY place ML (cv2/numpy/scipy via the pipeline) runs.
The Studio server shells this via the 3.13 venv python; it streams progress into
OUTPUT/<stem>/job/status.json. LLM is forced off in Phase 4 (step_author's real
client raises NotImplementedError → fall back to RAG).
"""
import argparse
import json
import os
import sys
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
    return None   # Phase 4: real Claude client seam not wired -> RAG only


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stem", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()
    client = _build_client() if a.llm else None

    def prog(stage, pct):
        _write(a.stem, a.job, state="running", stage=stage, pct=pct)

    try:
        _write(a.stem, a.job, state="running", stage="generate", pct=10)
        try:
            r = generate_guide(a.stem, client=client, on_progress=prog)
        except NotImplementedError:
            _write(a.stem, a.job, log_tail=["LLM 미구현 — RAG로 대체"])
            r = generate_guide(a.stem, client=None, on_progress=prog)
        _write(a.stem, a.job, state="done", stage="done", pct=100,
               bundle_path=r["bundle_path"], guide_url=r["guide_url"], error=None)
    except Exception as e:
        _write(a.stem, a.job, state="error", stage="generate",
               error=str(e), log_tail=traceback.format_exc().splitlines()[-40:])
        sys.exit(1)


if __name__ == "__main__":
    main()
