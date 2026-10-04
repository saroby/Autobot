---
name: autobot-ux-design
user-invocable: false
description: "Create Phase 2 Stitch mockups and design specs, including the unavailable-tool fallback."
---

# UX Design with Google Stitch

Phase 2: `.autobot/architecture.md`의 화면·Design Direction을 Stitch 목업과 `.autobot/design-spec.md`로 구체화한다.

## 경로·복구

- Phase 0에서 MCP 도구/`mcp__stitch__check_antigravity_auth` 또는 `npx @_davideast/stitch-mcp doctor`로 인증을 확인해 `build-state.json.environment.stitch`를 판정한다. 설치가 필요하면 `npm install -g @_davideast/stitch-mcp` 또는 `npx @_davideast/stitch-mcp init`.
- `stitch=true`: ux-designer primary 경로. 실패 시 1회 재시도 후 fallback.
- Stitch unavailable이면 architecture의 `## Design Direction`으로 최소 design-spec을 생성하고 Phase 2를 `fallback`으로 기록한다. 경고: `Stitch MCP 미설치. 최소 design-spec 계약으로 진행합니다.`
- fallback은 PNG 없이 진행할 수 있지만 필수 토큰·레이아웃·상태 섹션이 없으면 Gate 2→3은 실패한다. ui-builder는 design-spec + architecture를 사용한다.

## 생성

1. architecture의 `## Screens`(Screen/Purpose/Tab/Key UI Elements), `## Navigation Structure`, `## Features`의 P0/P1 매핑을 읽는다.
2. 화면별 프롬프트에 이름·목적·네비게이션 맥락·UI 요소·Design Direction 토큰·empty/loading/error 상태를 넣는다. iOS SF Pro, Dynamic Type, 여백, Liquid Glass 반투명 표면을 반영한다.
3. `create_project`로 앱 이름의 프로젝트를 만들고 ID를 확보(재개 시 기존 ID 사용) → `batch_generate_screens` → 실패 화면은 `generate_screen_from_text` → `list_screens`로 ID 확인.
4. 성공한 `fetch_screen_image` 결과는 즉시 `.autobot/designs/<ScreenName>.png`에 저장한다.
5. `fetch_screen_code`의 HTML/CSS에서 색·폰트·간격·컴포넌트를 추출해 SwiftUI 토큰/패턴으로 매핑하고 design-spec을 작성한다.

MCP `mcp__stitch__<작업>` 직접 호출이 우선이며, CLI fallback은 `npx @_davideast/stitch-mcp tool <작업> -d '<JSON>'`이다.

### 목업 캔버스 계약

프롬프트에 **393×852pt, 1179×2556px @3x** portrait 캔버스와 아래 구역을 명시한다:

| 구역 | Y(pt) | 허용 |
|---|---|---|
| Status bar | 0–47(상단 5.5%) | 시스템 chrome만: 9:41·신호/Wi-Fi/배터리(y=15–30), 중앙 Dynamic Island |
| 앱 콘텐츠 | 47–818 | 제목·버튼·리스트·카드·CTA·탭바 |
| Home indicator | 818–852(하단 4%) | 중앙 얇은 pill만(약 130×5pt, y=835) |

NavigationStack 바는 y=47–91, TabView 바는 콘텐츠 구역 하단 y=720–818(49pt 높이) 안에 배치한다. 앱 요소 bounding box가 y<47 또는 y>818과 겹치면 Phase 2.5 HIGH critique로 거부하고 `/autobot:resume 2 --force` 재생성이 필요하다. 상태 바·home indicator를 목업에 실제로 그린다.

### 부분 실패

성공 PNG를 보존하고 실패 화면을 개별로 1회 재시도한다. 최종 실패는 `## Failed Screens`에 기록한다. **전체의 절반 이상** 생성되면 `completed`(누락 화면은 architecture 기반 구현), 절반 미만이면 fallback.

## Design-spec 계약

아래 정확한 `##` 이름은 Gate 2→3이 검사한다. primary/fallback 모두 필수다:

| 섹션 | 내용 |
|---|---|
| `## Visual Concept` | 앱 성격·타깃 감정·피할 generic UI |
| `## Color Tokens` | Primary/Secondary/Accent/Surface → Theme |
| `## Typography` | Display/Headline/Body → Theme/Dynamic Type |
| `## Spacing & Radius` | 카드·섹션 간격·radius |
| `## Screen-by-Screen Layout` | 화면별 레이아웃·주요 컴포넌트 |
| `## Interaction Feel` | 모션·전환·피드백 강도 |
| `## Empty, Loading, Error States` | 상태별 시각 처리·액션 |

primary는 Stitch 프로젝트 ID, 화면별 PNG 경로·UI 패턴 노트, CSS→SwiftUI 매핑, 네비게이션 흐름도 포함한다.

매핑 시:
- 폰트 크기/굵기를 `.largeTitle`/`.headline`/`.body` 등 Dynamic Type 스타일로 변환한다.
- 앱 accent는 architecture.json의 `designSystemModule`인 `<Module>Color.accent`를 사용하며 `Color.accentColor`를 쓰지 않는다. 배경·텍스트는 iOS semantic color로 매핑한다.
- CSS 여백·gap·radius는 SwiftUI spacing/padding/clipShape 값으로, 반투명은 `.glassEffect()`로 매핑한다. 웹 컴포넌트는 `TabView`/`NavigationStack`/`sheet`/`searchable` 등 네이티브 패턴으로 옮긴다.

## 산출물·상태

ui-builder 입력: `.autobot/designs/*.png`, `.autobot/design-spec.md`.

| Phase 2 | build-state 기록 |
|---|---|
| completed | `stitch.projectId`, `stitch.screenCount`, `stitch.designsPath=.autobot/designs/`, `phases.2.status=completed`, `phases.2.completedAt` |
| fallback | `stitch=null`, `designSpec=.autobot/design-spec.md`, `phases.2.status=fallback`, `phases.2.reason=stitch not available — minimal design-spec generated from architecture.md` |
