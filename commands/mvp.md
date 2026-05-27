---
name: mvp
description: "앱 아이디어를 입력하면 질문 없이 엔터프라이즈급 iOS 26+ MVP를 로컬에서 빌드합니다. TestFlight 업로드는 /autobot:testflight 로 분리되어 있습니다."
argument-hint: "<앱 아이디어 설명>"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - Skill
  - TaskCreate
  - TaskUpdate
  - TaskList
  - WebSearch
  - WebFetch
---

# Autobot MVP — 한 줄 아이디어 → 로컬 iOS 빌드

이 명령은 진입점일 뿐이다. Phase 정의·상태 전이·Gate·Retry는 **`spec/pipeline.json`** 이 SSOT 이고, 실행 절차는 **`autobot-orchestrator` 스킬**이 관리한다. 이 문서가 spec 과 충돌하면 spec 이 이긴다.

`/autobot:mvp <아이디어>` 는 Phase 0–5 + Phase 7 까지만 실행한다. Phase 6 (TestFlight) 는 `/autobot:testflight` 가 트리거한다 — 의도된 분리.

## CRITICAL RULES

1. **자율 실행**: 로컬 파일 생성·수정·빌드·테스트·archive·resume 은 묻지 않고 진행한다.
2. **병렬 우선**: Phase 4 의 ui-builder/data-engineer/(backend-engineer) 는 한 메시지에서 동시에 디스패치한다.
3. **상태는 runtime 으로만 기록**: `.autobot/build-state.json` 직접 편집 금지. `scripts/pipeline.sh` 경로만 사용한다.
4. **CWD 고정**: Phase 0 에서 생성한 프로젝트 디렉토리가 CWD. 에이전트/스크립트는 모두 상대 경로. `cd` 로 이탈하지 않는다.

## Safety Policy

- `autonomous`: 로컬 생성·수정·빌드·테스트·archive·재시도 — 묻지 않는다.
- `warn`: Stitch·fastlane·ASC 미설치처럼 결과가 달라지지만 진행은 가능한 상황 — 경고 후 계속.
- `require_confirmation`: 원격 저장소 생성/푸시, 외부 시스템에 되돌리기 어려운 변경 — 기본 파이프라인에서 제외.

## 실행 흐름

`autobot-orchestrator` 스킬을 즉시 invoke 한다. 스킬은 `spec/pipeline.json` 을 SSOT 로 읽어 Phase 0 부터 순차/병렬로 실행한다. 이 명령 문서는 절차를 **다시 적지 않는다** — drift 가 생기기 때문이다.

스킬이 책임지는 단계 요약 (상세는 SSOT 와 스킬 참조):

- **Phase 0** — 빌드 잠금, 환경 감지 (`pipeline.sh env-snapshot ensure`), `build-state.json` init, 앱 이름 결정. env_snapshot 은 Xcode/SDK/simulator UDID/ASC 자격증명 상태를 한 번 캡처해 이후 phase 가 simctl 을 다시 조회하지 않도록 한다.
- **Phase 1** — architect → `architecture.md` + `Models/` + `ServiceProtocols.swift` + peer review 게이트
- **Phase 2** — ux-designer (Stitch primary, fallback 시 design-spec 만으로 진행) + `autobot-app-icon` 스킬로 1024 PNG 아이콘 생성 (필수, gate-enforced)
- **Phase 3** — Xcode 프로젝트 scaffold + Composition seam + PrivacyInfo + entitlements + AppIcon.appiconset apply (gate-enforced)
- **Phase 4** — ui-builder ∥ data-engineer ∥ (backend-engineer) 병렬 디스패치 + sandbox 사전/사후 검증
- **Phase 5** — quality-engineer 통합 빌드 + axiom critical audit + peer review + runtime smoke + visual contract
- **Phase 7** — build-report + learnings 누적 (Phase 6 는 `pending` 으로 남김)

각 Phase 전후의 `start-phase` / `advance-phase` 호출, gate 실행, snapshot 저장, error recovery 흐름은 스킬과 spec 만 본다.

## /autobot:mvp 가 트리거하지 않는 것

- Phase 6 (TestFlight archive/upload/invite) — `/autobot:testflight`
- App Store 메타데이터 — `/autobot:meta`
- 원격 git 저장소 생성/푸시
- ASC 자격증명 수정

## 중단 / 실패 시

`/autobot:resume` 으로 마지막 실패 지점부터 자동 재개한다. Phase 번호를 명시하면 그 Phase 부터 강제 재실행한다.

## 완료 보고

스킬이 Phase 7 까지 마치면 다음을 1 화면으로 출력한다:

- 앱 이름·식별자·번들 ID
- 프로젝트 경로
- 시뮬레이터 실행 안내 (`open <AppName>.xcodeproj` → Run)
- 실패한 Phase 가 있으면 `/autobot:resume` 안내
- TestFlight 업로드 옵션 안내 (`/autobot:testflight`)

자세한 출력 포맷은 `autobot-build-report` 스킬과 `autobot-orchestrator` 의 "완료 보고" 섹션이 관리한다.
