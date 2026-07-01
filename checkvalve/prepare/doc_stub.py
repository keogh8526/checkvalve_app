"""
PDF spec-upload STUB (inert). Stores the uploaded PDF + a placeholder process_spec.
The real deterministic doc_parse (pdfplumber → structured spec with per-cell provenance
+ human sign-off) is a later phase (ARCHITECTURE.md §8). This never blocks the GUI.
"""
import json
import time

from ..config import OUTPUT


def store_doc(part_id: str, pdf_bytes: bytes) -> dict:
    d = OUTPUT / "_specs" / part_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "source.pdf").write_bytes(pdf_bytes)
    spec = {"part_id": part_id, "status": "stub", "parsed": False,
            "note": "PDF 저장됨 — 결정적 파싱은 이후 단계(자리표시자)",
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bytes": len(pdf_bytes)}
    (d / "process_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "spec": spec}
