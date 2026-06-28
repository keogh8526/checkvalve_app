"""
[7] 렌더 — steps.json(융합 결과)을 디지털 작업지도서 HTML로 출력한다.
회사 QMS 양식(GMT-QI-700-4) 골격 계승: 단계별 [순서·표준시간·공정단계·작업내용·VA/NVA·검수].

입력 : steps.json (build_steps.py)  — {step, 공정단계, t_start, t_end, 표준시간_후보_초, 분류, 활동량, 나레이션}
출력 : work_instruction.html

표준시간 합계는 VA(작업) 구간만 합산(NVA=이동/대기는 제외)한다.

usage:
  python pose/generate_html.py --steps results/run_front_full/steps.json \
      --out results/run_front_full/work_instruction.html
"""
import argparse
import json
from pathlib import Path

HTML = """<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>작업지도서 (자동 초안) · Dual Plate Check Valve</title>
<style>
 body{{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;background:#eef1f5;color:#16202c;margin:0;padding:24px}}
 .page{{max-width:1080px;margin:0 auto;background:#fff;border:1px solid #8b94a3;box-shadow:0 4px 18px rgba(0,0,0,.12)}}
 .hd{{background:#1f3a5f;color:#fff;padding:14px 18px}}
 .hd h1{{margin:0;font-size:19px;letter-spacing:2px}}
 .hd small{{color:#b9c7da}}
 .meta{{display:flex;flex-wrap:wrap;gap:18px;padding:10px 18px;background:#e9edf3;font-size:13px;color:#3f4a59}}
 .meta b{{color:#1f3a5f}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{border:1px solid #b9c0cb;padding:8px 10px;font-size:13px;vertical-align:top}}
 th{{background:#e9edf3;color:#3f4a59}}
 .no{{text-align:center;font-weight:800;color:#1f3a5f;width:42px}}
 .time{{text-align:center;white-space:nowrap;width:108px}}
 .step{{font-weight:700;color:#0e7c8b;width:150px}}
 .cls{{text-align:center;width:96px;font-weight:700}}
 .va{{color:#1c8a4e}} .nva{{color:#b4761b}} .etc{{color:#7a8699}}
 .narr{{color:#3f4a59}}
 .chk{{text-align:center;width:46px;color:#9aa4b2}}
 .thumb{{width:170px;text-align:center}} .thumb img{{max-width:160px;border:1px solid #b9c0cb;border-radius:3px}}
 .fill{{background:#fffdf5;color:#b08900;font-size:12px;text-align:center}}
 .parts{{font-size:12px;color:#1f3a5f;background:#f3f7ff;font-weight:600;white-space:nowrap}}
 .ctrl{{font-size:12px;color:#7a3a3a;background:#fdf3f3}}
 .draftxt{{color:#9aa4b2;font-size:11px}}
 .note{{padding:10px 18px;font-size:12px;color:#5a6678;background:#fafbfc;border-top:1px solid #b9c0cb}}
 .draft{{position:fixed;top:8px;right:8px;background:#c0392b;color:#fff;padding:4px 10px;font-size:12px;border-radius:4px}}
 tfoot td{{background:#eef3ee;font-weight:700;color:#1f3a5f}}
 .filt{{padding:10px 18px;background:#f3f7ff;border-bottom:1px solid #b9c0cb;font-size:13px}}
 .fbtn{{margin:0 3px;padding:4px 10px;border:1px solid #1f3a5f;background:#fff;color:#1f3a5f;border-radius:4px;cursor:pointer;font-size:12px}}
 .fbtn.on{{background:#1f3a5f;color:#fff}}
</style></head><body>
<div class="draft">자동 초안 — 사람 검수 필요</div>
<div class="page">
 <div class="hd"><h1>작 업 지 도 서</h1><small>Dual Plate Check Valve · GMT-QI-700-4 양식 계승 · 자동 생성 초안</small></div>
 <div class="meta"><span><b>품명</b> 체크밸브(Dual Plate Wafer)</span><span><b>공정</b> 8 · DISC·SPACER·HINGE PIN 조립</span>
  <span><b>단계 수</b> {n}</span><span><b>VA 표준시간 합계</b> {va_total:.1f}s ({va_min:.1f}분)</span></div>
 <div class="filt"><b>공정 필터:</b> <button class="fbtn on" onclick="flt('all',this)">전체</button>{filters}</div>
 <table><thead><tr><th class="no">순서</th><th class="thumb">대표프레임</th><th class="time">구간/표준시간</th><th class="step">공정 단계</th>
  <th>사용 부품(재료)</th><th>작업 설명 (검수 기입)</th><th>근거 발화(원문)</th><th>중점관리항목</th><th class="chk">검수</th></tr></thead><tbody>
 {rows}
 </tbody>
 <tfoot><tr><td colspan="2" style="text-align:center">VA 표준시간 합계</td><td colspan="7">{va_total:.1f}s · {va_min:.1f}분 (NVA 이동/대기 제외)</td></tr></tfoot>
 </table>
 <div class="note">{note}<br>※ 표준시간·구간 = 영상 측정값 / 공정단계 = 공정지침서(GMT-QI-700-4) 매핑 / 근거발화 = 나레이션 원문(용어교정).
 <b>노란칸(작업설명·중점관리항목)은 사람/회사 검수 기입란</b> — 자동 채움 아님. 부품(재료)=공정서 BOM, 표준시간=영상 측정, 단계명=공정서 매핑.</div>
</div>
<script>
function flt(s, btn){{
  document.querySelectorAll('.fbtn').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('tbody tr').forEach(tr=>{{
    tr.style.display = (s==='all' || tr.dataset.step===s) ? '' : 'none';
  }});
}}
</script>
</body></html>"""

ROW = """<tr data-step="{qms}"><td class="no">{step}</td><td class="thumb">{thumb}</td><td class="time">{timecell}</td>
<td class="step">{qms}<br><span class="draftxt">{cls}</span></td>
<td class="parts">{parts}</td><td class="fill">{desc}</td><td class="narr">{narr}</td>
<td class="ctrl">{ctrl}</td><td class="chk">☐</td></tr>"""


def cls_class(cls):
    if cls and cls.startswith("VA"):
        return "va"
    if cls and "NVA" in cls:
        return "nva"
    return "etc"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    d = json.loads(Path(args.steps).read_text(encoding="utf-8"))
    steps = d["steps"]
    rows, va_total = [], 0.0
    for s in steps:
        cls = s.get("분류", "-")
        if "누적발화시간_초" in s:
            # 표준집계(설명영상 발화 기준) — 가짜 연속구간 금지, 누적·비연속 명시(C1)
            cum = s["누적발화시간_초"]
            timecell = f"누적 <b>{cum:.1f}s</b><br>출현 {s.get('출현_횟수','?')}회<br><span style='color:#b4761b'>(비연속·참고)</span>"
            dur = 0.0   # 표준시간 합계에 누적발화시간은 넣지 않음(작업시간 아님)
        else:
            t0, t1 = s["t_start"], s["t_end"]
            dur = s.get("표준시간_후보_초", t1 - t0)
            timecell = f"{t0:.1f}~{t1:.1f}s<br><b>{dur:.1f}s</b>"
            if str(cls).startswith("VA"):
                va_total += dur
        thumb = (f'<img src="{s["대표프레임"]}">' if s.get("대표프레임") else "—")
        # 사용 부품(재료) — 공정서 BOM
        bom = s.get("부품표", [])
        parts = ("<br>".join(f'{p["부품명"]} ×{p["수량"]}' for p in bom)
                 if bom else '<span class="draftxt">(부품 미정)</span>')
        desc = s.get("작업설명") or "☐ 검수 기입"
        ctrl = s.get("중점관리항목") or "☐ 검수 기입"
        rows.append(ROW.format(step=s["step"], thumb=thumb, timecell=timecell,
                               qms=s.get("공정단계", s.get("공정단계_추정", "-")),
                               parts=parts, desc=desc, ctrl=ctrl,
                               narr=(s.get("나레이션") or s.get("근거발화") or "(나레이션 없음)")[:220],
                               cls=cls))
    # 공정 필터 버튼(중복 단계명 제거, 순서 유지) — 멘토 요구: 공정 클릭→해당 공정만
    seen, labels = set(), []
    for s in steps:
        lab = s.get("공정단계", "-")
        if lab not in seen:
            seen.add(lab); labels.append(lab)
    filters = "".join(f'<button class="fbtn" onclick="flt(\'{l}\',this)">{l}</button>' for l in labels)
    html = HTML.format(n=len(steps), rows="\n".join(rows), note=d.get("note", ""),
                       va_total=va_total, va_min=va_total / 60.0, filters=filters)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"[done] 작업지도서 초안 HTML -> {args.out} ({len(steps)} 단계, VA합계 {va_total:.1f}s)")


if __name__ == "__main__":
    main()
