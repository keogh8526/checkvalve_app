"""
Operator Studio — stdlib http.server router. Imports ZERO ML (all ML runs in the
child `run_job`). Serves the SPA, the JSON API, and the generated guides (Range/206)
under OUTPUT with a path-boundary guard. See ARCHITECTURE.md §5 for the contract.
"""
import http.server
import json
import mimetypes
import re
import socketserver
import urllib.parse

PART_ID_RE = re.compile(r"[A-Za-z0-9_\-]+")   # /api/doc part_id allow-list (path-safe)

from ..config import OUTPUT, STATIC, TEMPLATE, is_timeline
from ..paths import list_stems
from ..prepare import doc_stub
from . import services
from .export import ExportBlocked
from .runner import RUNNER, JOBS, Busy

CHUNK = 1 << 16


def _stem_of(job):
    return job.rsplit(".", 1)[0]


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    # ── low-level helpers ──
    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _raw_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _qs(self, key):
        return (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get(key) or [""])[0]

    def _send_file(self, fs, ctype=None):
        ctype = ctype or (mimetypes.guess_type(str(fs))[0] or "application/octet-stream")
        size = fs.stat().st_size
        rng = self.headers.get("Range")
        do_range = False
        if rng and rng.startswith("bytes="):
            s, _, e = rng[6:].partition("-")
            try:
                start = int(s) if s else 0
                end = min(int(e), size - 1) if e else size - 1
                do_range = True
            except ValueError:
                do_range = False                     # malformed Range -> serve full body
        with open(fs, "rb") as f:
            if do_range:
                start = min(start, size - 1)
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
                self.end_headers()
                f.seek(start)
                while length > 0:
                    chunk = f.read(min(CHUNK, length))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    length -= len(chunk)
            else:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                while True:
                    chunk = f.read(CHUNK)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

    def _serve_output(self, path):
        rel = urllib.parse.unquote(path[len("/output/"):])
        parts = rel.split("/")
        if ".." in parts or not parts or parts[0] not in list_stems():
            return self._json(404, {"error": "not found"})
        fs = (OUTPUT / rel).resolve()
        if not (fs.is_file() and fs.is_relative_to(OUTPUT.resolve())):
            return self._json(404, {"error": "not found"})
        self._send_file(fs)

    def _serve_static(self, path):
        rel = urllib.parse.unquote(path[len("/static/"):])
        fs = (STATIC / rel).resolve()
        if not (fs.is_file() and fs.is_relative_to(STATIC.resolve())):
            return self._json(404, {"error": "not found"})
        self._send_file(fs)

    # ── GET ──
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path in ("/", ""):
                return self._send_file(STATIC / "index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                return self._serve_static(path)
            if path == "/api/parts":
                return self._json(200, services.api_parts())
            if path == "/api/status":
                st = JOBS.read(self._qs("job"))
                return self._json(200 if st.get("state") != "unknown" else 404, st)
            if path == "/api/bundle":
                stem = _stem_of(self._qs("job"))
                if stem not in list_stems():
                    return self._json(404, {"error": "unknown job"})
                try:
                    return self._json(200, services.get_bundle(stem))
                except FileNotFoundError:
                    return self._json(404, {"error": "no bundle"})
            if path == "/api/preview":
                stem = _stem_of(self._qs("job"))
                if stem not in list_stems():
                    return self._json(404, {"error": "unknown job"})
                if not is_timeline(stem):
                    return self._json(409, {"error": "preview는 타임라인 클립 전용"})
                try:
                    services.ensure_rendered(stem)
                except FileNotFoundError:
                    return self._json(404, {"error": "no bundle"})
                self.send_response(302)
                self.send_header("Location", f"/output/{stem}/guide/index.html")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path.startswith("/output/"):
                return self._serve_output(path)
            return self._json(404, {"error": "not found"})
        except BrokenPipeError:
            pass
        except Exception as e:
            self._json(500, {"error": str(e)})

    # ── POST ──
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/run":
                b = self._json_body()
                stem = b.get("stem")
                if stem not in list_stems():
                    return self._json(404, {"error": "unknown stem"})
                try:
                    job = RUNNER.start(stem, bool(b.get("use_llm")))
                except Busy as e:
                    return self._json(409, {"error": "busy", "job_id": e.job_id})
                return self._json(200, {"job_id": job})
            if path == "/api/step/review":
                b = self._json_body()
                stem = _stem_of(b.get("job", ""))
                if stem not in list_stems():
                    return self._json(404, {"error": "unknown job"})
                return self._json(200, services.mark_reviewed(stem, int(b["no"])))
            if path == "/api/approve":
                b = self._json_body()
                stem = _stem_of(b.get("job", ""))
                if stem not in list_stems():
                    return self._json(404, {"error": "unknown job"})
                ok, payload = services.approve(stem, b.get("signed_by") or "operator")
                return self._json(200 if ok else 403, payload)
            if path == "/api/export":
                b = self._json_body()
                stem = _stem_of(b.get("job", ""))
                if stem not in list_stems():
                    return self._json(404, {"error": "unknown job"})
                try:
                    return self._json(200, services.build_export(stem))
                except ExportBlocked as e:
                    return self._json(409, {"error": str(e)})
            if path == "/api/doc":
                part_id = self._qs("part_id") or "GMT-CV-008"
                if not PART_ID_RE.fullmatch(part_id):     # block path traversal via part_id
                    return self._json(400, {"error": "invalid part_id"})
                return self._json(200, doc_stub.store_doc(part_id, self._raw_body()))
            return self._json(404, {"error": "not found"})
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            self._json(500, {"error": str(e)})

    # ── PUT ──
    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/step":
                b = self._json_body()
                stem = _stem_of(b.get("job", ""))
                if stem not in list_stems():
                    return self._json(404, {"error": "unknown job"})
                return self._json(200, services.edit_step(stem, int(b["no"]), b.get("fields") or {}))
            return self._json(404, {"error": "not found"})
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            self._json(500, {"error": str(e)})


def serve(port=8765):
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler) as httpd:
        print(f"studio: http://127.0.0.1:{port}/", flush=True)
        httpd.serve_forever()


def main():
    assert TEMPLATE.exists(), f"template not found: {TEMPLATE}"
    JOBS.rebuild_on_boot()
    serve(8765)


if __name__ == "__main__":
    main()
