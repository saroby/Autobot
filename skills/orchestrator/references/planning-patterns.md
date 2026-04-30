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
| "로그인", "회원가입", "소셜 로그인", "계정" | Authentication, user profiles, session management |
| "AI", "GPT", "챗봇", "자동 요약", "텍스트 생성" | LLM API proxy, streaming responses |
| "이미지 생성", "그림 생성", "웹툰", "AI 그림", "스타일 변환" | Image generation API proxy, backend required |
| "Gemini", "OpenAI", "DALL-E", "Stable Diffusion" | External AI API proxy, backend required |

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

Does the app need authentication?
├── Yes
│   ├── Apple Sign In only → iOS native (no backend)
│   └── Third-party OAuth (Google, GitHub, Kakao) → Backend required
└── No → No auth

Does the app need external AI/LLM API calls?
├── Text generation:
│   "AI", "GPT", "챗봇", "LLM", "Claude", "Gemini",
│   "자동 요약", "텍스트 생성", "AI 추천", "자동 번역",
│   "감정 분석 리포트", "질문 답변", "대화형 ~" → Backend required
├── Image generation:
│   "이미지 생성", "그림 생성", "AI 그림", "웹툰", "만화 생성",
│   "DALL-E", "Stable Diffusion", "Midjourney", "스타일 변환" → Backend required
├── Multimodal:
│   "이미지 분석", "사진 설명", "비전 AI" → Backend required
├── API name mentioned:
│   "OpenAI", "Anthropic", "Google AI", "Gemini API",
│   "Replicate", "Hugging Face" → Backend required
├── ⚠️  FORBIDDEN: iOS 앱에서 외부 AI API 직접 호출 (사용자 API 키 입력 포함)
│   → 반드시 backend_required = true로 설정하고 프록시 경유
├── False positives (no backend needed):
│   "추천" (rule-based), "검색" (full-text), "분류" (on-device CoreML),
│   Apple Foundation Models (on-device, iOS 26+) → No backend
└── No → No LLM

Backend required?
├── Yes
│   ├── If auth exists → Apple Sign In also routes through server (unified JWT)
│   ├── Tech stack: Python + FastAPI (LLM SDK native support)
│   └── Output: architecture.md Backend Requirements section
└── No → Skip all backend sections
```

## Feature Prioritization

For Autobot builds, always implement features in this priority:

1. **P0 (Must have)**: Core value features that define the app
2. **P1 (Should have)**: Supporting features that enhance core
3. **P2 (Nice to have)**: Polish features (skip for MVP)

For initial builds, implement P0 and P1 only.
