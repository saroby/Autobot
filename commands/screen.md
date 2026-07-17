---
name: screen
description: "앱 화면 하나를 집중 인터뷰로 깊게 기획하고, SSOT 문서(SOUL.md · AGENTS.md · CLAUDE.md · docs/screens/)와 로직 제외 SwiftUI 뷰코드까지 산출합니다. Autobot 파이프라인과 무관하게 아무 앱 프로젝트에서나 사용 가능한 독립 명령입니다."
argument-hint: "<화면 이름 또는 한 줄 설명> (예: 홈 피드, '운동 기록을 캘린더로 보는 화면')"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Skill
  - AskUserQuestion
  - WebSearch
---

# Autobot Screen — 화면 하나 집중 인터뷰 → SSOT + SwiftUI 뷰

> **이 문서는 진입점이다. 실행하지 않는다.**
> 인터뷰 절차·SSOT 병합 규칙·뷰코드 계약의 SSOT 는 **`autobot-screen-interview` 스킬**이 소유한다.

- **입력** — 화면 이름 또는 한 줄 설명 (생략 시 인터뷰 첫 질문으로 대상 화면부터 확정)
- **결과물** — `docs/screens/<slug>.md` (화면 spec, 인터뷰의 주 산출물) + `SOUL.md` / `AGENTS.md` / `CLAUDE.md` 생성·병합 + presentation-only SwiftUI 뷰 (`<ScreenName>View.swift`, 상태별 `#Preview` 포함) + **Xcode 스캐폴드(없으면 생성) 후 프리뷰 캔버스로 결과 표시** (`xed`)

`/autobot:mvp` 의 화면 대량 생산과 반대 방향이다: **화면 하나 = 깊이의 단위.** 인터뷰로 존재 이유·콘텐츠 위계·인터랙션·상태·룩앤필을 끌어내고, 결정을 SSOT 문서에 남겨 이후 세션의 어떤 에이전트든 같은 맥락에서 이어 일할 수 있게 한다.

## 왜 이 명령이 있는가

화면을 나열식으로 생성하면 각 화면이 "왜 존재하는가" 없이 레이아웃만 남는다. 이 명령이 잡으려는 실패 모드:

1. **얕은 기획** — 화면의 훅·3초 가치·성공 기준 없이 UI 요소만 나열 → 인터뷰 R1 이 잡음
2. **맥락 증발** — 기획 결정이 대화에만 남고 세션이 끝나면 사라짐 → SSOT 문서(라운드마다 즉시 기록)가 잡음

## CRITICAL RULES

1. **화면 하나에만 집중** — 다른 화면 아이디어가 나오면 `docs/screens/<slug>.md` 의 "미결/후속" 에 기록하고 스코프를 지킨다.
2. **코드·문서에서 알 수 있는 것은 묻지 않는다** — 인터뷰 전에 프로젝트를 스캔하고, 이미 결정된 것은 확인만 받는다.
3. **라운드마다 기록** — 인터뷰 중간 결과는 대화가 아니라 `docs/screens/<slug>.md` 에 남는다. 세션이 끊겨도 그 파일에서 재개한다.
4. **뷰코드는 로직 제외** — 네트워크·저장·ViewModel 금지. mock 주입 + 콜백 파라미터 + 상태별 `#Preview`. 정의는 스킬이 소유.
5. **기존 SSOT 비파괴** — SOUL.md/AGENTS.md/CLAUDE.md 가 이미 있으면 이번 인터뷰에서 드러난 것만 병합하고, 기존 내용을 임의 삭제하지 않는다.
6. **빌드 검증은 advisory** — 컴파일 확인이 실패해도 산출물은 남기고 원인을 보고한다. hard fail 금지.

## 실행 흐름

`autobot-screen-interview` 스킬을 로드하고 그 절차를 따른다:

1. **Step 0 컨텍스트 스캔** — 프로젝트 구조·기존 SSOT·`.autobot/` 산출물(있으면) 파악, 대상 화면 확정
2. **R1–R5 인터뷰** — 존재 이유 → 콘텐츠 위계 → 인터랙션 → 상태 → 룩앤필 (혼합: 갈림길은 AskUserQuestion, 열린 질문은 대화)
3. **R6 확정** — 최종 spec 스냅샷 승인
4. **산출물 생성** — SSOT 생성·병합 + SwiftUI 뷰 + 컴파일 확인 + **Xcode 열기(프리뷰 캔버스가 결과 화면)** + 최종 보고
