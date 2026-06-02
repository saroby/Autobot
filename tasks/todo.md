# 품질 보고서 "타당한 부분" 구현 — quality-max 모드 + flow DSL (4 슬라이스)

목적: 외부 품질 보고서 7개 중 *타당*으로 판정된 것만 구현. 보류: 자동 재실행/재작업/
구현·context7 필수(자율성·circuit breaker 충돌). 사용자 합의 범위 = "모두".

## 핵심 설계 원칙 (평결에서)
- **기본 자율 경로(`/mvp`)는 무손상.** 엄격함은 `--quality=max` **opt-in** 으로만.
- **hard fail 금지, DEGRADED 사용.** hard fail 은 retryCount→전역 circuit breaker(합 3)
  trip→자율 빌드 정지(`transitions.py:53`, `build.py:119-122` 가 명시). DEGRADED 는
  출하만 차단(배지). benign skip(skipped only)은 green 유지(`gate_runner.py:344`).
- qualityMax 는 `allowVisualDrift` 와 동일 패턴: `spec.allowedFlags` + `set-flag` +
  게이트가 `state.get("qualityMax")` 분기.

## 슬라이스
- [x] **B 모드 골격**: spec.allowedFlags 에 qualityMax 추가 + mvp.md `--quality=max`
      섹션(argument-hint 갱신) + orchestrator 가 Phase 0 후 set-flag 실행. ✅
- [x] **C 모드 첫 효과 (#2·#6)**: review.py — qualityMax 면 axiom/peer 미가용 skip →
      DEGRADED(degraded=qmax). design.py — qualityMax 면 fallback 0 mockup → DEGRADED.
      `test_quality_max_mode.py` 8종(on/off 양경로 + flag allowed). 462 OK 회귀 0. ✅
- [x] **A 독립 fix (모드 무관, 자율 무손상)**: ✅
      - #5 unsupported 명시 제외: architect.md `## Out of Scope` 규칙 +
        capability_coverage `_mark_acknowledged`(OoS 섹션 grep) + render 가 "의도적
        제외 vs silent gap" 분리. `test_capability_out_of_scope.py` 5종. 자동 구현 X.
      - #3 waiver buildId-scoped: build.py `allowVisualDrift == buildId` 면제 +
        resume.md 가 buildId 로 set-flag + line 169 중복 제거. stale-waiver 만료
        테스트 추가(14종). 영구 세탁 제거, testflight 동일빌드 유지.
- [x] **D flow DSL (#4)**: ✅ flow_runner step 분기에 text_input/swipe/long_press +
      좌표 변환 헬퍼(_anchor_frame/_frame_center/_swipe_endpoint, 단위 테스트) +
      architect action 제약 완화 + functional P1 hard mode(qualityMax→DEGRADED).
      AXe 시그니처는 axe-cli.com 1차 문서 기반, 실행은 시뮬레이터 미검증(명시).
      flow_dsl 10종 + P1 1종. 479 OK 회귀 0. (relaunch 는 기존 postcondition 그대로.)

## 보류 (평결: 자율성/breaker 충돌 또는 비용)
- #1 HIGH critique → architect 자동 재실행 (비결정 신호 → breaker trip)
- #3 HIGH visual → 자동 UI 재작업 루프 (visual judge 가 이미 DEGRADED 로 후퇴한 길)
- #5 unsupported 자동 *구현* (스코프 폭발 — 명시 제외만 채택)
- #7 context7/WebSearch 필수 조회 (axiom-distilled 정적 지식 이미 풍부 + 비결정성 비용)

## Verify (슬라이스별)
- [ ] 각 게이트 분기: qualityMax on/off 두 경로 테스트 (off=기존 동작 보존)
- [ ] 전체 슈트 + render --check + verify_spec_docs
- [ ] D: 시뮬레이터 동작은 단위로 못 닫음 — 명시

---

# 시각 동질성 깨기 — Signature Layout + critique 축 + 모델 격상 (개선축 #1)

목적: 생성 앱이 "또 그 앱처럼 생김"(AI 슬롭) 에서 벗어나게. 근본 진단: Layout
Personality 가 **4종 폐쇄 분류**(`architecture-template.md:96`)고 ui-builder 가 그에
묶인 **고정 코드 스니펫**(`ui-builder.md:79-138`)을 적용 → 여행/레시피/뉴스 앱이 모두
content-forward 면 동일 LazyVStack 카드 피드. + 보이는 에이전트 전부 `model: sonnet`.

## 설계 결정 (advisor 프레임 — #2 와 다른 종류의 과제)
- **미적 품질은 결정적 측정 불가.** #2 플레이북(새 결정적 게이트) 그대로 끼우면 가짜
  검증. 동질성은 **intent 단계**(architect Design Direction / Phase 2.5 critique)에서
  잡는다 — Phase 5 충실도(visual_judge)에서 잡으면 Goodhart(제네릭을 충실히 구현=통과).
- **트랩 A (safe-area 보존)**: 4종 스니펫은 *레이아웃 모양*(동질성→바꿈)과 *안전
  스캐폴딩*(`.safeAreaInset`, bottom ignoresSafeArea 금지→불변)을 섞어 담음. 통째로
  헐면 `no_tabbar_safearea_smells` 가 막던 버그 재오픈. 둘을 분리: 모양 다양화 + 불변식 보존.
- 사용자 선택: **몰드 확장 + critique 축 + 모델 격상**(①+③ 짝, advisor 권장).

## 정직한 검증 스토리 (미적은 게이트 못 만듦 — 숨기지 않음)
- (a) architect 가 Signature Layout 을 emit 하나 → `design_direction_complete` 게이트 강제
- (b) critique 에 레이아웃 동질성 축이 들어갔나 → grep
- (c) **안전 불변식 생존** → `no_tabbar_safearea_smells` fixture 여전히 통과 (회귀 0)
- "더 예뻐졌다" = A/B·사람 판단. 게이트가 증명한다고 흉내내지 않는다.

## Plan — 결과
- [x] 1. `architecture-template.md` — 4종=출발 힌트로 강등 + `### Signature Layout`
        1급 표(hero·위계·density·화면간 차별화 + 예시 + 금지: 전화면 동일 List)
- [x] 2. `agents/architect.md` — Design Direction 규칙에 Signature Layout emit 강제
- [x] 3. `agents/ui-builder.md` — 4패턴=출발 골격(Signature 우선)으로 프레임 +
        safe-area 4규칙을 "레이아웃 불변식"으로 명시 강조(트랩 A) + `model: opus`
- [x] 4. `autobot-plan-preview/SKILL.md` — critique 디자인 축에 레이아웃 동질성(HIGH)
- [x] 5. `gate_checks/setup.py` — `check_design_direction_complete` 에 signature heading
- [x] 6. `test_signature_layout_gate.py` 2종 + CHANGELOG. (트랩 A: 4패턴 스니펫·게이트
        코드 `no_tabbar_safearea_smells`(app.py) 미변경 — 안전 스캐폴딩 보존+강화.)

## Verify — 결과
- [x] 전체 슈트 **454 OK** (452→454, 신규 2, 회귀 0)
- [x] render --check up-to-date / verify_spec_docs 전부 PASS (phase-gates drift 0)
- [x] (a) signature 누락(다른 섹션 완전) → Gate fail / 완전 → pass — 테스트로 특정 검증
- [x] (c) safe-area 불변식: 게이트 코드(`gate_checks/app.py`) 미변경 + ui-builder 가
      불변식으로 *강조* → 약화 아닌 강화. diff 로 변경 범위 확인.
- [x] 정직한 한계 명시: 미적 개선은 A/B·사람 판단(게이트가 증명 못 함).

## Results
- **변경 6파일**(코어): architecture-template.md, architect.md, ui-builder.md(+opus),
  plan-preview/SKILL.md, gate_checks/setup.py (+테스트·CHANGELOG).
- **동작**: architect 가 Signature Layout 을 1급으로 emit(Gate 1→2 가 heading *존재*
  강제) → ui-builder(opus) 가 4종 골격을 그 위에서 변형(safe-area 불변). Phase 2.5
  critique 동질성 축은 `manual` 이라 **자율 `/mvp` 에선 skip**, `/plan` 검토 시 advisory.
- **정직한 한계 (advisor 지적 반영)**: 자율 빌드 기계 강제 = heading 존재 grep 하나뿐
  (제네릭 한 줄로 통과 가능 = Goodhart). 실제 고유성은 architect Signature 품질 +
  opus 구현에 달렸고 A/B·사람 판단 — 게이트가 증명 못 함. CHANGELOG 에 명시.
- **⚠️ 무관 변경 발견**: `references/axiom-distilled/data-concurrency.md`(+41/-6,
  SFSpeechRecognizer @Sendable 함정)는 이 세션 외 변경 — 건드리지 않음. 사용자 확인 필요.

---

# First-launch seeding — 생성 앱의 "첫인상" 전문성 (개선축 #2)

목적: 플러그인이 만드는 앱이 TestFlight 첫 실행 시 빈 껍데기로 뜨지 않게 한다. 단,
빈 시작이 본질인 앱(todo/저널)은 그대로 둔다. 근본 진단: data-engineer 의
`SampleData.swift` 는 **Preview/test 전용**(data-engineer.md:33), ui-builder
`ServiceStubs` 도 Preview mock(ui-builder.md:70) — **런타임 first-launch seed 경로가
어느 에이전트 프롬프트에도 없다.** 반면 app-review SKILL.md:233 은 "Autobot
scaffolds include seed data" 라고 *가정* → 의도-구현 drift (unenforced 가정의 부패).

## 설계 결정 (advisor 2회 검토 반영)

1. **seedPolicy 는 architect 가 결정 → architecture.json** (게이트가 읽을 곳; scaffold
   /Gate 4→5 가 이미 이 파일 필드를 읽음, architect.md:93). `"seeded" | "empty"`.
2. **factory 패턴 (BLOCK)**: seed 는 매 호출 새 @Model 인스턴스 생성·insert. static
   let 인스턴스 insert 금지 (SwiftData 모델은 한 context 만 소유 → 크래시). `@Relationship`
   그래프까지 채워야 화면이 산다.
3. **versioned seed-once 플래그 (BLOCK)**: `autobot.seeded.v1` (UserDefaults). emptiness
   기반 금지 — 사용자 삭제분 부활 + feature-spec `value_persisted_after_relaunch` 와 충돌.
4. **게이트를 Slice 1 에 포함 (BLOCK·검증스토리)**: 프롬프트만 고치면 다음 빌드가 실제
   seed 하는지 증명 불가 = app-review:233 처럼 또 하나의 unenforced 가정. Gate 5→6 정적
   체크 `first_launch_seeded` (seeded 인데 진입점에 seed 호출 없으면 FAIL). 기존
   `app_uses_real_repositories` procedural 패턴 재사용.
5. **primary 화면 접지 (BLOCK)**: seed 는 `app-intent.primaryScreenTitle` 모델을 포함
   (주변 모델만 채우면 홈이 비어 vision_judge 통과 못 함). seeded 앱 feature-spec
   postcondition 은 절대값(정확히 N개) 금지 → 상대값(count_increased).
6. **empty 정책 안전 (확인됨)**: `visual_contract.py:281` — fill requirement(풀스크린
   요구) 없으면 occupancy 는 informational, 게이트 fail 안 함. todo/저널은 그런 요구가
   없어 기존 screen-fill/occupies 가 부당하게 막지 않는다. 새 정적 체크도 seeded 조건부.

## Plan (Slice 1 — 코어 + 정적 게이트) — 결과

- [x] 1. `agents/architect.md` — (d) 스키마 `seedPolicy` + 판단 규칙(seeded/empty,
        애매하면 empty) + primary 접지 + feature-spec rule 7(상대값 못박기)
- [x] 2. `agents/data-engineer.md` — step 6 확장 + *Runtime First-Launch Seeding*
        섹션(`seedIfNeeded(_:)` factory·seed-once·@Relationship·품질·코드예시)
- [x] 3. `wiring-patterns.md` — 도입부 시딩 규칙 + Pattern 1 init 호출 + 검증 #5
- [x] 4. `agents/quality-engineer.md` — Critical Rules 에 seed wiring 강제
- [x] 5. `scripts/gate_checks/build.py` — `check_first_launch_seeded`(예외안전·App/*.swift grep)
- [x] 6. `scripts/gate_runner.py` — import + GATE_CHECKS 매핑
- [x] 7. `spec/pipeline.json` — Gate 5→6 `first_launch_seeded` procedural check
- [x] 8. `autobot-app-review/SKILL.md` — seedPolicy 분기 안내로 drift 해소
- [x] 9. CHANGELOG [Unreleased] Added. (CONVENTIONS 는 Info.plist 전용 → seedPolicy
        SSOT 는 architect.md (d), 중복 안 함. README 는 auto-render, drift 0.)

## Verify — 결과
- [x] 전체 슈트 **452 OK** (443→452, 신규 9, 회귀 0) — `python3 -m unittest discover -s tests`
- [x] `render_pipeline_docs.py --check` = up to date / `verify_spec_docs.py` 전부 PASS
      (특히 "Check implementations in gate_runner.py: PASS" = spec↔registry 일치)
- [x] 게이트 4분기 직접 검증: seeded+호출=PASS / seeded+무=FAIL / empty=SKIP /
      legacy=SKIP. + garbled JSON·다른 App 파일 seam 도 테스트로 커버.
- [x] **집계 롤업 안전 (advisor 핵심)**: `gate_runner.py:340-348` 코드 확인 — benign
      skip(skipped only, no degraded)은 `group_passed=True` → 게이트 green 유지,
      배지 영향 0(backend_required N/A skip 과 동일 패턴). legacy 빌드 + 모든 empty
      앱 VERIFIED 유지(광범위 회귀 없음). `test_skip_is_benign_not_degraded` 로 잠금.
- [x] **e2e 직교 확인**: `e2e_verify.py:183-184` 는 logic/flow 두 축만 실행 →
      `first_launch_seeded` 미평가. GreenApp DEGRADED 는 시뮬레이터 부재(환경)이지
      이 변경과 무관. 게이트를 GreenApp/RedApp fixture 에 직접 돌려 skip→pass 확인.
- [x] **advisor 아티팩트 수정**: data-engineer seed 예시의 `try? context.save()` →
      `do/catch + assertionFailure` (프로젝트 자체 `try?` 금지 규칙과의 자가모순 제거,
      seed 실패=빈화면이라 loud fail 이 더 정확).

## Results
- **변경 8파일**: architect/data-engineer/quality-engineer.md, wiring-patterns.md,
  app-review/SKILL.md, gate_checks/build.py, gate_runner.py, pipeline.json (+테스트+CHANGELOG).
- **동작**: architect 가 앱 성격으로 seedPolicy 결정 → seeded 면 data-engineer 가 멱등
  factory 작성 → quality-engineer 가 ModelContainer init 직후 호출 → Gate 5→6 이
  의도-구현 일치를 강제. empty 앱은 전 경로 무영향(기존 게이트도 안 막음, 확인됨).
- **검증 스토리**: 게이트가 없으면 "프롬프트가 시드를 *말하지만* 빌드가 *하는지*"를
  증명 못 함 → app-review:233 의 부패한 가정 재현. 정적 grep 게이트가 그 갭을 닫음.

## Slice 2 (후속, 별도) — 행위 검증
- screen-fill 캡처(commit 9f6cfcf) 재사용해 "primary 화면이 실제로 채워졌나"를
  스크린샷으로 확인. 정적 체크 위에 행위 검증을 얹는다.
- **rule 7 게이트화**: "seeded 면 postcondition 상대값" 은 현재 architect 프롬프트
  지시일 뿐 미강제 — 어기면 seed 베이스라인 vs 절대-개수 acceptance 충돌이
  런타임 functional_flows 에서야 드러난다. Gate 1→2 의 `feature_spec_quality` 에
  "seedPolicy==seeded → 절대-개수 postcondition 거부" 정적 체크 추가 검토.

---

# CI 빨강 수정 — 단위 슈트의 Xcode/시뮬레이터 hard-coupling 제거 (외부 모델 검수 #1·#2·#3)

목적: 외부 모델이 짚은 약점 검증 후 수정. #1+#2 는 근본 원인 1개 — `conftest.IsolatedProjectCase.setUp` 이 `advance-phase 0` 를 돌리고 Gate 0 `environment_ready`(`gate_checks/setup.py`)가 `xcrun`/`xcode-select` 를 live probe 로 hard-fail → 무-Xcode Ubuntu CI 가 0.7.2 이후 ~5릴리스 빨강(맥에선 초록이라 안 보임). #3 버전/README drift.

## 검증 (1차 증거)
- `gh run list`: 최근 CI **5/5 failure**, 각 25–29초(즉시 실패). xcrun shim 으로 로컬 재현 → conftest setUp `AssertionError 1!=0`.
- 다른 hw 테스트는 전부 mock(`test_integration_build_destination`=mock.patch, `test_sim_runtime_selection`=which mock) → breaker 는 fixture Gate 0 단 하나.

## 수정 — 결과
- [x] `gate_checks/setup.py`: Gate 0 가 기존 `AUTOBOT_DISABLE_SIMULATOR`/`AUTOBOT_DISABLE_XCODEBUILD` 를 degraded-skip 으로 존중(sim_runtime/xcodebuild_runner 관례 일관). 프로덕션 live fail-fast 는 플래그 미설정 시 그대로.
- [x] `tests/conftest.py` `_scoped_env`: 두 플래그를 모든 subprocess 에 주입 → 슈트 hermetic, 무-Xcode CI 초록.
- [x] `pyproject.toml` 0.7.1 → 0.9.0. `README.md` stale `# 185 tests` 제거(ci.yml 처럼 숫자 삭제).
- [x] `tests/test_environment_gate_ci.py` 4종(무-플래그 hard-fail / 플래그 degraded-skip / conftest 주입).
- [x] CHANGELOG [Unreleased] Fixed 2건.

## 검증 결과
- **무-Xcode 시뮬레이션(xcrun·xcodebuild·simctl 가림) 전체 슈트 443 OK** (수정 전이면 ~51 실패). 맥 정상 443 OK. verify_spec_docs + render PASS.
- **실제 CI 초록 관측** (시뮬레이션 아님): push 후 run `26719020928` (커밋 0993713) — `unit-and-drift in 25s`, `Unit regression (stdlib unittest)` ✓, EXIT=0. 직전 5/5 빨강이던 워크플로가 초록으로 전환됨.
- 설계 판단: 프로덕션 Gate 0 의 live 시뮬레이터 검사를 약화하지 않음(약화하면 실유저가 무-시뮬레이터에서 Phase 5 까지 갔다 더 비싸게 실패). 단위 컨텍스트만 분리 = advisor 권고안.
- 비차단 관측: CI 에 Node.js 20 actions deprecation 경고(checkout@v4 / setup-python@v5, 2026-06-16 강제 전환 예정) — 이번 범위 밖, 후속.

## 범위 밖 (recurrence 가드, 후속 제안)
- plugin.json ↔ pyproject 버전 동기 강제하는 verify_spec_docs 체크 추가(재드리프트 방지). ci.yml 에 `env:` 명시는 in-process `test_sim_runtime` 와 충돌해 미채택(conftest 가 정확한 seam).

---

# /plan 스토리보드 품질 강화 (preview = 번호 매긴 화면-흐름 보드)

목적: `/autobot:plan` 의 preview(`designs/preview/index.html`)를 *순서 없는 그리드 + 텍스트 덤프* 에서 *번호 매긴 화면-흐름 스토리보드* 로. 근본 진단: 빌더가 architect 가 이미 emit 하는 구조화 산출물(architecture.json / feature-spec.json / design-spec.md 의 Screen Designs·states 섹션)을 안 읽고 architecture.md 산문을 regex 로 긁음.

## 핵심 결정 (Working Notes)
- **화면 번호 1개 메커니즘이 A1(순서)+C2(critique 앵커) 동시 해결.** 정렬된 화면에 ①②③ → 갤러리 카드 `id="screen-N"` → critique 가 `→ 화면 N` 점프 링크.
- preview/index.html **다운스트림 결합 없음** — Gate 2.5→3 은 파일 *존재*만 검사(`spec/pipeline.json:1098`). HTML 내부 자유 재구성 가능. `<!-- CRITIQUE_PLACEHOLDER -->` 마커만 보존(skill Step 3 Edit 의존).
- 정렬 = rootScreens(진입) 먼저 → Tab 그룹(featureModules 순 → 첫등장 순) → 무탭 순. 탭 내부는 원본 Screens 표 순서.

## 작업 — 결과
- [x] **B** crop 제거 — `.iphone-png object-fit: cover/top` → `contain` + letterbox(`--shot-letterbox`). 하단 safe-area 안 잘림.
- [x] **A1** `_load_arch_json` + `_order_screens`(진입→탭그룹, featureModules 순) + `_flow_html`(lane 다이어그램). 원본 nav `<details>` 보존. 렌더 확인: 진입[1.Home]→Feed[2.Feed→3.Detail]→Settings[4.Settings].
- [x] **A2** `_parse_states` + `_parse_interaction` + `_states_section_html`(둘 다 없으면 섹션 생략).
- [x] **A3** `_parse_screen_design_map` 우선, `_build_cards` 가 stem 휴리스틱 fallback. PNG 없는 화면 = placeholder.
- [x] **C2** SKILL.md `화면: N` 필드 + `→ 화면 N` 칩 계약 + 카드 `id="screen-N"` + `:target` 하이라이트 + `.critique-screen` 스타일.
- [x] 회귀 테스트 `tests/test_build_preview.py` 14종.
- [x] CHANGELOG [Unreleased] + plan.md 산문 갱신.

## 검증 결과
- test_build_preview 14/14 OK. 전체 슈트 **439 OK** (회귀 0).
- verify_spec_docs 전체 PASS (Prose contract drift PASS), render_pipeline_docs --check OK.
- fixture 렌더: 4화면 정렬·번호·flow·states(2)·crop-fix(`object-fit: contain`, `cover` 0건)·`screen-1..4` id 확인. FeedView 가 `scr_feed_v2.png`(휴리스틱 불가)로 매칭 = 권위 매핑 작동.

## 범위 밖 (의도적 — 메인테이너 기존 설계 존중)
- **C1 Stitch 자동 재생성 루프**: Phase 2.5 read-only non-goal + Stitch timeout·no-retry 신뢰성 위험. 재생성은 기존 `/autobot:resume 2 --force` 사용자 경로 유지. C2 가 화면별로 무엇을 다시 받을지 정밀 안내.
- **C3 vision-judge pre-code**: vision-judge 는 *빌드된 앱* 대상 Phase 5 게이트(`gate_checks/build.py:95`). Phase 2.5 엔 앱 없음.

## 성공 기준 (DoD) — 결과
- [x] test_build_preview 14/14 green + 전체 슈트 439 OK (회귀 0).
- [x] fixture 로 HTML 생성 시 순서·번호·flow·states·crop-fix·`screen-N` id 확인.
- [x] `<!-- CRITIQUE_PLACEHOLDER -->` 마커 보존. architecture.json/design-spec 섹션 부재 시 graceful fallback 확인.
- [x] **시각 검증 (advisor 지적 반영)**: 구조 문자열만이 아니라 실제 폰 비율(393×852) 목업으로 헤드리스 Chrome 스크린샷 → 하단 탭바/CTA(=cover+top 이 자르던 safe-area) 온전히 표시, ordinal 배지가 status bar 와 겹치지 않음, off-aspect letterbox 우아하게 degrade 확인.

---

# 전역 ASC 자격증명 — set-once (deploy 가 전역 `.env` 를 읽도록)

목적: `/autobot:setup` 한 번으로 ASC creds 를 전역에 넣으면 모든 프로젝트의 deploy(register/upload/invite)가 그걸 읽는다. 현재는 매 프로젝트 `.env` 에 다시 넣어야 함(set-once 마찰). 보안 경계(autobot-setup/SKILL.md:17 — 시크릿은 .env, 식별자는 config.json, 절대 합치지 않음)는 유지: `.env` 를 **프로젝트-로컬→전역**으로 올릴 뿐 config.json 에 시크릿을 넣지 않는다.

## 검증된 현재 상태
- ASC creds(`ASC_API_KEY_ID/ISSUER_ID/KEY_PATH`)는 **register-app.sh / upload.sh / invite.sh 3개 모두** env 에서 읽음. testflight.md:54 Step 0c 가 env 변수만 검사("set in .env").
- **어떤 `.env` 도 source 하지 않음** — 사용자가 직접 export 가정.
- Team ID 는 이미 config fallback(`register-app.sh:160-164` `--team-id > $DEVELOPMENT_TEAM > config.json:developmentTeam`), testerEmails 도 config 사용 → deploy 가 config 를 통째 무시하진 않음. **ASC creds 만 전역화 안 됨.**
- 전역 dir: `~/.autobot/`(`$AUTOBOT_CONFIG_DIR` override, dir 700/file 600, config.sh 소유). 기존 전역 `.env` 관례는 `~/.config/autobot/.env`(load-learnings.sh:13) — **디렉토리 불일치**.
- load-learnings `env_has_key` 는 `^[[:space:]]*KEY=` 매칭 → `export KEY=` 는 탐지 못 함. → 전역 `.env` 는 **`KEY='value'`(export 없이)** 로 써야 `set -a` source + load-learnings 탐지 둘 다 만족.

## 설계 (A 정제판 — 경계 유지)
- 표준 전역 `.env` = **`~/.autobot/.env`**(config.json 옆, 700 dir). `~/.config/autobot/.env` 는 legacy 로 계속 탐지.
- `/autobot:setup` 이 ASC creds 를 물어 `~/.autobot/.env` 에 기록(chmod 600). config.json 은 식별자만.
- deploy 스크립트가 `${AUTOBOT_CONFIG_DIR:-$HOME/.autobot}/.env` → 프로젝트 `.env` 순으로 self-source(에이전트 컨텍스트 무관). 프로젝트가 전역 override.

## 작업 (슬라이스) — 결과
- [x] S1 config.sh: `env-path`/`set-env`/`get-env`. `KEY='value'`(single-quote escape) upsert + dir 700/file 600. round-trip·escape·upsert·600·grep 호환 모두 검증.
- [x] S2 setup.md §3.7 (ASC creds → `config.sh set-env`, 시크릿이라 config.json 아님) + §4 set-env 기록 + SKILL.md Storage 재작성(두 파일 역할·경계·set-once·`AUTOBOT_ENV_FILE`).
- [x] S3 register-app.sh / upload.sh / invite.sh: **don't-clobber 루프**(단순 `set -a` 폐기). precedence **inherited env > project ./.env > 전역 ~/.autobot/.env**. testflight Step 0c / app-review: 전역→프로젝트 source + 안내 갱신.
  - 정정 1: 단순 `set -a; source` 는 files-win 이라 전역 `.env` 가 test 의 env-주입 creds 를 덮어 비-hermetic → don't-clobber(env 이김)로 교체.
  - 정정 2: `_k="${_line%%=*}"` 는 `export KEY=`(signing-guide 권장)를 skip → leading-ws + `export ` prefix strip 추가.
- [x] S4 load-learnings.sh: ENV_FILE 탐색 = 프로젝트 → ~/.autobot/.env → legacy ~/.config/autobot/.env.
- [x] S5 `tests/test_global_env_secrets.py` 13종(config.sh 10 + deploy precedence/export-form). 전체 슈트 414 OK + CHANGELOG + verify_spec_docs/render PASS.

## 보안 (결과)
- 시크릿은 `~/.autobot/.env`(700/600)만, `.p8` 는 디스크에 그대로(경로만 기록). config.json 엔 시크릿 0 (경계 유지).
- deploy 스크립트가 self-source(에이전트 컨텍스트 무관). 명시적 export 가 항상 이김(precedence) → 테스트 hermetic + 사용자 의도 존중.
- 깨진 .env 라인은 `eval` 실패 → `set -e` loud fail (사용자 자기 파일, silent 보다 나음).

---

# Autobot 구조 개선 — 검수 보고서 기반 작업

목적: 검수 리포트에서 식별된 P0~P2 결함 전부 수정. 더이상 수정이 불필요한 상태로 만들기.

## 합의된 설계 결정 (Working Notes)

1. **complete-phase + run-gate 통합 (P0 #1)**: 기존 `complete-phase`를 그대로 두면 호출자 부담이 큼. 새 명령 `advance-phase --phase N`을 만들어 `run-gate` → 통과 시에만 `complete-phase`. fail 시 phase 상태는 `failed`로 자동 마킹. 기존 `complete-phase`는 호환용으로 남겨두되 mvp.md/resume.md는 `advance-phase`만 사용.

2. **gate 경로 통합 (P0 #2)**: `validate-state.sh run-gate`를 제거(BC 깨뜨림 명시). `pipeline.sh run-gate`만 정설. `validate-state.sh`는 schema/transition validate처럼 read-only 기능만.

3. **build_succeeded SSOT (P0 #3 + P1 #4)**: integration-build/SKILL.md가 phase 5 metadata.build_succeeded=true를 명시 기록. gate_runner.py의 build-log fallback 완전 제거. truth source는 phase metadata 단 하나.

4. **이벤트 스키마 (P1 #5)**: `spec/log-events.json` 신설. event 이름 → required/optional 필드. runtime.py와 build-log.sh가 같은 검증 로직 공유. unknown event는 거부.

5. **declarative gate (P1 #6)**: `spec/pipeline.json`의 gate.checks가 단순 string에서 descriptor 객체로 진화. 기존 string 형식은 BC 유지 (procedural hook으로 fallback). 새 primitive: file_exists, dir_exists, dir_has_swift, file_grep, file_grep_negative, command_success. when 조건: backend_required, phase_status_eq, phase_not_fallback.

6. **fileOwnership SSOT (P1 #7 + #8)**: `spec/pipeline.json`의 phases.<id>.fileOwnership 추가. agent-sandbox.sh가 spec 읽어 enforce + 위반을 phases.<id>.sandbox.violations에 state 기록. Gate 4→5 checks에 sandbox_clean 추가.

7. **circuit breaker (P2 #9)**: runtime의 transition validator가 maxConsecutivePhaseFailures 검사. 임계 도달 시 in_progress 진입 거부. circuit_open 이벤트 기록.

8. **backend_required CLI (P2 #10)**: runtime.py에 `set-flag --key backend_required --value true` 추가. flag_changed 이벤트.

9. **learning_applied 추적 (P2 #12)**: agents/*.md에 학습 적용 후 build-log.sh 호출 의무. event=learning_applied. agents가 자율로 기록. state.learnings_consumed[phase] 누적.

10. **runtime.py 모듈 분리 (P2 #11)**: 정규화된 모듈 — `state_store.py`, `transitions.py`, `event_log.py`, `gate_persistence.py`, `cli.py`. runtime.py는 thin entry. 동작 변경 없음.

## 작업 순서 (loop budget 10)

- [x] Loop 1: 1차 진단 + codex 검토 + 통합 리포트
- [x] Loop 2: P0 #1 (advance-phase) + P0 #2 (gate path) + P0 #3 + P1 #4
- [x] Loop 3: P1 #5 (logEvents in spec, runtime+sh 공통 검증)
- [x] Loop 4: P1 #6 (declarative gate) + P1 #7 (fileOwnership in spec)
- [x] Loop 5: P1 #8 (sandbox_runner.py + state 기록 + sandbox_clean check)
- [x] Loop 6: P2 #9 (circuit breaker enforcement) + P2 #10 (set-flag) + P2 #12 (learning_applied 이벤트 + agent 인스트럭션)
- [x] Loop 7: P2 #11 (runtime.py 분리) — 1225L → 66L facade + 6개 모듈. 회귀 없음 검증.
- [x] Loop 8: 검증 통과 (verify_spec_docs all PASS, smoke test 정상)
- [x] Loop 9: README + orchestrator/SKILL.md 산문 갱신
- [x] Loop 10: lessons.md + 최종 점검

## 성공 기준 (DoD) — 결과

- [x] complete-phase 후 gate 실패가 비일관 상태를 만들지 않는다 → advance-phase가 gate 실패 시 phase를 `failed`로 마킹 (smoke 검증)
- [x] gate 실행 경로 1개 → `pipeline.sh run-gate`만 mutating, `validate-state.sh run-gate`는 명시적 ERROR 메시지로 차단
- [x] Phase 5 build_succeeded는 `phases.5.metadata.build_succeeded`만으로 판정 → build-log fallback 0줄 (smoke로 missing/false/true 케이스 모두 검증)
- [x] `spec.logEvents`가 SSOT, runtime/build-log.sh가 공통 검증 (unknown event 거부, required field 거부 동작 확인)
- [x] `spec.fileOwnership` 선언, sandbox_runner.py가 spec 읽음 → 새 agent 추가 시 spec만 갱신하면 enforcement 따라옴
- [x] Gate 4→5에 sandbox_clean 체크 포함 → 위반이 `phases.4.sandbox.violations`에 자동 기록 + gate가 잡아냄
- [x] circuit breaker가 runtime의 transition validator에서 enforce (global scope)
- [x] runtime.py 분리 완료. 1225L → 66L facade + 6개 모듈 (spec_loader/state_store/event_log/transitions/gate_persistence/cli). BC 호환을 위해 runtime.py가 외부 import 표면을 re-export
- [x] verify_spec_docs.py 모든 카테고리 PASS, render_pipeline_docs.py --check 통과

---

# v0.5.0 사이클 — declarative gate + axiom/peer bridge 정착

목적: Phase 5/Gate 5→6 에서 빌드는 통과하지만 런타임에서 깨지는 결함(Swift 6 data race, SwiftData 손실, 누수, SwiftUI 구조) 을 차단. 자기개선 루프의 마지막 마디(학습 효과 점수화 + 컨텍스트 팩) 도입.

## 작업 결과 (커밋 분할)

- [x] C1 — `feat(env)`: record-environment 에 runtimeHost / peerAi / peerReviewAvailable 3 필드 추가 (cli/state_store/conftest)
- [x] C2 — `feat(tools)`: 신규 헬퍼 모듈 14개 + 회귀 테스트 9종 + hooks/sandbox-pre-write.sh
- [x] C3 — `feat(bridge)`: detect-axiom.sh / detect-peer-ai.sh + autobot-axiom-bridge / autobot-peer-review-bridge SKILL.md
- [x] C4 — `feat(v0.5.0)`: declarative gate 확장(+620 in gate_runner) + spec(+290) + agent/command/orchestrator/integration/scaffold/retrospective SSOT 위임 + test_peer_review_bridge / test_axiom_and_peer_strict
- [x] C5 — `chore`: CHANGELOG [0.5.0] + plugin.json 0.4.0→0.5.0
- [x] C6 — `feat(hooks)`: PreToolUse sandbox-pre-write 정식 등록

## 성공 기준 (DoD)

- [x] 회귀 슈트 148/148 PASS — 각 토픽 커밋 직후 stash 격리로 검증
- [x] CHANGELOG [0.5.0] — 신규 모듈 14개, 회귀 테스트 11종, 거대 리팩토링, 핵심 변경 7항목 모두 기록
- [x] plugin.json version 0.5.0 으로 bump
- [x] hooks/sandbox-pre-write.sh 활성화 — 마커 없을 때 no-op + 마커 있을 때 broad-access 동작 검증
- [ ] smoke e2e 도입 — 단위로 못 잡는 회귀(실제 simulator 부팅, xclog 캡처, ASC 자격 검증) 보호
- [ ] Pillow API: getdata() → get_flattened_data() — visual_contract.py:89 DeprecationWarning 제거 (Pillow 14 / 2027-10-15 제거 예정)

## 후속 사이클 후보

1. **smoke e2e CI** — nightly 로 "Hello World 앱 1개 build + simulator boot + xclog capture" 시나리오 자동 실행. 회귀 슈트가 잡지 못하는 Xcode 26 / iOS 26 시뮬레이터 회귀 보호.
2. **declarative gate primitive 일반화** — gate_runner.py lazy import 라우팅을 spec 의 `gate.primitives` 등록표로 외부화하면 신규 primitive 추가 시 코드 변경 0.
3. **learning effect_score 자동 회귀** — `learning_impact.py` 가 5빌드 이상 누적될 때 effect_score 분포를 기반으로 한 학습 제거 추천 기능.
4. **peer-review verdict 캐싱** — 동일 input_hash 의 phase 재실행 시 peer-review 재호출 절약 (API/요금 비용 절감).

---

# 계약 동결 (frozen-by-default contracts) — resume drift 차단

목적: 검증된 약점 #4 수정. `/autobot:resume 1`(또는 `--force`/구 빌드)이 비결정적 architect 를 재실행해 타입 계약(Models/ServiceProtocols)을 갈아끼우면, 이미 작성된 downstream Views/Services 가 옛 심볼명을 참조한 채 조용히 컴파일이 깨진다. snapshot 까지 덮어써 되돌릴 수도 없다.

## 설계 결정 (Working Notes)

1. **input_hash 와 직교.** input_hash 는 "입력 불변 → phase skip"(architect 안 돔). 동결은 architect 가 *실제로 재실행될* 상황(force/입력변경/hash 미저장)에서 downstream 보호. 둘은 겹치지 않음.
2. **결정은 결정적 스크립트에.** 정책(frozen 판정)은 `contract_freeze.py`, resume.md 는 호출만 (lessons #5 — 정책은 산문이 아니라 엔진에).
3. **downstream 탐지는 spec.fileOwnership SSOT 에서 도출** — Phase-4 agent writes 의 dir 중 .swift 보유. backend/·Assets 는 .swift 없어 자동 제외 (하드코딩 0).
4. **frozen-by-default + opt-in.** 위험한 재생성은 `--regenerate-contracts` 명시할 때만. git `--force` 패턴.
5. **복원 실패 → halt.** 동결해야 하는데 snapshot 복원 실패 시 silent regenerate 금지 (`action: error`). 막으려던 drift 를 fallback 으로 일으키지 않음.
6. **재생성은 forward pass 로 cascade.** `--regenerate-contracts` 시 Models 체크섬 변경 → 이후 phase input_hash miss → Phase 4 가 새 계약에 맞춰 재생성. 추가 코드 불필요.

## 작업

- [x] `scripts/contract_freeze.py` — decide/apply + CLI
- [x] `spec/pipeline.json` logEvents.contracts_frozen
- [x] `scripts/pipeline.sh` freeze-contracts passthrough + USAGE/comment
- [x] `commands/resume.md` Phase 1 재개 freeze-aware + --regenerate-contracts 파싱
- [x] `CHANGELOG.md` [Unreleased]
- [x] `tests/test_contract_freeze.py` — decide matrix + apply 복원/로그 + pipeline.sh passthrough
- [x] Verify: contract_freeze 8/8 PASS, verify_spec_docs 전부 PASS (prose drift 포함)
- [x] adversarial review (advisor) 2건 반영: `--regenerate-contracts` 가 skip 루프보다 먼저 평가돼 조용한 no-op 되는 버그 → force 동일 취급으로 수정 / 동결 분기에 `completed→in_progress`(allow-terminal-restart) 명시

## 성공 기준 (DoD) — 결과

- [x] snapshot+downstream+¬regen → frozen=true, Models 가 snapshot 으로 복원 (drift 된 내용 사라짐) — `test_apply_restores_models_from_snapshot`
- [x] --regenerate-contracts → frozen=false, Models 손대지 않음 — `test_apply_leaves_models_untouched_when_regenerate` + skip 루프가 force 로 phase 1 재실행 보장 (building block: should_skip force=True → skip=False)
- [x] downstream 없음 / snapshot 없음 → frozen=false — `test_no_downstream_not_frozen` / `test_no_snapshot_not_frozen`
- [x] 동결 시 검증된 `contracts_frozen` 이벤트 1건 append — apply 테스트 + event_log 검증(detail 누락 시 거부)
- [x] 회귀 슈트 + verify_spec_docs PASS — 신규 8/8, 전체 385 중 2 실패는 **pre-existing**(phase 2.5, stash 격리 확인, 내 변경 무관)

## 후속 (이번 범위 밖)

- 더 강한 enforcement: architect sandbox 가 resume-with-downstream 에서 Models/ 쓰기를 거부 (현재는 resume.md 호출 의존). v1 은 결정 로직만 엔진화.
- feature-spec.json drift (현재 Models snapshot 만 동결; feature-spec 은 functional gate 영향, 컴파일 아님).
- ~~**별건 pre-existing red (main @ 0.7.2)**~~ **[FIXED]**: phase 2.5 도입 부산물 2건을 root-cause 로 수정.
  - `test_phase_advance_fallback_timing` 2건 실패 → **stale 픽스처** (state 인라인 phases 가 2.5 누락; `init_state`/`default_phases` 는 2.5 를 seed 하고 state validation 이 모든 spec phase 를 요구). 픽스처에 `"2.5": {"status":"pending"}` 추가. (다른 인라인 phases 픽스처는 grep 으로 0건 확인.)
  - verify_spec_docs `check_phase_count` 경고 → **checker 의 regex 버그**. `^\|\s*\d+\s*\|` 가 정수 id 만 매치해 `| 2.5 |` 행을 누락(8행), spec 은 9 → spurious. 0.7.2 의 `render_pipeline_docs int→float` 수정 때 같이 안 고쳐진 곳. regex 를 `\d+(?:\.\d+)?` 로 일반화. SKILL.md 표 자체는 정상(9행, auto-rendered)이었음.
  - 회귀 가드: `test_verify_spec_docs_contracts.test_phase_count_handles_fractional_ids` (regex 회귀 또는 2.5 행 손실 즉시 검출).
  - 검증: 전체 슈트 386 tests OK, verify_spec_docs "All checks passed" (경고 0).

---

# #2 디자인 의도 게이트 (vision judge) — 빌드된 앱 ↔ 디자인 충실도 검증

목적: 검증된 약점 #2 수정. 오늘 Phase 5 의 `check_visual_contract` 는 deltaE 색-매치를 informational-only 로만 출력(`visual_contract.py:225-228, 251`) → 디자인을 무시한 빌드(예: 커스텀 coral 팔레트인데 system-blue 렌더)도 ✅ VERIFIED 로 통과. 빌드된 앱의 실제 스크린샷을 디자인 의도(design-spec + Stitch 목업)와 **멀티모달 vision judge** 로 비교해, 충실도가 깨지면 배지를 DEGRADED 로 떨어뜨려 **shipping 을 차단**한다.

## 핵심 아키텍처 결정 (워크플로우 wf_e07cf73c-899 + 직접 read 로 검증)

1. **vision judge 는 에이전트, 게이트 체크는 결정적 — 분리 (load-bearing).** `visual_contract.py` 는 순수 Python(Pillow)이라 LLM 호출 불가. judge 는 Claude 가 PNG 를 Read 하는 **에이전트 디스패치** (Phase 2.5 plan-preview Step 2 와 동일 메커니즘). 패턴은 `check_build_succeeded`(build.py:36-54): **에이전트 작업 → `phases.5.metadata` 기록 → 결정적 게이트 체크가 읽음.** ⚠️ 워크플로우 일부 에이전트가 "judge 를 visual_contract.evaluate() 안에 넣어라"고 제안했으나 이는 오류 — 반영 안 함.

2. **DEGRADED-only, hard-fail 안 함 (자율 안전성).** `phase_advance.py:158-160`: gate 5->6 (soft=False) hard-fail → Phase 5 status=failed + retryCount++ → 글로벌 circuit breaker(합 3)가 trip → **자율 /mvp 가 멈춤.** vision judge 는 비결정적이고 ground-truth 없이 ~10 합성 빌드로 calibrate → hard-fail 시키면 false-positive 가 "질문 없이 끝까지" 핵심 가치를 깸. 따라서 judge fail → `_ok(True, skipped=True, degraded=True)` (DEGRADED), **절대 `_ok(False)` 반환 안 함.** shipping 차단은 배지 경로로: DEGRADED → not shippable → `/autobot:testflight`·`/autobot:app-review` 가 업로드 거부 (mvp.md:97, run_summary shippable==VERIFIED). 즉 자율 빌드는 완주하되 디자인 깨진 앱은 출하 불가.

3. **escape-hatch `--allow-visual-drift` (freeze-contracts 패턴 미러).** resume-only(/(mvp 는 자율이라 플래그 없음). 세팅 시 judge fail → `_ok(True)` green + `visual_drift_allowed` 이벤트 → 배지 VERIFIED 회복 → 사람이 의도적으로 출하. one-shot(미영속), `--regenerate-contracts` 와 동형.

4. **judge verdict 구조 = Phase 2.5 critique 재사용.** `{verdict: pass|fail, violations:[{severity:high|medium|low, axis, title, evidence, fix}], summary}`. verdict=fail ⟺ HIGH severity 충실도 위반 ≥1. evidence 인용 강제(위반 토큰 vs 관측 색, 부재 화면명)로 단일-judge false-positive 완화.

## 검증된 좌표

- 스크린샷: `sim_runtime.py` → `artifacts/{buildId}/phase-5/runtime-smoke/screenshot.png` (or `.autobot/phase-5/runtime-smoke/screenshot.png`). `visual_contract.py:_default_screenshot()` 가 이미 해석. 단일 launch 스크린샷(per-screen 아님).
- 디자인 의도: `.autobot/design-spec.json`(토큰) + `.autobot/design-spec.md` + `.autobot/designs/*.png`(Stitch 목업).
- 게이트 롤업: `_ok(True, skipped=True, degraded=True)` → gate.degraded → 배지 DEGRADED (gate_runner.py:338-347, run_summary.py:202-208).
- event 선언: `spec/pipeline.json` logEvents (contracts_frozen @319 미러). 미선언 시 event_log.py:77 FATAL.
- gate 체크 등록: gate_runner.py GATE_CHECKS + spec gate 5->6 checks.

## 작업 — 결과

- [x] T1 — 별도 스킬 대신 **integration-build Step 9** 로 접음(최소·일관). quality-engineer(멀티모달 Claude)가 스크린샷+의도 Read→충실도 verdict→`.autobot/artifacts/visual-judge.json` + 최종 advance-phase `--metadata visualJudge`.
- [x] T2 — `check_visual_judge` (gate_checks/build.py). DEGRADED-only 매핑. 10종 단위테스트 PASS.
- [x] T3 — gate_runner.py GATE_CHECKS 등록 + spec gate 5->6 checks 추가. `list-checks` ✓ 확인.
- [x] T4 — `visual_judge_verdict` 이벤트 선언. (`visual_drift_allowed` 는 set-flag 의 `flag_changed` 로 대체 — 불필요해 제거.)
- [x] T5 — `--allow-visual-drift` → top-level `allowVisualDrift` 플래그(set-flag 재사용, **영속**). resume.md Step 0.5 파싱. end-to-end 검증(set-flag OK, 미등록 플래그 FATAL).
  - 정정: 중첩 `allowances.visualDrift` → top-level `allowVisualDrift`. testflight 가 플래그 없이 게이트 재실행하므로 **영속 필요**(one-shot 폐기).
- [x] T6 — Phase 5 디스패치 위치 = integration-build Step 9 (orchestrator 가 quality-engineer 에 이 스킬을 위임). 별도 top-level 디스패치 불필요.
- [x] T7 — `tests/test_visual_judge_gate.py` 10종. 전체 슈트 398 PASS.
- [x] T8 — CHANGELOG [Unreleased] Added. verify_spec_docs + render_pipeline_docs PASS.

## 해소된 미해결
- **DEGRADED-only 정책** (advisor 검토): BLOCKER #1(DEGRADED 가 출하를 코드로 막는가)을 `commands/testflight.md:114 exit 1` + `check_functional_verification_passed` 로 확인 → DEGRADED-only 가 정답(hard-fail 불필요). hard-block 은 circuit breaker 로 자율빌드를 멈추므로 미채택.
- **T6 위치**: integration-build Step 9 (Step 7 axiom / Step 8 peer-review 와 동일 패턴).

## advisor 2차 검토 반영 (둘 다 green 슈트가 구조적으로 못 보는 경로)
- **#1 metadata round-trip 직접 검증**: `--metadata visualJudge='{...}'` 가 state 에 **dict 로** 저장되는지 (string 이면 게이트가 silently inert) → `parse_key_value`→`parse_json_value` 가 JSON 디코드 확인 (`isinstance dict: True`). 게이트 정상 작동.
- **#2 anti-laundering 의식적 결정**: verdict 부재 시 무조건 benign-skip 은 VERIFIED 경로(sim 있음→스크린샷 존재)에서 Step 9 미실행 빌드를 VERIFIED 로 세탁 → 약점 재개방. `functional_flows_pass`/`peer_review_acceptable` 선례 미러: **스크린샷 존재 시 verdict 부재/garbled → DEGRADED**, 스크린샷 부재 시만 benign-skip. `allowVisualDrift` 는 전체 면제. 테스트 10→13 으로 확장(anti-laundering 매트릭스).

## 알려진 v1 한계 / 후속
- **이중 스크린샷 캡처**: Step 9 가 judge 용으로 1회, 게이트의 `check_runtime_smoke` 가 liveness 용으로 1회. testflight 의 fresh 재검증 속성 보존을 위해 의도적. sim 이 이미 부팅돼 있어 비용은 launch+screenshot 1회. 후속: 게이트가 Step9 의 fresh 캡처를 재사용하도록 dedupe.
- **judge 보정**: tolerance/판정이 ground-truth 없이 ~10 빌드 기준 → 보수적 "애매하면 pass". 실 빌드 누적 후 fail 기준 정교화.
