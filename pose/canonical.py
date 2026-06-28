"""
공통 표준단계 taxonomy — 공정관리지침서 GMT-QI-700-4 공정8(DISC·SPACER·HINGE PIN 조립) 단계 정의.

단일 출처(Single Source of Truth): anchor_steps.py, build_steps.py가 모두 이 모듈을 import 한다.
(이전에는 build_steps=5범주 / anchor_steps=8범주로 분기해 단계명이 경로마다 달랐다.)

⚠️ 키워드는 나레이션 기반 '추정' 매핑이다. 실제 공정지침서 단계정의와 1:1로 회사 확정 필요(표준화 보강 항목).
"""
from terms import normalize_terms

# (표준단계명, 매칭 키워드). 위에서부터 점수 비교 — 동점 시 먼저 나온 단계 우선.
CANONICAL_STEPS = [
    # ★ 단계명은 정답셋(data/ground_truth.csv)·공정서 GMT-QI-700-4 와 1:1 일치(평가 가능하도록).
    ("개요/원리설명",          ["역류", "물이", "물을", "배관", "유수", "열려", "닫혀", "체크", "원리", "보통", "세요"]),
    ("부품 준비",              ["준비", "가공", "주물", "샤프트", "세 개", "들어오"]),
    ("정렬(SPRING·SPACER)",    ["정렬", "맞춰", "스페이서", "스프링", "spring", "spacer", "사이", "1자", "일자", "올려", "넣고", "꼽", "꽂"]),
    ("HINGE PIN 조립",         ["핀", "힌지", "hinge", "pin", "삽입", "끼", "관통", "조립"]),
    ("GUIDE 결합",             ["가이드", "guide", "양쪽"]),
    ("BODY-GUIDE 결합",        ["바디", "body", "삽입부", "밀어", "결합부"]),
    ("SET SCREW 결합",         ["볼트", "스크류", "스크루", "screw", "세트", "set", "탭", "나사"]),
    ("검사/측정",              ["검사", "측정", "확인", "캘리퍼", "버니어", "회전", "복귀", "작동", "눌러"]),
]

UNCLASSIFIED = "미분류"

# 표준 작업지도서에 들어갈 순서(공정지침서 순). '개요/원리설명'은 작업단계가 아니라 참고설명.
CANONICAL_ORDER = [label for label, _ in CANONICAL_STEPS]
NON_WORK_STEPS = {"개요/원리설명"}      # 작업이 아닌 설명 → 표준집계에서 제외(참고로만)

# ── 단계별 부품(BOM) — 공정서 GMT-QI-700-4 작업순서(공정8~11)에서 도출. 정답셋(ground_truth) 아님. ──
# 출처: 공정서 page4 작업순서 + page2~3 부품 도면. 멘토 요구 "공정 클릭→사용 부품 목록".
# 품번은 회사 BOM 필요(미정=""). 부품명·수량은 공정서 기반.
STEP_PARTS = {
    "부품 준비":             [("DISC", 2), ("SPACER", 1), ("HINGE PIN", 1), ("SPRING", 1)],
    "정렬(SPRING·SPACER)":   [("SPRING", 1), ("SPACER", 1), ("DISC", 2)],
    "HINGE PIN 조립":        [("HINGE PIN", 1), ("DISC", 2)],
    "GUIDE 결합":            [("GUIDE", 2)],
    "BODY-GUIDE 결합":       [("BODY", 1), ("GUIDE", 2)],
    "SET SCREW 결합":        [("SET SCREW", 2)],
    "검사/측정":             [("완성품", 1)],
    "개요/원리설명":         [],
}


def parts_for(step_label):
    """단계명 → 부품표 [(부품명, 수량)]. 공정서 BOM 기준."""
    return STEP_PARTS.get(step_label, [])


# ── 단계별 작업설명 — 공정서 GMT-QI-700-4 page4 '작업순서' 원문. LLM 불필요(문서가 출처). ──
STEP_DESC = {
    "부품 준비":            "가공 완료된 DISC·SPACER·HINGE PIN과 SPRING을 준비한다.",
    "정렬(SPRING·SPACER)":  "DISC 사이에 SPRING과 SPACER를 1자로 정렬한다.",
    "HINGE PIN 조립":       "정렬된 상태에서 HINGE PIN을 삽입해 조립한다.",
    "GUIDE 결합":           "조립된 HINGE PIN 양쪽으로 GUIDE를 조립한다.",
    "BODY-GUIDE 결합":      "BODY의 GUIDE 삽입부에 맞추어 밀어 넣는다.",
    "SET SCREW 결합":       "BODY와 GUIDE 중간 부분에 TAP 가공 후 SET SCREW를 결합한다.",
    "검사/측정":            "디스크 회전·복귀 작동과 치수를 확인한다.",
    "개요/원리설명":        "(작업 외 설명 구간)",
}

# ── 단계별 중점관리항목 — 멘토 목표양식 Key Control Points + 공정서 기준. ──
STEP_CONTROL = {
    "부품 준비":            "부품 누락·오부품 없을 것",
    "정렬(SPRING·SPACER)":  "SPRING 형상·방향 확인 · 1자 정렬",
    "HINGE PIN 조립":       "핀 돌출 없을 것 · 양쪽 균등 삽입",
    "GUIDE 결합":           "양쪽 GUIDE 정위치 결합",
    "BODY-GUIDE 결합":      "삽입부 정합 · 단차 없을 것",
    "SET SCREW 결합":       "체결 누락 없을 것 · 토크 확인",
    "검사/측정":            "디스크 회전·자동복귀 정상 · 치수 적합",
    "개요/원리설명":        "-",
}


def desc_for(step_label):
    return STEP_DESC.get(step_label, "")


def control_for(step_label):
    return STEP_CONTROL.get(step_label, "")


def classify(text: str):
    """나레이션 텍스트 → (표준단계명, 점수). 용어교정 후 키워드 점수 최댓값."""
    text = normalize_terms(text or "")
    best, score = UNCLASSIFIED, 0
    for label, kws in CANONICAL_STEPS:
        s = sum(text.count(k) for k in kws)
        if s > score:
            best, score = label, s
    return best, score
