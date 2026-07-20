---
name: autobot-clone-analyze
user-invocable: false
description: Use when analyzing an existing iOS app — from a physically connected iPhone and/or its App Store listing — to reconstruct a build-ready product brief for an original re-implementation. Drives the device with idb (screenshot + accessibility tree + optional tap/swipe), pulls App Store metadata/reviews via the mcp-appstore MCP, and synthesizes `.autobot/clone-analysis/brief.md` mapped to the architect's architecture.md sections so `/autobot:plan` or `/autobot:mvp` can build an original app from it. Triggers on "이 앱 분석해서 비슷하게 만들어줘", "실기기 앱 분석", "앱 복제 분석", "/autobot:clone".
---

# Autobot Clone-Analyze — 실기기/스토어에서 제품 브리프 재구성

기존 앱을 **실기기(idb) + App Store 메타데이터**로 분석해, Autobot 파이프라인이 **원본(original) 앱을 새로 빌드**할 수 있는 제품 브리프를 만든다. 산출물은 architect 에이전트의 `architecture.md` 섹션 구조에 1:1 대응하는 `.autobot/clone-analysis/brief.md` 이며, 사용자가 `/autobot:plan` 또는 `/autobot:mvp` 에 넘기면 진짜 architect 가 gate-valid 산출물을 만든다.

## 무엇을 하고 무엇을 하지 않는가 (법적/윤리 경계)

이 스킬은 **기능·구조·디자인 방향을 이해해 새로 만들기 위한 경쟁 분석**이다. 정상 범주:

- ✅ 화면 구성·네비게이션·기능 목록·정보 위계·색/타이포 *방향* 재구성
- ✅ App Store 설명·리뷰에서 유저가 원하는 것/불만 추출 → 차별화 훅 도출

선 밖 — **하지 않는다**:

- ❌ 대상 앱의 **이름·로고·상표·스크린샷·아이콘·문구를 그대로 복사**. 브리프에는 대상 앱 이름을 식별자로 넣지 않는다("reference app" 으로만 지칭).
- ❌ 소스/에셋 추출·바이너리 복호화·비공개 API 트래픽 가로채기.
- ❌ 픽셀 단위 클론. 재구성은 *방향*이지 *복제물*이 아니다.

브리프 상단에 이 경계를 한 줄로 명시한다: `> 원본 재구현용 분석 — 대상 앱의 이름/에셋/상표는 복제하지 않는다.`

## 재구성의 핵심 자산: 접근성 트리

`idb ui describe-all` 은 포그라운드 앱의 **접근성 트리를 JSON 으로 덤프**한다 — 각 요소의 role(`AXButton`/`AXHeading`/…), label, 정확한 frame 좌표, accessibility identifier, enabled 상태. 스크린샷 비전보다 훨씬 정확한 구조 소스다(요소 타입·계층·레이블이 텍스트로 나옴). **이 트리가 화면 재구성의 1급 입력**이고, 스크린샷은 시각적 보완, App Store 메타는 backbone 이다.

## 누가 조작하나 — 사람 주도가 기본, 에이전트 주도는 옵션

idb 는 `ui tap`/`ui swipe`/`ui text` 로 앱을 직접 조작할 수 있어 **에이전트가 스스로 넘길 수 있다**. 그래도 **사람 주도가 기본**이다:

- **사람 주도(기본, 안전)** — 사용자가 의미 있는 화면을 연다(로그인·페이월·삭제 등 부작용을 아는 사람이 몇 초 만에 핵심 흐름 커버). 각 화면에서 스킬이 `screen`(스크린샷 + 접근성 트리)을 덤프.
- **에이전트 주도(옵션)** — 사용자가 명시 요청 시에만. `idb ui describe-all` 로 현재 화면 요소를 읽고 `idb ui tap <x> <y>` 로 이동. *모르는 앱을 블라인드 탐색하면* 로그인/결제/파괴적 버튼에 걸릴 수 있으므로, 파괴적으로 보이는 요소(삭제·구매·로그아웃)는 탭하지 않고 사용자에게 넘긴다.

## 데이터 소스

| 소스 | 획득 방법 | 항상 가능? |
|------|----------|-----------|
| 실기기 화면 + 구조 | `scripts/clone_idb.sh screen` → `idb screenshot` + `idb ui describe-all` | idb 설치 + 기기 준비 시 |
| 공개 메타데이터 | `mcp-appstore` MCP — 설명·스크린샷·리뷰·유사앱·키워드 | 항상 (기기 불필요) |
| 사용자 제공 스크린샷 | 사용자가 캡처해 전달 | fallback |

## Setup (idb, 최초 1회)

```bash
# 네이티브 companion (소스 컴파일 — 수 분, Xcode 필요)
brew tap facebook/fb
brew trust --formula facebook/fb/idb-companion   # Homebrew 6.x 서드파티 tap 신뢰
brew install idb-companion
# Python CLI — ⚠️ fb-idb 1.1.x 는 Python 3.14 에서 깨진다(asyncio.get_event_loop 제거).
# 반드시 Python 3.13 이하로 설치한다.
pipx install fb-idb --python python3.11
idb list-targets   # 설치 확인
```

`scripts/clone_idb.sh targets` 가 위 확인을 감싼다. idb 설치가 불가하면 실패 처리하지 않고 App Store 메타 중심으로 진행(아래 Fallback).

## Workflow

### Step 1 — 대상 확정 + App Store 메타 수집 (기기 없이 시작)

`mcp-appstore` 도구로 먼저 공개 정보를 확보한다 (기기 준비와 병렬 가능):

1. `search_app` 로 앱 검색 → 대상 확정 (사용자에게 후보 확인)
2. `get_app_details` — 이름·카테고리·설명·subtitle·평점·스크린샷 URL
3. `fetch_reviews` + `analyze_reviews` — 유저가 사랑하는 것/불만 → **훅·리텐션 근거**
4. `get_similar_apps` — Market Context 표의 근거 앱들
5. `analyze_top_keywords` / `get_keyword_scores` — 카테고리 table-stakes 신호

App Store 스크린샷 URL 은 `WebFetch`/curl 로 `.autobot/clone-analysis/store/` 에 저장한다.

### Step 2 — 실기기 준비 점검

```bash
scripts/clone_idb.sh targets
```

- `OK: <udid> device Booted <name>` → 사용 가능. 그 udid 를 이후 캡처에 쓴다.
- `WARN: no physical device` → 기기 연결 + **Developer Mode ON(설정 > 개인정보 보호 및 보안 > 개발자 모드) + 이 Mac 신뢰** 안내 후 재확인. (시뮬레이터는 App Store 앱을 못 돌리므로 대상이 아니다.)
- idb 미설치 → Setup 안내 또는 Fallback.

### Step 3 — 캡처 (사람 주도가 기본)

Step 1 에서 파악한 화면 목록을 기준으로 캡처할 핵심 화면을 사용자에게 제시하고 하나씩:

1. "대상 앱에서 **[화면 이름]** 을 여세요" 안내
2. 사용자 확인 후:
   ```bash
   scripts/clone_idb.sh screen <udid> .autobot/clone-analysis/device <NN>-<screen>
   # → <NN>-<screen>.png + <NN>-<screen>.a11y.json
   ```
3. 접근성 덤프 실패(`WARN: ... accessibility dump failed`) → 그 앱이 접근성을 막은 것. 스크린샷만으로 진행.

최소 핵심 화면(홈/메인, 상세, 생성/입력, 설정, empty state 하나)을 목표로 한다. 완주보다 **핵심 흐름 커버**가 중요하다.

**에이전트 주도(사용자 명시 요청 시만)**: `idb ui describe-all` 로 현재 화면을 읽고, 이동할 요소의 frame 중심을 `idb ui tap <x> <y>` 로 탭. 파괴적 요소는 건너뛰고 사용자에게 위임. 2회 예상과 다른 화면이 나오면 멈추고 사용자에게 확인.

### Step 4 — 구조 분석

수집한 **접근성 트리(`.a11y.json`)를 1급 소스로, 스크린샷을 보완으로** 읽어 분석:

- **Screens**: 각 화면의 목적·Tab·주요 UI 요소 (a11y 트리의 role/label 로 정확히). architecture.md `## Screens` 표 형식
- **Navigation**: TabView / NavigationStack / Split — 트리의 탭바·네비바 요소로 판별
- **Features**: P0/P1 + role(`table-stakes`/`hook`/`retention`/`insight`). 리뷰에서 사랑받는 기능 = hook 후보, 불만 = 개선 차별점
- **Design Direction**: personality, color palette(스크린샷에서 추출한 *방향* — 정확한 hex 복제 아님), typography 느낌, layout personality, signature layout
- **Hook & Retention**: 리뷰·기능에서 도출. 제네릭 금지 — 이 앱만 식별되는 구체 문장

### Step 5 — 브리프 합성

`.autobot/clone-analysis/brief.md` 를 architect 의 `architecture.md` 섹션 순서로 작성한다 (참조: `skills/autobot-orchestrator/references/architecture-template.md`). 최소 포함 섹션:

- `## Overview` (원본 재구현 대상의 *가치*, 이름/상표 제외)
- `## Market Context` (유사앱 근거 표)
- `## Features` (P0/P1 + role)
- `### Hook & Retention` (구체·비제네릭)
- `## Screens`
- `## Navigation Structure`
- `## Design Direction` (color/typography/layout/**signature layout**)

브리프는 architect 의 *입력*이지 최종 산출이 아니다 — gate 계약(build-state, feature-spec, Models/*.swift)을 위조하지 않는다. architect 가 이 브리프를 받아 정식 파이프라인으로 완성한다.

### Step 6 — 검토 + 핸드오프

1. 수집 이미지·트리·브리프를 사용자가 보게 연다 (`open .autobot/clone-analysis/`).
2. 다음 안내:
   ```
   브리프 준비 완료 → 원본 앱을 빌드하려면:
     /autobot:plan  (기획·디자인 검토 후 진행)  또는
     /autobot:mvp   (질문 없이 바로 빌드)
   에 .autobot/clone-analysis/brief.md 내용을 아이디어로 넘기세요.
   ```

## Output Artifacts

| 산출물 | 경로 | 소비자 |
|-------|------|--------|
| 제품 브리프 | `.autobot/clone-analysis/brief.md` | 사용자 → `/autobot:plan`·`/autobot:mvp` (architect) |
| 접근성 트리 | `.autobot/clone-analysis/device/*.a11y.json` | Step 4 구조 분석 (1급 소스) |
| 실기기 캡처 | `.autobot/clone-analysis/device/*.png` | 시각 보완 |
| 스토어 스크린샷 | `.autobot/clone-analysis/store/*.png` | 구조 분석 |
| 리뷰 인사이트 | `.autobot/clone-analysis/reviews.md` | 브리프 Hook & Retention 근거 |

## Fallback (기기 없음/idb 불가/접근성 차단)

실패 처리하지 않는다:

1. App Store 스크린샷 + 설명 + 리뷰만으로 Step 4~5 수행 (스토어 스크린샷은 대개 핵심 화면을 담아 브리프에 충분)
2. 부족한 화면은 사용자에게 "해당 화면을 캡처해 보내주세요" 요청
3. 브리프 상단에 `> device-capture unavailable — store-metadata-primary` 표기
4. idb 없이 스크린샷만 급히 필요하면 `xcrun devicectl device capture screenshot` (접근성 트리는 없음) 을 임시 대안으로 쓸 수 있으나, 기기 잠금해제·Developer Mode 를 동일하게 요구한다.

## Preconditions

- 실기기 경로: idb 설치(`idb-companion` + `fb-idb` on Python ≤3.13), iPhone USB 연결 + Developer Mode + Trust
- 스토어 경로: `mcp-appstore` MCP 도구 사용 가능 (도구 목록에 `mcp__mcp-appstore__*` 존재)
- 둘 중 하나만 있어도 진행 가능 (스토어 경로가 최소 backbone)
