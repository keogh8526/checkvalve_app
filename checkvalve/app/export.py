"""
Self-contained export: a zip of the guide (index.html + steps_data.js + clip.mp4 +
a tiny file:// viewer). Approval-gated. Timeline clip only (the small ~75MB deliverable
clip, never the 309MB timing clip). Uses guide/clip.mp4 so there is no ../data traversal.
"""
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from ..config import OUTPUT, REPO, is_timeline
from ..paths import list_stems
from ..render import render
from .preview import _lock


class ExportBlocked(Exception):
    pass


def build_export(stem):
    if stem not in list_stems():
        raise ExportBlocked("unknown stem")
    if not is_timeline(stem):
        raise ExportBlocked("타임라인 클립만 내보낼 수 있습니다")
    b = json.loads((OUTPUT / stem / "steps_bundle.json").read_text(encoding="utf-8"))
    if not b.get("review", {}).get("approved"):
        raise ExportBlocked("not_approved")
    with _lock(stem):
        render(stem, b)   # SAME render path as preview -> guide/clip.mp4 present
    guide = OUTPUT / stem / "guide"
    exdir = OUTPUT / stem / "export"
    exdir.mkdir(parents=True, exist_ok=True)
    zpath = exdir / f"작업지도서_{stem[-9:]}.zip"

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        html = (guide / "index.html").read_text(encoding="utf-8")
        assert 'src="clip.mp4"' in html and "../" not in re.search(r"<video[^>]*>", html).group(0)
        (root / "index.html").write_text(html, encoding="utf-8")
        shutil.copy2(guide / "steps_data.js", root / "steps_data.js")
        shutil.copy2(guide / "clip.mp4", root / "clip.mp4")
        if (guide / "review.json").exists():
            shutil.copy2(guide / "review.json", root / "review.json")
        _add_viewer(root)
        tmp = zpath.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(root.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(root).as_posix())
        os.replace(tmp, zpath)

    return {"ok": True, "path": str(zpath),
            "download": f"/output/{stem}/export/{zpath.name}", "bytes": zpath.stat().st_size}


def _add_viewer(root):
    exe = REPO / "checkvalve" / "app" / "dist" / "체크밸브_작업지도서.exe"
    if exe.exists():
        shutil.copy2(exe, root / exe.name)
    else:
        vl = REPO / "checkvalve" / "app" / "viewer_launcher.py"
        if vl.exists():
            shutil.copy2(vl, root / "launcher.py")
    rm = REPO / "checkvalve" / "app" / "사용법.txt"
    if rm.exists():
        shutil.copy2(rm, root / "사용법.txt")
