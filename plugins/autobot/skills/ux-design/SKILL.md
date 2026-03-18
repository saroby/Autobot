---
name: autobot-ux-design
description: Use when generating UX designs for an iOS app using Google Stitch. Defines the Stitch integration workflow, design prompt patterns, and design token extraction process for Phase 1.5.
---

# UX Design with Google Stitch

Phase 1.5 스킬: architecture.md의 화면 정의를 기반으로 Google Stitch로 시각적 UI 목업을 생성한다.

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

```bash
# stitch-mcp 사용 가능 여부 확인
npx @_davideast/stitch-mcp doctor 2>&1
# 종료 코드 0 → stitch=true (Phase 1.5 실행)
# 종료 코드 != 0 → stitch=false (Phase 1.5 스킵)
```

## Conditional Execution

Phase 1.5는 **조건부**로 실행된다:

```
if build-state.json.environment.stitch == true:
    → ux-designer 에이전트 디스패치
    → design-spec.md + designs/ 생성
else:
    → Phase 1.5 스킵 (status: "skipped")
    → ui-builder는 architecture.md만으로 UI 결정 (기존 동작 유지)
```

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

```bash
# 사용 가능한 Stitch 도구 목록 확인
npx @_davideast/stitch-mcp tool --list

# Stitch 도구를 사용하여 앱 프로젝트 생성/화면 디자인 생성
# (구체적 도구 이름은 stitch-mcp 버전의 --list 출력 참조)
npx @_davideast/stitch-mcp tool <tool_name> -d '<json_params>'

# 생성된 화면 목록 확인
npx @_davideast/stitch-mcp screens -p <projectId>
```

### Step 4: 스크린샷 수집

```bash
# 각 화면의 스크린샷을 base64로 가져오기
npx @_davideast/stitch-mcp tool get_screen_image -d '{
  "projectId": "<projectId>",
  "screenId": "<screenId>"
}'

# base64 → PNG 파일로 저장
echo "<base64_data>" | base64 -d > .autobot/designs/<ScreenName>.png
```

### Step 5: Design Token 추출

```bash
# 화면의 HTML/CSS 코드 가져오기
npx @_davideast/stitch-mcp tool get_screen_code -d '{
  "projectId": "<projectId>",
  "screenId": "<screenId>"
}'
```

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

Phase 1.5 완료 시 `build-state.json`에 기록:

```json
{
  "stitch": {
    "projectId": "<stitch-project-id>",
    "screenCount": 5,
    "designsPath": ".autobot/designs/"
  },
  "phases": {
    "1.5": {
      "status": "completed",
      "completedAt": "2026-03-18T12:00:00Z"
    }
  }
}
```

Phase 1.5 스킵 시:

```json
{
  "stitch": null,
  "phases": {
    "1.5": {
      "status": "skipped",
      "reason": "stitch not available"
    }
  }
}
```
