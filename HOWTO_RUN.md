# 체크밸브 작업지도서 — 처음부터 끝까지 실행·확인 가이드

영상을 넣으면 작업지도서 초안이 나오는 전체 과정과, 로컬에서 결과를 보는 법.

---

## 0. 한눈에 (데이터 흐름)

```
입력: 6영상 (3시점 × 빠른조작+설명)              ← data/ 폴더
  │
  ├ 빠른조작(무설명): front·top60 → body 17점 → 손위치 분할      [타이밍·경계·표준시간]
  │                   hand → rtmlib 손21점 → 분할               [손 트랙]
  ├ 다시점 DTW 합의 → 섹터 경계 확정
  ├ 설명영상: front·top60·hand → Whisper ASR → 단계 앵커        [라벨 근거]
  ├ 융합: 섹터 + 공정서 BOM(부품) + 작업설명 + 라벨
  └ 렌더 → work_instruction.html                               [작업지도서 초안]
  │
[게이트] 사람 검수 (단계명·문장 확정)
```

---

## 1. 한 명령으로 실행

```bash
python pose/run_all.py --out results/all --n-steps 6 --channels "spd,posx,posy" --min-sec 3
```

내부에서 순서대로:
1. `extract_pose.py` — 빠른영상(front/top60) body 키포인트
2. `segment_multi.py` — 손위치 다채널 분할 (front/top60)
3. `extract_hands_rtm.py` + `segment_hands.py` — hand 손21점 분할
4. `fuse_views.py` — 다시점 DTW 합의 경계
5. `extract_asr.py` + `anchor_steps.py` — 설명영상 ASR → 단계 앵커 (front/top60/hand)
6. `assemble_fused.py` — 섹터 + 부품(BOM) + 작업설명 + 라벨 융합
7. `extract_thumbnails.py` + `generate_html.py` — 대표프레임 + 작업지도서 HTML

(무거운 단계 body.json/asr.json는 이미 있으면 자동 재사용)

---

## 2. 결과를 로컬에서 보기

```bash
open results/all/work_instruction.html        # 작업지도서 초안 (브라우저)
open results/all/steps.json                    # 섹터별 데이터(시간·단계·부품·작업설명)
open results/all/front_fast/velocity.png       # 분할 근거 속도곡선
```

작업지도서 HTML에서 보이는 것:
- 순서 / 대표프레임 / 구간·표준시간 / 공정단계 / **사용 부품(재료)** / 작업설명 / 근거발화 / 중점관리 / 검수
- **공정 필터 버튼**: 클릭하면 해당 공정 행만 표시

---

## 3. 정확도 검증 (정답셋 대비)

```bash
# 경계 정확도 (Hungarian 1:1, ±1s/±2s, F1)
python pose/eval_honest.py --gt data/ground_truth.csv --seg results/all/fused_segments.json --video front_fast --steps results/all/steps.json

# 구조·연결 검증 (35개 항목)
python tests/verify_pipeline.py
```

---

## 4. 현재 성능 (실측, 과장 없음)
| 항목 | 값 | 비고 |
|---|---|---|
| 포지션 추출 | 95~100% | 우수 |
| 경계 분할 F1 | 53~57% | 손위치+DINOv2 |
| 단계 라벨 | 22~33% | 규칙→DINOv2 |
| 재료(부품표)·표준시간 | 자동 | 공정서/실측 |

→ **자동 초안 + 사람 검수(반자동)**. 무인 완성 아님.

---

## 5. 한계 (정직)
- 단계 라벨 33%가 천장 (fine-grained 저데이터, 학계도 30~50%)
- "HINGE PIN↔정렬 동시진행"은 분리 불가(구조적)
- held-out 0 → 신규 작업자 일반화 미검증(추가 촬영 필요)
- 작업설명 문장은 공정서 기반(영상 노하우는 LLM/API 필요)
