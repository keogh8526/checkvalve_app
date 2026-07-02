"""
Studio entry — double-click / exe. Starts the ML-FREE server on the MAIN thread
and opens the browser from a timer thread. Frozen-aware (PyInstaller onefile).
"""
import os
import socket
import sys
import threading
import time
import webbrowser
from contextlib import closing


def _frozen():
    return getattr(sys, "frozen", False)


def repo_root():
    env = os.environ.get("CHECKVALVE_REPO")
    if env and os.path.isdir(env):
        return env
    if _frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # app/->checkvalve/->repo


def _free(pref=8765):
    with closing(socket.socket()) as s:
        try:
            s.bind(("127.0.0.1", pref)); return pref
        except OSError:
            s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def _wait(port, t=8.0):
    end = time.time() + t
    while time.time() < end:
        with closing(socket.socket()) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.15)
    return False


def _die(m):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, m, "체크밸브 스튜디오", 0x10)
    except Exception:
        sys.stderr.write(m + "\n")
    sys.exit(1)


def main():
    try:
        os.environ.setdefault("CHECKVALVE_REPO", repo_root())
        sys.path.insert(0, os.environ["CHECKVALVE_REPO"])
        from checkvalve.app import studio   # ZERO ML import
        from checkvalve.app.runner import JOBS
        JOBS.rebuild_on_boot()               # recover interrupted jobs (studio.main does this; keep parity here)
        port = int(os.environ.get("STUDIO_PORT") or _free())

        def opener():
            if _wait(port):
                webbrowser.open(f"http://127.0.0.1:{port}/")
            else:
                _die(f"스튜디오 서버 기동 실패 (포트 {port})")

        threading.Thread(target=opener, daemon=True).start()
        studio.serve(port)   # blocks on MAIN thread
    except Exception as e:
        _die("시작 오류:\n%r" % e)


if __name__ == "__main__":
    main()
