"""
Stage E — step author. Claude analyzes the video VISUALLY: it is sent sampled keyframe
IMAGES (timestamped) + the motion-segment timing + the process document (공정관리 지침서
PDF text, if any) + optional narration (ASR, off for silent clips), and writes the
work-instruction steps directly.

No RAG / gold pool — the API is the analyst. Grounding per step: "pdf" (backed by the
document), "visual" (seen in a frame), or "inferred" (guessed). Numeric specs must come
from the document, never invented. Each step carries a start time (at) + the closest
evidence frame. Human review of every step is the trust gate. Missing key = hard error.
If no frames could be extracted, it degrades to a text-only analysis of the timing+doc.
"""
from __future__ import annotations

import base64
import json
import re

from .config import OUTPUT, PART_ID
from . import settings
from .prepare.doc_stub import load_doc_text

_SYS = (
    "당신은 체크밸브(Dual Plate Check Valve, 도번 GMT-CV-008) 조립 공정을 분석해 "
    "표준작업지도서 단계를 작성하는 제조 공정 전문가입니다.\n"
    "입력: (a) 영상에서 뽑은 키프레임 이미지들 — 각 이미지 앞에 '[프레임 N · t=초]' 라벨이 붙습니다. "
    "(b) 모션 구간(motion_segments, 초 단위)과 경계 힌트. "
    "(c) 공정관리 지침서 텍스트(process_document, 없을 수도 있음). "
    "(d) 나레이션(narration, 없을 수도 있음).\n"
    "할 일: 프레임에 보이는 실제 동작과 시각을 근거로 작업을 의미 있는 단계로 통합하세요(보통 4~8단계). "
    "각 단계에 영상 시작 시각 at(초, 정수)를 프레임 라벨의 시각에서 정하고 시간 오름차순 정렬하세요.\n"
    "규칙:\n"
    "1) 각 단계에 grounding을 명시: 'pdf'(지침서에 근거), 'visual'(프레임에서 관찰), 'inferred'(추정).\n"
    "2) 치수·규격 같은 수치는 지침서(process_document)에 있는 값만 쓰세요. 프레임만으로 수치를 지어내지 마세요.\n"
    "3) 프레임에서 보이지 않고 문서에도 없으면 grounding='inferred'로 표시하고 일반적 표현을 쓰세요.\n"
    "4) insp(검사 유형): 1=순차검사, 2=자주검사, 3=측정.\n"
    "5) badge는 2~4자 짧은 동작명(예: 정렬, 걸기, 핀삽입, 측정, 검사).\n"
    "6) evidence_t: 그 단계를 가장 잘 보여주는 프레임의 시각(초)을 하나 적으세요.\n"
    "7) cap은 '(영상 M:SS~)' 형식 시점 표기를 포함한 한 줄 캡션. 검사 체크리스트 seq/self도 작성.\n"
    "출력은 오직 JSON 객체 하나: "
    "{\"steps\":[{\"at\":정수,\"evidence_t\":정수,\"badge\":str,\"text\":str,\"sub\":str,"
    "\"pts\":[str],\"insp\":1|2|3,\"cap\":str,\"grounding\":\"pdf|visual|inferred\"}],"
    "\"seq\":[str],\"self\":[str]} 형식으로만. 설명 문장·코드펜스 금지."
)


def _mmss(sec):
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def _extract_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t.strip("`")
        t = t[t.find("{"):]
    s, e = t.find("{"), t.rfind("}")
    if s == -1 or e == -1:
        raise ValueError("LLM 응답에서 JSON을 찾지 못함")
    return json.loads(t[s:e + 1])


def _frame_list(stem, keyframes):
    """Flatten the keyframe manifest to time-ordered {sec, path} entries."""
    fr = [{"sec": int(f["sec"]), "path": f["path"]}
          for seg in (keyframes or {}).get("segments", []) for f in seg.get("frames", [])]
    fr.sort(key=lambda x: x["sec"])
    return fr


def _nearest_image(frames, at):
    if not frames:
        return None
    return min(frames, key=lambda f: abs(f["sec"] - at))["path"]


_SPEC_NUM = re.compile(r"\d+\.\d+|\d{2,}")   # spec-like numbers (2+ digits or decimals), skips small counts


def _pdf_numbers_ok(step, doc_text):
    """A 'pdf'-grounded step must not carry a spec number that isn't in the document —
    catches fabricated specs claimed as doc-backed (finding 13). Small counts (1개, 2·3단계)
    are ignored; only 2+digit / decimal spec numbers are checked. `cap` is EXCLUDED: it always
    carries a '(영상 M:SS~)' timestamp whose zero-padded seconds (e.g. '05') would spuriously
    fail the check — real specs live in text/sub/pts."""
    doc = re.sub(r"[,\s]", "", doc_text)
    blob = " ".join([str(step.get("text", "")), str(step.get("sub", ""))]
                    + [str(p) for p in (step.get("pts") or [])])
    return all(re.sub(r"[,\s]", "", tok) in doc for tok in _SPEC_NUM.findall(blob))


def author_steps(stem: str, digest: dict, keyframes: dict, profile: dict, *, client=None) -> dict:
    """Claude analyzes keyframe images (+ timing + doc) and writes the steps. Requires a
    client — there is no RAG fallback (the API is the analyst)."""
    if client is None:
        raise ValueError("Claude API 키가 필요합니다 — RAG가 제거되어 생성은 API 분석으로만 동작합니다. "
                         "⚙ 설정에서 키를 입력하세요.")
    fps = digest.get("fps") or 30.0
    dur = digest.get("duration_sec") or 0
    segs = digest.get("candidate_segments", [])
    doc_text = load_doc_text(PART_ID)
    has_doc = bool(doc_text)
    frames = _frame_list(stem, keyframes)

    payload = {
        "part": {"품명": "체크밸브(Dual Plate Check Valve)", "도번": PART_ID,
                 "공정": "공정 8 · DISC·SPACER·HINGE PIN 조립"},
        "clip": {"duration_sec": round(dur, 1), "shot_type": profile.get("shot_type"),
                 "roles": profile.get("roles"), "frame_times_sec": [f["sec"] for f in frames]},
        "motion_segments": [{"start_sec": round(s["start_sec"], 1),
                             "end_sec": round(s["end_sec"], 1)} for s in segs][:60],
        "boundary_hints_sec": (digest.get("boundary_hints_sec") or [])[:40],
        "process_document": doc_text[:8000],
        "narration": "",   # ASR hook (optional) — populated only for narrated clips
    }
    tail = (("[공정관리 지침서 있음]\n" if has_doc else "[문서 없음]\n")
            + ("[키프레임 %d장 첨부 — 라벨의 t=초 기준으로 분석]\n" % len(frames) if frames
               else "[프레임 없음 — 타이밍/문서만으로 추정]\n")
            + json.dumps(payload, ensure_ascii=False))

    content = []
    for i, f in enumerate(frames):
        try:
            b64 = base64.b64encode((OUTPUT / stem / f["path"]).read_bytes()).decode("ascii")
        except OSError:
            continue
        content.append({"type": "text", "text": f"[프레임 {i + 1} · t={_mmss(f['sec'])} ({f['sec']}s)]"})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
    content.append({"type": "text", "text": tail})

    resp = client.messages.create(
        model=settings.model(), max_tokens=8000, system=_SYS, thinking={"type": "disabled"},
        messages=[{"role": "user", "content": content}],
    )
    if getattr(resp, "stop_reason", None) == "max_tokens":   # truncated JSON -> don't ship a partial guide
        raise ValueError("Claude 응답이 max_tokens로 잘렸습니다 — 단계가 너무 많거나 출력 한도 초과. 다시 시도하세요.")
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    data = _extract_json(text)

    steps, prev = [], -1
    for s in data.get("steps", []):
        try:
            at = int(s.get("at", 0))
        except (TypeError, ValueError, OverflowError):   # OverflowError: LLM emitted Infinity
            at = prev + 1
        if at <= prev:
            at = prev + 1
        prev = at
        try:
            ev_t = int(s.get("evidence_t", at))
        except (TypeError, ValueError, OverflowError):
            ev_t = at
        insp = s.get("insp") if s.get("insp") in (1, 2, 3) else 1
        grounding = s.get("grounding") if s.get("grounding") in ("pdf", "visual", "inferred") else "inferred"
        if grounding == "pdf" and (not has_doc or not _pdf_numbers_ok(s, doc_text)):
            grounding = "visual" if frames else "inferred"   # not doc-grounded (no doc, or a spec not in the doc)
        if grounding == "visual" and not frames:
            grounding = "inferred"                            # can't claim '영상근거' when no frames were sent
        img = _nearest_image(frames, ev_t)
        steps.append({
            "badge": (str(s.get("badge") or "미정"))[:12], "text": str(s.get("text") or ""),
            "sub": str(s.get("sub") or ""), "pts": [str(p) for p in (s.get("pts") or [])][:6],
            "insp": insp, "cap": str(s.get("cap") or f"(영상 {_mmss(at)}~)"), "at": at,
            "evidence": {"clip": stem, "frames": [int(round(at * fps))], "image": img, "at_sec": ev_t},
            "image": img, "grounding": grounding, "provenance": "llm",
            "grounded": grounding != "inferred",   # pdf/visual = grounded; inferred needs review
            "reviewed": False,
        })
    if not steps:
        raise ValueError("Claude 분석이 단계를 생성하지 못했습니다")

    return {"steps": steps,
            "seq": [str(x) for x in (data.get("seq") or [])],
            "self": [str(x) for x in (data.get("self") or [])],
            "mode": f"llm-vision:{settings.model()}", "has_document": has_doc,
            "n_frames": len(frames), "is_gold_clip": False, "dropped_pool_steps": 0, "gold": None}
