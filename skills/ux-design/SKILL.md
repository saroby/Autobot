---
name: autobot-ux-design
description: Use when generating UX mockup designs for an iOS app using Stitch MCP, extracting design tokens from generated screens, or creating design specifications for SwiftUI implementation. Also use when the Autobot build pipeline needs visual UI mockups before coding begins (Phase 2), or when Stitch integration fails and fallback design decisions are needed.
---

# UX Design with Google Stitch

Phase 2 스킬: architecture.md의 화면 정의를 기반으로 Google Stitch로 시각적 UI 목업을 생성한다.

## Prerequisites

### Stitch MCP 설치 및 인증

```bash
# 설치 (글로벌)
npm install -g @_davideast/stitch-mcp

# 또는 npx로 직접 실행 (설치 불필요)
npx @_davideast/stitch-mcp init

# 인증 확인
npx @_davideast/stitch-mcp doctor
```

### 환경 검증 (Phase 0에서 수행)

두 가지 방법으로 Stitch 사용 가능 여부를 확인한다:

```bash
# 방법 1: MCP 도구 존재 확인 (권장 — 도구 목록에 mcp__stitch__* 존재 여부)
# 오케스트레이터가 MCP 도구 호출을 시도하여 확인

# 방법 2: CLI 인증 확인
npx @_davideast/stitch-mcp doctor 2>&1
# 종료 코드 0 → stitch=true (Phase 2 실행)
# 종료 코드 != 0 → stitch=false (Phase 2 fallback)
```

MCP 도구(`mcp__stitch__check_antigravity_auth`)로 인증 상태를 확인할 수도 있다.

## Execution Strategy

Phase 2는 **필수(primary) 경로**다. Stitch MCP가 설치되지 않은 환경에서만 fallback 모드로 전환된다:

```
if build-state.json.environment.stitch == true:
    → ux-designer 에이전트 디스패치 (primary 경로)
    → design-spec.md + designs/ 생성
    → 실패 시 1회 재시도, 재실패 시 fallback 전환
else:
    → Phase 2를 fallback으로 마킹 (status: "fallback")
    → ⚠️ 경고: "Stitch MCP 미설치. UI는 architecture.md 기반으로 생성됩니다."
    → ui-builder는 architecture.md + fallback 디자인 원칙으로 UI 결정
```

### Fallback 모드 디자인 원칙

Stitch가 없을 때 ui-builder가 따라야 할 디자인 기준:

| 항목 | Fallback 기준 |
|------|--------------|
| **색상** | iOS semantic colors만 사용 (`Color.primary`, `Color(.systemBackground)`, `Color.accentColor`) |
| **타이포그래피** | Dynamic Type 기본 스타일만 사용 (`.largeTitle`, `.body`, `.caption`) |
| **레이아웃** | Apple HIG 기본 여백 — `.padding()` (16pt), 스택 기본 spacing |
| **컴포넌트** | 네이티브 SwiftUI 컴포넌트 우선 (`List`, `NavigationStack`, `TabView`, `.searchable()`) |
| **글래스 효과** | `.glassEffect()`를 toolbar와 tab bar에만 적용 |
| **다크모드** | semantic color 사용으로 자동 지원 확인 |

fallback 모드에서는 커스텀 디자인 토큰 없이 iOS 시스템 기본값에 의존하므로, 시각적 일관성은 iOS 플랫폼 기본을 따르게 된다.

## Workflow

### Step 1: Screen Inventory 추출

architecture.md에서 화면 목록 추출:
- `## Screens` 섹션의 테이블 (Screen, Purpose, Tab, Key UI Elements)
- `## Navigation Structure` 섹션의 화면 계층
- `## Features` 섹션에서 P0/P1 기능과 화면 매핑

### Step 2: Design Prompt 생성

각 화면에 대해 iOS 모바일 앱 특화 프롬프트 작성:

```
Mobile iOS app - [App Display Name]

Screen: [ScreenName]
Purpose: [from architecture.md Screens table]

Design Style:
- Modern iOS with translucent glass materials (Liquid Glass)
- Clean sans-serif typography (SF Pro)
- Generous whitespace and breathing room
- Subtle depth with layered translucent surfaces

Navigation Context:
- [Tab bar at bottom with N tabs / Navigation bar at top / Modal sheet / Full screen]
- [Current tab highlighted: Tab Name]
- [Back button to: PreviousScreen]

Key UI Elements:
- [Element 1 from Screens table: e.g., "Scrollable list of items with thumbnails"]
- [Element 2: e.g., "Floating action button for adding new item"]
- [Element 3: e.g., "Search bar at top"]

Layout Requirements:
- iPhone portrait orientation
- Safe area aware (notch, home indicator)
- iOS system colors (light/dark compatible)
- Dynamic Type ready text sizes

Interactive States:
- [Empty state: when no items exist]
- [Loading state: skeleton or spinner]
- [Error state: retry option]
```

### Step 3: Stitch 프로젝트 생성 및 화면 생성

Stitch MCP 도구를 사용한다. 두 가지 호출 방식이 있으며, MCP 도구 직접 호출을 우선 사용한다:

| 작업 | MCP 도구 (권장) | CLI fallback |
|------|----------------|-------------|
| 프로젝트 생성 | `mcp__stitch__create_project` | `npx @_davideast/stitch-mcp tool create_project -d '{...}'` |
| 화면 일괄 생성 | `mcp__stitch__batch_generate_screens` | `npx @_davideast/stitch-mcp tool batch_generate_screens -d '{...}'` |
| 화면 개별 생성 | `mcp__stitch__generate_screen_from_text` | `npx @_davideast/stitch-mcp tool generate_screen_from_text -d '{...}'` |
| 화면 목록 | `mcp__stitch__list_screens` | `npx @_davideast/stitch-mcp tool list_screens -d '{...}'` |
| 스크린샷 | `mcp__stitch__fetch_screen_image` | `npx @_davideast/stitch-mcp tool fetch_screen_image -d '{...}'` |
| HTML/CSS | `mcp__stitch__fetch_screen_code` | `npx @_davideast/stitch-mcp tool fetch_screen_code -d '{...}'` |

**생성 순서:**

a. `create_project`로 앱 이름의 Stitch 프로젝트 생성 → `projectId` 확보
b. `batch_generate_screens`로 모든 화면을 한 번에 생성 (효율적)
   - 실패 시 `generate_screen_from_text`로 화면별 개별 생성으로 전환
c. `list_screens`로 생성된 화면 ID 목록 확인

### Step 4: 스크린샷 수집

각 화면에 대해 `fetch_screen_image`로 스크린샷 이미지를 가져와서 저장한다:

```bash
# MCP 도구 결과의 base64 데이터를 PNG 파일로 저장
mkdir -p .autobot/designs
echo "<base64_data>" | base64 -d > .autobot/designs/<ScreenName>.png
```

### Step 5: Design Token 추출

각 화면에 대해 `fetch_screen_code`로 HTML/CSS를 가져온다.

HTML/CSS에서 추출할 디자인 토큰:
- **Colors**: 배경색, 텍스트색, 강조색 → iOS semantic color로 매핑
- **Typography**: 폰트 크기, 굵기 → Dynamic Type 스타일로 매핑
- **Spacing**: 여백, 패딩 → SwiftUI spacing 값으로 변환
- **Components**: 카드, 리스트, 버튼 → SwiftUI 컴포넌트 패턴으로 매핑

### Step 6: Design Spec 문서 작성

`.autobot/design-spec.md`에 다음 내용 포함:

| 항목 | 내용 |
|------|------|
| Stitch 프로젝트 ID | 참조 및 resume 시 재사용 |
| 화면별 스크린샷 경로 | `.autobot/designs/<Screen>.png` |
| 화면별 UI 패턴 노트 | ui-builder가 참조할 구현 가이드 |
| 디자인 토큰 매핑 | Stitch CSS → SwiftUI 속성 |
| 네비게이션 흐름 | 화면 간 전환 시각화 |

## Partial Screen Failure Recovery

일부 화면 생성이 실패한 경우 전체를 실패 처리하지 않는다:

1. **즉시 저장**: 성공한 화면의 스크린샷은 바로 `.autobot/designs/`에 저장
2. **개별 재시도**: 실패한 화면은 `generate_screen_from_text`로 개별 재시도 (1회)
3. **기록**: 최종 실패 화면은 `design-spec.md`의 `## Failed Screens` 섹션에 기록
4. **판정**: 부분 성공 = 성공. 전체 화면의 절반 이상 생성되면 Phase 2는 `completed`
   - ui-builder가 누락 화면은 architecture.md 기반으로 구현
   - 절반 미만이면 fallback 전환

```
총 화면 5개:
├── 3개 이상 성공 → Phase 2 completed (design-spec.md에 실패 화면 표시)
└── 2개 이하 성공 → fallback 전환 (Stitch 디자인 생성 실패로 판단)
```

## iOS Design Token Mapping

Stitch가 생성한 웹 디자인 토큰을 iOS SwiftUI 패턴으로 매핑하는 참조 테이블:

### Typography

| Web (Stitch CSS) | iOS (SwiftUI) |
|-----------------|---------------|
| `font-size: 34px; font-weight: bold` | `.font(.largeTitle)` |
| `font-size: 28px; font-weight: bold` | `.font(.title)` |
| `font-size: 22px; font-weight: bold` | `.font(.title2)` |
| `font-size: 20px; font-weight: 600` | `.font(.title3)` |
| `font-size: 17px; font-weight: 600` | `.font(.headline)` |
| `font-size: 17px` | `.font(.body)` |
| `font-size: 15px` | `.font(.subheadline)` |
| `font-size: 13px` | `.font(.footnote)` |
| `font-size: 12px` | `.font(.caption)` |
| `font-size: 11px` | `.font(.caption2)` |

### Colors

| Web (Stitch CSS) | iOS (SwiftUI) |
|-----------------|---------------|
| `#007AFF` / blue accent | `Color.accentColor` |
| `#FFFFFF` / white background | `Color(.systemBackground)` |
| `#F2F2F7` / light gray background | `Color(.secondarySystemBackground)` |
| `#000000` / primary text | `Color.primary` |
| `#3C3C43` / secondary text | `Color.secondary` |
| `#FF3B30` / red | `Color.red` |
| `#34C759` / green | `Color.green` |
| `rgba(255,255,255,0.8)` / translucent | `.glassEffect()` (Liquid Glass) |

### Layout & Spacing

| Web (Stitch CSS) | iOS (SwiftUI) |
|-----------------|---------------|
| `padding: 16px` | `.padding()` |
| `padding: 20px` | `.padding(20)` |
| `gap: 4px` | `VStack(spacing: 4)` / `HStack(spacing: 4)` |
| `gap: 8px` | `VStack(spacing: 8)` / `HStack(spacing: 8)` |
| `gap: 16px` | `VStack(spacing: 16)` / `HStack(spacing: 16)` |
| `border-radius: 10px` | `.clipShape(RoundedRectangle(cornerRadius: 10))` |
| `border-radius: 20px` | `.clipShape(RoundedRectangle(cornerRadius: 20))` |

### Components

| Web (Stitch Pattern) | iOS (SwiftUI) |
|---------------------|---------------|
| Card with shadow | `RoundedRectangle` + `.shadow()` or `.glassEffect()` |
| List item with chevron | `List { NavigationLink { } }` |
| Bottom tab bar | `TabView { Tab(...) { } }` |
| Top navigation bar | `NavigationStack { .navigationTitle() }` |
| Modal/overlay | `.sheet()` or `.fullScreenCover()` |
| Floating action button | `ZStack` + `.overlay(alignment: .bottomTrailing)` |
| Search bar | `.searchable()` |
| Toggle switch | `Toggle()` |
| Segmented control | `Picker(.segmented)` |
| Pull to refresh | `.refreshable { }` |

## Output Artifacts

| 산출물 | 경로 | 생성자 | 소비자 |
|-------|------|--------|--------|
| 화면 스크린샷 | `.autobot/designs/*.png` | ux-designer | ui-builder |
| 디자인 명세 | `.autobot/design-spec.md` | ux-designer | ui-builder |
| Stitch 프로젝트 ID | `build-state.json.stitch.projectId` | ux-designer | resume 시 재사용 |

## Build State Integration

Phase 2 완료 시 `build-state.json`에 기록:

```json
{
  "stitch": {
    "projectId": "<stitch-project-id>",
    "screenCount": 5,
    "designsPath": ".autobot/designs/"
  },
  "phases": {
    "2": {
      "status": "completed",
      "completedAt": "2026-03-18T12:00:00Z"
    }
  }
}
```

Phase 2 fallback 시:

```json
{
  "stitch": null,
  "phases": {
    "2": {
      "status": "fallback",
      "reason": "stitch not available — UI will be generated from architecture.md only"
    }
  }
}
```
