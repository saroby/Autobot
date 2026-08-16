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

# /autobot:clone 스킬 다듬기 — 2026-08-15

목표: Appium으로 타깃 앱을 관찰·조작하고, 그 증거를 바탕으로 화면·상태·전이를 같은 방식으로 재현하는 clone 스킬의 실행 계약을 다듬는다. 부분 실행을 완료로 오인하거나 상태·화면 누락을 숨길 수 있는 공백도 함께 막는다.

## 수용 조건
- [x] 기존 clone 산출물 계약과 `copy` 경계를 유지한다.
- [x] Appium 기반 대상 앱 탐험과 화면/상태/전이 재현이 스킬의 중심 계약으로 명확하다.
- [x] 여러 화면·상태 변형을 처리할 때 무엇을 탐험/재현/검증했는지 산출물에서 판별할 수 있다.
- [x] 스킬이 요구하는 정량 또는 구조 검증이 실제 스크립트와 회귀 테스트로 닫힌다.
- [x] 실기기 미연결 상태에서도 문서/파서/비교 경로를 오프라인으로 검증할 수 있다.
- [x] frontmatter·문서 검사·clone 관련 회귀가 통과하고, 전체 suite의 기존 비관련 실패를 결과에 기록한다.

## 체크리스트
- [x] clone 문서·도구·테스트의 현재 계약과 남은 위험을 조사한다.
- [x] 온라인 Appium/모바일 자동화 선행 구현을 조사하고 차용 항목을 결정한다.
- [x] 최소 수정 설계와 acceptance evidence를 기록한다.
- [x] 실행 절차와 산출물 계약을 보완한다.
- [x] 회귀 테스트를 추가/수정한다.
- [x] 문서 검증·테스트·diff 검사를 실행한다.
- [x] Results에 변경 사항과 검증 결과를 기록한다.

## Working Notes
- 기준 SSOT: `skills/autobot-clone-app/SKILL.md`; 진입점은 `commands/clone.md`.
- 핵심 실행 경로: Appium + WebDriverAgent로 실기기 대상 앱을 관찰하고 조작한다.
- 스크립트가 실제로 제공하지 않는 능력을 문서에 약속하지 않는다.
- 기존의 실기기 하드 게이트, flow 우선, 소유 확인, 대조 이미지 게이트는 유지한다.

## Results

- 온라인 조사 결론: Appium으로 타깃 앱을 그대로 복제하는 단일 목적의 공개 스킬은 확인하지 못했다. 대신 Appium 공식 XCUITest 문서와 `ios-simulator-skill`, `mobile-mcp`의 공통 패턴을 차용했다: 접근성 트리 우선, semantic locator 입력, bundle ID 기반 lifecycle, active-app 확인, 단계별 screenshot/tree 기록, 사람 검토를 보완하는 visual diff, 재개 가능한 구조화된 flow.
- 구현: `device_wda.sh session`은 `appium:bundleId`를 필수로 받고, `screen`/`tap`/`type`/`swipe` 실행 전 `mobile: activeAppInfo`와 세션 capability를 대조한다. `type`은 accessibility id로 요소를 찾고 입력값 대신 label·길이만 flow에 기록한다.
- 구현: flow 이벤트에 UTC 시각을 추가하고, `device_flow.py`가 changed 전이의 도착 캡처·접근성 트리 누락을 `incomplete`로 판정한다. 중복 탭은 coverage 분모를 부풀리지 않는다. `device_compare.py`는 동일 크기 이미지의 mismatch/MAE를 advisory로 출력한다.
- 호환성: 공용 `copy` 스킬도 새 세션 계약을 사용하도록 문서를 동기화했다.
- 검증 통과: 관련 회귀 63건, `scripts/verify_spec_docs.py`, clone skill frontmatter 검사, `bash -n scripts/device_wda.sh`, `git diff --check`.
- 전체 검증: `python3 -m unittest discover -s tests`는 1097건 중 3건 실패했다. 모두 이번 변경 파일과 무관한 기존 `test_visual_contract.py`의 palette/dark-mode 판정 실패이며, clone 관련 회귀는 통과했다. 실기기는 연결되어 있지 않아 WDA 실기기 세션·실제 앱 전이 검증은 수행하지 못했다.

## 후속 수정 (2026-08-15, 2차 검토)
- `capture_gaps`의 복구 불가 dead-end 제거: 도착 캡처를 "해당 tap ~ 다음 tap 사이"에서만 인정하던 조건이, 한 번 놓친 캡처를 영구 `incomplete`로 만들었다(재방문·재캡처로도 못 지움 → `next`가 영원히 exit 1). 조건을 "tap 이후 아무 시점의 durable 캡처"로 완화 — 낡은 캡처가 새 전이를 만족시키지 못하는 속성(캡처가 tap보다 뒤여야 함)은 유지. `to="?"`(unresolved)도 같은 규칙으로 복구 가능해짐. 회귀 3건 추가.
- `cmd_stats`의 no-op 집계를 새 `changed()` 헬퍼로 통일(문자열 `"false"` 비교 잔재 제거).
- SKILL.md 가드 목록에 `swipe` 누락 보완.
- 검증: flow/wda/compare 38건 green, `verify_spec_docs.py` All checks passed.
- 실기기 검증 필요(미해결 리스크): `_session_target`이 `GET /session/<sid>`로 세션 caps를 읽는데 이 엔드포인트는 Appium 2에서 deprecated고 Appium 3에서 제거됐을 수 있다 — 그러면 모든 action의 `_assert_target`이 실패해 스킬 전체가 막힌다. 실기기 회차에서 최우선 확인.

## 동일 목적 스킬 온라인 조사 + 차용 반영 (2026-08-15, 3차)
- 조사 결론: 타깃 모바일 앱을 기기에서 탐험해 네이티브 UI로 재현하는 동일 목적 공개 스킬은 없음. 인접 3계열 — ① `ui-cloner`(kensleDev/dotfiles, 웹사이트 클론 스킬, 목적 최유사) ② `agent-device`(callstack, 기기 구동 스킬) ③ AI 앱 크롤러(ai-mobile-ui-crawler·LLM-Explorer·UI-KOBE, 목적=테스트 커버리지). ③은 차용보다 검증: 접근성 트리 우선·화면 해시 dedupe·JSONL 전이 기록·target-app 가드·step 상한 모두 기존 설계와 일치.
- 차용 반영(문서): SKILL Step 6에 ui-cloner의 차이 분류·우선순위 표(누락/구조 → 간격/타이포/색 → 광택, 상위 미해결 시 하위 금지)와 수렴 루프 종료 기준(상·중 차이 0 + 남은 차이는 선언된 재현 불가 항목뿐; 안 좁혀지는 차이는 재현 불가 항목으로 승격) 추가. `commands/clone.md` CRITICAL RULES #4에 종료 기준 한 줄 동기화.
- 차용 보류: Tailwind식 표준 스케일 스냅핑(철칙 1 "측정값 그대로"와 충돌), agent-device식 selector-first tap(중간 규모 코드 변경 — 다음 실기기 회차에서 12pt 버킷이 실제 문제를 일으키는지 본 뒤 결정).
- 검증: `verify_spec_docs.py` All checks passed, 두 문서 frontmatter YAML 파싱 OK. (문서 전용 diff — 런타임 테스트 해당 없음)
# Threads 타사 앱 clone 실기기 실행 및 스킬 보완 — 2026-08-15

## 목표

기기에 설치된 Threads(`com.burbn.barcelona`)를 `autobot-clone-app`의 실기기/Appium 경로로 탐험하고, 실제 실행에서 확인된 결함만 최소 수정으로 스킬·보조 스크립트에 반영한다.

## 수용 조건

- [x] Threads bundle ID로 WDA 세션이 실제 대상 앱에 바인딩된다.
- [x] 탐험 가능한 범위의 raw 캡처, flow, stats, map을 남기고 미탐험·로그인/권한/데이터 장벽을 숨기지 않는다.
- [x] 타사 앱 분기를 지켜 원문 로고·이름·카피를 재현 산출물에 고정하지 않는다.
- [x] 실제로 발견한 재현/탐험 결함에 회귀 테스트와 스킬 문서 보완을 추가한다.
- [x] 가능한 경우 측정·스펙·SwiftUI·원본 대조 이미지까지 생성하고, 불가능한 단계는 정확한 증거와 다음 조치를 기록한다.
- [x] 관련 테스트, 문서 검사, 셸 문법 검사, diff 검증을 수행한다.

## 체크리스트

- [x] 현재 clone SSOT·스크립트·테스트·과거 미해결 리스크 조사
- [x] 기기/Appium/DEVELOPMENT_TEAM/Threads 설치 preflight (기기 게이트 실패: 연결된 물리 iPhone 0대, Appium 서버 미기동)
- [x] clone 전용 Xcode workspace 생성과 CoreDevice 자동 복구 경로 추가
- [x] Threads 세션 생성 및 진입 화면 캡처
- [x] flow 우선 탐험, 안전 후보 탭, stats/map 생성
- [x] 도달 화면 측정 및 타사 앱 역기획/스펙 기록
- [x] 선택 화면 SwiftUI 생성 및 원본 대조 검증
- [x] 실행에서 확인된 결함 수정 + 회귀 테스트 (실기기 대신 오프라인 재현 fixture로 스크롤/swipe 공백 검증)
- [x] 관련 검증 실행
- [x] Results와 Working Notes 기록

## Results (2026-08-15)

- 실기기 실행은 하드 게이트에서 중지했다. `scripts/device_wda.sh device`는 `ERROR: no connected iPhone`을 반환했고, Appium은 `3.5.2`/xcuitest `11.17.7`이 설치되어 있지만 `127.0.0.1:4723` 서버가 없어 Threads의 WDA 세션·bundle ID 설치 여부·화면 캡처를 검증하지 못했다. `xcrun devicectl list devices`에서도 물리 기기는 `available (paired)` 또는 `unavailable`이었고 `connected` 물리 기기는 없었다.
- 보완: `device_wda.sh swipe`가 현재 화면을 기준으로 settle을 기다리고 `swipe` 이벤트를 flow에 기록한다. 변경된 swipe 뒤 캡처 누락은 `device_flow.py`에서 `incomplete`로 유지한다.
- 보완: 동일 `nodekey`의 모든 durable screen 캡처에서 후보를 합치고, `next`가 후보별 원본 XML을 출력한다. 스크롤 피드에서 새 후보가 첫 캡처만 읽는 기존 큐에서 사라지던 문제를 막았다.
- 검증: 관련 회귀 75건 green, `scripts/verify_spec_docs.py` All checks passed, `bash -n scripts/clone_workspace.sh scripts/device_wda.sh`, `git diff --check`. 최종 전체 `bash tests/run_tests.sh`는 1107건 중 3건 실패했으며 모두 기존 `tests/test_visual_contract.py` palette/dark-mode 판정이다. 실제 Threads 캡처·측정·SwiftUI·대조 이미지는 기기 연결 후 재개해야 한다.

## Working Notes

- 이번 환경에서 Threads 앱 이름/카피/로고를 산출물에 넣지 않았다. 타사 앱 분기는 기기 캡처를 시작할 때도 유지한다.
- `cmd_swipe` 회귀 fixture는 임시 복사한 `device_wda.sh`가 `_HERE/device_a11y.py`를 참조한다는 실행 계약을 드러냈으므로 보조 스크립트까지 fixture에 복사했다.
- Threads는 사용자 소유 앱이라는 정보가 없으므로 타사 앱 분기를 적용한다.
- 실제 기기 증거와 시뮬레이터 렌더/비교 증거는 별개로 기록한다.
- `tasks/lessons.md`에 이번 회차의 fixture 실패 모드와 방지 규칙을 기록했다.

## 후속 설계 — clone 전용 Xcode workspace + CoreDevice 복구 (2026-08-15)

- 결정: clone 시작 시 `.autobot/clone/project/CloneWorkspace.xcodeproj`를 기존 `autobot-ios-scaffold`로 idempotently 준비한다. 이후 `device_wda.sh device`가 이 프로젝트를 Xcode로 열고 연결을 최대 30초 재조회한다.
- 의도적 제한: workspace를 먼저 빌드·설치·실행하지 않는다. 관찰 전에 foreground 앱이 바뀌면 Threads bundle ID 바인딩과 원본 전이 증거가 오염될 수 있다.
- 성공 기준: 물리 기기가 `connected`로 바뀌면 기존 WDA bundle ID 게이트로 진행하고, 계속 `paired`/`unavailable`이면 자동 복구 성공으로 보고하지 않고 Devices and Simulators/USB/잠금/Developer Mode/Trust 조치를 안내한다.
- 오프라인 증거: workspace 생성 멱등성, Xcode project open 호출, open 이후 connected UDID 재조회까지 회귀로 고정했다.

## 재시도 결과 (2026-08-15, 정정 전 기록)

- `heewook의 iPhone`(`00008101-000D38542180001E`)은 `connected`로 복구되었고 clone workspace 생성 및 device gate를 통과했다.
- (이전 판정은 잘못됨) 기본 `devicectl device info apps` 목록은 developer 앱만 포함하므로 Threads가 빠졌다. `--include-all-apps --search Threads`로 같은 기기의 Threads와 `com.burbn.barcelona`를 확인했다.
- Threads가 있을 것으로 보이는 `iPhone 14 Pro`(`00008120-001869921E90201E`)는 Xcode 프로젝트 open 및 **Window > Devices and Simulators** 자동 open 뒤에도 30초간 `unavailable`이었다. CoreDevice 앱 조회도 error 4016으로 실패했다.
- 당시에는 잘못된 기기 판정으로 탐험·캡처를 시작하지 않았다. 이 결론과 iPhone 14 Pro 재개 조건은 아래 정정으로 대체한다.

## 대상 앱 목록 판정 정정 (2026-08-15)

- `heewook의 iPhone`(`00008101-000D38542180001E`)이 `connected`로 복구된 뒤, `xcrun devicectl device info processes`에서 Threads 실행 프로세스를 확인했다.
- `xcrun devicectl device info apps --device <udid> --include-all-apps --search Threads` 결과는 `Threads / com.burbn.barcelona / 442.0.0`이었다. 대상 앱은 Debug 앱이 아니어도 된다.
- `com.instagram.barcelona`는 이 기기의 정확한 bundle ID가 아니므로 폐기했다. 올바른 ID로 WDA를 재시도했지만 WDA runner 설치 단계에서 `0xe8008001` 코드 서명 검증 오류로 중지됐다. 기기는 `connected`, Developer Mode enabled였고 provisioning profile에도 UDID가 포함됐다. WDA 산출물의 `codesign --verify --deep --strict`가 `invalid Info.plist`였으며, WDA scheme post-action의 재서명에서 동일 표시명의 개발 인증서 2개가 모호하게 선택되는 정황을 확인했다. 생성된 WDA 앱을 SHA-1 인증서로 수동 재서명하면 `devicectl device install app`은 통과했지만 Appium preinstalled 경로는 RemoteXPC tunnel 부재로 기동되지 않았다.
- 스킬 보완: clone Step 1에 `--include-all-apps` 조회와 target UDID 고정 규칙을 추가했다.

## Results (2026-08-15 실기기 재시도 및 생성본 검증)

- `heewook의 iPhone`(`00008101-000D38542180001E`)이 `connected`, Developer Mode enabled 상태임을 확인했다. 같은 UDID에서 `xcrun devicectl device info apps --include-all-apps --search Threads`로 Threads `com.burbn.barcelona` (442.0.0)를 확인했고, Appium/WDA 세션을 실제 대상 bundle ID에 바인딩했다.
- WDA의 `0xe8008001`/`invalid Info.plist` 원인은 대상 앱의 Debug 여부가 아니라, 중복 개발 인증서 표시명과 서명 후 Runner.app을 변형하는 post-action 조합이었다. `scripts/device_wda.sh`가 WDA를 `.autobot/clone/wda`에 격리 복사하고 no-op post-action을 주입하도록 보완했으며, 회귀 테스트를 추가했다. 격리 복사본으로 새 WDA 세션과 대상 앱 foreground guard를 통과했다.
- raw 캡처 8개, flow map, stats(`6/59`, partial), 화면 측정 4개, 역기획·스펙 4개를 남겼다. Follow/모두 팔로우/차단 같은 계정 상태 변경과 검색어 입력은 실행하지 않았고, 미탐험 후보 53개는 산출물에 남아 있다.
- 타사 앱 분기로 선택한 추천 화면·안내 화면만 generic placeholder 카피·이미지로 재현했다. 생성 SwiftUI를 clone Xcode 프로젝트에 연결했고, `xcodebuild` 빌드(exit 0), 시뮬레이터 설치·실행, 원본/생성본 대조 이미지 2개를 확인했다. 대조 캡처는 12 mini 원본과 17 Pro 시뮬레이터가 달라 정량 mismatch는 advisory로 계산하지 않았고, 나란히 검토 가능한 증거로만 사용했다.
- 검증: `bash -n`(WDA/post-action), 관련 unittest 43건, `verify_spec_docs.py`, `git diff --check`, clone Xcode `xcodebuild` 통과. 전체 suite는 1108건 중 3건 실패했으며 모두 기존 `tests/test_visual_contract.py`의 palette/dark-mode 판정(`paletteMatch`, `paletteWarning`, monochrome dark render)이고 이번 변경과 무관하다.

## Working Notes (latest)

- WDA 격리 복사본은 관찰 대상 앱이 아니라 자동화 runner만 대상으로 한다. 전역 Appium 설치물을 수정하지 않는다.
- 생성 Xcode 프로젝트의 미사용 로컬 디자인 시스템 패키지는 이번 빌드에서 디스크 압박과 불필요한 모듈 그래프를 만들었으므로 clone 산출물에서 제외했다. 소스 화면은 패키지 없이 SwiftUI만으로 빌드된다.
- 실기기 탐험은 `6/59`로 완료가 아니다. 추가 안전 후보를 탐험하려면 기존 flow에서 재개하고, 계정 상태를 바꾸는 후보는 사용자 승인 없이는 실행하지 않는다.

## 연구용 타사 자산 분기 보완 (2026-08-15)

- [x] 타사 앱을 연구 전용과 외부 공유·배포용으로 분리
- [x] 사용자 승인만으로 기술적 추출 가능성을 과장하지 않고, 접근 가능한 파일·payload/export·공개 원본·화면 crop만 허용
- [x] 연구용 자산의 출처·획득 방법·원본 프레임을 `assets/manifest.json`에 기록하도록 스킬 계약 보완
- [x] 자산 미확보·배포용 분기는 자리표시자/대체 자산으로 유지하고 샌드박스 우회를 금지
- [x] `verify_spec_docs.py`, frontmatter YAML, diff 검증

# clone 속도·품질 전면 개선 — 2026-08-15

## 목표와 수용 조건

실기기 왕복과 잘못된 탭 후보를 줄이고, 관찰된 화면 상태·전이를 실제 clone 앱이 재생하며, 자산·측정·렌더 검증을 반복 가능한 파이프라인으로 만든다.

- [x] 키보드·정적 설명문을 탭 후보에서 제외하고 계정 상태 변경 동작을 자동 탭하지 않는다.
- [x] 반복 데이터 행을 행동 클래스로 묶되 원시 후보 커버리지와 행동 클래스 커버리지를 모두 보고한다.
- [x] coarse 화면 키와 interaction 상태 키를 분리해 검색 포커스·키보드·선택 상태를 잃지 않는다.
- [x] 한 명령이 탭·settle·도착 PNG/XML·flow 기록을 원자적으로 완료한다.
- [x] Appium 준비, 세션 재사용, 대상 bundle 캐시, WDA 호출 계측과 디스크 preflight를 제공한다.
- [x] 캡처 자산 crop·xcassets·provenance manifest와 병렬/캐시 후처리를 제공한다.
- [x] flow에서 관찰된 전이 상태 머신을 생성해 clone 화면 콜백과 연결할 수 있다.
- [x] 반복 렌더에서 컴파일 결과를 캐시하고 고정 sleep 대신 안정 프레임을 기다린다.
- [x] 저장소 SSOT와 설치된 clone 스킬의 drift를 탐지·동기화할 수 있다.
- [x] 관련 단위 테스트, 셸 문법, 문서 검사, diff 검사와 가능한 런타임 검증을 통과한다.

## 체크리스트

- [x] 후보·상태 그래프 구현 및 회귀 테스트
- [x] WDA 원자 step·세션/서버/metrics 구현 및 회귀 테스트
- [x] 자산·후처리 구현 및 회귀 테스트
- [x] flow codegen·렌더 캐시 구현 및 회귀 테스트
- [x] 스킬·command 문서 및 설치본 sync 계약 갱신
- [x] 통합 검증과 Results/Working Notes 기록

## Results

- 후보 품질: Threads 검색 상태의 실제 접근성 트리에서 정적 문구와 `KeyboardKey` trait를 제거했다. 현재 flow는 화면 3개, raw target 5/26, behavior class 5/16이며 상태 변경 후보 13개는 `withheld`로 남겼다.
- 실기기 경로: `heewook의 iPhone`을 clone workspace로 Xcode 자동 기동 후 약 6초 안에 다시 연결했고, iPhone 12 mini / iOS 26.5.2 profile과 Threads `com.burbn.barcelona`를 확인했다. Appium 자동 시작도 확인했으며, iOS 18+ RemoteXPC tunnel 부재와 2 GB 미만 디스크는 세션 전에 명시적으로 차단한다. 최종 doctor에서 디스크 3369 MB는 통과하고 RemoteXPC tunnel 하나만 blocker로 남았다.
- 속도: `step`이 탭·settle·최종 XML·PNG·flow를 한 번에 기록하고, 동일 세션 재사용과 HTTP metrics를 지원한다. 후처리는 raw pair 8개를 첫 실행에 8개 처리하고 두 번째 실행에는 8개 모두 cache hit했다.
- 품질: capture crop/중복 제거/xcassets/provenance, interaction state key, flow router 생성, simulator 자동 선택, 컴파일 cache, 안정 프레임 대기, 영역별 비교·mask·heatmap을 추가했다.
- 계약: 저장소 clone SSOT는 0.13.9이고 설치본은 0.13.8뿐이라 `clone_skill_sync.py check`가 의도대로 drift를 차단했다. 서로 다른 버전의 문서와 runtime을 자동 혼합하지 않는다.
- 검증: clone 통합 회귀 176건 통과. `verify_spec_docs.py`, Python compile, shell syntax, frontmatter YAML, `git diff --check`를 통과했다. 공간 복구 후 `bash tests/run_tests.sh` 전체 1180건도 통과했다.

## Working Notes

- CoreDevice `connected`만으로 Appium 실기기 자동화가 준비된 것은 아니다. iOS 18+에서는 별도 터미널에서 `sudo appium driver run xcuitest tunnel-creation -- --udid <udid>`를 계속 실행해야 한다.
- 첫 전체 suite 시도는 루트 여유 공간이 118 MB까지 내려가 임시 파일 생성 오류로 무효화됐다. `/private/tmp/autobot-wda-deriveddata*`와 `.autobot/clone/deriveddata`처럼 이 작업이 만든 재생성 가능한 WDA/clone 빌드 cache만 제거했고, 원본 캡처·flow·비교 이미지·소스는 보존했다. 최종 여유 공간은 3.3 GB이며 doctor의 2 GB gate를 통과했다.
- 설치본을 갱신하려면 0.13.9 플러그인 패키지를 설치/reload한 뒤 `clone_skill_sync.py check`를 다시 통과시킨다.

---

# RemoteXPC 터널 자동 준비 — 2026-08-15

## 목표와 수용 조건

`autobot-clone-app`의 실기기 WDA 세션이 iOS 18+ RemoteXPC 터널을 별도 수동 명령 없이 준비하고, 기존 터널은 재사용하며, 관리자 인증이 불가능한 환경에서는 멈추지 않고 정확한 복구 방법을 제시한다.

- [x] iOS 18+ 실기기이면서 해당 UDID 터널이 없을 때만 자동 시작한다.
- [x] 이미 등록된 터널과 동시 시작 중인 프로세스를 재사용하고 중복 생성하지 않는다.
- [x] 비대화식 환경에서 `sudo` 비밀번호를 기다리며 멈추지 않는다.
- [x] 시작 후 레지스트리에 대상 UDID가 나타난 것을 확인해야 WDA 세션으로 진행한다.
- [x] 자동 시작을 끄는 명시적 환경변수와 실패 시 실행 가능한 안내를 제공한다.
- [x] 회귀 테스트, 셸 문법, 문서 검사, 전체 테스트를 실행한다.

## 체크리스트

- [x] 기존 터널/Appium 수명주기와 테스트 fixture 조사
- [x] 터널 자동 시작·잠금·준비 대기 구현
- [x] 회귀 테스트와 clone 스킬 계약 동기화
- [x] 대상/전체 검증 실행
- [x] Results와 Working Notes 기록

## Results

- `doctor`와 `session`이 iOS 18+ 대상 UDID의 RemoteXPC registry 상태를 함께 확인한다. 터널이 없으면 clone Xcode 프로젝트를 먼저 `open -g -a Xcode`로 연 뒤, 캐시된 `sudo -n` 또는 macOS 관리자 인증창으로 Appium tunnel을 백그라운드 시작하고 대상 UDID가 실제 registry에 나타날 때까지 bounded poll한다.
- 기존 터널은 즉시 재사용하고, 동시 호출은 atomic lock으로 한 프로세스만 시작한다. owner 파일 기록 전의 짧은 구간도 활성 lock으로 취급해 중복 tunnel을 막는다. CI/비대화식 권한 실패는 멈추지 않고 `sudo -v` 재시도와 정확한 수동 fallback을 출력한다.
- clone/copy 스킬과 command 문서를 자동 준비 계약에 맞췄다. `CLONE_AUTO_START_TUNNEL=0`으로 자동 시작을 끌 수 있고, 로그는 `.autobot/clone/remotexpc-tunnel.log`에 남는다.
- 검증: `bash -n`, RemoteXPC/skill sync 회귀 44건, 동시 시작 테스트 20회 반복, `verify_spec_docs.py`, `git diff --check`가 통과했다. 전체 suite는 1,188건을 실행했고 최초 4건 실패 중 이번 동시성 실패는 수정 후 반복/대상 suite에서 통과했다. 나머지 3건은 변경하지 않은 `visual_contract.py`가 설치된 Pillow 11.3의 미지원 API를 호출하는 기존 호환성 실패로 단독 재현했다.

## Working Notes

- 현재 `_require_tunnel`은 OS/레지스트리 판정까지 수행하지만 터널이 없으면 별도 터미널 명령을 출력하고 종료한다.
- `sudo -n true`는 현재 `a password is required`이므로, 테스트/에이전트 비대화식 실행은 암호 프롬프트를 열지 않는 경로가 필요하다.
- 자동 시작 기본값은 활성화하되, 권한이 이미 캐시되었거나 제한된 sudo 정책이 준비된 경우에만 백그라운드 실행한다. 그렇지 않으면 한 번의 `sudo -v` 인증 후 같은 스킬 명령을 재실행하도록 안내한다.
- Xcode 프로젝트는 tunnel-creation 명령의 입력은 아니지만, clone 흐름에서는 workspace 준비와 CoreDevice 연결 안정화를 선행하기 위해 tunnel 요청 전에 연다. 프로젝트를 빌드하거나 실행할 필요는 없다.
- 저장소 스킬을 수정했으며 현재 세션에 이미 로드된 설치본에는 재설치/reload 전까지 반영되지 않는다.

---

# Autobot 0.13.10 패치 릴리스 — 2026-08-16

- [x] 변경 범위, 브랜치, 원격 및 최근 릴리스 커밋 규칙 확인
- [x] 플러그인·Python·lock 버전을 0.13.10으로 정렬하고 changelog 확정
- [x] 릴리스 메타데이터와 RemoteXPC 회귀 검증
- [x] 의도한 0.13.10 릴리스 파일만 커밋 대상으로 확정

---

# clone RemoteXPC background launch 수정 — 2026-08-16

## 목표와 수용 조건

실기기 연구용 Threads clone에서 재현된 macOS `nohup: can't detach from console` 실패를 제거해 관리자 인증 후 RemoteXPC tunnel이 실제 registry에 게시되게 한다.

- [x] 0.13.10 실기기 실패 로그와 성공한 최소 launch 차이를 재현한다.
- [x] `nohup` detach 동작에 의존하지 않는 최소 background launch로 수정한다.
- [x] 관리형 Appium 서버도 shell tool 종료 뒤 생존하도록 launchd 소유 프로세스로 시작한다.
- [x] 캐시 sudo와 GUI 관리자 인증 fixture를 포함한 회귀 테스트를 통과한다.
- [x] 실기기 `doctor`에서 대상 UDID tunnel readiness를 재검증한다.
- [ ] 관련/전체 검증 후 feature branch를 push하고 PR을 연다.

## Working Notes

- 관찰: `/usr/bin/nohup ... &`는 관리자 `do shell script` 경로에서 `can't detach from console`로 즉시 종료했다.
- 대조: 같은 완전 리다이렉트 background command에서 `nohup`만 제거하면 프로세스가 PID 1의 자식으로 유지되고 대상 UDID와 RSD 서비스 83개가 registry에 게시됐다.
- 추가 관찰: WDA session 생성은 성공했지만 명령 프로세스 종료 직후 관리형 Appium PID와 포트 4723이 사라져 다음 `screen`이 active-app guard에서 중지됐다.
- 추가 관찰: Threads 검색창은 요소 조회 직후 포커스/레이아웃이 바뀌며 첫 입력이 `stale element reference`로 거절됐다. 같은 accessibility id를 한 번만 재조회하는 복구 경로를 추가한다.
- 추가 관찰: `device_wda.sh`가 `state`/`from_state`/`to_state`를 기록하지만 `device_flow.py`는 공식 `statekey` 필드만 허용해, 실제 Threads 로그의 `stats`/`map`이 1행부터 거절됐다. 생산자를 공식 필드로 정렬하고 WDA→flow 통합 회귀를 추가한다.
- 재개 호환: 0.13.10이 이미 만든 세 underscored alias 로그는 reader가 canonical field로 정규화하되, 다른 비공식 alias와 alias/canonical 충돌은 계속 거절한다.
- 화면 정체성: Threads는 커스텀 top bar 제목을 `Header` trait으로 내보내 표준 NavigationBar 제목만 보던 node/state key가 메시지↔설정, 홈↔검색을 충돌시켰다. 셀 내부 Header는 제외하고 screen-level Header만 landmark로 포함한다.
- Threads 접근성 트리의 최상위 콘텐츠는 화면 전체 크기 AXCell로 감싸져 있다. 이를 목록 row로 취급하면 제목과 거의 모든 컨트롤이 데이터로 제거되므로, viewport의 90%×75% 이상인 cell은 구조 wrapper로 분류하고 실제 작은 row만 churn에서 제외한다.

## Results

- 구현: 관리자 shell의 RemoteXPC 시작은 BSD `nohup` detach에 의존하지 않는다. 관리형 Appium은 launchd job으로 명령 shell보다 오래 살고, `stop-server`가 job/PID/label을 함께 정리한다.
- 구현: semantic type은 Appium의 `stale element reference`에만 target을 재확인한 뒤 동일 accessibility id를 한 번 재조회한다. flow 생산자는 공식 `statekey` 필드를 쓰며, 0.13.10 alias 로그는 reader가 충돌 없이 정규화한다.
- 구현: full-screen AXCell wrapper와 custom Header를 구분해, 데이터 row churn을 흡수하면서 Threads의 홈·검색·메시지·설정을 서로 다른 node/state로 유지한다.
- 실기기: RemoteXPC registry에 대상 UDID와 RSD 서비스 83개 게시, `doctor` 전체 통과, launchd Appium(PPID 1) 생존, Threads 검색 입력/결과 캡처를 확인했다. `quit` 후 `stop-server`가 실제 PID 56563과 session/PID/label 상태를 모두 정리했다. 이후 tunnel 종료 뒤 새 관리자 인증 시도는 승인되지 않아 bounded timeout으로 끝났으며 성공으로 위조하지 않았다.
- 검증: clone/a11y 관련 142건, `verify_spec_docs.py`, `bash -n`, `uv lock --check`, `git diff --check` 통과. legacy bounded-start 회귀는 scheduling 여유 조정 후 3회 반복 통과했다.
- 전체 suite: 1,197건 중 5건 실패. 이번 범위의 scheduling 2건(`device_wda` fake child, `make_port_kill` listener)은 단독 재실행에서 통과했다. 남은 3건은 Pillow 11.3에 `Image.get_flattened_data()`가 없어 발생하는 기존 `test_visual_contract.py` 실패다.
---
# clone 타사 앱 체크 프로세스 제거 — 2026-08-16

## 목표와 수용 조건

Threads 복제나 실기기 조작은 수행하지 않고, `autobot-clone-app`이 실행 전에 대상 앱 소유권과 사용 범위를 질문하는 프로세스만 제거한다.

- [x] 소유권·연구용/배포용 확인 질문과 그 분기를 canonical 스킬에서 제거한다.
- [x] `commands/clone.md` 진입 계약도 같은 내용으로 동기화한다.
- [x] clone 산출물은 별도 질문 없이 `research-only`를 기본값으로 유지한다.
- [x] 자산 provenance와 샌드박스·암호화·서명 우회 금지는 유지한다.
- [x] 설치된 동일 버전 스킬까지 동기화하고 문서·회귀 검증을 통과한다.
- [x] Threads 앱 실행, 캡처, 탐험, 재현은 수행하지 않는다.

## 체크리스트

- [x] 현재 스킬·command·테스트의 체크 프로세스 의존 범위 확정
- [x] 최소 문서 수정과 회귀 테스트 추가
- [x] 설치본 동기화
- [x] 관련 테스트·문서 검사·diff 검사
- [x] Results와 Working Notes 기록

## Working Notes

- canonical SSOT는 `skills/autobot-clone-app/SKILL.md`, 진입 문서는 `commands/clone.md`다.
- 사용자 교정으로 이번 회차의 범위는 프로세스 제거뿐이며 clone 실행은 금지한다.
- `clone_skill_sync.py sync`는 설치된 `SKILL.md`만 갱신하므로, 설치된 0.13.10의 `commands/clone.md`는 canonical 파일과 직접 동일하게 맞춘 뒤 `cmp`로 검증했다.

## Results

- mandatory 소유권·사용 범위 질문, 본인/타사/배포용 분기 표, Step 0 분기 규칙을 제거했다.
- 별도 질문 없이 모든 clone 산출물을 `research-only`로 생성하고, 접근 가능한 자산은 provenance를 남기며 샌드박스·암호화·서명 경계를 우회하지 않는 계약은 유지했다.
- canonical `SKILL.md`와 `commands/clone.md`, 설치된 Autobot 0.13.10의 두 파일을 동기화했다. 독립 forward-test도 소유권 질문 없이 기술 preflight로 진입했다.
- 검증: clone 관련 19 tests, frontmatter 1 test, `verify_spec_docs.py`, canonical/설치본 skill validation, `clone_skill_sync.py check`, installed command `cmp`, 제거 문구 부재 검사, `git diff --check` 모두 통과했다.
- Threads 앱 실행·캡처·탐험·재현은 수행하지 않았다.
