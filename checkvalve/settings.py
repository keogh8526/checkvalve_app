"""
Claude API settings — model + API key, stored in the operator's HOME directory
(~/.checkvalve/settings.json), deliberately OUTSIDE the repo so the key is never
committed. Shared by the ML-free Studio (reads model/has-key for the GUI) and the
run_job child (builds the real client). The raw key never leaves this module except
through get_client(); the GUI only ever sees the masked hint from public().
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".checkvalve"
CONFIG_PATH = CONFIG_DIR / "settings.json"

DEFAULT_MODEL = "claude-sonnet-5"
# Models that accept thinking:{type:"disabled"} (the structured-organize call disables
# thinking to stay fast + within a non-streaming budget). Fable 5 is excluded on purpose
# (thinking is always-on there and would need streaming). Sonnet 5 is the default.
ALLOWED_MODELS = [
    "claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5",
    "claude-opus-4-7", "claude-sonnet-4-6",
]


def load() -> dict:
    if CONFIG_PATH.is_file():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(model: str | None = None, api_key: str | None = None) -> dict:
    cfg = load()
    if model is not None:
        m = model.strip()
        if m and m not in ALLOWED_MODELS:
            raise ValueError(f"unsupported model: {m}")
        cfg["model"] = m or DEFAULT_MODEL
    if api_key is not None:            # empty string clears the stored key
        cfg["api_key"] = api_key.strip()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)
    try:
        os.chmod(CONFIG_PATH, 0o600)   # best-effort owner-only (POSIX; no-op on Windows)
    except Exception:
        pass
    return cfg


def model() -> str:
    return (load().get("model") or "").strip() or DEFAULT_MODEL


def api_key() -> str:
    # stored key wins; fall back to the standard SDK env var if present
    return (load().get("api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def configured() -> bool:
    return bool(api_key())


def public() -> dict:
    """Safe for the /api/settings response — never the raw key, only a masked hint."""
    k = api_key()
    hint = ""
    if k:
        hint = (k[:10] + "…" + k[-4:]) if len(k) > 16 else "설정됨"
    return {"model": model(), "has_key": bool(k), "key_hint": hint,
            "models": ALLOWED_MODELS, "default_model": DEFAULT_MODEL}


def get_client():
    """Return an anthropic.Anthropic bound to the stored key, or None (no key / SDK
    not installed). Called only in the run_job child, never in the Studio server."""
    k = api_key()
    if not k:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic(api_key=k)
