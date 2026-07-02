"""
Process-document (공정관리 지침서) upload + text extraction. The uploaded PDF is the
domain source the Claude analyst grounds step content in (part names, specs, 중점관리
항목). Stores the raw PDF + extracted text under OUTPUT/_specs/<part_id>/.

pdfplumber is imported lazily (only when parsing an upload) so the ML-free Studio and
the run_job child don't pay for it at import; load_doc_text() only reads the saved text.
"""
import json
import time

from ..config import OUTPUT


def _spec_dir(part_id: str):
    base = OUTPUT / "_specs"
    d = (base / part_id).resolve()
    if not d.is_relative_to(base.resolve()):        # defense-in-depth vs path traversal
        raise ValueError("invalid part_id")
    return d


def _extract_pdf_text(path) -> str:
    import pdfplumber   # lazy — heavy dep, only needed on upload
    parts = []
    with pdfplumber.open(str(path)) as pdf:
        for pg in pdf.pages[:40]:
            t = pg.extract_text() or ""
            if t.strip():
                parts.append(t)
    return "\n\n".join(parts).strip()


def store_doc(part_id: str, pdf_bytes: bytes) -> dict:
    d = _spec_dir(part_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "source.pdf").write_bytes(pdf_bytes)
    try:
        text = _extract_pdf_text(d / "source.pdf")
        parsed = bool(text)
        note = (f"PDF 파싱 완료 · 텍스트 {len(text)}자 — Claude 분석에 사용됩니다" if parsed
                else "PDF에서 텍스트를 추출하지 못했습니다 (스캔본일 수 있음)")
    except Exception as e:
        text, parsed, note = "", False, f"PDF 파싱 실패: {e}"
    (d / "process_text.txt").write_text(text, encoding="utf-8")
    spec = {"part_id": part_id, "status": "parsed" if parsed else "no_text", "parsed": parsed,
            "chars": len(text), "note": note,
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bytes": len(pdf_bytes)}
    (d / "process_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "spec": spec}


def load_doc_text(part_id: str) -> str:
    """Return the extracted process-document text for the part, or '' if none/unparsed."""
    try:
        p = _spec_dir(part_id) / "process_text.txt"
    except ValueError:
        return ""
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def doc_status(part_id: str) -> dict:
    try:
        p = _spec_dir(part_id) / "process_spec.json"
    except ValueError:
        return {"parsed": False, "chars": 0}
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"parsed": False, "chars": 0}
