# Architecture Document Template

architect 에이전트가 생성하는 `.autobot/architecture.md`의 정형화된 템플릿.
모든 섹션이 존재해야 Gate 1→2를 통과한다. 해당 없는 섹션은 "N/A"로 표시.

---

```markdown
# [Display Name] Architecture

- **Identifier**: `PascalCaseAppName`
- **Display Name**: `표시 이름`
- **Bundle ID**: `com.saroby.pascalcaseappname`

## Overview

[1-2 문단. 앱의 핵심 가치, 대상 사용자, 주요 차별점]

## Features

| # | Feature | Priority | Description |
|---|---------|----------|-------------|
| 1 | [기능명] | P0 | [설명] |
| 3 | [기능명] | P0 | [설명] |
| 4 | [기능명] | P1 | [설명] |

> P0 = Must have, P1 = Should have, P2 = Nice to have (초기 빌드에서 스킵)

## Screens

| Screen | Purpose | Tab | Key UI Elements |
|--------|---------|-----|-----------------|
| HomeView | [목적] | Home | [List, FAB, SearchBar 등] |
| DetailView | [목적] | — (push) | [Form, Image, Actions] |
| SettingsView | [목적] | Settings | [Toggle, Picker] |

## Navigation Structure

[TabView / NavigationStack / NavigationSplitView 중 택]

```
TabView
├── Tab 1: Home
│   └── NavigationStack
│       ├── HomeView
│       └── DetailView (push)
├── Tab 2: Search
│   └── NavigationStack
│       └── SearchView
└── Tab 3: Settings
    └── SettingsView
```

## Design Direction

### App Personality
[3-5 adjectives: e.g., "warm, organic, personal" or "bold, energetic, data-driven"]

### Color Palette
| Role | Name | Light | Dark | Usage |
|------|------|-------|------|-------|
| Primary | [color name] | #XXXXXX | #XXXXXX | Brand identity, CTAs, key highlights |
| Secondary | [color name] | #XXXXXX | #XXXXXX | Supporting UI, section headers, tags |
| Accent | [color name] | #XXXXXX | #XXXXXX | Badges, notifications, small emphasis |
| Surface | [color name] | #XXXXXX | #XXXXXX | Card backgrounds, elevated surfaces |

> Primary는 system blue(#007AFF)를 피한다 — 앱만의 고유 색상을 선택.
> Dark Mode는 Light의 채도를 낮추거나 밝기를 조정한 변형.

### Typography Style
| Element | Font Design | Weight | 용도 |
|---------|------------|--------|------|
| Display | .rounded / .default / .serif | .bold | 화면 타이틀, 히어로 텍스트 |
| Headline | [design] | .semibold | 섹션 헤더, 리스트 타이틀 |
| Body | .default | .regular | 본문, 설명 텍스트 |

### Component Patterns
| Component | Style | 설명 |
|-----------|-------|------|
| Cards | [photo-forward / compact / stat] | [e.g., "큰 이미지 + 하단 캡션, 16pt radius, subtle shadow"] |
| List Rows | [icon-led / content-led / minimal] | [e.g., "tinted circle 아이콘 + 제목/부제목 + 우측 메타데이터"] |
| Buttons | [filled-capsule / outline / text] | [e.g., "Primary: filled capsule, Secondary: tinted outline"] |
| Empty States | [icon+message / minimal] | [e.g., "SF Symbol + 안내 메시지 + 액션 버튼"] |
| Section Headers | [bold / subtle / accented] | [e.g., "bold + primary underline"] |

## Data Models

> 정확한 타입 정의는 `Models/*.swift` 파일 참조.
> 아래는 관계 개요만 기술.

| Model | Properties (요약) | Relationships |
|-------|------------------|---------------|
| Item | title, note, createdAt, isCompleted | → [Tag] (cascade) |
| Tag | name, color | → [Item] (nullify) |

## Integration Map

| ViewModel | Service Protocol | Screen | 주요 동작 |
|-----------|-----------------|--------|----------|
| HomeViewModel | ItemServiceProtocol | HomeView | fetchAll, add, delete |
| DetailViewModel | ItemServiceProtocol | DetailView | fetch by id, update |

## API Endpoints (if applicable)

| Method | Path | Description | Response Type |
|--------|------|-------------|---------------|
| GET | /api/items | 목록 조회 | [ItemResponse] |
| POST | /api/items | 새 항목 생성 | ItemResponse |

> API가 필요 없는 로컬 전용 앱이면 "N/A" 기재.

## Backend Requirements (if applicable)

> backend가 필요 없는 앱이면 이 섹션 전체를 "N/A"로 기재.

- **Required**: true/false
- **Reason**: OAuth ([providers]) / LLM Proxy / Both
- **Tech Stack**: Python + FastAPI
- **Streaming**: SSE (Server-Sent Events) for LLM endpoints

### Auth Architecture
| Provider | iOS Side | Backend Side |
|----------|----------|-------------|
| Apple | AuthenticationServices (네이티브 UI) | POST /auth/apple — identity token 검증 + JWT 발급 |
| [Provider] | 서버 리다이렉트 | GET /auth/[provider] → callback → JWT 발급 |

> 백엔드가 존재하면 모든 인증은 서버에서 통합 JWT를 발급한다.
> 유저 테이블은 provider-agnostic: (id, email, name, provider, provider_id)

### LLM Endpoints
| Endpoint | Method | Streaming | Upstream | Purpose |
|----------|--------|-----------|----------|---------|
| /api/chat | POST | ✅ SSE | OpenAI | 채팅 응답 |

### Backend File Structure
```
backend/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── app/
│   ├── main.py
│   ├── config.py
│   ├── auth/
│   │   ├── router.py
│   │   ├── apple.py
│   │   ├── [provider].py
│   │   └── jwt.py
│   └── llm/
│       ├── router.py
│       └── proxy.py
├── .env
├── .env.example
└── DEPLOY.md
```

### Environment Variables (.env.example)
| Variable | Purpose |
|----------|---------|
| APPLE_TEAM_ID | Apple Sign In 검증 |
| JWT_SECRET | 토큰 서명 |
| OPENAI_API_KEY | LLM 프록시 (해당 시) |
| ALLOWED_ORIGINS | CORS 허용 도메인 |

## API Contract (if backend required)

> backend가 필요 없으면 "N/A"로 기재.
> 병렬 에이전트(data-engineer, backend-engineer) 간 계약.
> 대응하는 Swift 타입은 Models/APIContracts.swift에 정의.

#### POST /auth/apple
```
Request:  { "identity_token": "string" }
Response: { "access_token": "string", "user": { "id": "string", "email": "string", "name": "string" } }
```

#### POST /api/chat (example)
```
Request:  { "messages": [{ "role": "string", "content": "string" }] }
Response (SSE):
  data: { "content": "string", "done": false }
  data: { "content": "", "done": true }
```

## iOS Configuration (if backend required)

> backend가 필요 없으면 "N/A"로 기재.

### xcconfig
| Key | Debug | Release |
|-----|-------|---------|
| API_BASE_URL | http://localhost:8080 | https://$(PRODUCTION_HOST) |

### Info.plist
- `API_BASE_URL = $(API_BASE_URL)` — xcconfig에서 주입

### NetworkService Rules
- data-engineer는 `Bundle.main`의 `API_BASE_URL`을 base URL로 사용
- Auth 헤더: `Authorization: Bearer <JWT>`
- LLM 스트리밍: `URLSession` bytes iteration으로 SSE 파싱

## Privacy API Categories

| API Category | Reason Code | 사용 이유 |
|-------------|-------------|----------|
| NSPrivacyAccessedAPICategoryFileTimestamp | C617.1 | SwiftData 파일 접근 |

> SwiftData 사용 시 FileTimestamp는 필수. 추가 API는 기능에 따라.

## Required Permissions

| Key | Description (Korean) | 사용 기능 |
|-----|---------------------|----------|
| NSCameraUsageDescription | 카메라 설명 | 기능명 |

> 권한이 필요 없으면 "N/A" 기재.

## Entitlements

| Capability | Entitlement Key | 이유 |
|-----------|----------------|------|
| iCloud | com.apple.developer.icloud-container-identifiers | CloudKit 동기화 |

> capability가 필요 없으면 "N/A" 기재.

## Dependencies

| Package | URL | Version | 사용 목적 |
|---------|-----|---------|----------|
| — | — | — | — |

> Apple 기본 프레임워크만으로 충분하면 "N/A" 기재.

## File Structure

> 프로젝트 루트에 `.autobot/`, `.git/`, `.xcodeproj`가 위치하고,
> **모든 소스 파일은 `AppName/` 서브디렉토리(Xcode 소스 그룹) 안에** 있다.

```
ProjectRoot/                      ← 프로젝트 루트 (git root)
├── .autobot/
│   ├── architecture.md
│   ├── build-state.json
│   ├── design-spec.md            ← Phase 2 (Stitch 사용 시)
│   └── designs/                  ← Phase 2 (화면별 UI 목업)
│       ├── HomeView.png
│       └── DetailView.png
├── .gitignore
├── AppName.xcodeproj/
├── AppName/                      ← Xcode 소스 그룹 (Folder Reference)
│   ├── App/
│   │   ├── AppNameApp.swift
│   │   └── ServiceStubs.swift (Phase 4, Phase 5에서 삭제)
│   ├── Models/                   ← architect만 생성, 다른 에이전트 수정 금지
│   │   ├── Item.swift
│   │   ├── Tag.swift
│   │   └── ServiceProtocols.swift
│   ├── Views/
│   │   ├── Screens/
│   │   │   ├── HomeView.swift
│   │   │   └── DetailView.swift
│   │   └── Components/
│   │       └── ItemRow.swift
│   ├── ViewModels/
│   │   ├── HomeViewModel.swift
│   │   └── DetailViewModel.swift
│   ├── Services/
│   │   ├── ItemRepository.swift
│   │   └── Networking/ (if applicable)
│   ├── Utilities/
│   │   ├── Theme.swift
│   │   └── SampleData.swift
│   ├── Assets.xcassets/
│   ├── PrivacyInfo.xcprivacy
│   ├── AppName.entitlements
│   ├── Debug.xcconfig (if backend required)
│   └── Release.xcconfig (if backend required)
├── AppNameTests/
│   └── AppNameTests.swift
└── backend/ (if backend required)
    ├── Dockerfile
    ├── docker-compose.yml
    └── app/
```
```
