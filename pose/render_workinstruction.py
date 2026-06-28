"""
[최종 렌더] 파이프라인 산출물(steps.json) → 팀원 작업지도서 양식(app/check_valve.html)에 자동 주입.
양식(디자인·영상·체크리스트·결재·개정이력)은 팀원 원본 그대로 두고, STEPS 데이터만 파이프라인 값으로 교체.
멘토 보강: 각 단계에 사용부품(BOM) 추가 → 단계 활성화 시 부품표 표시.

원칙: 손으로 박지 않는다. steps.json(6영상 파이프라인 수집)이 유일 데이터 출처.

usage:
  python pose/render_workinstruction.py --steps results/all/steps.json \
      --template app/check_valve.html --out results/all/work_instruction_final.html
"""
import argparse
import json
import re
from pathlib import Path

# 공정단계명 → (badge 짧은이름, 검사유형 insp 1순차/2자주/3측정)
BADGE = {
    "부품 준비": ("준비", 1), "정렬(SPRING·SPACER)": ("정렬", 1),
    "HINGE PIN 조립": ("핀삽입", 1), "GUIDE 결합": ("가이드", 1),
    "BODY-GUIDE 결합": ("바디결합", 1), "SET SCREW 결합": ("체결", 2),
    "검사/측정": ("검사", 3),
}


PROC_ORDER = ["부품 준비", "정렬(SPRING·SPACER)", "HINGE PIN 조립",
              "GUIDE 결합", "BODY-GUIDE 결합", "SET SCREW 결합"]
PROC_TAG = {"부품 준비": "①", "정렬(SPRING·SPACER)": "②", "HINGE PIN 조립": "③",
            "GUIDE 결합": "④", "BODY-GUIDE 결합": "⑤", "SET SCREW 결합": "⑥"}


def collapse_to_6(steps):
    """9섹터 → 공정서 6단계로 정리. '검사/측정'(빠른영상 정답에 없음=오생성) 제거,
    인접 동일단계 병합(시간 합산), 공정서 순서로. 어색한 중복·짧은섹터 제거."""
    # 1) 검사/측정(빠른영상 오생성) 제거 — 그 시간은 인접 이전 단계가 흡수
    kept = []
    for s in steps:
        if s.get("공정단계") == "검사/측정":
            if kept:
                kept[-1]["t_end"] = s["t_end"]   # 이전 단계가 시간 흡수
            continue
        kept.append(dict(s))
    # 2) 인접 동일 단계 병합
    merged = []
    for s in kept:
        if merged and merged[-1]["공정단계"] == s["공정단계"]:
            merged[-1]["t_end"] = s["t_end"]
        else:
            merged.append(s)
    # 3) ★공정서 표준순서로 정렬 + 번호 재계산 (작업지도서=표준 문서이므로 공정서 순서가 맞음).
    #    영상은 각 단계가 나오는 시점(at)으로 점프 — 순서가 영상과 달라도 됨.
    #    (영상시간순 정렬 시 '정렬된 상태에서 핀삽입'인데 정렬이 뒤에 오는 설명↔순서 모순 발생)
    order = {name: i for i, name in enumerate(PROC_ORDER)}
    merged.sort(key=lambda s: order.get(s.get("공정단계", ""), 99))
    for i, s in enumerate(merged, 1):
        s["step"] = i
        s["표준시간_후보_초"] = round(s["t_end"] - s["t_start"], 1)
    return merged


def steps_to_js(steps):
    """steps.json → 팀원 양식 STEPS 배열(JS) 문자열. 파이프라인 데이터만 사용."""
    out = []
    for s in steps:
        label = s.get("공정단계", "-")
        badge, insp = BADGE.get(label, (label[:4], 1))
        tag = PROC_TAG.get(label, "AI")
        at = int(round(s.get("t_start", 0)))
        parts = s.get("부품표", [])
        parts_js = "[" + ",".join(f'["{p["부품명"]}",{p["수량"]}]' for p in parts) + "]"
        # 작업내용 = 공정서 작업설명(깔끔). 보조 = 표준시간·구간 (ASR 잡담은 제외).
        dur = s.get("표준시간_후보_초", 0)
        text = (s.get("작업설명") or label).replace('"', "'")
        sub = f"표준시간 {dur:.0f}초 · 영상 {int(round(s.get('t_start',0)))}~{int(round(s.get('t_end',0)))}s 구간"
        ctrl = s.get("중점관리항목") or ""
        pts = [p.strip() for p in re.split(r"[·,]", ctrl) if p.strip()] or [label]
        pts_js = "[" + ",".join(f'"{p}"' for p in pts) + "]"
        end = int(round(s.get("t_end", at)))
        out.append(
            f'    {{no:{s["step"]}, tag:"{tag}", at:{at}, end:{end}, insp:{insp}, badge:"{badge}",\n'
            f'     text:"{text}",\n'
            f'     sub:"{sub}",\n'
            f'     pts:{pts_js},\n'
            f'     parts:{parts_js},\n'
            f'     cap:"[{label}] 표준시간 {dur:.0f}초 (영상 {at}s~)"}}')
    return "  const STEPS = [\n" + ",\n".join(out) + "\n  ];"


def chapters_to_js(steps):
    """공정버튼(CHAPTERS)을 파이프라인 6단계로 생성. 각 버튼=실제 공정, idx=STEPS 위치(0base).
    → 버튼 클릭 시 그 공정만 강조+해당 공정 부품표 표시(멘토 요구)."""
    out = []
    for i, s in enumerate(steps):
        label = s.get("공정단계", "-")
        badge, _ = BADGE.get(label, (label[:4], 1))
        tag = PROC_TAG.get(label, "·")
        out.append(f'["{tag} {badge}",{i}]')
    return "  const CHAPTERS=[" + ",".join(out) + "];"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", required=True)
    ap.add_argument("--template", default="app/check_valve.html")
    ap.add_argument("--video", default="front_skeleton.mp4",
                    help="작업지도서에 표시할 영상(HTML 기준 상대경로). 기본=스켈레톤 오버레이")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    steps = json.loads(Path(args.steps).read_text(encoding="utf-8"))["steps"]
    steps = collapse_to_6(steps)          # 9섹터 → 공정서 6단계 정리(검사오생성 제거·병합)
    tpl = Path(args.template).read_text(encoding="utf-8")

    # 0) 좌측 영상 교체 (분석↔표시 일치). 기본=스켈레톤 오버레이(포즈 분석 시각화).
    tpl = re.sub(r'(<video[^>]*src=")[^"]*(")', rf'\1{args.video}\2', tpl, count=1)

    # 1) 템플릿의 const STEPS = [...]; 를 파이프라인 데이터로 교체
    new_steps = steps_to_js(steps)
    tpl2 = re.sub(r"  const STEPS = \[.*?\n  \];", new_steps, tpl, count=1, flags=re.S)
    if tpl2 == tpl:
        raise SystemExit("[err] 템플릿에서 'const STEPS = [...]' 패턴을 못 찾음")

    # 1c) ★공정버튼(CHAPTERS)도 파이프라인 6단계로 교체 (옛 고정 4챕터 제거)
    #     → 버튼=실제 공정, 클릭 시 그 공정 강조+해당 부품표 (멘토 요구 충족)
    new_chap = chapters_to_js(steps)
    tpl3 = re.sub(r"  const CHAPTERS=\[.*?\];", new_chap, tpl2, count=1, flags=re.S)
    if tpl3 == tpl2:
        raise SystemExit("[err] 템플릿에서 'const CHAPTERS=[...]' 패턴을 못 찾음")
    tpl2 = tpl3

    # 1b) ★작업표준시간 = 파이프라인 실측값으로 교체 (손박음 '38~45초' 제거)
    va = [s for s in steps if s.get("공정단계") != "검사/측정"]
    total = sum(s.get("표준시간_후보_초", 0) for s in steps)
    work = sum(s.get("표준시간_후보_초", 0) for s in va)
    std_txt = f'<span class="big">{work:.0f}초</span><small style="color:var(--mut)"> 측정값 · 전체 {total:.0f}초(검사 포함) · 6영상 다시점 실측</small>'
    tpl2 = re.sub(r'<span class="big">[^<]*</span><small[^>]*>[^<]*</small>', std_txt, tpl2, count=1)

    # 2) 멘토 보강 — 공정버튼 클릭 → 그 공정 강조 + 부품표. 하이라이트는 '하나'로 통합.
    #    핵심: 템플릿 setSeg(.active)와 별도 .focus/.dim이 따로 놀면 두 행이 동시 강조되는 충돌 발생.
    #    → setSeg를 감싸 focus/dim/부품표를 항상 .active와 일치시켜 단일 하이라이트 보장.
    inject = """
  // ── 멘토 보강: 공정버튼/행 클릭 → 단일 하이라이트(강조) + 사용부품(BOM) ──
  (function(){
    // 영상 아래 부품표 박스
    const cap = document.getElementById("cap");
    const box = document.createElement("div");
    box.id = "partsbox";
    box.style.cssText = "margin-top:8px;border:1.5px solid var(--navy);background:#eef4ff;padding:9px 11px;font-size:12.5px;border-radius:4px";
    if(cap) cap.after(box);
    const rowEls = [...document.querySelectorAll("tr.row")];

    // 전체 BOM(완성품 구성) — 같은 부품이 여러 단계에 나오므로 '합산'이 아니라 '최댓값'.
    //  (예: DISC가 준비·정렬·핀삽입 단계마다 표시돼도 실제 밸브엔 2개 → 합산하면 6개로 틀림)
    function fullBom(){
      const m={}, ord=[];
      STEPS.forEach(s=>(s.parts||[]).forEach(([n,q])=>{ if(!(n in m)){m[n]=0;ord.push(n);} m[n]=Math.max(m[n],q); }));
      return ord.map(n=>[n,m[n]]);
    }
    function showParts(seg){
      if(seg<0){ const p=fullBom();
        box.innerHTML = "<b style='color:var(--navy)'>전체 사용 부품(완성품 BOM)</b><br>" +
          p.map(x=>"· "+x[0]+" × "+x[1]).join("&nbsp;&nbsp;"); return; }
      const st=STEPS[seg]||{}, p=st.parts||[];
      box.innerHTML = "<b style='color:var(--navy)'>["+(st.badge||"")+"] 사용 부품(재료)</b><br>" +
        (p.length ? p.map(x=>"· "+x[0]+" × "+x[1]).join("&nbsp;&nbsp;") : "· (부품 정보 없음)");
    }

    // 강조 보강 CSS(.active 배경 위에 테두리만 추가; .dim은 나머지 흐림)
    const fcss=document.createElement("style");
    fcss.textContent=".row.dim td:not(.figcell){opacity:.32} .row.focus td:not(.figcell){outline:2px solid var(--hl-bd)}";
    document.head.appendChild(fcss);

    // ★단일 하이라이트: setSeg를 감싸 focus/dim/부품표를 .active와 항상 일치 (두 행 동시강조 방지)
    let filterOn=false, lockSeg=-1;
    const _setSeg = setSeg;
    setSeg = function(seg){
      _setSeg(seg);                                   // 템플릿: .active=seg, 칩 on
      rowEls.forEach((el,i)=>{ el.classList.toggle("focus", filterOn&&i===seg);
                               el.classList.toggle("dim",   filterOn&&i!==seg); });
      showParts(filterOn?seg:-1);
    };

    // 영상시간→단계: at/end 구간 기반(공정서순서로 at이 뒤섞여도 정확)
    segAt = function(t){
      let best=0,bestAt=-1;
      for(let i=0;i<STEPS.length;i++){
        if(t>=STEPS[i].at-0.05 && t<STEPS[i].end) return i;
        if(STEPS[i].at<=t && STEPS[i].at>bestAt){ bestAt=STEPS[i].at; best=i; }
      }
      return best;
    };

    function clearFilter(){ filterOn=false; lockSeg=-1;
      rowEls.forEach(el=>el.classList.remove("focus","dim"));
      [...document.querySelectorAll(".chip")].forEach(x=>x.classList.remove("on"));
      showParts(-1); }
    window.clearFilter=clearFilter;

    // 칩(공정버튼) = 필터 토글 (같은 버튼 재클릭 = 전체)
    const chips=[...document.querySelectorAll(".chip")];
    chips.forEach((c,ci)=>{
      const idx=(typeof CHAPTERS!=="undefined"&&CHAPTERS[ci])?CHAPTERS[ci][1]:ci;
      c.onclick=()=>{
        if(filterOn && lockSeg===idx){ clearFilter(); return; }
        filterOn=true; lockSeg=idx;
        if(D){ vid.pause(); vid.currentTime=STEPS[idx].at+0.05; }
        setSeg(idx);
      };
    });
    // '전체' 버튼
    const allBtn=document.createElement("span");
    allBtn.className="chip"; allBtn.textContent="전체"; allBtn.style.fontWeight="800";
    allBtn.onclick=clearFilter;
    const chipBox=document.getElementById("chips"); if(chipBox) chipBox.prepend(allBtn);

    // 행(오른쪽 공정) 직접 클릭 = 칩과 동일하게 그 공정으로 필터 → 그 공정 부품 표시.
    //  (템플릿 tr.onclick의 seekToStep이 먼저 실행된 뒤 이 핸들러가 filterOn을 켜고 setSeg로 부품 갱신)
    rowEls.forEach((el,i)=>{ el.addEventListener("click",e=>{
      if(e.target.closest(".vidwrap,.chip,#partsbox")) return;
      filterOn=true; lockSeg=i; setSeg(i); }); });

    showParts(-1);  // 시작 = 전체 BOM
  })();
"""
    tpl2 = tpl2.replace("</script>\n</body>", inject + "</script>\n</body>")

    # 3) 제목 주석 — 자동생성 표기
    tpl2 = tpl2.replace('<div class="t">작업지도서<small>',
                        '<div class="t">작업지도서(자동생성)<small>파이프라인 산출 · ')

    Path(args.out).write_text(tpl2, encoding="utf-8")
    print(f"[done] 팀원 양식 + 파이프라인 데이터 → {args.out} ({len(steps)}단계)")
    print("  양식: 팀원 원본 유지 / 데이터: steps.json(6영상 파이프라인) / 보강: 부품표")


if __name__ == "__main__":
    main()
