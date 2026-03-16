# Autobot

앱 아이디어 하나로 iOS 26+ 앱을 빌드하고 TestFlight에 배포하는 Claude Code 플러그인.

5개의 전문 에이전트가 병렬로 협업하여, 아키텍처 설계부터 TestFlight 업로드까지 질문 없이 자동으로 수행합니다.

## 빠른 시작

### 1. 설치

```bash
# 마켓플레이스에서
/plugin → Add Marketplace → saroby/Autobot

# 또는 로컬
claude --plugin-dir /path/to/Autobot/plugins/autobot
```

### 2. (선택) 환경 설정

TestFlight 자동 배포를 원하면 `.env` 파일을 설정합니다:

```bash
cat > .env << 'EOF'
ASC_API_KEY_ID=XXXXXXXXXX
ASC_API_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ASC_API_KEY_PATH=~/.appstoreconnect/private_keys/AuthKey_XXXXXXXXXX.p8
DEVELOPMENT_TEAM=A1B2C3D4E5
TESTER_EMAIL=your@email.com
EOF
```

> 미설정 시 빌드까지는 정상 진행되고, 배포 단계에서 IPA 파일 경로와 수동 업로드 방법을 안내합니다.

### 3. 빌드

```bash
/autobot:build 소셜 피트니스 트래킹 앱
```

### 4. 중단 시 재개

```bash
/autobot:resume        # 마지막 실패 지점부터 자동 재개
/autobot:resume 4      # Phase 4(빌드 검증)부터 강제 재개
```

## 빌드 파이프라인

```
 ┌─────────┐ Gate  ┌───────────┐ Gate  ┌──────────┐ Gate  ┌─────────────────┐
 │ Phase 0  │─────▶│  Phase 1   │─────▶│ Phase 2   │─────▶│    Phase 3       │
 │Pre-flight│      │ Architect  │      │ Scaffold  │      │ ┌─────────────┐ │
 └─────────┘      │ (opus)     │      └──────────┘      │ │ ui-builder  │ │
                   └───────────┘                          │ │ data-eng.   │ │
                                                          │ └─────────────┘ │
                                                          └────────┬────────┘
                   ┌─────────┐ soft   ┌───────────┐ Gate          │
                   │ Phase 6  │◀──────│  Phase 5   │◀─────┌───────┴────────┐
                   │ Retro    │       │  Deploy    │      │    Phase 4      │
                   └─────────┘       └───────────┘      │ Quality Eng.    │
                                                          └────────────────┘
```

| Phase | 이름 | 에이전트 | 산출물 |
|-------|------|---------|--------|
| 0 | Pre-flight & 환경 준비 | (self) | `build-state.json`, 환경 검증 |
| 1 | 아키텍처 + 계약 | architect (opus) | `architecture.md`, `Models/*.swift`, `ServiceProtocols.swift` |
| 2 | Xcode 프로젝트 | (self) | `.xcodeproj`, `.gitignore`, `PrivacyInfo.xcprivacy`, `.entitlements` |
| 3 | 병렬 코드 생성 | ui-builder + data-engineer (sonnet, worktree) | `Views/`, `ViewModels/`, `Services/`, `App/` |
| 4 | 통합 + 빌드 검증 | quality-engineer (sonnet) | 빌드 성공, 테스트, Integration Wiring |
| 5 | TestFlight 배포 | deployer (sonnet) | 앱 등록, 아카이브, 업로드, 테스터 초대 |
| 6 | 회고 | (self) | `learnings.json` 갱신 |

### Validation Gate

각 Phase 완료 후 다음 Phase에 진입하기 전에 산출물을 자동 검증합니다:

- **Gate 1→2**: architecture.md 구조, Models/*.swift 존재, ServiceProtocols.swift 존재
- **Gate 2→3**: .xcodeproj 유효성, PrivacyInfo/Entitlements/gitignore 존재
- **Gate 3→4**: Views/Services 파일 존재, **Models/ 무결성** (체크섬 비교 → 오염 시 자동 복원)
- **Gate 4→5**: xcodebuild BUILD SUCCEEDED, ServiceStubs 제거 완료

Gate 실패 시 자동 재시도(최대 2회), 반복 실패 시 Phase 6(회고)으로 건너뛰고 `/autobot:resume`으로 재시도 안내.

### 병렬 에이전트 격리

Phase 3의 ui-builder와 data-engineer는 **별도의 git worktree**에서 실행됩니다:
- 파일시스템 수준의 격리로 충돌 방지
- `Models/`는 양쪽 모두 읽기 전용 (타입 계약)
- 완료 후 `git merge`로 통합 — 서로 다른 디렉토리에 쓰므로 충돌 없음

### Service Protocol 패턴

병렬 에이전트 간 연결 문제를 프로토콜 기반으로 해결합니다:

```
architect → Models/ServiceProtocols.swift (인터페이스 정의)
                     │                              │
          ui-builder가 의존          data-engineer가 구현
          (ViewModel → Protocol)    (Repository : Protocol)
                     │                              │
                     └──── quality-engineer가 연결 ────┘
                           (Phase 4: stub → 실제 구현체)
```

## 필수 요건

| 요건 | 확인 명령 | 용도 |
|------|----------|------|
| Xcode 16+ (CLI Tools) | `xcode-select -p` | 빌드, 시뮬레이터 |
| iOS 26+ SDK | `xcrun --sdk iphoneos --show-sdk-version` | 타겟 SDK |
| Python 3 | `python3 --version` | pbxproj fallback 생성 |
| Apple Developer 계정 | — | TestFlight 배포 (선택) |

### 선택 도구

| 도구 | 설치 | 효과 |
|------|------|------|
| `xcodegen` | `brew install xcodegen` | 더 안정적인 프로젝트 생성 |
| `fastlane` | `brew install fastlane` (또는 자동 설치) | App Store Connect 앱 자동 등록 |

## 환경변수 설정

TestFlight 자동 배포용. 미설정 시 빌드까지는 정상 동작.

| 변수 | 필수 | 설명 |
|------|------|------|
| `ASC_API_KEY_ID` | 배포 시 | App Store Connect API Key ID |
| `ASC_API_ISSUER_ID` | 배포 시 | App Store Connect Issuer ID |
| `ASC_API_KEY_PATH` | 배포 시 | .p8 키 파일 경로 |
| `DEVELOPMENT_TEAM` | 선택 | 개발 팀 ID (자동 감지 가능) |
| `TESTER_EMAIL` | 선택 | TestFlight '내부' 그룹 초대 이메일 |

설정 방법:
- **프로젝트별**: 작업 디렉토리에 `.env` 파일 (우선)
- **글로벌**: `~/.config/autobot/.env`

## 플러그인 연동

설치되어 있으면 자동으로 활용합니다 (없어도 정상 동작):

| 플러그인 | 활용 | Fallback |
|----------|------|----------|
| **Axiom** | iOS 전문 스킬 (ios-ui, ios-data, ios-build 등) | 내장 iOS 지식 |
| **Serena** | 시맨틱 코딩 — 심볼 기반 편집, 리팩토링 | 일반 Edit 도구 |
| **context7** | 최신 라이브러리/프레임워크 문서 조회 | 학습 데이터 |

## 구성 요소

```
plugins/autobot/
├── .claude-plugin/plugin.json          # 플러그인 매니페스트
├── commands/
│   ├── build.md                        # /autobot:build — 전체 빌드 파이프라인
│   └── resume.md                       # /autobot:resume — 중단된 빌드 재개
├── agents/
│   ├── architect.md                    # Phase 1: 아키텍처 + 타입/통합 계약 (opus)
│   ├── ui-builder.md                   # Phase 3: SwiftUI 뷰 (sonnet, worktree)
│   ├── data-engineer.md                # Phase 3: 데이터 레이어 (sonnet, worktree)
│   ├── quality-engineer.md             # Phase 4: 통합 + 빌드 검증 (sonnet)
│   └── deployer.md                     # Phase 5: TestFlight 배포 (sonnet)
├── skills/
│   ├── orchestrator/                   # 파이프라인 조율
│   │   ├── SKILL.md                    #   Phase 정의, Gate, 에러 복구, 롤백
│   │   └── references/
│   │       ├── phase-gates.md          #   Phase별 검증 항목
│   │       ├── architecture-template.md#   architecture.md 정형 템플릿
│   │       ├── planning-patterns.md    #   아이디어 분석 패턴
│   │       ├── agent-dispatch.md       #   병렬 에이전트 전략
│   │       └── troubleshooting.md      #   증상별 진단 + 해결법
│   ├── ios-scaffold/                   # Xcode 프로젝트 생성
│   │   ├── SKILL.md
│   │   ├── references/project-templates.md
│   │   └── scripts/
│   │       ├── create-xcode-project.sh #   프로젝트 생성 (xcodegen 우선, fallback)
│   │       └── generate-pbxproj.py     #   xcodegen 없이 .xcodeproj 생성
│   ├── testflight-deploy/              # TestFlight 배포
│   │   ├── SKILL.md
│   │   ├── references/signing-guide.md
│   │   └── scripts/archive-upload.sh
│   └── retrospective/                  # 자기 개선 학습
│       ├── SKILL.md
│       └── references/learning-schema.md
├── hooks/hooks.json                    # SessionStart + UserPromptSubmit 훅
└── scripts/
    ├── detect-plugins.sh               # 플러그인/도구 감지
    └── load-learnings.sh               # .env 로드 + 학습 데이터 + 빌드 상태
```

## 자기 개선

매 빌드마다 `.autobot/learnings.json`에 학습 데이터가 축적됩니다:

- 반복되는 빌드 에러 패턴 및 해결법
- 효과적인 아키텍처 패턴 (앱 유형별)
- 배포 팁 및 사이닝 트러블슈팅
- 에이전트 전략 개선점

다음 빌드 시 `SessionStart` 훅이 과거 학습을 자동 로드하여 빌드 품질을 개선합니다.

## 트러블슈팅

자세한 증상별 진단은 `skills/orchestrator/references/troubleshooting.md` 참조.

| 상황 | 해결 |
|------|------|
| Phase 실패 | `/autobot:resume` (자동 재개) 또는 `/autobot:resume <N>` (특정 Phase부터) |
| 빌드 에러 반복 | `/autobot:resume 3` (코드 재생성부터) |
| 배포만 재시도 | `/autobot:resume 5` |
| 전체 초기화 | `rm -rf .autobot/build-state.json` 후 `/autobot:build` |

## 라이선스

MIT
