# Autobot

앱 아이디어 하나로 엔터프라이즈급 iOS 26+ 앱을 빌드하고 TestFlight에 배포하는 Claude Code 플러그인.

## 설치

Claude Code 마켓플레이스에서 설치:

```
/plugin → Add Marketplace → saroby/Autobot
```

또는 로컬 테스트:
```bash
claude --plugin-dir /path/to/Autobot/plugins/autobot
```

## 사용법

```
/autobot:build 소셜 피트니스 트래킹 앱
```

질문 없이 자동으로:

1. **아키텍처 설계** — architect 에이전트가 기능, 화면, 데이터 모델 정의
2. **프로젝트 생성** — Xcode 프로젝트 스캐폴딩 (xcodegen 또는 수동)
3. **병렬 개발** — ui-builder + data-engineer 에이전트 동시 실행
4. **빌드 검증** — quality-engineer 에이전트가 컴파일 에러 수정 및 테스트 작성
5. **TestFlight 배포** — deployer 에이전트가 아카이브 → 업로드 → '내부' 테스터 그룹 생성

## 빌드 파이프라인

```
아이디어 입력
    │
    ▼
┌─────────────┐
│  architect   │  Phase 1: 아키텍처 설계
└──────┬──────┘
       ▼
┌─────────────┐
│  scaffold    │  Phase 2: Xcode 프로젝트 생성
└──────┬──────┘
       ▼
┌──────┴──────┐
│  병렬 실행    │  Phase 3: 코드 생성
├─────────────┤
│ ui-builder  │──▶ Views/, ViewModels/, App/
│ data-engineer│──▶ Models/, Services/
└──────┬──────┘
       ▼
┌─────────────┐
│  quality     │  Phase 4: 빌드 검증 & 테스트
└──────┬──────┘
       ▼
┌─────────────┐
│  deployer    │  Phase 5: TestFlight 배포
└──────┬──────┘
       ▼
┌─────────────┐
│ retrospective│  Phase 6: 학습 데이터 축적
└─────────────┘
```

## 필수 요건

- Xcode 16+ (Command Line Tools 포함)
- iOS 26+ SDK
- Apple Developer 계정 (TestFlight 배포용)

## 선택적 설정

### TestFlight 자동 업로드

App Store Connect API Key 방식 (권장):
```bash
export ASC_API_KEY_ID="XXXXXXXXXX"
export ASC_API_ISSUER_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
export ASC_API_KEY_PATH="~/.appstoreconnect/private_keys/AuthKey_XXX.p8"
```

또는 Apple ID 방식:
```bash
export APPLE_ID="your@email.com"
export APP_SPECIFIC_PASSWORD="xxxx-xxxx-xxxx-xxxx"
```

> 자격증명 미설정 시 IPA 파일 경로를 안내하고 수동 업로드를 유도합니다.

### 선택적 도구

- `xcodegen` — 더 안정적인 프로젝트 생성 (`brew install xcodegen`)

## 플러그인 연동

설치되어 있으면 자동으로 활용합니다 (없어도 정상 동작):

| 플러그인 | 활용 내용 |
|----------|-----------|
| **Axiom** | iOS 전문 스킬 (ios-ui, ios-data, ios-build, ios-concurrency 등) |
| **Serena** | 시맨틱 코딩 — 심볼 기반 편집, 리팩토링 |
| **context7** | 최신 라이브러리/프레임워크 문서 조회 |

플러그인 감지는 `UserPromptSubmit` 훅에서 자동으로 수행됩니다.

## 구성 요소

```
plugins/autobot/
├── .claude-plugin/plugin.json       # 플러그인 매니페스트
├── commands/build.md                # /autobot:build 커맨드
├── agents/                          # 5개 전문 에이전트
│   ├── architect.md                 #   아키텍처 설계 (opus)
│   ├── ui-builder.md                #   SwiftUI 뷰 (sonnet, 병렬)
│   ├── data-engineer.md             #   데이터 레이어 (sonnet, 병렬)
│   ├── quality-engineer.md          #   빌드 검증/테스트 (sonnet)
│   └── deployer.md                  #   TestFlight 배포 (sonnet)
├── skills/                          # 4개 전문 스킬
│   ├── orchestrator/                #   파이프라인 조율
│   ├── ios-scaffold/                #   Xcode 프로젝트 생성
│   ├── testflight-deploy/           #   배포 절차
│   └── retrospective/               #   자기 개선 학습
├── hooks/hooks.json                 # SessionStart/UserPromptSubmit 훅
└── scripts/                         # 플러그인 감지/학습 로드
```

## 자기 개선

매 빌드마다 `.autobot/learnings.json`에 학습 데이터가 축적됩니다:

- 반복되는 빌드 에러 패턴 및 해결법
- 효과적인 아키텍처 패턴 (앱 유형별)
- 배포 팁 및 사이닝 트러블슈팅
- 에이전트 전략 개선점

다음 빌드 시 `SessionStart` 훅이 과거 학습을 자동 로드하여 빌드 품질을 개선합니다.

## 라이선스

MIT
