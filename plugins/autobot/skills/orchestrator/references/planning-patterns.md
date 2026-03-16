# Planning Patterns for Autobot

## Idea Analysis Framework

When analyzing an app idea, extract these dimensions:

### 1. Core Value Proposition
- What problem does it solve?
- Who is the target user?
- What is the unique differentiator?

### 2. Feature Extraction Heuristics

| Idea Keywords | Implied Features |
|--------------|-----------------|
| "소셜", "공유" | User profiles, feed, sharing, notifications |
| "트래킹", "기록" | Data logging, charts, history, export |
| "쇼핑", "구매" | Product listing, cart, payment, order history |
| "학습", "교육" | Content display, progress tracking, quizzes |
| "건강", "피트니스" | HealthKit, activity tracking, goals |
| "사진", "갤러리" | PhotosPicker, image display, albums |
| "메모", "노트" | Text editor, categories, search |
| "날씨", "위치" | Location services, API calls, maps |
| "음악", "오디오" | AVFoundation, playlist, playback controls |
| "채팅", "메시지" | Real-time messaging, contacts, notifications |

### 3. Screen Count Estimation

| App Complexity | Screen Count | Feature Count |
|---------------|-------------|---------------|
| Simple | 3-5 | 2-3 |
| Medium | 5-8 | 4-5 |
| Complex | 8-12 | 6-7 |

Default to Medium complexity unless the idea explicitly suggests otherwise.

### 4. Navigation Pattern Selection

| Pattern | When to Use |
|---------|-------------|
| TabView + NavigationStack | 3+ distinct sections (most common) |
| NavigationStack only | Linear flow or single-domain app |
| NavigationSplitView | Master-detail (iPad-optimized) |

Default to TabView + NavigationStack for most apps.

## Architecture Decision Tree

```
Is there external data?
├── Yes → Networking layer needed
│   ├── REST API → URLSession + async/await
│   └── Real-time → WebSocket or Firebase
└── No → Local-only app

Is there user-generated content?
├── Yes → SwiftData + iCloud sync consideration
└── No → SwiftData local only

Are there complex interactions?
├── Yes → Dedicated ViewModels per screen
└── No → Lightweight @Observable models

Are there background tasks?
├── Yes → BGTaskScheduler consideration
└── No → Standard foreground-only
```

## Feature Prioritization

For Autobot builds, always implement features in this priority:

1. **P0 (Must have)**: Core value features that define the app
2. **P1 (Should have)**: Supporting features that enhance core
3. **P2 (Nice to have)**: Polish features (skip for MVP)

For initial builds, implement P0 and P1 only.
