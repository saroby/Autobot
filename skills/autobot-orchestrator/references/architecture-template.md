# Architecture Document Template

architect 에이전트가 생성하는 `.autobot/architecture.md`의 정형화된 템플릿.
모든 섹션이 존재해야 Gate 1→2를 통과한다. 해당 없는 섹션은 "N/A"로 표시.

---

```markdown
# [Display Name] Architecture

- **Identifier**: `PascalCaseAppName`
- **Display Name**: `표시 이름`
- **Bundle ID**: `com.axi.pascalcaseappname`

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
>
> **접근성 가이드라인:**
> - Primary/Secondary 색상은 해당 모드의 배경색 위에서 WCAG AA (4.5:1) 이상의 대비율 확보
> - Large text (18pt+ 또는 14pt bold)는 3:1 이상
> - Surface 색상은 그 위에 올라갈 텍스트와 충분한 대비를 갖출 것
>
> **색상 조화:** Primary-Secondary-Accent는 다음 중 하나를 따른다:
> - Analogous (유사색): 색상환에서 인접한 색 — 조화롭고 차분
> - Complementary (보색): 반대편 색 — 대비가 강하고 역동적
> - Split-complementary: 보색의 양 옆 — 대비+조화 균형

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

### Layout Personality

앱의 핵심 콘텐츠 유형에 대한 **출발 힌트**(starting hint)다. 아래 4종은 *기본 골격*일
뿐 — 그대로 베끼면 모든 앱이 닮는다(AI 슬롭). 반드시 다음의 `### Signature Layout` 으로
이 앱만의 고유한 구성을 명시하고, ui-builder 는 그것을 우선한다.

| Type | Pattern | 특징 | 적합한 앱 |
|------|---------|------|----------|
| data-driven | Dashboard + Grid | 큰 숫자 stat 카드, LazyVGrid, 차트 영역, compact density | 피트니스 트래커, 금융, 대시보드 |
| content-forward | Card Feed | 큰 이미지 카드, ScrollView, pull-to-refresh, spacious | 레시피, 소셜, 뉴스, 여행 |
| utility | Step / Form | 순차 단계, Form + Section, 체크리스트, efficient density | 할일, 설정, 유틸리티 |
| social | Feed + Compose | 타임라인 리스트, 프로필 헤더, FAB compose, avatar-centric | 소셜, 커뮤니티, 메시징 |

```
Layout Personality: [data-driven / content-forward / utility / social]
```

> 앱의 주요 화면이 여러 유형을 혼합할 수 있다 (예: 홈=dashboard, 상세=content-forward).
> 이 경우 화면별로 다른 패턴을 지정한다.

### Signature Layout

이 앱을 *같은 Layout Personality 의 다른 앱과 구별되게* 만드는 고유 구성. 4종 골격을
**이 아이디어에 맞춰 변형**하는 지점이다 — "또 그 앱처럼 생김"을 막는 1급 출력.
아래 4가지를 구체적으로 적는다 (추상어 금지 — "modern, clean" 같은 말은 무효):

| 항목 | 설명 | 예 (여행 일정 앱, content-forward 기반) |
|------|------|------------------------------------------|
| **Hero element** | 각 핵심 화면에서 가장 크게/먼저 보이는 시각 요소 | Today: 다가오는 여행의 풀블리드 커버 사진 + 카운트다운 오버레이 |
| **정보 위계** | 무엇을 강조하고 무엇을 부차로 | 날짜·장소가 1순위, 예약 디테일은 탭 시 펼침 |
| **Density** | compact / comfortable / spacious + 근거 | spacious — 여행은 설렘이 핵심, 정보 밀도보다 여백·이미지 |
| **화면 간 차별화** | 모든 화면이 동일 컨테이너면 안 됨 — 화면별 고유 구성 | Today=히어로 카드 / Itinerary=수직 타임라인 / Map=풀스크린 지도+하단 시트 |

> **금지**: 모든 화면을 같은 `List`/`LazyVStack` 카드로 채우는 것. "화면 간 차별화" 칸에는
> **주요 화면 각각**의 컨테이너/구성을 한 줄씩 적고(primary 둘만이 아니라 전부), 최소한 primary 와
> 2순위 화면은 서로 다른 몰드를 가져야 한다.
>
> **제네릭 무효 판별 (작성 직후 자가 점검 — 필수)**: 표를 다 채운 뒤 **앱 이름·도메인 명사를
> 가려도** 어느 앱인지 알 수 없으면 그 칸은 무효다 — 다시 써라. 아래 대조가 기준이다
> (위 예시는 여행 앱 / 아래는 피트니스 트래커 — *서로 다른 도메인에서 원칙이 똑같이 성립*).
>
> | 칸 | ❌ 무효 (어떤 앱이든 해당) | ✅ 유효 (이 앱만 식별됨) |
> |----|--------------------------|--------------------------|
> | Hero element | "큰 카드" · "상단 배너" · "리스트" | "Today: 활동 링 3종(이동·운동·서기) 풀와이드 + 가운데 큰 칼로리 숫자" |
> | 정보 위계 | "중요한 것 강조" | "오늘 달성률 링이 1순위, 개별 운동 로그는 하단 스크롤로 부차" |
> | Density | "comfortable" | "compact — 한눈에 여러 지표를 비교하는 게 핵심이라 카드를 촘촘히" |
> | 화면 간 차별화 | "화면마다 다르게" | "Today=활동 링 대시보드 / History=주간 막대 차트 / Workout=풀스크린 타이머+심박 게이지" |
>
> Gate 1→2 는 이 heading 의 *존재만* 강제한다(제네릭도 통과) — 자율 빌드(`/mvp`)에선 위 자가
> 점검이 품질의 유일한 장치이고, Phase 2.5 critique(디자인 축, "templated/제네릭/화면 간 동일")는
> `/plan` 경로에서 2차로 점검한다.

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

> 프로젝트 루트에 `.autobot/`, `.xcodeproj`가 위치하고,
> **모든 소스 파일은 `AppName/` 서브디렉토리(Xcode 소스 그룹) 안에** 있다.

```
ProjectRoot/                      ← 프로젝트 루트
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
