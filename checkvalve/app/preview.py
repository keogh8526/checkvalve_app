"""Preview uses the IDENTICAL render path as export — so what the operator approves
is byte-for-byte what ships. Per-stem lock serializes concurrent guide rewrites."""
import json
import threading

from ..config import OUTPUT
from ..paths import list_stems
from ..render import render

_LOCKS = {}
_GUARD = threading.Lock()


def _lock(stem):
    with _GUARD:
        return _LOCKS.setdefault(stem, threading.Lock())


def ensure_rendered(stem):
    if stem not in list_stems():
        raise KeyError("unknown stem")
    b = json.loads((OUTPUT / stem / "steps_bundle.json").read_text(encoding="utf-8"))
    with _lock(stem):
        render(stem, b)
    return f"/output/{stem}/guide/index.html"
