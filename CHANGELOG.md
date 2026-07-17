# Changelog

이 파일은 Autobot 플러그인의 주요 변경을 기록한다. 형식은 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)을 따르고, 버전은 [Semantic Versioning](https://semver.org/)을 사용한다.

## [Unreleased]

전수 감사(일반 8렌즈 + 기획깊이 3렌즈, finding별 적대적 반증 검증 — 확정 56 / 기각 9, `tasks/weakness-audit-2026-07-17.md`) 후 9-워크스트림 일괄 수정 + codex 교차 검수(A/B/D 3영역 지적 30건 반영, 4건 근거 유지). 테스트 667 → 962 전부 green.

### Added — 기획 깊이 층 (소유자 목표: "화면 나열이 아닌, 유저를 끌어들이는 회사급 첫 버전")
- **시장 조사 입력**: orchestrator Phase 1 직전 market-brief self-step(mcp-appstore 유사앱/리뷰 → `.autobot/market-brief.json`), architect 에 Category Expectation Research 사다리(market-brief → WebSearch → model-knowledge 표기) + `## Market Context` 섹션. Gate 1→2 `market_context_present`(DEGRADED).
- **기능 구성 요건**: table-stakes ≥3 · 훅 P0 ≥1 · 리텐션 ≥1 · 인사이트 ≥1 을 architect 계약에 명문화, feature-spec 에 `role` 필드 신설. `### Hook & Retention` 섹션(Signature Layout 동형 무효/유효 자가점검) + `hook_retention_present` 게이트(DEGRADED).
- **기획 깊이 게이트**: `feature_spec_depth`(P0+P1 수·distinct screens·postcondition 종류·steps 하한 — DEGRADED 기본, quality-max hard; 단 "P0 1개 & steps ≤2" 원탭 퇴화만 기본 hard) + P2 접지·P1 pass-rate(70%)·다단계 여정 하한.
- **도메인 로직 깊이**: P0 도메인당 비-CRUD 파생 메서드 ≥1 계약(앵커링 삼중화) + `service_protocol_depth` 게이트(DEGRADED).
- **첫 실행 설계**: `firstRunPolicy: direct|primer` + 조건부 `## First-Run Experience` 섹션. delight P1 1개 필수(구 "P2=polish 스킵" 대체) + ui-builder 햅틱/모션 지침.
- **기획 검토 배선**: codex 아키텍처 리뷰에 planningViolations 축(경고-only), Phase 2.5 critique 에 매력도 4항목.
- **flow 검증 강화**: postcondition 이 존재 검사에서 상태 변화 검증으로 — navigated_to 신규성(entry 스냅샷 대비), artifact/setting 은 AXLabel/AXValue delta, unknown kind 관대 통과 폐지, delta 기준선을 flow-entry 로 통일(다단계 오탐 해소).

### Added — /autobot:screen 화면 집중 인터뷰 (독립 명령)
- **`commands/screen.md` + `autobot-screen-interview` 스킬 신설**: 화면 하나를 5라운드 인터뷰(존재 이유 → 콘텐츠 위계 → 인터랙션 → 상태 → 룩앤필, 혼합 방식)로 깊게 기획. 라운드마다 `docs/screens/<slug>.md` 에 즉시 기록해 세션이 끊겨도 재개 가능(status: interviewing → confirmed → built).
- **SSOT 문서 산출**: SOUL.md(제품 정체성) + AGENTS.md(에이전트 규칙 정본) + CLAUDE.md(@AGENTS.md 참조) 생성·비파괴 병합. 템플릿은 `references/templates.md`.
- **presentation-only SwiftUI 뷰**: 로직(네트워크·저장·ViewModel) 금지, mock 주입 + 콜백 파라미터 + R4 상태 전부 `#Preview`. 컴파일 검증은 advisory (hard fail 금지 철칙 준수).
- Autobot 파이프라인과 무관하게 아무 앱 프로젝트에서 동작. `.autobot/architecture.md` 가 있으면 컨텍스트로 활용해 중복 질문 제거.
- **결과 표시 필수화 — Xcode 프리뷰 캔버스**: "Xcode 에서 확인하세요"라는 말로 끝내기 금지 — 프로젝트가 없으면 최소 스캐폴드(project.yml + xcodegen) 생성, advisory 빌드 후 `xed` 로 뷰 파일을 열어 살아있는 `#Preview` 캔버스가 결과 화면이 되게 한다. (1차 구현이던 NSHostingView PNG 스냅샷 표시는 사용자 결정으로 폐기 — 이미지가 아니라 실제 프리뷰. 다독다독 독푸딩 2회로 검증)

### Fixed — 배포 체인 무인 완주
- **[HIGH] 메타데이터·스크린샷 업로드/심사 제출이 creds 를 못 읽던 결함**: 3개 스크립트가 release_env.sh 를 source 하지 않아 doctor 통과 후 실행만 실패 — upload.sh 패턴으로 통일 + grep 계약 테스트.
- redundant binary 를 성공으로 오분류하던 재시도: attempt-1 redundant = `build_number_conflict`(exit 6, 비재시도 halted — ASC 의 옛 바이너리로 심사 직행 차단), attempt≥2 만 `already_uploaded`.
- submit 폴링이 미지 상태값에서 pipefail 로 조기 사망 → awk 상태 추출로 교체. app_review_controller 에 attempts ≥3 halted + 비재시도 reason(`auth_failed`/`build_number_conflict` 포함) 즉시 종결.
- 심사 verdict 회수: `check-review-status.sh` 신설(API Key, 온디맨드) → `.autobot/review-verdict.json` → `/autobot:feedback` 이 REJECTED 를 학습 테마로 흡수(source=app_review).
- 시크릿: .p8 PEM argv 노출 제거(heredoc), FASTLANE_SESSION lines 출력 마스킹, JWT 는 mode-600 curl config 로.

### Fixed — 엔진 상태머신 복원력
- fail-phase 경로 circuit breaker 트립 시 회고 데드락(alwaysRun 예외 + handle_breaker_trip 대칭 배선), 상태 전이 TOCTOU(락 안 재검증), build.lock lease heartbeat(renew), init-state 락 누수, checkpoint restore 저널링(+cross-build 격리·원자 기록), operator_override 감사(state `operatorOverrides` + run-summary 컬럼 + 채점 강등), schemaVersion 자동 승격.
- preflight-ship 이 상류 게이트(1→2 THIN-SPEC 등)의 미해소 DEGRADED 를 못 보던 갭 → 전 게이트 degraded 집계 후 출하 거부.

### Fixed — 게이트 세탁 차단
- peer/axiom/visual-judge PASS 자기보고: 아티팩트 실파일·JSON·메타데이터 일치 검증(+visual-judge 는 buildId 스코프) — `--metadata` 한 줄 세탁 불가.
- no-stub 게이트 denylist 확장(Mock/Fake/InMemory/Dummy/Preview) + 주석·문자열 리터럴 제거 스캔(공용 `strip_swift_noncode`), 배선 검사는 인스턴스화 패턴 요구, sandbox_clean 완전성(스펙 에이전트 집합 대조), DS 컴포넌트 5종 존재 게이트(hard) + 사용 게이트(DEGRADED), kill-switch env 를 DEGRADED 로, Gate 6→7 deploy-status 집계 스키마 인정(+round-trip 계약 테스트), ux-designer 의 죽은 `Theme.*`/`Color.accentColor` 템플릿 정정 + `no_legacy_theme_refs` 게이트.
- codex-architecture-review.sh 의 모델 출력 Python 보간 인젝션(Critical) 제거 — argv+json.load, 파싱 실패는 감사 가능한 skipped.

### Fixed — 학습 루프 무결성
- 외부 피드백 write-only 3단선 배선(적용 프로토콜·grade 재키잉·quarantine 전파), rule 교체 시 approved 리셋, grade_build 멱등화(+self-mint 규칙은 score 0 + provenance), 리뷰 인용문 프롬프트 렌더 제거(인젝션 반쪽 방어 해소), 글로벌 스토어 캡(500), 재폴링 frequency 인플레 차단.

### Fixed — CI·드리프트·관측성
- **[HIGH] CI 가 첫 스텝에서 항상 실패해 GitHub 에서 검증이 강제된 적 없던 구조** 해소(중복 스텝 제거) + ci.yml 인라인 명령 회귀 테스트. e2e-verify paths 의존 4개 보강.
- verify_spec_docs 확장: AUTOBOT_* env 45종 드리프트, phase-learning 매핑, 게이트 구조(빈 checks=error), retry/phase-count error 승격, docs/ 스캔 편입. smoke-e2e crash-on-launch 통과 버그 + 실패 아티팩트 삭제 trap 수정. run-summary stale 배지(소비 시점 재생성) + unknown 상태 가드. detect-plugins.sh 삭제, 죽은 인증 경로(APP_SPECIFIC_PASSWORD) 제거, spec dead 이벤트 `circuit_breaker_triggered` 정리, phase-gates.md Gate 5→6 를 spec 15개 체크와 동기화.

### Tests
- fake-fastlane PATH 스텁 실행 테스트(deliver 3종 끝까지 실행 + 셸 확장 증명), 게이트 체크 전수 스모크(registry 동적 순회), Swift 주석/문자열 스크러버 단위 테스트 등 — 667 → 962.

## [0.12.2] — 2026-07-12

### Fixed — fastlane deliver 인증이 항상 실패 (API 키 JSON 에 `key` 누락)
- `fastlane deliver` 를 쓰는 3개 스크립트(`upload-metadata.sh`, `upload-screenshots.sh`, `submit-for-review.sh`)가 `--api_key_path` 에 넘길 JSON 을 `{"key_id", "issuer_id", "key_filepath": <.p8 경로>}` 로 생성했다. fastlane 의 `Spaceship::ConnectAPI::Token.from_json_file` 는 `key_filepath` 를 인식하지 않고 **PEM 콘텐츠를 담은 `key` 필드를 강제**하므로, 로그인 단계에서 `App Store Connect API key JSON is missing field(s): key` 로 죽었다 — 즉 메타데이터 업로드·스크린샷 업로드·심사 제출이 **ASC 에 닿기도 전에** 전부 차단돼 있었다 (모든 API-Key 인증 deliver 경로의 공유 결함).
- `.p8` 파일 내용을 `ASC_API_KEY_CONTENT="$(cat "$ASC_API_KEY_PATH")"` 로 읽어 `key` 필드에 임베드하도록 3개 스크립트 동일 수정. 실제 `.p8` + 설치된 fastlane 2.237.0 `Token.from_json_file` 로 토큰 로드·PEM 파싱 성공 확인.
- 회귀 `tests/test_fastlane_api_key_json.py` — 3개 스크립트가 `key_filepath` 로 되돌아가지 않고 `key` 콘텐츠를 emit 하는지 소스 계약 검증.
- ⚠️ 이 수정은 fastlane **인증(토큰 구성)** 만 푼다. 업로드 자체는 앱이 ASC 에 등록돼 있어야 하고(등록은 spaceauth 세션 경로 — [0.12.0] 참조), 세션 만료 시 `asc_session_expired` 로 다음 단계에서 별도로 막힐 수 있다.

## [0.12.1] — 2026-07-12

### Fixed — 테스터 초대가 config 경로에서 조용히 0명 (invite.sh)
- `config.sh get-or testerEmails` 는 배열을 `json.dumps` 해 `["a@x.com", "b@x.com"]` 문자열로 반환하는데, deployer 가 이를 그대로 `--emails` 로 넘기고 `invite.sh` 는 콤마 split 만 해서 `["a@x.com` / `"b@x.com"]` 토큰이 이메일 검증에 걸려 exit 1 — 즉 `/autobot:setup` 으로 테스터를 넣는 **정식 경로가 초대 0명으로 깨져** 있었다 (env `TESTER_EMAIL` 단수 fallback 만 동작). `invite.sh` 파서가 콤마 문자열과 JSON 배열을 **둘 다** 수용하도록 수정 (모든 호출자가 지나는 공유 지점). 회귀 `tests/test_invite_emails.py`(6).

## [0.12.0] — 2026-07-12

전체 감사(7렌즈 병렬 + 적대적 검증, finding 확정 22/반증 0) 후 "인간 도움 없이 최고의 앱" 목표 대비 6개 workstream 일괄 수정. 테스트 533→597 전부 green.

### Fixed — 무인 앱 등록 경로 (존재한 적 없는 플래그)
- **`fastlane produce` 는 API Key 인증을 지원한 적이 없다** — 앱 레코드 생성은 Apple 비공개(iris) API 뿐이고 공개 ASC API 에는 생성 endpoint 자체가 없음. `register-app.sh` 의 `--api_key_path` 는 허구 플래그라 신규 등록이 항상 `invalid option` 으로 죽고 있었다 (과거 성공은 사람이 2FA 로그인한 spaceship 세션의 잔광 + 에이전트 임기응변).
- 세션 기반 인증으로 전환: Apple ID 해석(`--apple-id` → `FASTLANE_USER` → `APPLE_ID` → `config.json:appleId`) + 세션 프리플라이트(쿠키/`FASTLANE_SESSION`, 부재 시 exit 2 + `fastlane spaceauth` 안내). reason `asc_session_expired` 신설, `api_key_insufficient_role` → `asc_permission_denied` 개명 (deployer/testflight/app-review 문서 연동). `FASTLANE_HIDE_GITHUB_ISSUES=1` 로 이슈 제목의 분류기 오염 차단.
- 불가피 인간 개입에 "ASC 웹 세션 갱신(~30일 2FA 1회)" 을 autonomy-touchpoints §IRREDUCIBLE 4번으로 명문화. setup 에 §3.8(appleId 저장 + 세션 점검) 추가.
- 테스트 격리 버그 수정: `~/.autobot/.env` 존재 시 테스트가 실 자격증명으로 fastlane 을 실호출하던 것을 `AUTOBOT_CONFIG_DIR` 샌드박스로 차단.

### Fixed — 에이전트-게이트 계약 정합 (WS1)
- architect 에 Bash 미부여로 Gate 1→2 필수 산출(swiftc typecheck, learning_applied)이 기록 불가하던 critical 해소. Design Direction 하위 헤딩 5종 명시 + 데드 템플릿 경로 정정 + context_pack 배선.
- 레퍼런스의 실존하지 않는 Liquid Glass API 정정 (`.buttonStyle(.glass)`, `.glassEffect(.regular.tint(...))` — iOS 26.5 SDK 실컴파일로 good/bad 쌍 검증).
- agent-dispatch ui-builder 템플릿의 composition seam 충돌 제거, ux-designer 팬텀 MCP grant 정리, ui-builder try?-삼킴 예제 교체.
- `verify_spec_docs.py` generic 드리프트 검사 신설: 52개 md 전수에서 이벤트명/pipeline.sh 서브커맨드/스크립트 경로를 spec·코드와 자동 대조.

### Fixed — 엔진 상태머신 복원력 (WS2)
- circuit breaker 가 "consecutive" 선언과 달리 retryCount 를 영구 누적 — 성공 시 리셋 복원 (정상 범위의 분산 재시도만으로 무인 빌드가 죽던 결함).
- 크래시 잔류 in_progress phase reclaim, retry 소진 phase 의 운영자 재진입 (`--allow-terminal-restart` operator override), spec 에 phase 추가 시 구 build-state 브릭 → pending backfill.
- learning_applied 이벤트 검증을 state mutation 앞으로 (비원자성 제거).

### Fixed — 학습 저장소 무결성 (WS3)
- 테스트 스위트가 실 글로벌 `~/.config/autobot/learnings.json` 을 오염시키던 것 차단 (XDG 격리 + `AUTOBOT_NO_GLOBAL_PUBLISH` 이중 방어) + 오염 데이터 일회성 정리 (테스트 픽스처 9건·agent-name item 8건·폭증 frequency 882→1, 백업 `.bak.20260712`).
- `_merge_patterns` 가 리스트형 패턴을 publish 마다 클로버하던 것 → 텍스트 매칭 병합, frequency max(재합산 금지) 멱등화.
- SessionStart 훅이 플러그인 캐시에 학습을 쓰던 경로 → `CLAUDE_PROJECT_DIR` 로 정정. 첫 빌드 learningsConsumed 게이트 모순 해소 (`sources:[]` 기록).

### Fixed — App Review 무인 체인 (WS4)
- `/autobot:meta` 로 메타데이터를 만들면 rating config 가 영영 안 만들어져 `/autobot:app-review` 무인 완주가 깨지던 스킵 게이트 이원화 + meta.md 가 rating config 를 직접 생성 (파리티 테스트로 드리프트 차단).
- commands/app-review.md 를 SKILL.md 위임 구조로 재작성 (Phase 열거 드리프트 2번째 재발 → 클래스 자체 봉쇄). meta 에 `--upload/--no-upload` 비대화형 플래그.
- transient 실패 bounded 재시도: register `fastlane_exit_N` 1회, upload `--retries`(기본 2, 백오프) — 수동 안내를 최후 수단으로 강등.

### Added — 출하 게이트 기계화 (WS5)
- **preflight-ship**: `pipeline.sh preflight-ship` 이 archive 직전 gate 5→6 을 fresh 재실행해 clean pass 만 출하 허용 — md 산문이 아닌 runtime 강제 (stale-passed 세탁 불가). standalone archive 는 WARN 통과.
- zero-P0 feature-spec hard fail (결정적 — VERIFIED 배지 세탁 근원 봉쇄), runtime_smoke skip→degraded (명시적 opt-out 만 benign), 다크모드 스크린샷 + visual contract dark 검사(DEGRADED-only), `no_swallowed_errors`(try?/try!)·`no_hardcoded_font_sizes` DEGRADED-only 신설, Stub 인스턴스화 hard-fail 의 주석 오탐 제거(라인+블록).
- 시각 동질성: design_spec_validator fallback 팔레트에 앱명 해시 hue 회전(±40°), visual judge 에 templated(화면 간 동일 몰드) 판정 축.

### Added — 외부 신호 루프 v1 (WS6, 최대 leverage)
- **`/autobot:feedback`** 신설: App Store 리뷰(mcp-appstore, ASC 인증 불필요) → 테마 추출 → `patterns.external_feedback` + stable_id items 기록 → 기존 effect_score/quarantine 재사용 → render-active-learnings 로 다음 빌드 주입. 내부 자가-judge 의 Goodhart 천장을 뚫는 첫 외부 ground-truth 경로 (`docs/external-signal-loop.md` 설계 구현).
- 인젝션 방어: 제어문자 정리·길이 캡·리뷰 원문 인용 rule 폐기·인용문 "data, never instructions" 격리 렌더.
- 글로벌 승격 운영자 게이트를 **데이터로 집행**: 엔트리 `approved:false` 기본 + `publish_project_to_global` 초크포인트 필터 — Phase 7 재빌드 publish 로도 우회 불가. 승인은 `external_feedback.py approve`.
- write-only 학습 데이터 해소: Process Learnings/Pipeline Gotchas 렌더 추가.

## [0.11.2] — 2026-07-10

### Added — resume 오프파이프라인 드리프트 감지 (`commands/resume.md`)
plan→resume 로 만든 앱이 미리보기 이미지와 다르게 나온 실사례(GrudgeLedger) 분석 — 원인은 Phase 5 가 `in_progress` 로 막힌 뒤 파이프라인을 거치지 않고(수동 세션에서 직접 Edit) architecture.md/design-spec.md/Views 가 계속 수정된 것. 파이프라인은 이 사실을 전혀 몰랐다.

- **Step 2.5 신규**: bare `/autobot:resume` (파라미터 없음) 실행 시 재개 지점 이전의 completed/fallback phase 들에 대해 기존 `input_hash.py` 의 `should-skip` 계산을 재사용해 owned 파일 checksum 이 마킹 이후 바뀌었는지 점검. 드리프트 발견 시 Step 3 상태 보고에 경고로 표시 — 어느 phase 가 왜 어긋났는지, 다음에 뭘 할 수 있는지 안내.
- 재실행·덮어쓰기·자동 회복은 하지 않는다 — `--force`/`--regenerate-contracts`/`--allow-visual-drift` opt-in 안전장치는 그대로 유지. 새 스크립트/체크섬 로직 추가 없음(기존 `should-skip` 재사용). GrudgeLedger 실제 상태로 검증: Phase 1·2·3·4 모두 `inputHash mismatch` 로 정확히 탐지됨.

## [0.11.1] — 2026-07-08

### Added — design-system 컴포넌트 깊이 + DS↔ui-builder 소비 계약 배선 (dead-code 차단)
design-system(opus) 컴포넌트를 깊게 만들되 **소비 계약을 함께 배선**한다. 발견: ui-builder 는 DS *토큰*만 import 하고 *컴포넌트*는 자체 `Views/Components/` 에 재구현했다 — 깊은 컴포넌트를 만들어도 아무도 import 안 하면 invisible dead-code(빌드 시간만↑). 그래서 design-system 만 강화는 theater. 게이트 무손상(`.md` 2 파일).

- **Pre-read 에 Signature Layout + Component Patterns 추가** (`design-system.md`): 컴포넌트가 이 앱 고유 스타일을 구현하도록 — A2 의 Signature Layout 강화를 design-system 이 실제로 읽게 연결(load-bearing — 없으면 깊은 컴포넌트도 순수 cross-app 동질성).
- **Components 고정 4 개 → app-agnostic primitive 5 개** (+`ListRow`): 상태 변형(pressed/disabled) + Component Patterns 스타일 반영으로 *within-app 깊이*. 5 개 외 확장 금지·"반드시 컴파일" 명시 — opus 가 컴파일 표면을 늘려 build hard-fail→circuit breaker 를 트립하는 걸 방지(bound).
- **Boundary rule 양쪽 1 줄** (`design-system.md` + `ui-builder.md`): DS = app-agnostic primitive(ui-builder 가 *반드시* import) / ui-builder `Views/Components/` = 화면 고유 composition. 5 개 타입 *이름·시그니처 고정*(generic 금지는 *스타일*에만 — 이름을 앱별로 바꾸면 import desync 로 빌드 깨짐).
- **정직한 트레이드(상승)**: 이전엔 컴포넌트 미참조라 누락 = benign dead-code(빌드 OK). 이제 ui-builder 가 정확한 이름으로 import 하므로 produce/consume *desync = 컴파일 에러 = Phase 5 hard-fail → circuit breaker*. net 은 옳다(visible > invisible, dead-code 제거)지만 `/mvp` 의 build-break 표면을 *올린다* — 그래서 이름 고정·"반드시 컴파일"·5 개 bound 로 desync 벡터를 좁혔다.
- **A3 의 정직한 기여**: cross-app 다양성 레버가 아니다(그건 A2 가 composition 으로 소유) — within-app styling 깊이 + 상태 변형뿐. multi-agent 이름 계약이라 *실제 빌드가 5 개를 desync 없이 produce+consume 할 때까지 미검증*(테스트는 프롬프트를 안 덮음).

### Added — 시각 동질성 상류 차단: design-system opus + architect Signature Layout 품질 강화
생성 앱 AI slop(모든 앱이 닮아 보이는 *시각 동질성*)을 **게이트가 아니라 intent 단계 생성 품질**에서 줄인다. 미적 품질은 이진 게이트로 측정 불가(Goodhart) — 게이트는 동질성을 *감지*만 할 뿐 다양성을 *생성*하지 못한다. 그래서 다양성은 상류에서 주입한다. 게이트/circuit breaker 무손상(프롬프트 `.md` 3파일만 변경 → 자율 `/mvp` 경로·hard-fail 철칙 정합).

- **design-system 에이전트 sonnet→opus** (`agents/design-system.md`): 디자인 토큰(Color/Typography/Spacing/Radius)·공유 컴포넌트의 *재료*를 만드는 단계가 한 티어 낮아 다양성/깊이가 제한됐다(architect/ui-builder/quality-engineer 는 이미 opus). 빌드당 1회 호출이라 비용 증가는 제한적.
- **architect Signature Layout 품질 강화** (`agents/architect.md`, `skills/.../architecture-template.md`): heading 존재만 보는 Gate 1→2 는 제네릭 한 줄로 통과 가능 → 상류 프롬프트로 품질을 끌어올린다. ❌무효/✅유효 4행 대조표 + "앱 이름·도메인 명사를 가려도 어느 앱인지 식별되나" 자가 판별 추가, 위 예시(여행앱)와 *다른 도메인*(피트니스 트래커)으로 대조해 원칙이 도메인을 넘어 성립함을 보임(한 도메인 복붙은 앵커를 키워 역효과라 의도적 분리), 화면 차별화를 "primary+2순위"에서 "주요 화면 전체"로 확장.
- **정직한 효과 구분**: `/plan` 은 프롬프트+Phase 2.5 critique 2단 방어. `/mvp` 자율 경로는 critique 가 `manual:true` 라 안 돌아 self-check(프롬프트 텍스트)가 유일한 품질 장치 — 새 backstop 이 아니라 "더 날카로운 프롬프트 + self-check nudge" 한 겹. 게이트 없이 줄 수 있는 정직한 최대치.
- 코드 변경 0(`.md` 3파일). 테스트 영향 없음 — 효과는 다음 빌드 `architecture.md` 의 Signature Layout 품질로 드러난다.

### Added — External Signal Loop 설계 스파이크 (`docs/external-signal-loop.md`, 미구현)
최고 leverage(외부 ground-truth)를 명문화한 **설계 문서 — 코드 0**. 출시된 앱 + (일부) ASC 인증 환경에서 구현한다. 조사 결과: 리뷰/평점 회수는 `mcp-appstore` public 스크래핑(**인증 불필요**, bundle ID 만), 비공개 메트릭(crash/retention)만 ASC Key(이미 `setup` §3.7 이 받음 — setup 수정 불필요). 핵심 미해결 = *글로벌* learnings 저장소 아키텍처(현재 프로젝트별이라 재빌드 드물어 leverage 낮음). 자가-judge Goodhart 천장을 뚫는 유일한 외부 닻 — 우선순위 최상위지만 느린 베팅.

### Added — quality 모드 결정적 게이트 2종 (2차 품질 보고서 채택분)
2차 외부 품질 보고서의 갭 중 **결정적**(grep/파일 검사 — 거짓양성 없음)이라 quality-max 에서 DEGRADED 로 올려도 circuit breaker 를 안 태우는 둘만 채택. 비결정적 판정(visual judge·critique)은 quality 에서도 DEGRADED 천장 유지(차단 게이트로 안 올림 — 결정적/비결정적 승격 선).

- **#4 P0 logic acceptance 테스트 완전성** (`gate_checks/functional.py` `_completeness_subcheck`): 기본은 비차단 warning, `qualityMax` 면 named 테스트 없는 P0 logic acceptance → **DEGRADED**(출하 차단, hard fail 아님).
- **#6 backend 배포 준비** (`gate_checks/build.py` `check_backend_deploy_readiness`, Gate 5→6 신규): `backend_required` 앱의 `Release.xcconfig` 가 `$(PRODUCTION_HOST)` placeholder/localhost 면 `qualityMax` 에서 **DEGRADED** — 출하 후 auth/AI 호출이 죽는 것(AI 앱 치명)을 막는다. 기본 모드는 benign(capability_coverage 가 이미 localhost caveat 보고).
- `commands/mvp.md` quality mode 섹션에 두 게이트 + 결정적/비결정적 승격 선 명시.
- 신규 테스트 7종(#4 completeness 3 + #6 backend 4) on/off 양경로. 전체 **486 OK 회귀 0**.
- (보류: visual/P0-logic 의 *비결정* 강화, unsupported 자동 구현, 외부 신호 루프 — 마지막은 실 출시 앱 + ASC 인증이 필요해 이 환경에서 검증 불가.)

## [0.11.0] — 2026-06-02

### Added — #4 flow DSL: text_input/swipe/long_press + P1 hard mode (quality-max)
flow acceptance 의 step `action` 을 `tap` 1종 → `tap`/`text_input`/`swipe`/`long_press` 로 확장. AXe 서브커맨드 시그니처는 `axe-cli.com/docs/command-reference` **1차 출처** 기반(`type '<text>'` positional · `swipe --start-x/--start-y/--end-x/--end-y` · `touch -x -y --down --up --delay`). anchor-based 시스템이라 swipe/long_press 는 anchor 의 describe-ui frame 중심 좌표로 변환한다.

- **flow_runner step 분기** (`scripts/flow_runner.py`): text_input(anchor tap→`axe type`), swipe(frame center→direction 좌표→`axe swipe`), long_press(frame center→`axe touch --down --up --delay`). 좌표 변환(`_anchor_frame`/`_frame_center`/`_swipe_endpoint`)은 순수 함수라 단위 테스트로 닫힘.
- **architect** (`agents/architect.md`): feature-spec step action 제약(tap only) 완화 — `text_input`(step.text)·`swipe`(step.direction)·`long_press`(step.duration) 명시.
- **P1 hard mode** (`scripts/gate_checks/functional.py`): qualityMax 면 P1 flow 실패가 warning 이 아니라 **DEGRADED**(출하 차단). 기본 모드는 기존 warning 유지. hard fail 아님(circuit breaker 회피).
- 신규 테스트: flow_dsl 좌표 10종 + P1 hard mode 1종. 전체 **479 OK 회귀 0**.
- **검증 한계 (정직)**: AXe 명령 *시그니처*는 1차 문서 기반이나, *실행*(실제 swipe/type/touch 가 시뮬레이터에서 동작하는지)은 AXe 미설치 + 시뮬레이터 부재로 **이 환경에서 미검증**. 좌표 math 만 단위로 닫혔다.

### Added — 품질 보고서 "타당한 부분": `--quality=max` opt-in 모드 + waiver 범위 축소 + unsupported 명시 제외
외부 품질 보고서 7개 중 *타당*으로 판정된 것만 구현. **보류**(자율성·circuit breaker 충돌 또는 비용): 자동 critique 재실행·자동 UI 재작업 루프·unsupported 자동 구현·context7 필수 조회. 원칙: 기본 자율 경로(`/mvp`)는 동작 무변, 엄격함은 **opt-in**; hard fail 금지(retryCount→breaker→자율 정지 회피) → **DEGRADED**(출하만 차단).

- **`--quality=max` opt-in 모드** (`spec.allowedFlags` + `commands/mvp.md` + `autobot-orchestrator`): `qualityMax` 플래그(`allowVisualDrift` 와 동일 set-flag 패턴, orchestrator 가 Phase 0 후 세팅). 이 모드에서만 게이트가 엄격해지고, 플래그 없으면 모든 게이트가 기존 자율 동작 유지.
- **#2 peer/axiom** (`gate_checks/review.py`): qualityMax 면 peer review·Axiom critical audit 의 미가용 skip 을 PASS 가 아니라 **DEGRADED**(degraded=qmax). (이미 있던 anti-laundering — `peerReviewAvailable=true` 면 runtime-failure allowlist 만 통과 — 은 그대로.)
- **#6 design fallback** (`gate_checks/design.py`): qualityMax 면 Stitch fallback 이어도 최소 1 개 mockup PNG 요구(0 개면 DEGRADED).
- **#5 unsupported 명시 제외** (`agents/architect.md` + `scripts/capability_coverage.py`): architect 가 미지원 카테고리(StoreKit/Push/WidgetKit/CloudKit 등)를 `## Out of Scope` 에 명시하면 capability_coverage 가 "의도적 제외(excluded by design)"와 "silent gap(요구됐으나 누락)"을 구별해 보고. 자동 *구현*은 하지 않음(보류 — 스코프 폭발).
- **#3 visual waiver buildId-scoped** (`gate_checks/build.py` + `commands/resume.md`): `--allow-visual-drift` 가 영속 boolean → 현재 **buildId 에 바인딩**. `visual_judge` 는 `allowVisualDrift == buildId` 일 때만 면제 → `/autobot:testflight` 동일빌드 재검증은 유지되지만(`build.py` 영속 사유 해소), 새 빌드는 자동 만료해 stale waiver 가 이후 빌드를 조용히 세탁하지 못한다.
- 신규 테스트: `test_quality_max_mode`(8, on/off 양경로) + `test_capability_out_of_scope`(5) + visual_judge stale-waiver 만료(1). 전체 **468 OK 회귀 0**. (보류 항목 + #4 flow DSL 은 미구현 — flow DSL 은 실기기 검증이 필요한 후속 슬라이스.)

### Added — 시각 동질성 깨기: Signature Layout + critique 동질성 축 + ui-builder opus
근본 진단: Layout Personality 가 **4종 폐쇄 분류**(`architecture-template.md`)고 ui-builder 가 그에 묶인 **고정 코드 스니펫**(`ui-builder.md`)을 적용 → 여행/레시피/뉴스 앱이 모두 content-forward 면 동일 `LazyVStack` 카드 피드. + 보이는 에이전트(ux-designer/design-system/ui-builder/data-engineer) 전부 `model: sonnet`. "전문가적 = 고유함"의 반대(AI 슬롭).

설계 원칙(미적 품질은 #2 같은 결정적 게이트로 측정 불가 → 동질성은 코드 *전* intent 단계에서 잡는다; Phase 5 충실도에서 잡으면 Goodhart — 제네릭을 충실히 구현 = 통과):
- **Signature Layout 1급 출력** (`architecture-template.md`, `agents/architect.md`): architect 가 `## Design Direction` 안에 `### Signature Layout`(hero element·정보 위계·density·화면 간 차별화)을 emit. 4종 Layout Personality 는 *출발 힌트*로 강등. 추상어("modern/clean") 금지, 모든 화면 동일 `List`/`LazyVStack` 금지.
- **ui-builder 가 Signature 우선** (`agents/ui-builder.md`): 4패턴 스니펫은 변형의 출발점으로만. **트랩 회피**: safe-area 4규칙(과거 재발 2회)을 "레이아웃 *모양* 은 자유화하되 *안전 스캐폴딩* 은 불변"으로 명시 강조 — `no_tabbar_safearea_smells` 가 막던 버그 재오픈 방지. **모델 `sonnet`→`opus`**(앱 시각을 가장 많이 결정하는 최대 볼륨 에이전트; Signature 확장과 *짝일 때만* 의미).
- **Phase 2.5 critique 동질성 축** (`autobot-plan-preview/SKILL.md`): 디자인 축에 "레이아웃 동질성/templated(HIGH)" 추가 — Signature Layout 이 실제 PNG 에 구현됐는지, primary 와 2순위 화면이 시각적으로 구별되는지 점검. (기존 "generic=색 정체성"과 별개인 *레이아웃/구성* 정체성 축.) **단 Phase 2.5 는 `manual: true` — 자율 `/mvp` 에선 skip 되고 `/autobot:plan` 으로 명시 검토할 때만 돈다. Gate 2.5→3 은 preview HTML *존재*만 검사하므로 이 축은 사람이 보는 advisory(codegen 차단 안 함) — `/plan` 검토 품질을 높이는 것이지 자율 빌드를 막지 않는다.**
- **Gate 1→2 강제** (`gate_checks/setup.py`): `check_design_direction_complete` 가 `### Signature Layout` heading 을 grep — 다른 섹션이 다 있어도 Signature 누락이면 FAIL(프롬프트 지시가 unenforced 로 썩는 것 방지).
- **정직한 검증 한계 (Goodhart 인정)**: 자율 `/mvp` 빌드의 동질성 *기계 강제*는 위 heading **존재** grep 하나뿐이고, 그조차 `### Signature Layout` + 제네릭 한 줄로 통과 가능하다 (heading 존재 ≠ signature *품질*). 실제 고유성은 architect 가 좋은 Signature 를 쓰고 opus ui-builder 가 충실히 구현하는 데 달렸으며 — 이는 A/B·사람 판단이지 게이트가 증명하지 못한다. 게이트/테스트가 증명하는 건 (a) Signature heading emit 강제 (b) critique 축이 `/plan` 에 존재 (c) safe-area 불변식 생존뿐.
- `tests/test_signature_layout_gate.py` 2종(signature 누락 시 FAIL / 완전 시 PASS). 전체 슈트 **454 OK**.

### Added — 첫인상 시딩: `seedPolicy` 로 빌드된 앱이 빈 껍데기로 열리지 않게
근본 진단: data-engineer 의 `SampleData.swift` 는 **Preview/test 전용**이고 ui-builder 의 `ServiceStubs` 도 Preview mock — **런타임 first-launch seed 경로가 어느 에이전트 프롬프트에도 없었다.** 그래서 콘텐츠/대시보드형 앱조차 TestFlight 첫 실행 시 빈 화면(잘해야 EmptyState)으로 열렸다(미완성으로 읽힘). 반면 `autobot-app-review/SKILL.md` 는 "Autobot scaffolds include seed data" 라고 *가정* → 의도와 구현의 drift(unenforced 가정의 부패).

- **architect 가 `seedPolicy` 결정** (`agents/architect.md`, architecture.json 스키마): `"seeded"`(콘텐츠/대시보드/소셜/갤러리 — 빈 첫 화면이 고장으로 읽힘) vs `"empty"`(todo/저널/노트 — 빈 시작이 본질, EmptyState 가 정답). 애매하면 `"empty"`. 시드는 `app-intent.primaryScreenTitle` 모델을 반드시 채우고, seeded 앱 feature-spec postcondition 은 절대-개수 단언 금지(상대값 `count_increased` 만 — 시드 베이스라인과 충돌 방지).
- **data-engineer 런타임 seed factory** (`agents/data-engineer.md`): `seedPolicy=="seeded"` 일 때 `SampleData.seedIfNeeded(_:)` 작성. **factory 패턴**(매 호출 새 `@Model` 인스턴스 — Preview 의 `static let` 인스턴스를 production `ModelContext` 에 insert 하면 SwiftData 크래시) + **versioned seed-once 플래그**(`autobot.seeded.v1` — emptiness 기반 금지: 사용자 삭제분 부활 + `value_persisted_after_relaunch` 와 충돌) + `@Relationship` 그래프 + 도메인 현실적 데이터(`"Sample"`/placeholder 금지).
- **quality-engineer wiring** (`agents/quality-engineer.md`, `wiring-patterns.md`): `ModelContainer` 생성 직후 `SampleData.seedIfNeeded(container.mainContext)` 호출(SwiftUI `App` 은 `@MainActor` 라 직접 호출 가능). `"empty"`/미지정이면 호출 안 함.
- **Gate 5→6 `first_launch_seeded`** (`scripts/gate_checks/build.py` + `gate_runner.py` + `spec/pipeline.json`): `seedPolicy=="seeded"` 인데 진입점에 `seedIfNeeded()` 호출이 없으면 FAIL. `"empty"`/legacy 는 skip. 프롬프트만 고치면 다음 빌드가 실제로 시드하는지 *증명할 수 없어* app-review:233 처럼 unenforced 가정이 되는 것을 코드로 막는다. (`empty` 앱은 `visual_contract.py:281` 이 fill 요구 없을 때 occupancy 를 informational 로만 보므로 기존 screen-fill 게이트도 부당히 막지 않음 — 확인됨.)
- **app-review seed 안내 정합** (`autobot-app-review/SKILL.md`): `seedPolicy` 를 읽어 seeded=직접 캡처 / empty=캡처 전 primary flow 로 항목 생성 / legacy=as-is.
- `tests/test_first_launch_seeded.py` 8종(seeded 호출 有/無, empty, legacy, 파일 부재, garbled JSON, 다른 App 파일의 seam, registry 등록). 전체 슈트 **451 OK**(443→451, 회귀 0).

### Changed
- **내부 전용 스킬 11종을 사용자 슬래시 목록에서 숨김** (`user-invocable: false`) — 오케스트레이터·에이전트가 Skill 도구로만 호출하는 순수 내부 스킬에 frontmatter 한 줄 추가 → 사용자 `/autobot:` 자동완성·`/help` 에서 제외(모델 호출은 유지). 사용자 진입점은 commands 7개로 충분. 숨김: orchestrator·ios-scaffold·integration-build·axiom-bridge·peer-review-bridge·archive-build·upload-build·register-app·invite-testers·ux-design·plan-preview. 노출 유지(손수 부를 여지): build-report·retrospective·generate-metadata·upload-metadata·app-icon·setup·app-review.
- **CI GitHub Actions Node 20 → Node 24** — `actions/checkout@v4`→`@v6`, `actions/setup-python@v5`→`@v6`, `actions/upload-artifact@v4`→`@v5`(node24 범프, 기능 비파괴). 3개 워크플로(ci/e2e-verify/smoke-e2e) 전부. 2026-06-16 GitHub 의 Node 20 강제 종료 전 선제 대응. (직전 0.10.0 CI 런의 deprecation 경고 해소.)

## [0.10.0] — 2026-06-01

### Changed — `/plan` 스토리보드 품질: preview 가 *순서 없는 그리드 + 텍스트 덤프* → *번호 매긴 화면-흐름 보드*
근본 진단: `build_preview.py` 가 architect 가 이미 emit 하는 구조화 산출물(`architecture.json`, design-spec.md 의 `## Screen Designs`·상태 섹션)을 **하나도 안 읽고** architecture.md 산문을 regex 로 긁어 흐름을 재구성했다. 그 결과 화면이 순서 없이 나열되고, nav 는 `<pre>` 텍스트 덤프였으며, critique 가 판정해야 할 하단 safe-area 를 preview 자신이 잘라 숨겼다.

- **화면 PNG crop 제거** (`scripts/build_preview.py`): `.iphone-png` 가 `object-fit: cover` + `object-position: top` → `contain` + letterbox. 하단 home-indicator/탭바 safe-area(critique 계약이 HIGH 로 판정하라고 *명시한* 바로 그 영역)가 더 이상 잘리지 않는다.
- **번호 매긴 화면-흐름 스토리보드**: `architecture.json` 의 `rootScreens`/`featureModules` + Screens 표 `Tab` 열로 화면을 진입→탭그룹 순서로 정렬, **1..N 번호**(①②③) 부여, lane 별 flow 다이어그램 렌더. 원본 Navigation Structure 는 `<details>` 로 보존. 화면 목록·flow 노드·갤러리 카드가 같은 번호를 공유.
- **상태 & 인터랙션 표면화**: design-spec.md 의 `## Empty, Loading, Error States` + `## Interaction Feel` 를 preview 에 노출(기존엔 색·타이포 토큰만 추출, 가장 풍부한 UX 콘텐츠가 안 보였음).
- **권위 있는 화면↔PNG 매칭**: design-spec.md `## Screen Designs` 표(`Screen | Design File`)를 1순위로 사용하고 stem 휴리스틱은 fallback. Stitch 가 화면명과 다른 파일명을 써도 안 깨진다. PNG 없는 화면은 placeholder 카드로 표시(번호 정합 + 미생성 화면 가시화).
- **critique 화면 딥링크** (`skills/autobot-plan-preview/SKILL.md`): critique 항목 계약에 `화면: N` 필드 추가 → `→ 화면 N` 칩으로 렌더되어 해당 갤러리 카드(`#screen-N`)로 점프(`:target` 하이라이트). 앱 전반 항목은 `—`. 산문 critique 를 화면별 액션으로 전환 — 사용자가 "어느 화면의 어디"를 눈대중하지 않는다.
- `tests/test_build_preview.py` — crop·정렬·번호·flow·상태·권위매핑·딥링크 앵커·마커 보존·graceful fallback·FATAL 14종. (의도적 범위 밖: Stitch 자동 재생성 루프 — Phase 2.5 read-only non-goal + Stitch 신뢰성, 재생성은 기존 `/autobot:resume 2 --force` 사용자 경로 유지. vision-judge pre-code — 빌드된 앱 대상 Phase 5 게이트라 Phase 2.5 엔 부적용.)

### Fixed — CI 가 모든 푸시에서 빨강이었다 (단위 슈트가 Xcode/시뮬레이터에 hard-coupling)
`ci.yml` 은 "Fast, no Xcode required" 라며 `ubuntu-latest` 에서 단위 슈트를 돌리는데, 공통 fixture(`conftest.IsolatedProjectCase.setUp`)가 `advance-phase --phase 0` 를 실행하고 Gate 0 의 `environment_ready`(`gate_checks/setup.py`)가 `xcrun simctl` / `xcode-select` 를 **live probe 로 hard-fail** 했다. 시뮬레이터가 없는 Ubuntu 에선 11개 fixture 기반 테스트 파일이 setUp 에서 전부 깨져 **0.7.2 이후 ~5릴리스 내내 CI 가 빨강**이었다(회귀 슈트가 사실상 CI 에서 검증되지 않음). 맥(Xcode 보유)에선 초록이라 드러나지 않았다.

- **Gate 0 가 기존 disable 플래그를 존중** (`scripts/gate_checks/setup.py`): `AUTOBOT_DISABLE_SIMULATOR` / `AUTOBOT_DISABLE_XCODEBUILD` 가 설정되면 해당 하드웨어 probe 를 **degraded-skip**(hard-fail 아님)으로 처리 — 이미 `sim_runtime.py` / `xcodebuild_runner.py` 가 쓰던 관례를 Gate 0 에도 적용. **프로덕션(플래그 미설정)은 live fail-fast probe 그대로 유지.**
- **fixture 분리** (`tests/conftest.py`): `_scoped_env` 가 두 플래그를 모든 subprocess 에 주입 → Gate 0 이 degrade-skip → 슈트가 mac/Linux 무관 **hermetic**, 무-Xcode CI 에서 초록. (다른 하드웨어 의존 테스트는 이미 전부 mock 이라 무영향.)
- `tests/test_environment_gate_ci.py` — 플래그 없을 때 hard-fail(=probe 가 진짜), 있을 때 degraded-skip, conftest 가 플래그 주입을 잠금. **무-Xcode 시뮬레이션(xcrun·xcodebuild·simctl 가림)에서 전체 슈트 443 OK 검증** (수정 전이면 ~51 실패).

### Fixed — 버전/문서 드리프트
- `pyproject.toml` 가 `0.7.1` 로 멈춰 `plugin.json`(0.9.0)과 어긋나 있던 것을 릴리스 버전과 동기화 — 이번 릴리스로 둘 다 `0.10.0`.
- `README.md` 의 stale `# 185 tests` 제거 — 이전 사이클에 `ci.yml` 에선 지웠으나 README 에 남아 있던 같은 문자열. ci.yml 과 동일하게 숫자를 빼 drift 를 영구 제거.

## [0.9.0] — 2026-05-31

### Added — 품질 스파인: 레이아웃/충실도 요구를 *캡처·차단·반복*한다
지금까지 ~15개 게이트는 거의 전부 *내부 정합성*(파일 존재·형식·build-vs-spec)만 봤고, "사용자가 요구한 대로 보이는가 / 화면을 채우는가"를 검사 가능한 단언으로 담는 곳이 입력·계약·판정 어디에도 없었다. 그 결과 사용자가 "화면을 꽉 채우는"을 명시했는데도 화면의 13%만 차지하는 빌드가 **모든 게이트 초록**으로 출하됐다(visual_judge 는 letterbox 를 *처방한* 자기-저작 design-spec 에 "일치"로 합격). 이 릴리스는 그 구멍을 닫는다.

- **공간/비주얼 postcondition 문법** (`scripts/intent_spec.py`): `POSTCONDITION_KINDS` 에 `occupies_screen_fraction`(`params:{min,axis}`) + `matches_visual_reference` 추가. CRUD 6종만으로는 표현 불가능해 P2 stub 으로 증발하던 레이아웃/충실도 요구가 이제 1급 acceptance 로 산다. `layout_intent_signal()`(KR+EN: 꽉/가득/전체화면/풀스크린/그대로/픽셀/fill/full-screen/edge-to-edge) + `assess_idea_layout_capture()`.
- **Gate 1→2 intake 캡처 게이트** (`idea_layout_requirements_captured`, `gate_checks/capability.py`): 사용자 verbatim 아이디어에 화면-점유/풀스크린/픽셀충실 절이 있으면 feature-spec 이 공간 postcondition 으로 그것을 인코딩해야 한다 — 누락 시 **코드 작성 전에** fail. 결함을 50개 파일이 생기기 전 출처에서 잡는다. (요구가 없으면 benign-pass — 풀스크린 안 시킨 앱엔 무관.)
- **결정적 화면-fill floor** (`scripts/visual_contract.py`): 렌더 스크린샷의 content bounding-box 축별 span(밀도 아님 — 어두운 풀스크린 앱 오탐 방지)을 측정. fill 요구가 있는데 span < min 이면 **HARD-FAIL**(letterboxed window). 결정적이라 비결정적 visual_judge 와 달리 출하를 막아도 정당하다. fill 요구 없는 앱은 informational 만.
- **품질 반복 루프** (`policies.qualityRefineLoop` + `autobot-integration-build` Step 9b/9e): visual_judge 가 이제 **사용자 원문을 1순위 oracle** 로 절(clause)별 met/unmet 판정(자기-저작 design-spec 자기-인증 제거). occupancy fail / 명시적 사용자-절 위반은 build-fix 루프로 라우팅돼 레이아웃을 고치고 재렌더(maxAttempts=2). 소진 시 정직하게 UNVERIFIED.
- **architect 가이드** (`agents/architect.md`): fill/충실도 아이디어 절은 P0 `occupies_screen_fraction` acceptance 로 강제 인코딩 + architecture/design-spec 이 요구를 부정하는 레이아웃(floor 정수배+letterbox 같은)을 적지 말 것 — fit-to-screen 전략 명시.
- `tests/test_screen_fill_gate.py` — layout 신호(KR+EN)·intake 캡처·occupancy 게이트(letterbox hard-fail / 풀스크린 pass / 미요구 무영향) 9종. 실제 13%-fill 산출물에 대해 hard-fail 검증.

### Changed
- **배지 정직성** (`scripts/run_summary.py`): DEGRADED/UNVERIFIED 사유를 "axe 부재" 하드코딩이 아니라 gate 5→6 의 *실제 비-초록 체크*에서 도출(`_gate56_findings`). occupancy hard-fail 은 이제 배지를 **UNVERIFIED**(품질 결함)로 떨어뜨려 "도구만 깔면 됨(DEGRADED)"으로 위장되지 않는다 — "검증 못함"과 "검증했는데 나쁨"을 분리.

## [0.8.0] — 2026-05-31

### Added
- **전역 ASC 자격증명 — set-once via `/autobot:setup`.** ASC API Key 3종(`ASC_API_KEY_ID`/`ISSUER_ID`/`KEY_PATH`)을 매 프로젝트 `.env` 에 다시 넣어야 했던 마찰 제거. 이제 `/autobot:setup` 이 전역 `~/.autobot/.env`(권한 600)에 한 번 기록하면 모든 프로젝트의 deploy(register/upload/invite, `/autobot:testflight`, `/autobot:app-review`)가 읽는다. 시크릿 경계(autobot-setup/SKILL.md — 시크릿은 `.env`, 식별자는 `config.json`, 절대 합치지 않음)는 유지: `.env` 를 프로젝트-로컬에서 전역으로 올릴 뿐 `config.json` 에 시크릿을 넣지 않는다(key_id/issuer_id 는 "공유 가능" framing 을 깨므로 config 에 부적합).
  - `skills/autobot-setup/scripts/config.sh` — `env-path` / `set-env <KEY> <VALUE>` / `get-env <KEY>`. 전역 `.env` 쓰기의 SSOT. `KEY='value'`(no `export`, single-quote 이스케이프) upsert + chmod 600. 이 포맷이라 `set -a` source 와 load-learnings 의 `^KEY=` 탐지 둘 다 호환.
  - deploy 스크립트(register-app.sh / upload.sh / invite.sh)가 상단에서 `.env` 를 **이미 설정된 var 는 덮지 않고** 로드 — precedence **inherited env > 프로젝트 ./.env > 전역 ~/.autobot/.env**. 에이전트 컨텍스트 무관(각 스크립트 self-source). 명시적 export 가 항상 이김 → 테스트가 hermetic.
  - `commands/setup.md` §3.7 (ASC creds 대화형 입력 → `config.sh set-env`), `commands/testflight.md` Step 0c / `commands/app-review.md` — 전역→프로젝트 `.env` 로드 후 검사, 누락 시 `/autobot:setup` 안내.
  - `scripts/load-learnings.sh` — SessionStart `asc_configured` 배지가 `~/.autobot/.env` 도 탐지(프로젝트 → ~/.autobot/.env → legacy ~/.config/autobot/.env).
  - `skills/autobot-setup/SKILL.md` — config.json + .env 두 파일의 역할·경계·set-once 동작 문서화. `AUTOBOT_ENV_FILE` override 추가.
  - `tests/test_global_env_secrets.py` — config.sh set-env/get-env round-trip·escape·upsert·600·grep 호환·invalid 거부 + deploy precedence(global/env>global/project>global) 12종.
- **디자인 의도 게이트 (vision judge) — 빌드된 앱 ↔ 디자인 충실도 검증 (Phase 5 / Gate 5→6).** 기존 `check_visual_contract` 의 deltaE 색-매치는 informational-only 라, 디자인을 무시한 빌드(예: design-spec 은 커스텀 coral 인데 앱은 system-blue 로 렌더)도 `✅ VERIFIED` 로 통과했다(검증된 약점 #2). 이제 Phase 5 의 quality-engineer 가 **빌드된 앱의 실제 스크린샷을 디자인 의도(design-spec + Stitch 목업)와 멀티모달로 비교**해 충실도 verdict 를 기록하고, 새 게이트 체크 `visual_judge` 가 이를 읽어 강제한다. Phase 2.5 plan-preview 가 *목업*을 비평하는 것과 달리 *빌드 산출물*을 의도와 비교한다.
  - `scripts/gate_checks/build.py` `check_visual_judge` — `phases.5.metadata.visualJudge` verdict 를 게이트로 매핑. **DEGRADED-only, hard-fail 안 함**: Gate 5→6 은 `soft=false` 라 hard-fail 시 Phase 5 가 `failed`+retryCount++ 되어 글로벌 circuit breaker 를 태우고 자율 /mvp 빌드를 멈춘다 — 비결정적·미보정 judge 의 false-positive 가 "질문 없이 끝까지"를 깨선 안 되므로 `verdict=fail` → DEGRADED(`skipped+degraded`). 차단은 *출하 경로*에서: DEGRADED → `functionalVerification` DEGRADED → `/autobot:testflight`·`/autobot:app-review` 의 anti-laundering(`check_functional_verification_passed`)이 업로드 거부. `pass` → green.
  - **anti-laundering**: verdict 없음/garbled 일 때, 런타임 스크린샷이 디스크에 있으면(=충실도 검증이 가능했음) → DEGRADED (검증 안 한 빌드를 VERIFIED 로 세탁 금지, `functional_flows_pass`/`peer_review_acceptable` 의 "검증 가능했는데 metadata 없으면 거부" 선례 미러). 스크린샷이 없으면(sim 부재) → benign-skip(green). `allowVisualDrift` 면제는 fail·anti-laundering 양쪽 모두에 적용.
  - escape-hatch `--allow-visual-drift` (`/autobot:resume`) — `fail` verdict 를 green 으로 강등(운영자가 드리프트 수용·출하). 영속 top-level 플래그 `allowVisualDrift`(`spec.policies.allowedFlags` 추가, `set-flag` 재사용, `flag_changed` 로 감사)로 저장 — testflight 의 플래그 없는 Gate 5→6 신선 재실행이 존중하도록(freeze-contracts 의 one-shot 과 의도적 차이).
  - `spec/pipeline.json` — gate 5→6 checks 에 `visual_judge` 추가, `logEvents.visual_judge_verdict` 선언, `allowedFlags` 에 `allowVisualDrift`.
  - `skills/autobot-integration-build/SKILL.md` Step 9 (Visual Fidelity Judge) — 스크린샷 확보(`sim_runtime`)→멀티모달 충실도 판정(보수적: 애매하면 pass)→`.autobot/artifacts/visual-judge.json` + 최종 `advance-phase --metadata visualJudge` + `visual_judge_verdict` 이벤트. Step 7/8(axiom/peer-review) 과 동일한 "에이전트 기록 → 결정적 게이트가 읽음" 패턴.
  - `commands/resume.md` Step 0.5 — `--allow-visual-drift` 파싱 + set-flag.
  - `scripts/run_summary.py` — `visualJudge` 를 quality signals 에 노출(완료 보고에서 DEGRADED 가시화).
  - `tests/test_visual_judge_gate.py` — verdict→게이트 매핑 매트릭스(no-verdict/garbled→skip, pass→green, fail→DEGRADED-not-hardfail, fail+override→green) 10종.
- **계약 동결 (frozen-by-default) — `/autobot:resume 1` 의 비결정적 계약 drift 차단.** Phase 1(architect)은 타입 계약(`Models/*.swift` + `ServiceProtocols.swift`)을 만들고 Phase 4 코드가 그 심볼명에 의존한다. architect 출력은 비결정적이라, downstream 코드가 이미 있는 상태에서 `/autobot:resume 1`(또는 `--force`, 또는 hash 미저장 구 빌드)이 architect 를 재실행하면 필드명이 바뀌어 조용히 컴파일이 깨지고 snapshot 까지 덮어써 되돌릴 수 없었다. 이제 resume 는 **계약을 기본 동결**: snapshot 이 있고 downstream 코드가 존재하면 architect 를 재실행하지 않고 snapshot 을 복원해 계약을 보존한다. 새 계약이 필요하면 `--regenerate-contracts` 로 명시 opt-in (Phase 4 가 새 계약에 맞춰 재생성하도록 forward pass 로 cascade). `input_hash` 의 "입력 불변 시 skip" 과 직교하는 보호 — architect 가 실제로 재실행될 상황에서만 동작.
  - `scripts/contract_freeze.py` — `decide`/`apply`. `frozen = snapshot 존재 ∧ downstream .swift 존재 ∧ ¬regenerate`. downstream 디렉토리는 `spec.fileOwnership` 의 Phase-4 agent writes 에서 도출(SSOT, backend/·Assets 는 .swift 없어 자동 제외). 동결 시 `snapshot-contracts.sh restore` 위임 + 검증된 `contracts_frozen` 로그 이벤트. 복원 실패 시 silent regenerate 금지 — `action: error` 로 호출자 halt 유도.
  - `spec/pipeline.json` `logEvents` 에 `contracts_frozen` (required: phase, detail) 추가.
  - `scripts/pipeline.sh` `freeze-contracts decide|apply --phase 1 [--regenerate]` passthrough.
  - `commands/resume.md` Phase 1 재개 를 freeze-aware 로 교체 + `--regenerate-contracts` 인자 파싱.
  - `tests/test_contract_freeze.py` — decide 결정 매트릭스(snapshot×downstream×regenerate) + apply 복원/로그 + pipeline.sh passthrough.

### Fixed
- **ux-designer 가 Stitch 를 항상 npx CLI fallback 으로 실행하던 버그 (Phase 2 / `/autobot:plan`·`/autobot:mvp`).** `agents/ux-designer.md` 본문은 `mcp__stitch__*` MCP 도구를 primary 경로로, `npx @_davideast/stitch-mcp ...` 를 "MCP 사용 불가 시 fallback" 으로 지시했지만, frontmatter `tools:` 가 `Read, Write, Bash, Glob, Grep` 로 제한돼 **MCP 도구를 한 번도 호출할 수 없었다** — Stitch MCP 서버가 세션에 연결돼 있어도 에이전트는 매번 Bash→npx 로 강제됐다. Claude Code 는 서브에이전트의 MCP 접근을 `tools:` 에 `mcp__<server>__<tool>` 전체 이름으로 나열했을 때만 부여한다(와일드카드 미지원). ux-designer 가 (스킬 포함) 사용하는 Stitch 도구 9종을 `tools:` 에 명시 추가. 최소권한 유지를 위해 `tools:` 생략(전체 상속) 대신 명시 부여 선택.
  - 회귀 가드 `tests/test_agent_mcp_tool_grants.py` — `tools:` 를 선언한 에이전트는 본문이 참조하는 모든 `mcp__…` 도구를 grant 해야 한다(일반 규칙). 수정 전 상태에서 정확히 5개 미부여 도구를 검출함을 확인.
  - (관찰만, 미변경) `scripts/detect-plugins.sh` 의 Stitch 감지는 `npx … doctor` 기반 — 라이브 MCP 레지스트리를 셸이 못 보므로 caller 가 `STITCH_AVAILABLE` 을 선주입하는 게 정설. 실행 경로 버그는 `tools:` grant 로 해소되며, `autobot-ux-design/SKILL.md` 의 "방법 1: `mcp__stitch__*` 도구 존재 확인(권장)" 감지와 이제 정합.

## [0.7.2] — 2026-05-30

`/autobot:plan` 명령 + Phase 2.5 (Plan Preview HTML) 신설. mvp 자율 흐름의 취약점 — architect/ux-designer 의 첫 패스 결과가 사람 검토 없이 Phase 3–5 의 코드로 곧장 변환되는 것 — 을 막는 게이트. 새 명령은 Phase 0–2 까지만 빌드하고 `designs/preview/index.html` (self-contained 모바일 갤러리 + 기획 요약 + nav flow + token swatch + LLM critique) 을 브라우저로 자동 표면화. OK 면 `/autobot:resume` 으로 Phase 3 진입.

### Added
- `/autobot:plan <아이디어>` 명령 — Phase 0–2 자율 + Phase 2.5 명시 진입 + STOP 의 7-step enumeration (dispatcher 의 manual-skip 을 prose 가 아닌 명령 entry 에서 명시 override).
- `autobot-plan-preview` 스킬 — Phase 2.5 self 단계. `build-preview.sh` 호출 + 멀티모달 critique 작성 (축 1 기획 정합성, 축 2 디자인/HIG; safe area 침범 1순위) + HTML placeholder 주입 + 브라우저 자동 열기.
- `scripts/build_preview.py` + `build-preview.sh` — 외부 CDN 0, base64 PNG, iPhone 16 Pro aspect 393/852 깨끗한 베젤 frame 의 self-contained HTML 빌더.
- `spec/pipeline.json` 의 phase `"2.5"` + gate `"2.5->3"` (`manual: true` → mvp 자율 흐름은 자동 skip, `/autobot:plan` 만 명시 트리거).

### Changed
- `skills/autobot-ux-design/SKILL.md` — Stitch prompt 의 Layout Requirements 를 픽셀 단위 3-zone 표 (status 0–47pt / content 47–818pt / home indicator 818–852pt) + 시각 chrome 강제 ("9:41" 시계, 신호/wifi/배터리, home indicator pill) 로 교체. Stitch image generator 가 chrome 자체를 그려야 safe area 가 자연스럽게 보호된다. 침범 시 Phase 2.5 critique HIGH severity → `/autobot:resume 2 --force` 재생성 안내.
- `skills/autobot-orchestrator/SKILL.md` — dispatcher 결정 로직에 `manual: true` phase 자동 skip + 전용 명령 트리거 명시 (phase summary 표 auto-rendered, 2.5 행 포함).
- `skills/autobot-orchestrator/references/phase-gates.md` — Gate 2.5→3 추가 (file_exists 만 검사; critique 품질 강제는 스킬 contract).
- `commands/resume.md` — phase 2.5 행 추가, Phase 3 의 "2.5 pending 무방" 명시.

### Fixed
- `scripts/event_log.py` — `int(phase)` 가 `"2.5"` 에서 ValueError. 정수 phase id 케이스는 back-compat 으로 int 저장, 비정수 id 는 str 저장으로 lenient.
- `scripts/render_pipeline_docs.py` — `int(phase_id)` 정렬을 `float()` 로 일반화. fractional phase id 안전.

## [0.7.1] — 2026-05-29

`/autobot:mvp` 진입점 문서(`commands/mvp.md`)의 SSOT drift·문서 간 불일치 5건 교정. 동작 변화 없음 — 진입점 문서가 실제 스크립트·스킬·sibling 커맨드와 어긋나 사용자를 오인시키던 지점을, 다중 렌즈 감사 + 적대적 검증(라운드별 ground-truth 대조)으로 찾아 고치고, 이어 같은 문서를 정보·가드레일 100% 보존 하에 가독성 중심으로 재구성했다(형태만 변경).

### Fixed
- **env_snapshot 동작 오기재** — Phase 0 설명이 env_snapshot 이 "Xcode/SDK/simulator UDID/ASC 자격증명"을 캡처한다고 했으나, `env_snapshot.py` 는 선택된 simulator UDID(+axe 가용성)만 기록한다(Xcode/SDK 는 staleness 회피로 의도적 비캐싱, ASC 는 비대상). 문서가 자신의 "충돌 시 spec/script 우선" 원칙과 모순되던 drift.
- **coverage JSON 경로 base 불일치** — Capability Coverage 안내가 `scope.*`(coverage 상대)와 `coverage.iteration`(절대)을 혼용. 실제 `run-summary.json` 구조에 맞춰 `coverage.scope.*` 로 통일 — 최상위 `scope` 키를 찾으려다 실패하던 오독 방지.
- **잘못된 섹션명 인용** — `autobot-orchestrator` 의 "완료 보고" 섹션을 가리켰으나 실제 헤더는 "보고 / 회고".
- **DEGRADED 배지 문구가 차단 커맨드를 누락** — anti-laundering preflight 는 `/autobot:testflight`·`/autobot:app-review` 둘 다 적용하는데 배지 문구가 testflight 만 언급. 둘 다 명시하도록 교정.

### Added
- `/autobot:mvp 가 트리거하지 않는 것` 라우팅 목록에 `/autobot:app-review`(App Store 심사 제출) 포인터 추가 — 출시 경로 안내 누락 보완.

### Changed
- **mvp.md 가독성 폴리싱 (정보·가드레일·얇은 진입점 설계 100% 보존, 형태만 변경)** — Safety Policy 와 "트리거하지 않는 것"을 표로, 완료 보고를 "기능 검증 배지" / "Capability Coverage" 두 `###` 섹션으로 분리, 진입점 계약을 인용구로, frontmatter description 에 범위(Phase 0–5 + 7) 명시, 입력/결과물 오리엔테이션 추가. judge-panel 4안 생성 → 합성 → 적대적 드리프트/가드레일 검증을 거쳐 명백한 스캔성 이득만 채택하고 길이·중복은 배제(4052→4502자).

## [0.7.0] — 2026-05-29

검증을 "형태"에서 "실제 동작"으로. 초록불이 *"앱이 아이디어대로 실제로 동작한다"* 를 의미하도록 기능 검증 척추를 넣고(cycle 1), 그 검증기를 실 iOS 26 시뮬레이터에서 실제로 돌려 증명했다(cycle 2). 증명 과정에서 검증기가 실 하드웨어에선 작동하지 않던 버그 3개를 찾아 고쳤다 — 전부 mock 이 숨기고 있던 것.

### Added
- **기능 검증 척추 (Gate 5→6 의 "초록불 = 실제 동작")**:
  - **`feature-spec.json`** — architect 가 한 줄 아이디어를 기계검증 가능한 feature 단위로 분해(`{id,title,priority,screen,anchor,acceptance[]}`). 자율 emit (질문 없이). `scripts/intent_spec.py` 에 `FeatureSpec`/`Acceptance`/`Postcondition` + `load/validate/assess` 검증기.
  - **Gate 1→2**: `feature_spec_declared` (P0/P1 마다 acceptance + anchor) + `feature_spec_quality` (모든 P0/P1 acceptance 에 "anchor 존재" 이상의 관찰가능한 상태변화 postcondition 강제 — Goodhart 방어). postcondition kinds: `count_increased/decreased`, `value_persisted_after_relaunch`, `navigated_to`, `artifact_generated`, `setting_stored`.
  - **Gate 5→6 `logic_tests_pass`** — 작성된 Swift Testing 유닛/통합 테스트를 `xcodebuild test` 로 실제 실행하고 `.xcresult` 를 파싱(기존 죽은 코드 `integration_build(test=True)` 배선). 빌드를 하니스가 독립 재검증.
  - **Gate 5→6 `functional_flows_pass`** — `scripts/flow_runner.py` 가 AXe(`describe-ui`/`tap`)로 P0 happy-path 를 실제 구동하고 postcondition 을 단언. P0 실패 = hard-fail, P1 실패 = 경고, 시뮬레이터/axe 부재 = degraded-skip.
  - **DEGRADED 3값 게이트 판정** — `run_gate` 가 passed/degraded/failed 를 구분. 검증을 *돌릴 수 있는데* 안 돈 경우는 조용한 PASS 가 아니라 DEGRADED. `build_gate_evidence` status 4값화.
  - **anti-laundering 출시 차단** — `functional_verification_passed` + `/autobot:testflight`·`/autobot:app-review` 의 archive 전 preflight `run-gate 5->6` 재실행. degraded/미검증 빌드의 출시를 거부(과거 플래그 불신뢰).
  - **검증기 불변성** — `.autobot/feature-spec.json` 을 `forbiddenInfra` 로 (architect 만 수정 가능). fix loop 이 스펙을 약화시켜 통과하는 것을 차단.
  - **run-summary 배지** — `VERIFIED / DEGRADED / UNVERIFIED` 를 `run-summary.{json,md}` + mvp/testflight 완료 출력에 표기. axe preflight 를 Phase 0 env_snapshot 에 기록.
  - Phase 0 axe preflight (`environment.axe`/`axeVersion`).
- **E2E 검증 증명 (실 Mac)** — `scripts/e2e_verify.py` 하니스 + `tests/e2e/fixtures/GreenApp`(정상)·`RedApp`(깨진 UI) fixture. GreenApp → VERIFIED, RedApp → flow 가 0→0 으로 hard-fail (로직 테스트는 통과하므로 "로직만으론 못 잡는 깨진 UI 를 flow 가 잡는다" 를 증명). `.github/workflows/e2e-verify.yml` (macos-26, PR path-filtered) 이 실 iOS 26 시뮬레이터에서 두 fixture 를 게이트.

### Fixed
- **flow_runner 가 실 AXe 출력에서 anchor 를 못 찾던 버그** — AXe 는 접근성 식별자를 `AXUniqueId` 에 담는데 `identifier` 를 읽고 있었음. 모든 flow 가 "anchor never ready" 로 실패. cycle-1 mock 이 가짜 키를 써서 숨김. (`_anchor_id` = AXUniqueId∥identifier)
- **`xcodebuild test` 가 generic destination 으로 항상 실패하던 버그** — `integration_build` 가 `generic/platform=iOS Simulator` 를 써서 test 액션이 거부됨("Tests must be run on a concrete device"). 이제 concrete sim UDID 를 해석해 전달(없으면 degraded-skip).
- **describe-ui 트리 미평탄화** — flow_runner 가 top-level 노드만 검사하고 중첩 `children` 을 재귀하지 않아, children 안의 anchor 를 못 찾음. `_flatten` 으로 전체 트리 평탄화.
- `smoke-e2e.yml` 러너 `macos-15` → `macos-26` (iOS 26 빌드가 한 번도 성공하지 못하던 원인). `ci.yml` 의 stale "185 tests" 라벨 제거. `integration_build` 가 stale `.xcresult` 를 제거(재실행 안정).

## [0.6.0] — 2026-05-28

자기개선 루프를 App Store 심사 제출까지 확장. TestFlight 이후의 마지막 마디 — ASO 최적화 메타데이터, 모든 iPhone 사이즈 스크린샷, AXI-Homepage 제품 등록, 빌드 processing 폴링 + 자동 리뷰 제출 — 을 단일 슬래시 커맨드로 묶었다. 동시에 Design System SPM 분리가 합쳐졌다.

### Added
- **`/autobot:app-review` — App Store 심사 제출 일괄 자동화** — 신규 슬래시 커맨드 + `autobot-app-review` 스킬:
  - **Phase A — Marketing context**: `architecture.md` + `build-state.json` 에서 `app-marketing-context.md` 를 프로젝트 루트에 작성 (aso-skills lookup 위치 요구).
  - **Phase B — Metadata**: ASO 원칙 inline 적용 (Q&A 발동 막기 위해 aso-skills 는 Skill-invoke 안 함). `marketing_url` / `support_url` 은 slug 기반 `https://axi.dev/products/<slug>` prefill. `autobot-generate-metadata` + `autobot-upload-metadata` 체인.
  - **Phase C — Screenshot narrative**: 5-슬롯 narrative (Hook / Feature×3 / Closing) 를 `.autobot/screenshot-plan.md` 로.
  - **Phase D-1 — Raw capture**: `ParthJadhav/ios-marketing-capture` 스킬 위임 (자동 git clone fallback). 시뮬레이터 in-app 캡쳐로 `marketing/<locale>/*.png` 생성.
  - **Phase D-2 — Composite**: `app-store-screenshots:app-store-screenshots` 위임. 4개 iPhone 사이즈 (6.9"/6.5"/6.3"/6.1") × 모든 locale 합성 → `fastlane/screenshots/<locale>/*.png`.
  - **Phase H — Homepage 등록 (신규 앱만)**: `scripts/register-on-homepage.sh` 가 AXI-Homepage 레포 clone → `src/data/products.ts` 에 TS-aware 삽입 → 아이콘 + 스크린샷을 `public/` 에 복사 → `git push origin main`. 멱등 (slug 존재 시 no-op, `--force` 로 덮어쓰기). Dirty worktree 거부, atomic write.
  - **Phase E — Screenshots upload**: `scripts/upload-screenshots.sh` (fastlane deliver `--skip_binary_upload --skip_metadata --overwrite_screenshots`).
  - **Phase F — Build upload**: 기존 `deployer` 에이전트 위임 (register → archive → upload, idempotent).
  - **Phase G — Submit for review**: `scripts/submit-for-review.sh` 가 `fastlane pilot builds` 폴링으로 빌드가 PROCESSING → VALID 전이 대기 (최대 30분, transient error 5회 tolerance) 후 `fastlane deliver --submit_for_review` 호출. Submission JSON 기본값은 Autobot 스캐폴드 가정 (encryption=false, IDFA=false, has_rights=true, automatic_release=true) 과 일치.
- **Design System SPM**: 매 MVP 빌드마다 in-tree 로컬 패키지 `Packages/<Name>DS/` 를 자동 생성. architect 가 `architecture.json.designSystemModule` 로 이름 결정 (관례: `<AppName>DS`), Phase 3 scaffold 가 골격 + project.yml wiring, 새 `design-system` 서브 에이전트가 Tokens/Components 채움.
- 새 게이트: `design_system_package_exists`, `design_system_tokens_exist` (Gate 3→4).
- `create-xcode-project.sh --design-system-module` 플래그.

### Changed
- ui-builder 는 더 이상 `Utilities/Theme.swift` 를 생성하지 않는다. 대신 `import <Name>DS` 후 패키지 토큰을 사용한다.
- Phase 3 가 (self scaffold → design-system 에이전트) 2 단계 dispatch 로 변경.
- `fileOwnership.agents` 에 `design-system` 추가, `ui-builder.writes` 에서 `Theme.swift` 제거.
- plugin.json `description` 갱신: "App idea to TestFlight" → "App idea to App Store review" — `/autobot:app-review` 추가를 반영.

### Notes
- `aso-skills:*` 와 `app-store-screenshots:app-store-screenshots` 는 cross-plugin skill. orchestrator 는 Q&A 발동을 피하기 위해 `app-marketing-context.md` 를 프로젝트 루트에 사전 작성 + reference 로만 inline 적용.
- Phase H 의 git push 이후 배포는 AXI-Homepage 레포가 외부에서 처리 — Autobot 의 책임은 push 까지.
- iPad 자산은 생성하지 않는다 (iPhone App Store 전용).
- Apple 신규 앱 제출 시 연령 등급 / App Privacy 질문지는 ASC 웹에서 1회만 수동 처리 필요 — fastlane API 영역 밖.

## [0.5.0] — 2026-05-26

자기개선 루프의 마지막 마디를 닫고, Phase 5/Gate 5→6 에서 빌드는 통과하지만 런타임에서 깨지는 결함을 차단하는 릴리스. 신규 헬퍼 모듈 14개 + 회귀 테스트 11종 + declarative gate 확장 + agent/command/orchestrator 거대 리팩토링.

### Added
- **신규 헬퍼 모듈 14개** (`scripts/`) — gate descriptor 가 직접 호출하는 단일 책임 도구:
  - `sandbox_guard.py` — agent file ownership 사전 차단
  - `visual_contract.py` — 디자인 룩앤필 픽셀 비교 (Pillow)
  - `sim_runtime.py` — 시뮬레이터 부팅 + smoke 실행
  - `xcodebuild_runner.py` — xcodebuild 호출 + 에러 시그니처 추출
  - `intent_spec.py` — 앱 의도 manifest 로드 + 미사용 앵커 탐지
  - `input_hash.py` — 입력 해시 + phase skip 판정 (`/autobot:resume` 의존)
  - `error_signature.py` — 빌드 에러 정규화 + 누적 (Build-Fix Loop 학습 입력)
  - `metadata_validator.py` — App Store 메타데이터 길이/형식 검증
  - `design_spec_validator.py` — design-spec 룩앤필 계약 검증/합성
  - `learning_impact.py` — 학습 적용 효과 점수화 (effect_score 자동 갱신)
  - `run_summary.py` — `artifacts/<buildId>/run-summary.{json,md}` 생성
  - `context_pack.py` — phase/agent 별 컨텍스트 팩 빌드 (토큰 예산 인식)
  - `env_snapshot.py` — capture/load/ensure/is-stale 환경 스냅샷
  - `verify-phase7-axiom.py` — Phase 7 axiom health-check 결과 검증
- **회귀 테스트 11종** — `test_sandbox_guard`, `test_visual_contract`, `test_intent_spec`, `test_input_hash`, `test_error_signature`, `test_design_spec_validator`, `test_learning_impact`, `test_run_summary`, `test_peer_review_bridge`, `test_axiom_and_peer_strict`. 회귀 슈트 148 → 148 통과 (이전 39 → 신규 109).
- **Axiom / Peer Review Bridge SSOT** — `skills/autobot-axiom-bridge/SKILL.md` + `skills/autobot-peer-review-bridge/SKILL.md`. 호출 규칙·프롬프트·결과 기록 위치를 한 곳에 정리. 감지는 `scripts/detect-axiom.sh` / `scripts/detect-peer-ai.sh` (exit code 기반, silent skip 보장).
- **record-environment 필드 확장** — `runtimeHost`, `peerAi`, `peerReviewAvailable` 3개 추가. peer-review 가용성을 build-state 에 명시 기록해 Gate 5→6 verdict 검증의 근거로 사용.
- **`pipeline.sh` 신규 서브커맨드 8개** — `env-snapshot`, `write-run-summary`, `grade-learnings`, `input-hash`, `context-pack`, `error-signature`, `design-spec`, `sandbox`. 모든 신규 도구를 단일 진입점으로 노출.
- **`hooks/sandbox-pre-write.sh`** — PreToolUse 활성화 후보. payload schema 검증 전까지는 hooks.json 미등록 (메모 보존).

### Changed
- **agent/command/orchestrator 거대 리팩토링 — SSOT 위임** — drift 표면 6→1:
  - `agents/architect.md` -330 줄 (Design Direction 체크리스트 → references 위임)
  - `commands/mvp.md` -450 줄 (Phase 단계 설명 → orchestrator SKILL 위임)
  - `skills/autobot-orchestrator/SKILL.md` -380 줄 (spec/pipeline.json 으로 위임)
  - `agents/quality-engineer.md` / `agents/ui-builder.md` — 신규 헬퍼 사용 의무 명시
- **Gate 5→6 강화** — axiom critical-audit 통과 + peer-review verdict ∈ {PASS, skipped} 강제. 코드 변경: `spec/pipeline.json` (+290), `scripts/gate_runner.py` (+620 lazy import 라우팅), `scripts/phase_advance.py`.
- **Phase 1 codex review verdict 강화** (`scripts/codex-architecture-review.sh`) — skipped 명시 기록, hardViolations 적재, max 2회 재실행.
- **Phase 5 통합 빌드 SKILL** (`skills/autobot-integration-build/SKILL.md`) — error_signature 호출 + Build-Fix Loop 환경 우선 체크리스트 5항목 선행.
- **Phase 7 회고 — axiom health-check 흡수** (`skills/autobot-retrospective/SKILL.md`) — `verify-phase7-axiom.py` 결과를 build-report.md / learnings.json 에 누적.
- **Xcode 프로젝트 생성 강화** (`skills/autobot-ios-scaffold/scripts/create-xcode-project.sh`) — Export Compliance 자동 처리, privacy/entitlements 기본값 보정.
- **README** — Axiom / Peer Review Bridge 섹션 신설, Phase 표 갱신.

### Notes
- 모든 신규 헬퍼는 lazy import — gate 미사용 경로에서 import 오버헤드 0.
- 회귀 슈트는 stdlib only (`python3 -m unittest`) — pytest 의존성 없음.

## [0.4.0] — 2026-05-22

### Added
- **axiom-distilled 지식 베이스** — `references/axiom-distilled/` 디렉토리 신설. axiom 플러그인(MIT)의 iOS 26+ 핵심 규칙을 Autobot 자족 형태로 증류한 4개 문서:
  - `design.md` (172줄) — Liquid Glass Regular/Clear 결정 트리, HIG 빠른 결정, SF Symbols 렌더링 모드, App Composition (@main + @Observable + Root 분기), 6항목 자가 체크리스트
  - `swiftui.md` (197줄) — @State private 강제, @Observable 소유권 4가지 도구 결정 트리, NavigationStack 라우터, 성능 7항목 점검, iOS 26 신기능, 8항목 자가 체크리스트
  - `data-concurrency.md` (284줄) — SwiftData @Model 규칙(final, @Relationship 배열 기본값, deleteRule), VersionedSchema 강제, Repository @MainActor 패턴, Swift 6 Sendable 5규칙, 런타임 크래시 진단표, 9항목 자가 체크리스트
  - `build-testing.md` (245줄) — 환경 우선 빌드 실패 분류, 에러 메시지→도메인 매핑표, Swift Testing 표준(@Test/#expect), sleep 금지 패턴, .xcresult 추출 명령, 9항목 자가 체크리스트
- 각 파일은 axiom MIT 출처 명시 + WWDC 2025+ 갱신 정책 명시 + Anti-Rationalization 표 포함.

### Changed
- **에이전트 4개의 Pre-read 의무 추가** — Autobot 이 외부 axiom 플러그인 없이도 iOS 26+ 코드 품질을 보장하도록 4개 에이전트 헤더에 "Pre-read (필수, 순서대로)" 섹션 삽입:
  - `agents/architect.md` (+4줄) — design.md, data-concurrency.md 의무 참조. Design Direction 작성 시 6항목 체크리스트 충족.
  - `agents/ui-builder.md` (+7줄) — swiftui.md, design.md, data-concurrency.md 의무 참조. Phase 4 완료 직전 8항목 grep 검증.
  - `agents/data-engineer.md` (+6줄) — data-concurrency.md, build-testing.md 의무 참조. Repository 구현이 9항목 체크리스트 통과.
  - `agents/quality-engineer.md` (+7줄) — build-testing.md, data-concurrency.md, swiftui.md 의무 참조. Build-Fix Loop 시 *코드 수정 전* 환경 체크리스트 5항목 선행.

### Notes
- 외부 axiom 플러그인 의존성 0건 (감지 코드 `scripts/detect-plugins.sh` 의 `axiom` 필드는 호환성 유지 위해 보존).
- distilled 파일이 SSOT — WWDC 또는 iOS 메이저 릴리스 후 본 파일만 갱신하면 4개 에이전트가 즉시 신지식을 받는다.
- 별도 인프라(훅, CLI) 변경 0건 — 순수 프롬프트/지식 변경으로 재시작 없이 다음 빌드부터 효과.

## [0.3.2] — 2026-05-19

### Added
- **학습 로드 프로토콜 SSOT** — `skills/autobot-orchestrator/references/learning-bootstrap.md` 신설. phase-learnings/active-learnings 2단계 fallback 순서, phase→파일 매핑, `build-log.sh` 호출 규약, `phases.<N>.learningsConsumed[]` 누적 메커니즘을 한 곳에 정리. architect, quality-engineer, deployer, data-engineer, ui-builder, backend-engineer 6개 에이전트의 중복 preamble(각 7-16줄)을 위임 + 에이전트별 필터로 축소해 드리프트 표면을 6→1.

### Changed
- **스킬 디렉토리 작명 통일** — 모든 스킬 디렉토리에 `autobot-` prefix 적용. 기존 8개 디렉토리(`app-icon`, `build-report`, `integration-build`, `ios-scaffold`, `orchestrator`, `retrospective`, `setup`, `ux-design`)가 각각 `autobot-app-icon`/`autobot-build-report`/`autobot-integration-build`/`autobot-ios-scaffold`/`autobot-orchestrator`/`autobot-retrospective`/`autobot-setup`/`autobot-ux-design`로 이동. frontmatter `name:` 필드와 일치하므로 grep/문서 참조가 한 번에 잡힌다.
- `agents/quality-engineer.md`, `agents/deployer.md`, `commands/mvp.md`, `commands/meta.md`, `commands/setup.md`, 일부 skill SKILL.md/스크립트가 새 경로로 일괄 업데이트.
- `scripts/verify_spec_docs.py`, `scripts/render_pipeline_docs.py`가 `autobot-orchestrator` 경로를 가리키도록 갱신. `DOCS_TO_CHECK`에서 사라진 `commands/make.md` 제거하고 `mvp.md`/`testflight.md`로 교체.
- README "구성 요소" 트리가 실제 디렉토리(agents 7개, skills 14개)와 일치하도록 재작성. 누락되어 있던 `backend-engineer`, `ux-designer` 에이전트와 `autobot-app-icon`, `autobot-build-report`, `autobot-integration-build`, `autobot-setup`, `autobot-ux-design` 스킬을 트리에 명시.

### Fixed
- CHANGELOG 0.3.1 항목의 스킬 이름 오타 정정 — `autobot-app-register` → `autobot-register-app`.

## [0.3.1] — 2026-05-19

### Added
- **Phase 6 단일책임 스킬 분해** — 기존 `testflight-deploy` 단일 스킬을 4개로 분리: `autobot-archive-build`(아카이브), `autobot-upload-build`(업로드), `autobot-generate-metadata`/`autobot-upload-metadata`(메타데이터), `autobot-invite-testers`(테스터 초대). 각 스킬은 독립 실행 가능한 `scripts/*.sh`를 동봉.
- **ASC 앱 등록 전용 스킬** `autobot-register-app` 추가. `scripts/register-app.sh`로 App Store Connect 신규 앱 레코드 생성을 분리. 회귀 테스트 `tests/test_app_register.py` 동봉.
- **명령 분리** — `make` 단일 명령을 목적별로 분해: `/autobot:mvp`(MVP 빌드), `/autobot:testflight`(TestFlight 전체 흐름), `/autobot:meta`(메타데이터 작업). `resume`, `setup` 명령도 새 레이아웃에 맞춰 정비.
- **design-spec 룩앤필 계약 의무화** — 디자인 사양에 룩앤필 필드를 강제하고 Stitch 사용 불가 시 fallback 경로를 강화.

### Changed
- `agents/deployer.md`, `skills/orchestrator/SKILL.md`, `spec/pipeline.json`이 새 Phase 6 스킬 구조에 맞춰 갱신.
- README, troubleshooting, build-report 문서가 분리된 스킬/명령 체계 기준으로 정리.
- 검증 표면(validation surfaces) 정합성 보강 — 누락 조건 차단과 디버그 가시성 향상.

### Removed
- `skills/testflight-deploy/` — 4개 단일책임 스킬로 대체.

## [0.3.0] — 2026-04-30

### Changed
- **플러그인 레이아웃 평탄화** — 저장소 루트 자체가 Claude Code 플러그인 디렉토리가 되도록 재배치. `plugins/autobot/` 중첩 트리를 해체하고 `agents/`, `commands/`, `hooks/`, `skills/`, `spec/`, `scripts/`, `tests/`, `references/`, `.claude-plugin/plugin.json`이 모두 루트 직속에 위치한다.
- 설치 명령이 `claude --plugin-dir /path/to/Autobot/plugins/autobot` → `claude --plugin-dir /path/to/Autobot`으로 단축됨.
- 문서 내 `plugins/autobot/...` 경로 참조와 README 디렉토리 트리를 새 레이아웃 기준으로 정리.
- `verify_spec_docs.py` / `render_pipeline_docs.py`의 `PLUGIN_DIR` 상수가 곧바로 저장소 루트를 가리키도록 단순화.

### Notes
- `$CLAUDE_PLUGIN_ROOT`(플러그인 위치)와 `$CLAUDE_PROJECT_DIR`(빌드 대상 앱 디렉토리)은 의미가 다르다. `scripts/*.sh`의 `CLAUDE_PROJECT_DIR` 참조는 빌드 중 사용자 앱 디렉토리를 가리키므로 그대로 유지된다.

## [0.2.1] — 2026-04-28

### Added
- **Phase 1 codex architecture review 게이트**. architect 산출물을 Gate 1→2 전에 codex가 컴파일 영향 이슈로 사전 검증. Phase 5 빌드에서 발견되는 Swift 6 strict concurrency / SwiftData / AVFoundation lifecycle 문제 중 architect 결정에서 비롯된 것을 architect 재실행 단계에서 차단. PASS / FAIL / skipped 세 verdict 모두 처리 — codex 미설치 시 skipped로 진행 보장, FAIL 시 hardViolations를 state에 적재 후 architect 재디스패치(max 2회), `excludeFromCircuitBreaker`로 orchestrator-side 재시도가 breaker를 트립하지 않음.
- 신규 스크립트 `scripts/codex-architecture-review.sh` (334 LoC).

### Removed
- `marketplace.json` — 마켓플레이스 등록 경로 폐기.
- README의 `.env` 언급 및 `.env.example` 자동 복사 기능.

## [0.2.0] — 2026-04-27

플러그인 골격 정합성 — 단일 기준(SSOT) 강화 + atomic semantics + 회귀 보호.

### Added
- **자동 회귀 테스트 슈트** (`tests/`, stdlib unittest, 19개 케이스). `tests/run_tests.sh`로 실행.
- **advance-phase** 명령. `scripts/pipeline.sh advance-phase --phase N` — 해당 phase의 outgoing gate 실행 + 통과 시에만 phase 완료 마킹. 실패 시 자동 retryCount 증가. 호출자가 `--increment-retry`를 빠뜨리는 회귀 차단.
- **set-flag** 명령. `pipeline.sh set-flag --key backend_required --value true`. 화이트리스트는 `spec.policies.allowedFlags`.
- **Circuit breaker auto-recovery**. global retryCount 합이 `policies.circuitBreaker.maxConsecutivePhaseFailures`에 도달하면 retro phase가 자동으로 `in_progress`, 미완료 phase는 `skipped`(`skipReason` 기록).
- **Sandbox enforcement**. `spec.fileOwnership.agents.<>.writes`가 SSOT. 위반은 `phases.<id>.sandbox.violations`에 기록되고 Gate 4→5의 `sandbox_clean` 체크가 평가. Unknown agent는 즉시 거부.
- **Phase-level snapshot SSOT**. `snapshot_runner.py`가 `fileOwnership.agents.<phase 담당>.writes`에서 디렉토리 자동 도출. shell case-hardcode 제거.
- **logEvents 스키마**. `spec.logEvents`에 event 이름 + required/optional 필드 + per-event `detailSchema`. `build-log.sh`/`runtime append-log`가 검증. 알 수 없는 event 또는 누락 필드는 fail-loud.
- **learning_applied 추적**. agent가 학습 적용 시 이벤트 기록 → `phases.<id>.learningsConsumed` 누적 → Gate 1/4/5의 `state_field_contains` 체크가 강제.
- **Declarative gate descriptors**. spec에 `file_exists`, `dir_exists`, `dir_has_swift`, `file_grep`, `command_success`, `state_field_eq`, `state_field_contains`, `all` primitive. 절차적 체크는 `procedural` 디스크립터로 명시 등록.
- **CONVENTIONS.md** — 출력 prefix 정책, atomicity 규칙, 모듈 의존 그래프, SSOT 위치를 한 곳에 정리.

### Changed
- `runtime.py` 1225L → 66L facade. 6개 모듈로 책임 분리: `spec_loader.py`, `state_store.py`, `event_log.py`, `transitions.py`, `gate_persistence.py`, `phase_advance.py`. 호환을 위해 `from runtime import X`는 그대로 동작 (각 모듈의 `__all__`이 facade의 source-of-truth).
- `validate-state.sh`는 read-only 진단 전용으로 축소 (schema/transition/list-checks/verify-docs/render-docs). mutating 명령은 모두 `pipeline.sh`로 일원화.
- `phases.<5>.metadata.build_succeeded`가 Gate 5→6의 단독 truth source. build-log fallback 제거.
- `gate_runner` procedural 함수가 `spec.fileOwnership`에서 경로 도출. hard-code 제거.
- `phase_advance.advance_phase`가 `AdvanceResult`를 반환하고 CLI wrapper가 출력 — testability 향상.
- spec `schemaVersion`을 1 → 2로 bump. build-state에 `schemaVersion` 기록 + 호환성 검사 (구버전은 WARN, 신버전은 ERROR).

### Fixed
- "complete-phase → run-gate" 순서 뒤집힘으로 phase가 `completed` 상태에서 gate fail이 발생해 비일관 상태로 박제되던 회귀.
- `build_attempt` 이벤트의 `succeeded` 필드 부재로 Gate 5→6의 build-log fallback이 항상 false 반환하던 silent failure.
- Sandbox enforcement가 `allowed=[]` 분기에서 OWNERSHIP 검사를 silent skip하던 결함.
- `advance_phase`가 transition 거부 시 gate evidence와 build-log 행을 기록하던 partial-write 회귀 (codex Q6).
- soft gate 실패가 phase status에 흔적을 남기지 않아 resume이 놓치던 결함 → `phases.<id>.gate_evidence.softFailure`로 기록.
- Sandbox snapshot 파일이 직접 overwrite되어 partial JSON 가능성이 있던 결함 → tmp + rename atomic write.
- `append_build_log`가 spec load 실패를 silent fallback으로 삼키던 결함 → fail-loud.

### Removed
- `validate-state.sh`의 mutating 서브커맨드 (`init-state`, `set-phase-status`, `record-environment`, `record-gate-result`, `run-gate`). 명시적 ERROR + 대체 명령 안내.
- `advance-phase`의 `--increment-retry`/`--retry-count` 옵션 — 자동 증가가 표준이라 잡음.
- `_circuit_breaker_tripped` BC alias.

## [0.1.11] — 2026-04 이전

이전 릴리스. 본 changelog 도입 전이라 git log를 참조한다.
