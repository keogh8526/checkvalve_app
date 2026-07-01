# 통합 아키텍처 — `feature/gui-architecture`

체크밸브(Dual Plate Check Valve, 부품 `GMT-CV-008`) 조립 **표준 작업 지도서 자동 생성** 시스템의 목표 아키텍처.
두 갈래 구현을 하나로 합친다:

- **A = 다시점 파이프라인** (`pose/`, 본 브랜치) — 실측 타이밍(다시점 DTW 합의), ASR 나레이션, 정직한 정확도 평가
- **B = sopgen** (`../sopgen`) — RAG gold 라벨 재사용, 검수 게이트, 로컬 GUI, 자기완결

> 산출물은 항상 `app/check_valve.html` 양식(영상 + 단계 동기화 표 + 검사 체크리스트). 출력은 **자동 초안 + 사람 검수(반자동)**.

---

## 0. 선결 결정 3가지 (병합 코드 작성 전에 확정)

**D0.1 — 단일 taxonomy, 평면 리스트가 아닌 계층.**
A는 8 fine 단계, B의 gold는 5 단계 — 소스 확인 결과 **같은 부품·같은 공정**(공정8 DISC·SPACER·HINGE PIN 조립). B gold는 A canonical의 검수된 거친 뷰.
→ `canonical.py`가 **단일 taxonomy + 명시적 `FINE → SUPER` 맵**. 작성기는 gold를 **canonical(SUPER) 라벨로 정렬**(리스트 인덱스로 매핑 금지).

**D0.2 — production 영상은 6개 다시점 세트 하나.**
A의 타이밍과 B의 gold는 서로 다른 촬영본에서 검증됨 → 교차는 의미상 무효. 6영상 세트(타이밍 body 시점 ≥2개 = A의 진짜 강점)를 본선으로.
→ **gold pool을 6영상 세트의 `source_clip` 기준으로 재시드**. 기존 5개 KakaoTalk 클립은 **평가용 회귀 fixture로만** 보존. 5클립에선 다시점 DTW가 단일시점으로 퇴화 → 그 경로는 배포 안 함.

**D0.3 — MediaPipe 전면 제거.**
py3.13 휠 없음. 교차모델 불일치(`disagree_pct`)는 **stub이 아니라 제거**. shot_type은 **YOLO 단독 신호**(상체 키포인트 신뢰도/커버리지 + 손 커버리지)로 분류. 각 클립 `clip_profile.json`은 **커밋**(캐시 재현). `CLIP_ROLES` + `needs_manual_role` 플래그가 GUI의 사람 보정 경로.

---

## 1. 전체 아키텍처 & 데이터 계약

```
 ┌───────────────────── 커밋·재현 가능 ─────────────────────┐
 │ manifest.json (clip_id↔role/view/group)  ·  clip_profile.json │
 │ gold pool seed (SQLite/gold_seed.json)   ·  ground_truth.csv  │
 │ canonical.py (FINE+SUPER)                ·  embeddings.npz(평가)│
 └──────────────────────────────────────────────────────────────┘
        data/*.mp4 (gitignore)  ─┐                 산출물: app/check_valve.html
                                 │                 (단일 frozen 양식, sha256 고정)
                                 ▼
 ══ PREPARE (무거움·PART 단위·오프라인·캐시·HTTP 핸들러서 절대 실행 안 함) ══
   ingest ── ffprobe → normalize(H.264+faststart, fps 패스스루) → audio(16k wav)
        └─▶ registry: manifest.json (content-hash clip_id, 자동스캔+사람 role 편집)
   profile ─ YOLO 단독 신호 → clip_profile.json {shot_type, roles, needs_manual_role}
   extract ─ shot_type 라우팅: body_reliable→YOLO body.json
                                hand_closeup →RTMPose hands.json (body 안 씀)
                                has_audio    →faster-whisper asr.json (선택)
            (source_sha1+model+stride+version 키로 skip-if-exists)
   fuse ──── 타이밍 시점 + DTW 합의 → fused_segments.json (실측 섹터)
   anchor ── asr.json → canonical.classify → anchors.json (라벨 힌트 채널)
                                 │
 ══ GENERATE (빠름·CLIP 단위·GUI 생성 버튼이 호출·in-process) ══
   ① digest    fused 섹터 → digest.candidate_segments (source='fused')
   ② collapse  섹터 → canonical SUPER 라벨(단조) → segment_labels.json
   ③ label     세그먼트별 우선순위 캐스케이드 → labels.json {label, channel, routing}
   ④ keyframes digest 세그먼트 → keyframes.json
   ⑤ author    RAG gold(SUPER 라벨) | client≠None: Claude vision (STEP_SCHEMA)
   ⑥ assemble  steps + gold SEQ/SELF + standard_time + 검수 게이트 → bundle.json
   ⑦ render    bundle → output/<stem>/guide/{steps_data.js, index.html, review.json}
   ⑧ store     bundle → SQLite document/step (status=draft, provenance)
                                 │
 ══ OPERATOR ══  Studio (stdlib http.server) + launcher.exe (더블클릭)
   목록 → 생성 → 미리보기(실제 산출물 iframe) → 검수/라벨편집 → 승인 → 내보내기
        승인 → store.promote_to_validated() ─┐ 피드백: 검증된 초안이 RAG pool에 합류
                                             ▼ (다음 실행 자동수용률↑)
 ══ EVAL ══ (개발자 전용·운영 경로 밖·커밋된 fixture)
   eval_honest: 경계 F1(Hungarian ±1/2s) + 라벨 정확도(채널별·캐스케이드후·SUPER)
```

### 스테이지 데이터 계약 (이음새)

| 스테이지 | 출력 계약 | 비고 |
|---|---|---|
| **registry** | `manifest.json`: `{version, clips:[{clip_id(sha1), raw, normalized, audio\|null, probe{fps,res,duration,codec,has_audio}, group, view, take, role:[…], role_source, shot_type}]}` | clip_id=콘텐츠 해시. role 사람 편집·override 우선. **A의 하드코딩 `VIEWS` 대체** |
| **profile** | `clip_profile.json`: `{clip_id, duration_sec, fps, res, no_detection_pct, upper_body_conf, hand_cov, shot_type, body_trust, hand_trust, roles, role_source, needs_manual_role}` | **`disagree_pct` 게이트 없음.** YOLO 단독. 커밋 |
| **extract** | `body.json`/`hands.json`/`asr.json` — **고정 파일명+스키마**. `qc.json`(무디코딩 커버리지) | hand_closeup은 body 실행 안 함 |
| **fuse** | `fused_segments.json`: `{ref, ref_dur, tol, sectors:[{sector,t_start,t_end,dur_sec,start_support_views}]}` | A의 실측 타이밍 권위. **PART 단위** |
| **collapse** | `segment_labels.json`: `[{seg_id, t_start, t_end, super_label, fine_label?, source}]` | A의 `collapse_to_6`을 **렌더러 밖**으로, 세그먼트→canonical 맵 생성 |
| **label** | `labels.json`: `{seg_id → {label, channel:'rag\|llm\|asr\|asr+vision\|vision', routing:'auto\|review\|blocked', hint?}}` | **캐스케이드**(§4) |
| **author** | step dict `{badge,text,sub,pts[],insp,cap,at,evidence,provenance,grounded,reviewed}` | RAG(SUPER 라벨) 또는 Claude vision, 동일 I/O |
| **assemble** | `bundle.json` (정본 문서, §1.1) | B의 bundle, 렌더 직전 계약 |
| **render** | `output/<stem>/guide/{steps_data.js(var STEPS/CHAPTERS/SEQ/SELF), index.html, review.json}` | 양식 frozen + sha256 검증 |
| **store** | SQLite `document`+`step` (status, provenance, signed_by/at) | B 스키마 + 서명 필드 |

### 1.1 정본 문서 계약 — `bundle.json`

> **중요(GUI 검증):** 정본 frozen 양식(sopgen `check_valve.html`)이 소비하는 STEPS 필드는 `{no, tag, at, insp, badge, text, sub, pts, cap}` — `segAt`은 **`at`만** 사용(다음 단계 `at`이 경계). 검수 체크는 항목 수 동적 카운트.
> **주의(양식 분기):** A(cv_full)의 `render_workinstruction.py`는 **`end` 필드를 쓰는 다른 양식 변형**을 타깃함(segAt이 `STEPS[i].end` 사용). D0.1에서 **at-only 원본으로 통일**(더 단순·검증됨), `spec_compiler`가 at-only STEPS 생성. `end`를 정본 계약에 넣지 않음.

`bundle = { stem, video, shot_type, roles, meta{품명·도번·공정명·관리번호·작업표준시간·개정}, standard_time{method,caveat,value}, STEPS[], CHAPTERS[], SEQ[], SELF[], review{evidence_ok, signed_off, approved, needs_review[], blocked[], warnings[], provenance{...}} }`

---

## 2. 레포 구조 & 마이그레이션 (재작성 아님, 재사용)

`checkvalve_app` 안에 단일 패키지 `checkvalve/`. **B를 척추로**(단일 진입 오케스트레이션·렌더·store·검수게이트·GUI), **A를 증거 엔진으로 접목**(CLI 스크립트를 import 가능한 함수로).

```
checkvalve_app/                     (branch: feature/gui-architecture)
  checkvalve/
    canonical.py    # A/pose/canonical.py + FINE→SUPER + B badge/insp
    contracts.py    # NEW: 스테이지별 dataclass + validate()(의미 검증)
    config.py, paths.py  # B/paths+config, ffmpeg=shutil.which (NO /opt/homebrew)
    pipeline.py     # prepare_part(part) + generate_guide(stem, client=None)  [두 진입점]
    prepare/        # 무거움·PART·오프라인
      ingest.py     # ffprobe+normalize+audio (ffmpeg, NEW — A의 wav 공백 메움)
      registry.py   # manifest.json 스캔/병합 (A의 VIEWS 대체)
      profile.py    # B/clip_profile.py, YOLO 단독 (NO mediapipe)
      extract.py    # A/extract_pose·extract_hands_rtm·extract_asr 셸
      fuse.py       # A/segment_multi·segment_hands·fuse_views·align_dtw
      anchor.py     # A/anchor_steps (ASR 힌트 채널)
    generate/       # 빠름·CLIP (GUI 버튼)
      digest.py     # B/signal_digest.py
      collapse.py   # A collapse_to_6, 렌더러 밖으로 → 세그먼트→canonical 맵
      label_router.py  # NEW: 우선순위 캐스케이드 (A label_by_rule 대체)
      keyframes.py  # B/keyframe_sampler.py
      author.py     # B/step_author.py (RAG SUPER + Claude seam)
      assemble.py   # B/assembler.py (검수 게이트·승인 규칙 그대로)
      render.py     # B/render.py (외부 steps_data.js + smoke + sha256)
    store.py        # B/store.py + signed_by/at/approved + promote_to_validated()
    app/
      studio.py     # B/app.py 강화: SPA + JSON API + Range
      runner.py     # NEW: bg 스레드, venv python 셸(A subprocess 패턴)
      launcher.py   # A/app/launcher.py: studio 기동 + 브라우저(frozen-aware exe)
      static/{index.html, app.js, app.css}  # 무빌드 바닐라 SPA, 한국어
    eval/           # 개발자 전용, app/·generate/에서 import 금지
      eval_honest.py, test_label_ceiling.py
  app/check_valve.html  # 단일 정본 frozen 양식 (BOM #partsbox 내장)
  data/                 # gitignore mp4
  fixtures/             # ground_truth.csv + embeddings.npz (커밋, 평가 재현)
  manifest.json, clip_profile/*.json, gold_seed.json  # 커밋
```

**마이그레이션 (A → 병합):**

| A 산출물 | 변환 | 조치 |
|---|---|---|
| extract_pose/hands_rtm/asr | `prepare/extract.py` | 함수 래핑, 검증된 argparse 플래그로 셸 |
| segment_multi/hands/fuse_views/align_dtw | `prepare/fuse.py` | 거의 그대로 승격 — B에 없던 A의 핵심 |
| anchor_steps (문장별 score 유지) | `prepare/anchor.py` | 최종 라벨 아닌 **힌트**로 |
| `assemble_fused.label_by_rule` | **삭제** | `label_router.py`로 단일 호출지점 대체 |
| `collapse_to_6`(렌더러 내) | `generate/collapse.py` | 상류로, 신뢰도 태그 맵 생성 |
| `render_workinstruction`(정규식) | **폐기** | B의 외부 JS 렌더러 채택, BOM은 양식에 내장 |
| canonical.py/terms.py | `checkvalve.canonical` | + FINE→SUPER, 전 스테이지 공유 |
| eval_honest/test_label_ceiling | `eval/` | **순이득 — B엔 평가 없음** |
| run_all.py (VIEWS·mac ffmpeg) | `prepare_part` + `generate_guide` 분리 | 다시점 루프 → PART PREPARE |

**첫 커밋 = "B를 이 레포 안에서 돌게":** sopgen 모듈(app/store/render/assembler/step_author/pipeline) `checkvalve/`로 vendor, 상대 import 재작성, `/sopgen/output/` URL 접두사를 `/output/<stem>/`로, `REPO/OUTPUT/DB_PATH/TEMPLATE` 재지정, 레포 루트 import 테스트. (`autoguide`는 더 오래된 중복 프로토타입 — 무시. **sopgen만** 차용.)

---

## 3. 레이어별 기술 선택

| 레이어 | 선택 | 근거 |
|---|---|---|
| 전처리 | ffmpeg=`shutil.which`(+`FFMPEG_BIN`, 부재 시 MessageBox); content-hash clip_id; **fps 패스스루 불변식** + `컨테이너 fps == body.json fps` assert | A의 `/opt/homebrew` 하드코딩·VIEWS 제거; fps 변경은 `at` 기반 동기화 무음 파손 |
| 스키마 고정 | body/hands json 단일 파일명+스키마; **`extract_hands_rtm`에 `total_frames`+`both_hands_frames` 추가** | 프로파일러 손 커버리지 읽기가 A가 안 내던 필드에 의존했음 |
| 프로파일 | YOLO 단독: `어깨 conf<0.3 AND 손 있음→hand_closeup`; `no_detection 높음→sparse`; else `body_reliable` | 없으면 py3.13에서 모든 클립이 review로 |
| 분할/타이밍 | ruptures 변화점(약한 사전치) + DTW 시점 합의(`fuse.py`). 경계는 합의가 제안→검수 확정, 모션에너지 단독 신뢰 금지 | 양 코드 공통: 분할은 약한 사전치 |
| 표준시간 | 타이밍 시점 ≥2면 **다시점 fused total 정본**, autocorrelation은 문서화된 폴백(`method`+`caveat` 항상 동반) | 두 소스 충돌을 `contracts.validate()` 규칙으로 해소 |
| 라벨 | **우선순위 캐스케이드**(보정 가중치 없음), 기본 **SUPER 입도**; fine7은 grounded일 때만·편집 가능 | 0.75/0.40 가중투표는 held-out ~3클립으로 보정 불가; 캐스케이드는 최선 grounded 채널 이상을 보장 |
| 검수 게이트 | B의 `approved = evidence_ok AND signed_off` **그대로**; `blocked[]`+`low_confidence[]` 추가; 승인 전 export 차단 | 약한 라벨러를 수용가능케 하는 안전망 |
| RAG store | SQLite(WAL, busy_timeout) — 이 규모엔 ANN 없이 SQL 필터. `promote_to_validated()`로 루프 닫음 | 서명 초안 1 UPDATE로 다음 RAG 후보화 |
| GUI 스택 | stdlib `http.server`(HTTP/1.0, Threading, Range/206) + 무빌드 바닐라 SPA + 실제 산출물 iframe. GUI 프로세스는 **ML import 0**, `runner.py`가 venv python 셸. PyInstaller onefile | 산출물이 이미 브라우저 페이지; Tk/Qt면 영상+동기화 재구현. ML 워커 분리로 exe 작고 크래시 격리 |
| 선택 LLM seam | **단 하나의 스테이지만** LLM 인지: `author(client=None)`. 기본 RAG; `client` 설정→Claude(`claude-opus-4-8`) vision under `STEP_SCHEMA`. CI는 `client=None` 전체 실행 스모크 | B가 이미 stub해둔 seam; 오프라인 경로 기계적 보장 |

---

## 4. 라벨 전략 — 22~33% 천장 공략

배포 라벨러(A `label_by_rule` duration 휴리스틱)를 **결정적 우선순위 캐스케이드**로 교체(가중투표 아님 — 보정 데이터 없음). 세그먼트별:

```
1. grounded RAG (gold pool, 이 부품, SUPER 라벨)   → routing=auto,   grounded=True
2. grounded LLM (Claude vision, client 있을 때만)  → routing=auto,   grounded=True
3. ASR 앵커 AND vision 일치                        → routing=review (힌트)
4. ASR 앵커 단독                                   → routing=review (힌트)
5. vision 단독 (DINOv2, torch 있으면)              → routing=review (힌트)
6. 없음 / 채널 충돌                                → routing=blocked (편집 필수)
```

**핵심 규칙:**
- **RAG는 gold를 SUPER 라벨로 세그먼트에 정렬**(B의 `pool[i]` 위치 루프 금지 — 개수 불일치 시 무음 드롭/패딩). 불일치는 `review.warnings`로 명시.
- **SUPER 입도가 auto 기본.** 정렬↔핀삽입 동시진행은 비전으로 거의 분리 불가 → SUPER로 시퀀스 단조화. fine7은 grounded일 때만 채우고 **GUI에서 편집 가능**.
- **v1에선 ASR/vision은 검수 힌트**(렌더 단계를 바꾸지 않음). 신뢰 경로 = RAG gold + 사람 서명. 가중투표·신뢰도 융합은 fixture 존재 조건의 **v2**.
- **채널은 깔끔히 self-skip.** torch·API키·오디오 없어도 `bundle.json` 생성(저신뢰·review 多). vision 채널은 `cuda→mps→cpu` 셀렉터 필요(A `label_superlabel`은 mps 전용) + cu124 venv 스모크 후 사용.
- **편집 표면 = 라벨만.** 운영자는 `badge/text/sub/pts/공정단계` 인라인 편집; 실측 `at`/`standard_time`은 읽기전용(`measured` 배지, override 시 provenance→manual). 사람 노력을 수치가 약한 곳에 집중, 신뢰되는 DTW 타이밍 보호.

**평가 루프(재현 불가하면 주장 안 함):** `fixtures/ground_truth.csv`(시간+라벨만, 영상 없음) + `fixtures/embeddings.npz`(로드시 `model_id`+버전 assert) 커밋. `eval_honest`가 경계 F1 + 라벨 정확도(채널별·캐스케이드후·SUPER). 게이팅 지표=**캐스케이드후 SUPER ≥ 커밋 베이스라인**. CI가 `client=None` 전체 파이프라인 실행.

**피드백 루프(천장을 시간으로 이기는 유일한 길):** GUI 승인 → `promote_to_validated(doc_id)`로 draft→validated. 다음 실행에 풍부한 pool → 캐스케이드 규칙1 커버리지↑ → 자동수용↑. **v1부터.** 콜드스타트(부품 gold 없음)는 대부분 review로, "gold 없음 — 첫 초안 전체 검수" 배너 표시(빨간 벽 아님).

---

## 5. 운영자 흐름 & 백엔드 API (더블클릭 단순)

**5화면:** `수집(role 태그) → 실행 → 미리보기 → 검수/라벨편집 → 승인/내보내기`

```
GET  /                       → Studio SPA
GET  /api/parts              → 알려진 부품 + 최근 상태
POST /api/run {stem}         → {job_id}   (generate_guide 호출 — FAST 경로만)
GET  /api/status?job=        → {state,stage,pct,log_tail,bundle_path,error}
GET  /api/bundle?job=        → bundle.json
PUT  /api/step {job,no,fields}   → 라벨 채널 편집(실측 필드 보호)
POST /api/step/review {job,no}   → 단계 검수 표시
POST /api/approve {job,signed_by} → evidence_ok 강제, signed_off
POST /api/export {job}       → 자기완결 zip(html+steps_data.js+mp4+launcher.exe)
GET  /api/preview?job=       → render → 302 /output/<job>/guide/index.html
GET  /output/<stem>/guide/*  → 정적, Range/206  [is_relative_to(REPO) 가드]
```

**하드 규칙:**
- 생성 버튼은 **`generate_guide(stem)`만**(FAST). `prepare_part`(extract+ASR+다시점 fuse)는 오프라인 선행·캐시. **`fuse.timing`은 동기 HTTP 핸들러서 절대 실행 금지.**
- **job 상태 디스크 영속**(`status.json`, atomic `os.replace`); 부팅 시 메모리 재구축; 고아 running→`error:interrupted`. part_id 단일실행은 lockfile.
- **모든 쓰기 엔드포인트**가 job_id/stem을 allow-list(`stem in list_stems()`) + `is_relative_to(REPO)` 검증. 작은 타임라인 클립만 서빙(다GB 분석 mp4 금지).
- 미리보기/내보내기는 **동일 렌더 경로** → 승인한 것이 곧 출하물.
- 선택 LLM은 **실행 토글**(API키 있으면 author에 client 1회 주입), 단계별 버튼 아님. 키 없으면 토글 숨김.

**패키징:** `launcher.py`(frozen-aware, 콘솔 없음) → PyInstaller onefile **Studio exe(torch 없음)**. 내보낸 가이드는 운영자가 더블클릭하던 동일 launcher exe 동봉, 외부 `var` steps_data.js + `os.path.relpath` 영상으로 `file://` 안전.

---

## 6. 단계별 로드맵 (각 단계 독립적으로 유용)

- **Phase 0 — 토대(첫 걸음).** sopgen 모듈 `checkvalve/`로 vendor·import 재작성·경로/URL 재지정·레포루트 import 테스트. **D0 3개 게이트 해소:** 두 양식을 단일 frozen `app/check_valve.html`(BOM 내장)으로 병합·sha256 커밋; `canonical.py`에 `FINE→SUPER`; `gold_seed.json`을 6클립 `source_clip`으로 재시드. *유용: B 파이프라인이 새 레포에서 RAG-only로 production 세트 완주.*
- **Phase 1 — 재현 가능한 전처리.** `paths.py`(ffmpeg 발견), `ingest.py`(normalize+faststart+audio, fps 패스스루), `registry.py`(manifest=VIEWS 대체), YOLO 단독 `profile.py`. manifest+clip_profile 커밋. *유용: 모든 클립 재현 수집/프로파일, 하드코딩·MediaPipe 0.*
- **Phase 2 — 증거 엔진(A 접목).** `fuse.py`(DTW 타이밍)+`anchor.py`(ASR 힌트)를 `prepare_part`로. `fused_segments → digest`. *유용: 실측 다시점 표준시간이 bundle에 — A의 핵심.*
- **Phase 3 — 라벨 캐스케이드 + collapse.** `collapse.py`+`label_router.py`로 `label_by_rule` 대체. RAG SUPER 정렬. *유용: 라벨이 맹목 휴리스틱에서 벗어나고 불일치가 경고로.*
- **Phase 4 — 운영자 Studio.** `studio.py`(API+Range), `runner.py`(bg+디스크상태), `static/` SPA(5화면), `launcher.py` exe. 검수게이트·provenance·export 게이트. *유용: 비개발자가 더블클릭으로 전 흐름.*
- **Phase 5 — 정직한 평가 + 피드백.** `fixtures/` 커밋; `eval_honest` 확장(채널/SUPER); CI 스모크(`client=None`). `promote_to_validated` 승인 연결. *유용: 22~33%가 커밋된 회귀 테스트로, 정확도가 사용으로 복리.*
- **Phase 6 (선택) — LLM 작성 + vision 채널.** `author(client)`→Claude vision; DINOv2 vision 힌트(cuda 셀렉터). 둘 없어도 실행. *유용: 키/GPU 있을 때 강한 초안, 필수 아님.*

---

## 7. 어려운 부분 / 사람이 개입하는 지점

- **라벨 천장은 신규 콘텐츠에 실재·영구.** 캐스케이드+SUPER+RAG 재사용은 *신뢰* 비율을 올릴 뿐, fine 비전 라벨링을 해결하지 않음. **사람이 모든 초안을 서명 후 표준 문서화.** 설계 의도.
- **role/shot_type은 QC가 완전 결정 못 함**(특히 MediaPipe 없이). 자동 프로파일러가 제안, `needs_manual_role`+`CLIP_ROLES`+수집 화면이 보정. 부품별 gold 시드 선행.
- **촬영본 교차 무효성.** 타이밍·gold은 동일 세트(D0.2). `contracts.validate()`가 `gold.source_clip`의 세트 소속을 assert·GUI 배너로 노출 — 잘못 매핑된 초안이 실측인 척 못 함.
- **hand-closeup body pose는 죽음** — 라우팅 결정으로 1회 인코딩(`hands-only, 타이밍 합의 제외`), 이후 특수처리 없음.
- **단일시점 표준시간은 autocorrelation(n=1)으로 퇴화** — `caveat` 동반, 다시점 실측인 척 안 함.
- **frozen 양식은 계약.** sha256+앵커 문자열을 스모크가 assert — 양식 편집은 무음 파손 대신 빌드 실패.
- **재현성은 fixture 커밋 조건부.** `ground_truth.csv` 커밋 불가면 정직-평가 주장을 약화가 아니라 **철회**.

---

## 8. 문서 입력 & 환각 방지 재설계 (v3 — Codex 2패스 반영)

**입력 = PDF만.** `.docx`/HWP 배제(Claude Files API는 PDF·텍스트만; docx는 변환 필요, HWP 불가). 스캔 PDF는 OCR **저신뢰 플래그 + 엄격 검수**, 텍스트 PDF 권장.

**핵심 원칙 전환 — LLM은 "사실 추출자"가 아니다.** 수치·정렬·단계수 같은 load-bearing 사실은 **결정적 코드 + 사람**이 확정하고, **LLM은 의미 조직(semantic structuring)만** 한다. (Codex 두 패스가 v2의 환각 방어를 층별로 뚫음 → 아래로 대체.)

### 스테이지 재정의: `prepare/doc_parse.py` (부품당 1회·오프라인 폴백 유지)
1. **결정적 파서가 먼저** — 텍스트 PDF=`pdfplumber`(표 셀 bbox/page), 스캔=OCR(저신뢰). LLM 이전에 **원문 사실 + 위치 provenance** 확보. `.docx`는 지원 안 함(PDF만).
2. **LLM은 의미 조직만** — 파싱된 텍스트/표를 `process_spec`로 구조화(어느 셀이 어느 단계의 어느 필드인지 **연결**). **숫자 전사 금지.** citations는 **안 씀**(구조화출력과 API 비호환 — 400).
3. **수치·BOM = 원문 regex + 단계/섹션 맥락 바인딩**(전역 문자열매칭 금지). 각 값 `{step_id, field, page, row/col, raw_span, value, unit}`. 단위/전각/공백/범위 정규화 후 대조. LLM은 숫자 공급 안 함.
4. **셀별 사람 서명 — 렌더된 원문 페이지 대조**(LLM 텍스트 대조 아님). 승인UI가 원문 페이지 + 추출셀 하이라이트. 승인물 = **content-hash + 서명자·시각**(불변).
5. **오프라인 폴백:** `process_spec` 없고 API 없으면 `canonical.py` **수동입력 경로 유지**(폐기 아님). LLM 문서파싱은 *가속기*, 필수 아님. CI `client=None` 전체 실행.

### 정렬·검증·컴파일 (전부 결정적, LLM 아님)
6. **정렬 = 결정적 단조, `N≠M`은 하드 블록**(경고 아님 — 필수 단계 무음 드롭 금지). 동시진행(정렬↔핀삽입)은 taxonomy의 **공유세그먼트 규칙(SUPER 그룹)** 으로 명시. LLM은 근거/설명만.
7. **verifier = 결정적 재추출**(원문 bytes regex), 2차 LLM 아님(상관오류 회피). 2차 LLM은 sanity 힌트로만.
8. **abstain = 코드 게이트** — 스키마에 `confidence:number` + `abstained:bool` 추가, **코드가** 저신뢰/기권을 검수로 라우팅(프롬프트 의존 아님).
9. **`spec_compiler`(결정적)** — 검증된 process_spec + fused_segments → bundle(`at·badge·tag·insp`, at-only). LLM 없음.
10. **`provider` 인터페이스** — process_spec가 `canonical.py` 인터페이스(`CANONICAL_ORDER/parts_for/desc_for/control_for/BADGE/PROC_ORDER`) 구현, importer 3개(assemble_fused·render_workinstruction·anchor_steps) 전환 후 canonical 폐기. `store.py`+`STEP_SCHEMA`에 `source_cite/confidence/grounded/numeric_guard` 컬럼 추가.

**한 줄:** LLM이 어떤 load-bearing 수치·정렬의 **유일 출처가 되지 않게** 아키텍처를 짠다 — 결정적 파서가 사실을, LLM이 의미를, 코드·사람이 검증을.
