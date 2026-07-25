# /autobot:screen — 화면 하나 집중 인터뷰 스킬 신설 — 2026-07-17

목표: 앱 화면 하나를 인터뷰로 깊게 기획하고, SSOT 문서(AGENTS.md + CLAUDE.md + SOUL.md + docs/) + 로직 제외 SwiftUI 뷰코드까지 산출하는 독립 스킬.

## 수용 조건
- [ ] `/autobot:screen <화면>` 진입점 + `autobot-screen-interview` 스킬 (기존 command/skill 컨벤션 준수)
- [ ] 인터뷰: 혼합 방식(AskUserQuestion 갈림길 + 오픈 질문), 라운드별 스냅샷 → docs/screens/<slug>.md 에 즉시 기록 (중단 재개 가능)
- [ ] SSOT 병합 규칙: 신규 생성 + 기존 문서 비파괴 병합, CLAUDE.md 는 AGENTS.md 참조 (중복 금지)
- [ ] SwiftUI 뷰: presentation-only 정의 명확 (mock 주입, 콜백 파라미터, 상태별 #Preview), 빌드 검증은 advisory
- [ ] Autobot 프로젝트(.autobot/)면 컨텍스트 활용, 아니어도 동작 (독립)
- [ ] README 트리 + CHANGELOG [Unreleased] 반영
- [ ] Workflow 리뷰 패널 (컨벤션·인터뷰 설계·정합성) → confirmed 지적 반영

## 체크리스트
- [x] 리포 컨벤션 조사 (commands/meta.md, skills/autobot-ux-design, plan.md)
- [x] 사용자 결정 확보: 산출물=SSOT+뷰코드, 방식=혼합, 통합=독립
- [x] commands/screen.md 작성
- [x] skills/autobot-screen-interview/SKILL.md 작성
- [x] skills/autobot-screen-interview/references/templates.md 작성 (SSOT 4종 템플릿)
- [x] README + CHANGELOG 갱신
- [x] Workflow 리뷰 → 반영 → Results 기록

## Results (2026-07-17)
- 신규: commands/screen.md, skills/autobot-screen-interview/{SKILL.md, references/templates.md}. 갱신: README(트리 + 독립 명령 소단락 + 누락 명령 3종 보충), CHANGELOG [Unreleased].
- Workflow 리뷰(3렌즈 20에이전트, finding별 적대적 반증): raw 17 → confirmed 15(중복 2 포함, 실질 12) / 기각 2. 전부 반영 —
  주요: allowed-tools Skill 누락(high), status 3분기 재개(confirmed/built 미정의, high), R2 헤딩 계약 불일치(high), R6 하류 전파(high), built 전이 누락(medium), 미결정 에스컬레이션(medium), refreshing/stale 상태 축(medium).
- 검증: 새 파일 frontmatter YAML 파싱 OK, scripts/verify_spec_docs.py All checks passed. (문서 전용 diff — 런타임 테스트 해당 없음)

## Working Notes
- SSOT 역할 분담: SOUL.md=제품 정체성(왜), AGENTS.md=에이전트 작업 규칙 정본, CLAUDE.md=@AGENTS.md 참조+Claude 전용, docs/screens/<slug>.md=화면 spec(인터뷰 주 산출물, 라운드마다 갱신).
- 로직 제외 = 네트워크/저장/ViewModel 금지, 액션은 `var onX: () -> Void = {}` 콜백 노출, 상태는 이니셜라이저 주입.
- 기획 깊이 철칙 (memory): 화면 나열 금지 — R1 에서 훅·3초 가치·성공 기준 필수 도출.
- 게이트 철학 (memory): 빌드 검증 실패는 advisory 보고, hard fail 금지.

# 리뷰 후속 수정 — 메타데이터 업로드/자격 증명 안내 — 2026-07-24

## 수용 조건
- [x] 첫 버전 fastlane 우회 성공 전에 연령 등급 적용을 검증한다.
- [x] doctor와 troubleshooting의 ASC 자격 증명 안내가 canonical 변수명과 일치한다.
- [x] 두 회귀 경로를 실행 테스트로 검증한다.

## Results
- `upload-metadata.sh`: `app_store_rating_config.json`이 있을 때 `Setting the app's age rating...` 로그가 없으면 #20538 우회를 적용하지 않도록 수정.
- `scripts/doctor.py` 및 `skills/autobot-orchestrator/references/troubleshooting.md`: `APP_STORE_CONNECT_API_KEY_*` 3종으로 remediation을 통일.
- 검증: 대상 테스트 12개 통과, 전체 `bash tests/run_tests.sh` 999개 통과, `bash -n` 및 `git diff --check` 통과.

# /autobot:clone 자율 탐험 기본화 + 실기기 하드 게이트 — 2026-07-25

## 수용 조건
- [x] 실기기 미연결/다중연결/idb 미설치 시 스킬이 브리프를 만들지 않고 중지한다.
- [x] 에이전트가 스스로 탭/스와이프하며 탐험하는 것이 기본 경로다 (사람 주도는 접근성 차단 시 열화 경로).
- [x] 파괴적 요소 탭이 후보 생성 지점에서 기계적으로 차단된다.
- [x] 탐험 루프에 수치화된 종료 조건이 있다(무한 루프 방지).
- [x] 신규 서브커맨드가 오프라인 테스트로 검증된다.

## Results
- `scripts/device_idb.sh`: `device`(하드 게이트, stdout=udid 단독, idb 미설치는 별도 분기) / `candidates`(a11y 트리 → 안전한 탭 후보, 파괴적 라벨 withheld, 모달이면 후보 0개) / `sig` / `tap` / `swipe` 추가. `screen` 이 화면 서명 `INFO: sig <hash>` 를 함께 출력(루프 종료 primitive).
- `skills/autobot-copy-analyze/SKILL.md`: 기본 모드 반전(Step 3 자율 루프 + STOP 조건 표), Step 2 를 하드 게이트로 교체, "기기 없음 → store-metadata-primary" 폴백 제거, 중지 vs 열화 절 신설, Preconditions 필수화.
- `commands/copy.md`: description·데이터 소스·CRITICAL RULES(#2 기기 게이트, #3 후보 밖 탭 금지) 갱신.
- 검증: `bash -n` OK, `tests/test_device_idb.py` 13건 + 서브테스트 5건 green, 전체 스위트 green. 게이트 3경로(0/1/N대)를 macOS 기본 `/bin/bash` 3.2 로 직접 실행해 확인 — 빈 배열 `${#a[@]}` 는 3.2 에서도 정상이라 우회 불필요.

## Working Notes
- 후보 필터를 tap 이 아니라 candidates 에 둔 이유: tap 은 좌표만 받아 라벨을 모른다 — 블랙리스트가 강제되는 유일한 지점이 후보 생성이다.
- `device_capture.sh`(devicectl)는 탭 불가 → 자율 경로 대안 아님. 접근성 차단 시 스크린샷 보조로만 생존.
- 평범한 `취소`/`Cancel` 은 블랙리스트에서 제외: 시트를 여는 건 에이전트 자신이고, 닫는 버튼을 막으면 모달에 갇힌다. 구독 해지 어휘만 차단.

## 실기기 실행 결과 (2026-07-25, 추가 회차)
- **드라이버 교체**: idb → Appium/WebDriverAgent. 실기기(iPhone 12 mini, iOS 26.5.2)에서 fb-idb 의 `ui describe-all`/`ui tap`/`screenshot` 이 전부 거부됨을 확인 → `scripts/device_wda.sh` + `scripts/device_a11y.py` 신규.
- **실기기 end-to-end 검증**: device 게이트 → WDA 세션 → `screen`(png+xml+sig) → `candidates` → `tap` → 새 화면 sig → 메뉴 닫기 후 sig 복귀(`02-back` == `00-home`). 재방문 감지가 실물에서 동작.
- **WDA 셋업 함정**: 설정 > 개발자 > **UI 자동화** OFF 면 WDA 가 설치·실행까지 성공하고도 `Timed out while enabling automation mode` → xcodebuild code 65 로 보인다. 서명은 `DEVELOPMENT_TEAM` 필요.
- **연결 함정**: devicectl `pairingState: paired` 는 연결이 아니다(`transportType: None` 인데 paired 였음). Xcode 에는 보이는데 devicectl 이 못 보면 Xcode > Devices and Simulators 를 한 번 열면 CoreDevice 터널이 살아난다. `system_profiler SPUSBDataType` 은 이 환경에서 0줄이라 판정 근거로 쓸 수 없다.
- 검증: 전체 스위트 1023건 green (clone 관련 32건 + 서브테스트 5).

## 실행 중 발견된 버그 수정 (2026-07-25, clone 실기기 완주 시도)
- [x] 낡은 좌표 탭 차단: `tap` 이 트리 인자 필수 + 후보 검증(`device_a11y.py verify`) + 라이브 sig 대조. 실기기에서 그 실패 동작이 실제로 거부되는 것 확인.
- [x] 후보 노이즈: 큰 후보 안의 비활성 텍스트/이미지 제거(실측 31 → 12), 행 안의 실제 컨트롤은 유지.
- [x] `analyze_reviews` 조용한 0건 → 감지·재시도·`> review-signal unavailable` 표기 의무화 (SKILL).
- [x] `get_similar_apps` 카테고리 오염 → 기능 명사 대조 후 `search_app` 재구성 (SKILL).
- 검증: `tests/test_device_a11y.py` 22건 green + 실기기에서 stale-tap 거부 확인.

# clone → copy 개명 + 신규 clone(실제 재현) 스킬 — 2026-07-25

## 수용 조건
- [x] 기존 스킬이 `copy` 로 개명되고 동작은 그대로다 (순수 개명).
- [x] 기기 드라이버 스크립트가 스킬 이름과 분리된다 (`device_*`).
- [x] 신규 `clone` 이 화면을 측정값 기반으로 재현하는 절차를 갖는다.
- [x] 문서가 존재하지 않는 능력을 전제하지 않는다 (측정 스크립트 실재 + 에셋 추출 불가 명시).

## Results
- 개명: `commands/copy.md`, `skills/autobot-copy-analyze/`, `.autobot/copy-analysis/`, `scripts/device_{wda,a11y,idb,capture}`, `tests/test_device_*.py`. `git clone` 문자열은 건드리지 않도록 대상 파일을 한정해 치환.
- 신규: `commands/clone.md`, `skills/autobot-clone-app/SKILL.md`, `scripts/device_measure.py`, `tests/test_device_measure.py`.
- 검증: `verify_spec_docs.py` All checks passed, 전체 1044건 green. 측정기는 실기기 캡처(일기 앱 심층 분석 화면)로 scale 2.997·팔레트 12색·타이포 추정 확인.

## Working Notes
- 두 스킬은 기기 드라이버와 안전 가드를 공유하고 **목표만 다르다** — copy=방향, clone=픽셀. 가드를 한 곳(device_a11y.py)에 둔 게 이 분리를 가능하게 했다.
- 신규 clone 의 Step 4~6 은 미검증. 다음 실행 때 여기서 결함이 나올 가능성이 높다(copy 의 Step 4~5 와 같은 위치).

## /autobot:clone 실기기 독푸딩 (2026-07-25)
- [x] Step 1~6 완주: 일기 앱 빈 상태 화면 → 측정 → 스펙 → SwiftUI → iPhone 12 mini 시뮬레이터 렌더 → 대조 이미지.
- [x] 결함 7건 수정 (CHANGELOG [Unreleased] 참조). 전체 1055건 green.
- 남은 차이는 사전 선언한 `unmeasurable` 항목뿐 — 번들 아이콘(자리표시자), 타사 앱이라 자리표시자로 둔 문구.
- 미검증: 여러 화면 연속 처리, 상태 변형(채워진 상태·에러) 재현, `copy` 와 병행 실행.

## /autobot:clone 2차 독푸딩 (2026-07-25, 저널 앱 홈 화면)
- [x] Step 1~6 재완주: 저널 앱 홈 → 측정 → 스펙 → SwiftUI → iPhone 12 mini 시뮬레이터 렌더 → 대조.
- [x] 측정기 결함 4건 수정: 스크롤 막대 미제거 / 크롬 자식이 루트로 승격 / WDA 이중 창으로 인한 전 요소 중복 / 겹침 무시한 스택 축 판정(+ 카드 배경이 형제 간격 오염). 루트 레이아웃이 `spacing 147` → 실제와 일치하는 `gaps [0,16,10,-1]` 로 교정.
- [x] Step 6 의 미실행 갭 해소: `scripts/device_render.sh` 신설 — 프로젝트 파일 없이 `swiftc` → `.app` → `simctl install/launch/screenshot`. 철칙 4(대조 이미지 없이 완료 금지)가 처음으로 실행 가능해짐.
- [x] 사용자 재정의 반영: 충실도 계약을 **픽셀 → 레이아웃·룩앤필·기능**으로 변경(SKILL + `commands/clone.md`). 측정 규율(철칙 1)은 유지 — 측정은 룩앤필에 도달하는 수단이지 목표가 아니다. 기능은 Step 4 의 **동작 계약** 표로 담고 로직 생성은 하지 않는다(`/autobot:mvp` 가 소비).
- [x] 외부 선행연구 대조 → `tasks/lessons.md`. 가장 큰 배움: 이 작업의 지배적 실패는 **요소 누락(85%)** 이며 우리 검증은 그걸 세지 않았다 → Step 6 에 누락 카운트 추가.
- 검증: 전체 1064건 green (`python3 -m unittest discover -s tests`). 회귀 8건 추가(`test_device_measure.py` 5, `test_device_render.py` 4 중 신규).
- 미검증(다음 회차): 상태 변형(채워진 목록·에러) 재현, 여러 화면 연속 처리, 재현본을 다시 측정해 원본과 요소 수를 자동 대조하는 커버리지 지표(`device_compare.py` 는 아직 정량 지표 없음).

## /autobot:clone flow 우선 재설계 (2026-07-25)
- [x] Step 2 전수 탐험 — 전이 자동 기록(`flow.jsonl`), settle 폴링, 커버리지 리포트, 재개(`device_flow.py next`).
- [x] 화면 정체성 분리 — `sig`(탭 가드) / `nodekey`(flow 노드, 구조 해시). 실기기에서 세션 넘어 안정성 확인.
- [x] Step 2a flow 맵 HTML — 깊이별 썸네일 + 전이 + 미탐험 목록. 의존성 0.
- [x] Step 2b 역기획 — 관찰/해석 물리적 분리, 해석 항목마다 근거 관찰 표시.
- [x] Step 2c 재현 대상 선택 — 전 화면 코드 생성 금지.
- [x] 실기기 검증: 3화면(빈 목록 → 홈 → 요약 상세), 전이 2건, 커버리지 2/25, 맵 깊이 0~2, 역기획 6항목.
- 검증: 전체 1077건 green. 설계 결정 기록: `docs/superpowers/specs/2026-07-25-clone-flow-first-design.md`.
- 미검증: 채워진 상태(기기 데이터 0개), 긴 목록 앱에서 `nodekey` 버킷 폭, 탐험 20+화면 규모에서의 맵 가독성.
