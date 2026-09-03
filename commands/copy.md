---
name: copy
description: "연결된 iPhone 에서 대상 앱을 에이전트가 스스로 탐험(탭·스와이프·캡처)하고 App Store 리스팅을 더해, Autobot 이 원본 앱을 새로 빌드할 수 있는 제품 브리프(`.autobot/copy-analysis/brief.md`)를 재구성합니다. 실기기 연결이 필수이며 없으면 중지합니다. 대상 앱의 이름·에셋·상표는 복제하지 않는 경쟁 분석용 도구입니다."
argument-hint: "<앱 이름 또는 App Store URL> [bundle ID] (예: 'Things', 'https://apps.apple.com/app/id...')"
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
  - mcp__mcp-appstore__search_app
  - mcp__mcp-appstore__get_app_details
  - mcp__mcp-appstore__fetch_reviews
  - mcp__mcp-appstore__analyze_reviews
  - mcp__mcp-appstore__get_similar_apps
  - mcp__mcp-appstore__analyze_top_keywords
  - mcp__mcp-appstore__get_keyword_scores
---

# Autobot Copy — 기존 앱 분석 → 원본 재구현 브리프

> **이 문서는 진입점이다. 실행하지 않는다.**
> 분석 절차·데이터 소스·법적 경계·산출물 계약의 SSOT 는 **`autobot-copy-analyze` 스킬**이 소유한다.

- **입력** — 분석할 앱 이름 또는 App Store URL (생략 시 첫 질문으로 대상부터 확정)
- **결과물** — `.autobot/copy-analysis/brief.md` (architect 의 `architecture.md` 섹션에 대응하는 제품 브리프) + `flow-map.html` (화면 흐름도 — 어느 지점을 눌러 어디로 갔는지가 스크린샷 위에 찍히고, 미탐 영역도 그 자리에 표시된다) + 실기기/스토어 스크린샷 + 리뷰 인사이트
- **다음 단계** — 브리프를 `/autobot:plan` 또는 `/autobot:mvp` 에 넘겨 **원본 앱**을 빌드

## 무엇을 만드는가

대상 앱을 **베끼는 게 아니라**, 그 앱이 왜 다운로드되고 왜 다시 열리는지(기능·구조·훅·리텐션·디자인 방향)를 실기기 화면과 스토어 메타로 재구성해 **새 원본 앱의 기획 입력**으로 만든다. 대상 앱의 이름·로고·에셋·상표는 브리프에 넣지 않는다.

## 두 개의 데이터 소스

1. **실기기 (Appium/WebDriverAgent) — 필수** — 연결된 iPhone 에서 WDA `GET /source`(접근성 트리)로 화면 **구조**를 읽고, 안전한 탭 후보를 골라 W3C pointer actions 로 **에이전트가 스스로 앱을 돌아다니며** `GET /screenshot` 으로 캡처한다. 접근성 트리(요소 type·label·좌표·visible)가 재구성의 1급 소스. **Developer Mode + Trust + 잠금 해제 + 설정 > 개발자 > UI 자동화 ON 필요**. (fb-idb 의 UI 명령은 시뮬레이터 전용이라 실기기에 쓸 수 없다.)
2. **App Store 메타 (mcp-appstore)** — 설명·스크린샷·리뷰·유사앱·키워드. 기기 캡처를 **보완**하는 backbone.

**기기가 없으면 스킬을 중지한다.** 스토어 메타는 기기의 대체재가 아니다.

## CRITICAL RULES

1. **복제 금지 경계** — 이름·로고·상표·에셋·문구를 그대로 옮기지 않는다. 재구성은 *방향*이지 *복제물*이 아니다. 브리프 상단에 경계를 명시한다.
2. **기기와 대상 바인딩 없으면 중지** — `device_wda.sh device` → `device_wda.sh session <udid> <bundle_id>` 두 게이트를 먼저 통과해야 한다. 로컬 Appium과 iOS 18+ RemoteXPC tunnel은 필요할 때 자동 준비한다. 미연결·다중 연결·관리자 인증 실패·서명 누락·UI 자동화 OFF·대상 bundle ID 누락/미설치면 안내만 하고 **종료한다**. 스토어 메타만으로 브리프를 만들지 않는다.
3. **탭 후보 밖은 탭 금지** — 자율 탐험은 `device_wda.sh candidates` 가 내보낸 `INFO: tap` 목록 안에서만 움직인다. 파괴적 라벨(삭제·구매·구독·로그아웃…)은 후보에서 제외되며, 좌표를 임의로 지어내 탭하지 않는다. **유일한 예외는 `device_wda.sh back`** — 라벨 없는 chevron 때문에 후보에 나오지 않는 leading nav 슬롯만 누르는 별도 명령이고, 그것이 상세 화면에서 나오는 길이다. 시스템 다이얼로그·로그인·페이월을 만나면 멈추고 사용자에게 넘긴다.
   - 커스텀 렌더러 앱(모든 요소가 trait 없는 `Other`)은 `candidates` 가 `WARN: role-blind screen` 을 내며 **라벨-리프 티어**로 자동 전환한다. 파괴 필터는 그대로 적용되지만 라벨 없는 컨트롤은 걸러지지 않으므로, 이 티어에서는 **탭 전에 스크린샷을 읽고 화면 종류를 LLM 이 직접 판단**한다. 로그인·페이월·결제 화면이면 후보가 남아 있어도 중단한다.
4. **파이프라인 상태 위조 금지** — 이 명령은 gate-valid `build-state.json`/`architecture.json` 을 만들지 않는다. 브리프는 architect 의 *입력*이고, `/autobot:plan`·`/autobot:mvp` 가 정식 산출을 만든다.
5. **부분 성공 = 성공** — 기기 게이트를 한 번 통과했다면, 그 뒤의 캡처 실패·접근성 차단·세션 사망은 중지 사유가 **아니다**. 루프만 끝내고 커버한 화면까지로 브리프를 쓰고 한계를 명시한다. 브리프를 만들지 않고 끝내는 것은 게이트를 통과하기 **전에** 실패한 경우뿐이다.

전체 절차는 `autobot-copy-analyze` 스킬을 로드해 그대로 따른다.
