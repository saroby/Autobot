---
name: clone
description: "실기기에 연결된 iPhone 과 App Store 리스팅에서 기존 앱을 분석해, Autobot 이 원본 앱을 새로 빌드할 수 있는 제품 브리프(`.autobot/clone-analysis/brief.md`)를 재구성합니다. 대상 앱의 이름·에셋·상표는 복제하지 않는 경쟁 분석용 도구입니다."
argument-hint: "<앱 이름 또는 App Store URL> (예: 'Things', 'https://apps.apple.com/app/id...')"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Skill
  - AskUserQuestion
  - WebFetch
  - WebSearch
---

# Autobot Clone — 기존 앱 분석 → 원본 재구현 브리프

> **이 문서는 진입점이다. 실행하지 않는다.**
> 분석 절차·데이터 소스·법적 경계·산출물 계약의 SSOT 는 **`autobot-clone-analyze` 스킬**이 소유한다.

- **입력** — 분석할 앱 이름 또는 App Store URL (생략 시 첫 질문으로 대상부터 확정)
- **결과물** — `.autobot/clone-analysis/brief.md` (architect 의 `architecture.md` 섹션에 대응하는 제품 브리프) + 실기기/스토어 스크린샷 + 리뷰 인사이트
- **다음 단계** — 브리프를 `/autobot:plan` 또는 `/autobot:mvp` 에 넘겨 **원본 앱**을 빌드

## 무엇을 만드는가

대상 앱을 **베끼는 게 아니라**, 그 앱이 왜 다운로드되고 왜 다시 열리는지(기능·구조·훅·리텐션·디자인 방향)를 실기기 화면과 스토어 메타로 재구성해 **새 원본 앱의 기획 입력**으로 만든다. 대상 앱의 이름·로고·에셋·상표는 브리프에 넣지 않는다.

## 두 개의 데이터 소스

1. **실기기 (idb)** — 연결된 iPhone 에서 `idb screenshot` + `idb ui describe-all`(접근성 트리) 로 화면과 **구조**를 캡처. 접근성 트리(요소 role·label·좌표)가 재구성의 1급 소스. **Developer Mode + Trust + 잠금 해제 필요**. idb 는 `ui tap`/`swipe` 로 에이전트가 직접 넘길 수도 있으나 기본은 사람 주도.
2. **App Store 메타 (mcp-appstore)** — 설명·스크린샷·리뷰·유사앱·키워드. 기기 없이 항상 가능한 최소 backbone.

둘 중 하나만 있어도 진행한다. 기기가 없으면 스토어 메타 중심으로 브리프를 만든다.

## CRITICAL RULES

1. **복제 금지 경계** — 이름·로고·상표·에셋·문구를 그대로 옮기지 않는다. 재구성은 *방향*이지 *복제물*이 아니다. 브리프 상단에 경계를 명시한다.
2. **사람 주도가 기본** — idb 로 에이전트가 탭/스와이프해 넘길 수 있지만, 모르는 앱 블라인드 탐색은 로그인·결제·파괴적 버튼 위험이 있어 기본은 사용자가 핵심 화면을 열고 스킬이 덤프한다. 에이전트 주도는 사용자 명시 요청 시만, 파괴적 요소는 건너뛴다.
3. **파이프라인 상태 위조 금지** — 이 명령은 gate-valid `build-state.json`/`architecture.json` 을 만들지 않는다. 브리프는 architect 의 *입력*이고, `/autobot:plan`·`/autobot:mvp` 가 정식 산출을 만든다.
4. **부분 성공 = 성공** — 일부 화면 캡처 실패해도 핵심 흐름이 커버되면 진행. 캡처 불가 시 스토어 메타 fallback.

전체 절차는 `autobot-clone-analyze` 스킬을 로드해 그대로 따른다.
