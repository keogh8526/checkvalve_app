"""
공통 용어교정 모듈 — 작업자 구어/ASR 오인식 → 공정관리지침서(GMT-QI-700-4) 표준 용어.

단일 출처(Single Source of Truth): anchor_steps.py, build_steps.py가 모두 이 모듈을 import 한다.
(이전에는 anchor_steps에만 있어 build_steps 경로의 steps.json에 오인식어가 그대로 들어갔다 — L4 잔존.)

추가할 용어는 여기 TERM_MAP 한 곳에만 넣으면 모든 단계에 반영된다.
"""

# 구어/ASR 오인식 → 표준어. (키: 잘못 들린 말, 값: 표준 용어)
TERM_MAP = {
    "테프론": "스페이서", "베프론": "스페이서", "데프론": "스페이서", "데퍼런": "스페이서",
    "서포트": "가이드",
    "디스켓": "디스크", "디스플로드": "디스크", "차속": "디스크",
    "바이드": "디스크",          # 'bide'로 오인식되는 디스크 호칭
    "ICG": "",                   # 의미없는 머리글자 오인식 제거
}


def normalize_terms(text: str) -> str:
    """ASR 텍스트의 도메인 오인식어를 표준 용어로 치환."""
    if not text:
        return text
    for spoken, std in TERM_MAP.items():
        text = text.replace(spoken, std)
    # 치환으로 생긴 이중 공백 정리
    return " ".join(text.split())
