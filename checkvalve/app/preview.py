"""Preview uses the IDENTICAL render path as export — so what the operator approves
is byte-for-byte what ships. Per-stem lock serializes concurrent guide rewrites."""
import json

from ..config import OUTPUT
from ..paths import list_stems
from ..render import render
from ..pipeline import _stem_lock as _lock   # ONE shared per-stem lock (edit/preview/export)


def ensure_rendered(stem):
    if stem not in list_stems():
        raise KeyError("unknown stem")
    with _lock(stem):
        # read the bundle UNDER the lock so a concurrent edit can't slip a stale
        # render in between the read and the render (mirrors export.py's pattern).
        b = json.loads((OUTPUT / stem / "steps_bundle.json").read_text(encoding="utf-8"))
        render(stem, b)
    return f"/output/{stem}/guide/index.html"
