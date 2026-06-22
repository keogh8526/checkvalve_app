"""
M7 렌더 — steps.json(융합 결과)을 디지털 작업지도서 HTML로 출력한다.
회사 QMS 양식(GMT-QI-700-4) 골격 계승: 단계별 [순서·표준시간·작업내용·공정단계·근거나레이션].

입력 : steps.json (build_steps.py)
출력 : work_instruction.html

usage:
  python pose/generate_html.py --steps results/run_front/steps.json --out results/run_front/work_instruction.html
"""
import argparse
import json
from pathlib import Path

HTML = """<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>작업지도서 (자동 초안) · Dual Plate Check Valve</title>
<style>
 body{{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;background:#eef1f5;color:#16202c;margin:0;padding:24px}}
 .page{{max-width:1000px;margin:0 auto;background:#fff;border:1px solid #8b94a3;box-shadow:0 4px 18px rgba(0,0,0,.12)}}
 .hd{{background:#1f3a5f;color:#fff;padding:14px 18px}}
 .hd h1{{margin:0;font-size:19px;letter-spacing:2px}}
 .hd small{{color:#b9c7da}}
 .meta{{display:flex;gap:24px;padding:10px 18px;background:#e9edf3;font-size:13px;color:#3f4a59}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{border:1px solid #b9c0cb;padding:8px 10px;font-size:13px;vertical-align:top}}
 th{{background:#e9edf3;color:#3f4a59}}
 .no{{text-align:center;font-weight:800;color:#1f3a5f;width:48px}}
 .time{{text-align:center;white-space:nowrap;width:120px}}
 .step{{font-weight:700;color:#0e7c8b;width:160px}}
 .narr{{color:#3f4a59}}
 .auto{{color:#1c8a4e;font-weight:700}} .human{{color:#b4761b;font-weight:700}}
 .note{{padding:10px 18px;font-size:12px;color:#5a6678;background:#fafbfc;border-top:1px solid #b9c0cb}}
 .draft{{position:fixed;top:8px;right:8px;background:#c0392b;color:#fff;padding:4px 10px;font-size:12px;border-radius:4px}}
</style></head><body>
<div class="draft">자동 초안 — 사람 검수 필요</div>
<div class="page">
 <div class="hd"><h1>작 업 지 도 서</h1><small>Dual Plate Check Valve · GMT-QI-700-4 양식 계승 · 자동 생성 초안</small></div>
 <div class="meta"><span>품명: 체크밸브(Dual Plate Wafer)</span><span>공정: 8 · DISC·SPACER·HINGE PIN 조립</span><span>단계 수: {n}</span></div>
 <table><thead><tr><th class="no">순서</th><th class="time">구간/표준시간</th><th class="step">공정 단계</th><th>작업 내용 (나레이션 근거)</th></tr></thead><tbody>
 {rows}
 </tbody></table>
 <div class="note">{note}<br>※ 표준시간·구간 = 영상 측정값 / 공정단계 = 공정지침서(GMT-QI-700-4) 매핑 / 작업내용 = 나레이션 원문. 수치는 자동 측정, 문장은 사람 검수 후 확정.</div>
</div></body></html>"""

ROW = """<tr><td class="no">{step}</td><td class="time">{t0:.1f}~{t1:.1f}s<br><b>{dur:.1f}s</b></td>
<td class="step">{qms}</td><td class="narr">{narr}</td></tr>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    d = json.loads(Path(args.steps).read_text(encoding="utf-8"))
    steps = d["steps"]
    rows = []
    for s in steps:
        rows.append(ROW.format(step=s["step"], t0=s["t_start"], t1=s["t_end"],
                               dur=s.get("표준시간_후보_초", s["t_end"] - s["t_start"]),
                               qms=s.get("공정단계_추정", "-"),
                               narr=(s.get("나레이션", "") or "(나레이션 없음)")[:200]))
    html = HTML.format(n=len(steps), rows="\n".join(rows), note=d.get("note", ""))
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"[done] 작업지도서 초안 HTML -> {args.out} ({len(steps)} 단계)")


if __name__ == "__main__":
    main()
