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

### 새 빌드
```
/autobot:build 소셜 피트니스 트래킹 앱
```

### 중단된 빌드 재개
```
/autobot:resume        # 마지막 실패/중단 지점부터 재개
/autobot:resume 4      # Phase 4(빌드 검증)부터 강제 재개
/autobot:resume 5      # Phase 5(배포)만 다시 실행
```

빌드가 중간에 실패하거나 세션이 끊겨도 `.autobot/build-state.json`에 진행 상태가 저장되어 있어 이어서 실행할 수 있습니다.

### 빌드 파이프라인

`/autobot:build` 실행 시 질문 없이 자동으로:

1. **아키텍처 설계** — architect 에이전트가 기능, 화면, 데이터 모델 정의
2. **프로젝트 생성** — Xcode 프로젝트 스캐폴딩 (xcodegen 또는 수동)
3. **병렬 개발** — ui-builder + data-engineer 에이전트 동시 실행
4. **빌드 검증** — quality-engineer 에이전트가 컴파일 에러 수정 및 테스트 작성
5. **TestFlight 배포** — deployer 에이전트가 앱 등록(fastlane) → 아카이브 → 업로드 → '내부' 테스터 그룹 생성

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
- `fastlane` — App Store Connect 앱 자동 등록용 (`brew install fastlane`, 없으면 자동 설치 시도)

## 환경변수 설정 (TestFlight 배포용)

TestFlight 자동 배포를 사용하려면 `.env` 파일을 설정합니다.
세션 시작 시 `SessionStart` 훅이 자동으로 읽어 환경변수를 주입합니다.

### 방법 1: 프로젝트별 설정 (권장)

앱을 빌드할 작업 디렉토리에 `.env` 파일 생성:

```bash
# 작업 디렉토리에서
cat > .env << 'EOF'
ASC_API_KEY_ID=XXXXXXXXXX
ASC_API_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ASC_API_KEY_PATH=~/.appstoreconnect/private_keys/AuthKey_XXXXXXXXXX.p8
DEVELOPMENT_TEAM=A1B2C3D4E5
TESTER_EMAIL=your@email.com
EOF
```

### 방법 2: 글로벌 설정 (모든 프로젝트 공용)

```bash
mkdir -p ~/.config/autobot
cat > ~/.config/autobot/.env << 'EOF'
ASC_API_KEY_ID=XXXXXXXXXX
ASC_API_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ASC_API_KEY_PATH=~/.appstoreconnect/private_keys/AuthKey_XXXXXXXXXX.p8
DEVELOPMENT_TEAM=A1B2C3D4E5
TESTER_EMAIL=your@email.com
EOF
```

### 방법 3: Apple ID 인증 (API Key 대안)

```bash
APPLE_ID=your@email.com
APP_SPECIFIC_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

> **우선순위**: 프로젝트 `.env` → 글로벌 `~/.config/autobot/.env`
>
> 미설정 시 IPA 파일 경로를 안내하고 수동 업로드를 유도합니다.

### 환경변수 전체 목록

| 변수 | 필수 | 설명 |
|------|------|------|
| `ASC_API_KEY_ID` | 배포 시 | App Store Connect API Key ID |
| `ASC_API_ISSUER_ID` | 배포 시 | App Store Connect Issuer ID |
| `ASC_API_KEY_PATH` | 배포 시 | .p8 키 파일 경로 |
| `APPLE_ID` | 대안 | Apple ID 이메일 (API Key 미사용 시) |
| `APP_SPECIFIC_PASSWORD` | 대안 | 앱 전용 비밀번호 (appleid.apple.com에서 생성) |
| `DEVELOPMENT_TEAM` | 선택 | 개발 팀 ID (자동 감지 가능) |
| `TESTER_EMAIL` | 선택 | TestFlight '내부' 그룹 초대 이메일 |

### 선택적 도구

- `xcodegen` — 더 안정적인 프로젝트 생성 (`brew install xcodegen`)
- `fastlane`이 없을 경우 자동 설치를 시도하지만, Homebrew가 없으면 수동 설치 필요

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
├── commands/resume.md               # /autobot:resume 커맨드 (중단된 빌드 재개)
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
