"""
Background job runner + on-disk JobStore. The Studio (ML-free) starts a child
`checkvalve.run_job` via the venv python; state lives in OUTPUT/<stem>/job/status.json.
Single-flight per stem via an O_EXCL lockfile; boot-rebuild marks interrupted jobs.
"""
import calendar
import json
import os
import subprocess
import threading
import time

from ..config import OUTPUT, REPO, VENV_PY

_MAX_STALE_SEC = 1800   # a live run refreshes updated_at every stage (max gap ~a few min);
#                         only a wedged job / server-restart-orphan-with-reused-pid exceeds this.


def _age_sec(ts):
    try:
        return time.time() - calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None


class Busy(Exception):
    def __init__(self, job_id):
        self.job_id = job_id


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _jdir(stem):
    d = OUTPUT / stem / "job"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _atomic(p, o):
    t = p.with_suffix(p.suffix + ".tmp")
    t.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(t, p)


def _pid_alive(pid):
    if not pid:
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259   # STILL_ACTIVE
    except Exception:
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ValueError):
            return False


def is_generating(stem):
    """True if a run_job child is actively generating for this stem. Cross-process
    job-state guard: the trust gates (approve/edit/review/export) refuse while this holds,
    because generation rewrites steps_bundle.json/review_state.json/guide from another
    process that the in-process _stem_lock cannot exclude."""
    p = OUTPUT / stem / "job" / "status.json"
    if not p.is_file():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    if d.get("state") not in ("queued", "running") or not _pid_alive(d.get("pid")):
        return False
    age = _age_sec(d.get("updated_at"))
    if age is not None and age > _MAX_STALE_SEC:
        return False   # pid looks alive but status is long-stale (restart + reused pid) — don't hard-block forever
    return True


class JobStore:
    def read(self, job):
        st = job.rsplit(".", 1)[0]
        p = OUTPUT / st / "job" / "status.json"
        if not p.is_file():
            return {"state": "unknown", "error": "no such job", "stage": "", "pct": 0, "log_tail": []}
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if d.get("job_id") == job else {"state": "unknown", "error": "superseded",
                                                 "stage": "", "pct": 0, "log_tail": []}

    def rebuild_on_boot(self):
        if not OUTPUT.exists():
            return
        for p in OUTPUT.glob("*/job/status.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            lk = p.parent / ".lock"
            if d.get("state") in ("running", "queued") and not _pid_alive(d.get("pid")):
                d.update(state="error", error="interrupted", seq=(d.get("seq", 0) + 1))
                _atomic(p, d)
            if lk.exists() and not _pid_alive(d.get("pid")):
                lk.unlink(missing_ok=True)


JOBS = JobStore()
_START_GUARD = threading.Lock()   # serialize lock-acquire across threads (closes unlink->reopen TOCTOU)


class Runner:
    def start(self, stem, use_llm):
        d = _jdir(stem)
        lock = d / ".lock"
        sp = d / "status.json"
        # Hold the guard across the WHOLE acquire->spawn->pid-write sequence. If it were
        # released right after os.close(fd), a second thread could enter, see the lockfile,
        # read status.json while pid is still None (_pid_alive(None)==False), treat it as
        # stale, unlink+reopen, and spawn a duplicate child. Popen is fast; single-operator.
        with _START_GUARD:
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                cur = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else {}
                if _pid_alive(cur.get("pid")):
                    raise Busy(cur.get("job_id", f"{stem}.busy"))
                lock.unlink(missing_ok=True)   # stale lock from a dead child
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            job = f"{stem}.{time.time_ns()}"   # ns (single dot preserved for _stem_of): unique even <1s apart
            _atomic(sp, {"job_id": job, "stem": stem, "pid": None, "seq": 0, "state": "queued",
                         "stage": "spawn", "pct": 0, "log_tail": [], "bundle_path": None,
                         "guide_url": None, "error": None, "started_at": _now(), "updated_at": _now()})
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            args = [str(VENV_PY), "-m", "checkvalve.run_job", "--stem", stem, "--job", job]
            if use_llm:
                args.append("--llm")
            p = subprocess.Popen(args, cwd=str(REPO), env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            st = json.loads(sp.read_text(encoding="utf-8"))
            st.update(pid=p.pid, state="running", seq=st.get("seq", 0) + 1)
            _atomic(sp, st)
        threading.Thread(target=self._reap, args=(p, d, lock, job), daemon=True).start()
        return job

    def _reap(self, p, d, lock, job):
        rc = p.wait()
        sp = d / "status.json"
        with _START_GUARD:   # only clean up if a NEWER job hasn't already taken over this stem's lock
            st = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else {}
            if st.get("job_id") != job:
                return                          # superseded — the newer job owns .lock + status
            lock.unlink(missing_ok=True)
            if st.get("state") == "running":    # child died w/o writing a terminal state
                st.update(state="error", error=f"exit {rc}", seq=st.get("seq", 0) + 1)
                _atomic(sp, st)


RUNNER = Runner()
