# checkvalve_app

**Dual Plate Check Valve(체크밸브) 조립 공정 작업지도서 + 포즈/손 키포인트 분석 파이프라인**

조립 작업 영상을 사람 자세·손가락 키포인트로 분석하고, 그 결과를 바탕으로 만든
**웹 작업지도서(Work Instruction)** 를 함께 담은 프로젝트입니다.

- `app/` — 더블클릭으로 실행되는 웹 작업지도서 (영상 재생 + 단계 동기화 + 검사 체크리스트)
- `pose/` — 작업 영상에서 전신/손 키포인트를 추출하고 **품질을 자동 검증(QC)** 하는 파이프라인

> 두 파트의 연결: `pose/` 파이프라인으로 조립 영상을 분석 → 어느 구간이 신뢰 가능한지(특히
> 손 클로즈업 구간)를 검증 → 그 분석을 근거로 `app/`의 작업지도서 단계·중점관리 항목을 구성.

---

## 저장소 구조

```
checkvalve_app/
├── app/                                  # 웹 작업지도서 (배포용)
│   ├── 체크밸브_작업지도서.exe            # 더블클릭 실행 (PyInstaller 빌드)
│   ├── check_valve.html                  # UI 본체 (영상 재생·단계 동기화·체크리스트)
│   ├── launcher.command                  # macOS 실행 파일 (더블클릭)
│   ├── launcher.py                        # 런처 원본 소스 (html 을 브라우저로 오픈)
│   ├── KakaoTalk_20260606_171834495.mp4  # 작업 영상 H.264/mp4 (앱이 재생)
│   └── 사용법.txt
└── pose/                                 # 키포인트 추출 + 검증 파이프라인
    ├── extract_pose.py    # YOLO11-pose 전신 17점 (GPU 가속)
    ├── extract_hands.py   # MediaPipe Holistic 전신 33 + 양손 21×2 (손가락)
    ├── qc_validate.py     # 교차모델 QC: 오탐/이상치 자동 검출
    ├── render_overlay.py  # 스켈레톤 오버레이 영상 렌더링
    └── run_pipeline.py    # 폴더 내 모든 영상 일괄 처리 드라이버
```

---

## 1. 작업지도서 앱 실행 (`app/`)

가장 간단한 방법 (더블클릭):

- **Windows** → `app/체크밸브_작업지도서.exe`
- **macOS** → `app/launcher.command` (최초 1회만 우클릭 → "열기")
- **어느 OS든** → `app/check_valve.html` 을 브라우저로 직접 열어도 됩니다

기본 브라우저에 작업지도서 UI가 뜹니다 (영상 재생 · 단계 자동 하이라이트 · 검사 체크리스트 · 인쇄).

> ⚠️ 실행 파일·`check_valve.html`·`KakaoTalk_...mp4` 는 **같은 폴더**에 함께 있어야 합니다.
> 파이썬 설치 없이 폴더째 USB·다른 PC 로 옮겨도 동작합니다.
> 영상은 **H.264/mp4(faststart)** 라 모든 최신 브라우저·OS 에서 재생됩니다.

파이썬으로 직접 실행하거나 exe 를 다시 빌드하려면:

```bash
python app/launcher.py                      # html 을 브라우저로 오픈
# 또는 exe 재빌드:
pip install pyinstaller
pyinstaller --onefile --noconsole --name 체크밸브_작업지도서 app/launcher.py
```

---

## 2. Pose 파이프라인 (`pose/`)

### 설치

```bash
python -m venv venv && venv\Scripts\activate         # Windows (Python 3.11~3.13)
# GPU(CUDA) 사용 시 torch 먼저:
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
```

### 한 영상 처리

```bash
# 전신 키포인트 (YOLO11-pose, GPU 자동 사용)
python pose/extract_pose.py    --video input.mp4 --out-json body.json
# 손가락 키포인트 (MediaPipe Holistic, 모델 자동 다운로드)
python pose/extract_hands.py   --video input.mp4 --out-json hands.json
# 품질 검증 (교차모델 QC + 의심 프레임 이미지 덤프)
python pose/qc_validate.py     --video input.mp4 --body-json body.json --hands-json hands.json --out-dir out/
# 스켈레톤 오버레이 영상
python pose/render_overlay.py  --video input.mp4 --body-json body.json --hands-json hands.json --out overlay.mp4
```

### 폴더 일괄 처리

```bash
python pose/run_pipeline.py --data-dir ./videos --out-dir ./results
```

각 영상마다 `results/<영상이름>/` 아래에 `body_yolo.json`, `hands_mediapipe.json`,
`qc.json`/`qc.txt`, `suspicious_frames/`, `<영상이름>_overlay.mp4` 가 생성됩니다.

### 검증(QC)이 잡아내는 것

`qc_validate.py` 는 **서로 다른 두 모델(YOLO ↔ MediaPipe)** 을 공통 관절(어깨·팔꿈치·손목)에서
비교해, 한 모델만으로는 못 잡는 오탐을 찾아냅니다:

- 미검출 구간 / 인원수 급증(허위 추가 검출) / 만성 저신뢰 관절
- 순간이동(jitter) · 화면 밖 좌표 · **모델 간 불일치**
- 가장 의심스러운 프레임을 키포인트 오버레이 이미지로 저장

**핵심 발견:** 손 클로즈업 영상(머리·어깨가 화면 밖)에서는 전신 포즈 모델이 가려진 관절을
억지로 추정하여 두 모델이 거의 100% 어긋남 → **이런 구간은 body 키포인트를 버리고 손(hand)
키포인트만 신뢰**해야 한다는 점을, 교차모델 검증으로 확인했습니다.

---

## 모델 · 대용량 파일 안내

- YOLO 가중치(`yolo11x-pose.pt`)와 MediaPipe 모델(`holistic_landmarker.task`)은 **첫 실행 시
  자동 다운로드**되며 `.gitignore` 로 제외됩니다.
- **원본 공정 영상과 키포인트 데이터(`data/`, `results/`)는 용량(수백 MB~)이 커서 git에 포함하지
  않습니다.** GitHub 파일 용량 제한(100MB) 때문이며, 영상·데이터는 **별도(클라우드/로컬)로 보관**합니다.
  레포에는 코드만 있으므로, 실행하려면 영상을 `data/` 에 직접 넣어야 합니다.
- 작업지도서가 재생하는 `app/KakaoTalk_...mp4`(약 72MB)만 앱 동작을 위해 포함되어 있습니다.

---

## 작업지도서 자동화 파이프라인 (`pose/` 신규 모듈)

영상 → 키포인트 → 단계 분할 → 작업지도서로 잇는 자동화 모듈. `pipeline.py` 가 아래를 순서대로 묶는다.

| 모듈 | 역할 |
|------|------|
| `extract_pose.py` | YOLO11-pose 전신 키포인트 (Apple MPS 가속 지원) |
| `extract_hands_rtm.py` | rtmlib RTMPose-Hand 손 21점 (MediaPipe의 Python 3.13 대체) |
| `segment.py` | 손목속도(One-Euro 평활) → `ruptures` 변화점으로 작업 단계 자동 분할 |
| `align_dtw.py` | DTW로 서로 다른 각도·회차 영상을 공통 타임라인에 정렬 |
| `extract_asr.py` | faster-whisper(large-v3) 한국어 나레이션 전사 + 도메인 어휘 주입 |
| `anchor_steps.py` | 나레이션을 공정관리지침서 표준 단계에 매핑 + 용어 표준화 |
| `build_steps.py` / `refine_steps.py` | 구간 × 나레이션 × 공정단계 융합, 부가/비부가(VA/NVA) 동작 구별 |
| `generate_html.py` | 단계 결과(`steps.json`)를 작업지도서 HTML로 렌더 |
| `pipeline.py` | 위 단계를 한 명령으로 연결하는 오케스트레이터 |

> 설계 원칙: **수치(시간·구간)는 측정값, 단계명·순서는 공정관리지침서, 설명은 나레이션** 에서 가져오고
> LLM은 문장만 다듬어 환각을 막는다. 출력은 자동 초안이며 **사람 검수 후 확정(반자동)** 한다.

## 사용 모델

- [Ultralytics YOLO11-pose](https://github.com/ultralytics/ultralytics) — 전신 17 키포인트
- [MediaPipe Holistic Landmarker](https://ai.google.dev/edge/mediapipe) — 전신 33 + 양손 각 21 키포인트
