---
name: autobot-ux-design
user-invocable: false
description: Use when defining the UX design direction for an iOS app in the Autobot pipeline (Phase 2). The ux-designer agent authors `.autobot/design-spec.md` directly — no mockup generation — with native-first SwiftUI component decisions that the ui-builder implements.
---

# UX Design Direction (Phase 2)

Phase 2 스킬: architecture.md의 화면 정의를 기반으로 ux-designer 에이전트가
`.autobot/design-spec.md`를 **직접 저작**한다. 목업 생성 도구는 쓰지 않는다 —
LLM은 픽셀 목업을 복제할 때 가장 약하고, 네이티브 컴포넌트를 조합해 화면을
작성할 때 가장 강하다.

## Execution

```
→ ux-designer 에이전트 디스패치
→ .autobot/design-spec.md 생성 (Gate 2→3 필수 섹션 포함)
→ 실패 시 1회 재시도
→ 재실패 시: architecture.md의 Design Direction을 최소 design-spec으로 변환해
  Phase 2를 fallback으로 마킹 (룩앤필 계약은 반드시 보존)
```

Gate 2→3의 hard 계약은 design-spec의 섹션 완결성과 design-spec.json 유효성이다.
목업 PNG는 요구되지 않는다.

필수 섹션 (Gate 2→3이 검사 — 표기 이름을 임의로 바꾸지 않는다):
- `## Visual Concept`
- `## Color Tokens`
- `## Typography`
- `## Spacing & Radius`
- `## Screen-by-Screen Layout`
- `## Interaction Feel`
- `## Empty, Loading, Error States`

## Design Principles (에이전트 프롬프트와 동일 계약)

1. **시스템 컴포넌트 기본값** — `List`/`Form`/`NavigationStack`/`TabView`/
   `.searchable()`/`.refreshable()`/Liquid Glass 우선. 커스텀은 시스템
   컴포넌트로 해당 UX가 불가능할 때만, design-spec에 정당화 한 줄과 함께.
2. **레퍼런스 앵커** — 카테고리에서 UX가 검증된 실제 iOS 앱 1–2개를 지정하고
   차용/배제 항목을 Visual Concept에 명시.
3. **시맨틱 우선** — 배경·텍스트는 시맨틱 컬러, 아이콘은 SF Symbols, 타이포는
   Dynamic Type. 브랜드 컬러는 `<Module>Color.*` DS 토큰으로만.
4. **anti-slop** — 보라 그라데이션, 이유 없는 카드 남발, 커스텀 폰트,
   웹스러운 히어로 섹션 금지.

## Native Component Vocabulary

화면 요소를 결정할 때의 기본 선택지:

| 화면 요소 | iOS (SwiftUI) |
|----------|---------------|
| 스크롤 목록 | `List` (`.insetGrouped` / `.plain`) |
| 설정/입력 폼 | `Form` + `Section` |
| 화면 전환 | `NavigationStack` + `NavigationLink` / `.navigationDestination` |
| 하단 탭 | `TabView { Tab(...) }` |
| 검색 | `.searchable()` |
| 당겨서 새로고침 | `.refreshable { }` |
| 행 액션 | `.swipeActions()` / `.contextMenu()` |
| 모달 | `.sheet()` / `.fullScreenCover()` (+ `.presentationDetents`) |
| 빈 상태 | `ContentUnavailableView` |
| 로딩 | `ProgressView` / `.redacted(reason: .placeholder)` |
| 반투명 표면 | `.glassEffect()` (Liquid Glass) |
| 토글/선택 | `Toggle()` / `Picker(.segmented)` |
| 카드 | `Section` 우선, 진짜 카드가 필요할 때만 `<Module>Card` |

## Output Artifacts

| 산출물 | 경로 | 생성자 | 소비자 |
|-------|------|--------|--------|
| 디자인 명세 | `.autobot/design-spec.md` | ux-designer | ui-builder, Gate 2→3, plan-preview |

## Build State Integration

Phase 2 완료 시:

```json
{
  "phases": {
    "2": { "status": "completed", "completedAt": "<ts>" }
  }
}
```

에이전트가 2회 실패해 오케스트레이터가 최소 design-spec으로 대체한 경우에만
`"status": "fallback"`, reason에 사유를 기록한다.
