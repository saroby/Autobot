# Autobot

앱 아이디어 하나로 iOS 26+ 앱을 빌드하고 TestFlight에 배포하는 Claude Code 플러그인.

5개의 전문 에이전트가 병렬로 협업하여, 아키텍처 설계부터 TestFlight 업로드까지 자동으로 수행합니다.

> 파이프라인 실행 규격의 단일 기준(SSOT)은 `spec/pipeline.json`입니다. `skills/orchestrator/SKILL.md`와 README는 이 스펙을 설명하는 문서입니다.
> 상태 전이, Gate 실행/기록, Phase lifecycle 로그의 유일한 엔진은 `scripts/pipeline.sh` + `runtime.py`입니다.

## 빠른 시작

### 1. 설치

저장소 자체가 Claude Code 플러그인입니다. 클론한 뒤 `--plugin-dir`로 등록하세요.

```bash
git clone <repo-url> Autobot
claude --plugin-dir /path/to/Autobot
```

### 2. 빌드

```bash
/autobot:make 소셜 피트니스 트래킹 앱
```

### 3. 중단 시 재개

```bash
/autobot:resume        # 마지막 실패 지점부터 자동 재개
/autobot:resume 5      # Phase 5(빌드 검증)부터 강제 재개
```

## 빌드 파이프라인

```
 ┌─────────┐ Gate  ┌───────────┐ Gate  ┌───────────┐ Gate  ┌──────────┐ Gate
 │ Phase 0 │─────▶│  Phase 1  │─────▶│  Phase 2   │─────▶│ Phase 3  │─────▶
 │Preflight│      │ Architect │      │ UX Design  │      │ Scaffold │
 └─────────┘      └───────────┘      └───────────┘      └──────────┘
                                                                      Gate
 ┌─────────┐ soft   ┌───────────┐ Gate  ┌─────────────────┐───────────────▶
 │ Phase 7 │◀──────│  Phase 6  │◀─────│    Phase 5       │
 │ Retro   │       │  Deploy   │      │ Quality Eng.     │
 └─────────┘       └───────────┘      └────────┬─────────┘
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │   Phase 4    │
                                        │ Parallel Dev │
                                        └──────────────┘
```

<!-- AUTOBOT_PHASE_TABLE:START -->
| Phase | 이름 | 에이전트 | 산출물 |
|-------|------|---------|--------|
| 0 | Pre-flight & 환경 준비 | (self) | `build-state.json`, 환경 검증 |
| 1 | 아키텍처 + 계약 | architect | `architecture.md`, `Models/*.swift`, `ServiceProtocols.swift` |
| 2 | UX Design (필수) | ux-designer (Stitch) | `.autobot/designs/*.png`, `.autobot/design-spec.md` |
| 3 | Xcode 프로젝트 | (self) | `.xcodeproj`, `.gitignore`, `PrivacyInfo.xcprivacy`, `.entitlements` |
| 4 | 병렬 코드 생성 | ui-builder + data-engineer (+ backend-engineer) | `Views/`, `ViewModels/`, `Services/`, `App/`, `backend/` |
| 5 | 통합 + 빌드 검증 | quality-engineer | 빌드 성공, 테스트, Integration Wiring |
| 6 | TestFlight 배포 | deployer | 앱 등록, 아카이브, 업로드, 테스터 초대 |
| 7 | 회고 | (self) | `build-report.md`, `learnings.json` 갱신 |
<!-- AUTOBOT_PHASE_TABLE:END -->

### Validation Gate

각 Phase 완료 후 다음 Phase에 진입하기 전에 산출물을 자동 검증합니다:

<!-- AUTOBOT_GATE_SUMMARY:START -->
- **Gate 0→1**: 환경, 앱 이름, 초기 build state 준비가 끝났는지 검증
- **Gate 1→2**: architecture.md 구조, Models/*.swift, ServiceProtocols.swift, 계약 snapshot이 준비됐는지 검증
- **Gate 2→3**: Stitch 성공 시 design-spec/designs 산출물이 있고, 미설치 시 fallback 상태가 기록됐는지 검증
- **Gate 3→4**: .xcodeproj, PrivacyInfo, entitlements, gitignore 등 스캐폴드 필수 파일 존재를 검증
- **Gate 4→5**: Views/Services 산출물 존재 + Models 체크섬 무결성 + sandbox 위반 0건
- **Gate 5→6**: 빌드 성공, 실제 Repository wiring, ServiceStubs.swift 보존 여부를 검증
- **Gate 6→7**: 배포 시도 결과가 기록됐는지 확인하되, 실패해도 회고는 계속 진행 (soft gate)
<!-- AUTOBOT_GATE_SUMMARY:END -->

Gate 실패 시 자동 재시도(최대 2회), 반복 실패 시 Phase 7(회고)으로 건너뛰고 `/autobot:resume`으로 재시도 안내.

### 병렬 에이전트 격리

Phase 4의 ui-builder와 data-engineer는 **파일 소유권 계약**으로 충돌을 피합니다:
- ui-builder는 `Views/`, `ViewModels/`, `App/`만 기록
- data-engineer는 `Services/`, `Utilities/`만 기록
- `Models/`는 Phase 1 계약 스냅샷으로 보호되며 다른 에이전트는 수정 금지

### Service Protocol 패턴

병렬 에이전트 간 연결 문제를 프로토콜 기반으로 해결합니다:

```
architect → Models/ServiceProtocols.swift (인터페이스 정의)
                     │                              │
          ui-builder가 의존          data-engineer가 구현
          (ViewModel → Protocol)    (Repository : Protocol)
                     │                              │
                     └──── quality-engineer가 연결 ────┘
                           (Phase 5: stub → 실제 구현체)
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

## 플러그인 연동

설치되어 있으면 자동으로 활용합니다 (없어도 정상 동작):

| 플러그인 | 활용 | Fallback |
|----------|------|----------|
| **Axiom** | iOS 전문 스킬 (ios-ui, ios-data, ios-build 등) | 내장 iOS 지식 |
| **Serena** | 시맨틱 코딩 — 심볼 기반 편집, 리팩토링 | 일반 Edit 도구 |
| **context7** | 최신 라이브러리/프레임워크 문서 조회 | 학습 데이터 |

## 구성 요소

```
Autobot/                                # 플러그인 루트 ($CLAUDE_PLUGIN_ROOT)
├── .claude-plugin/plugin.json          # 플러그인 매니페스트
├── commands/
│   ├── make.md                         # /autobot:make — 전체 빌드 파이프라인
│   └── resume.md                       # /autobot:resume — 중단된 빌드 재개
├── agents/
│   ├── architect.md                    # Phase 1: 아키텍처 + 타입/통합 계약
│   ├── ui-builder.md                   # Phase 4: SwiftUI 뷰
│   ├── data-engineer.md                # Phase 4: 데이터 레이어
│   ├── quality-engineer.md             # Phase 5: 통합 + 빌드 검증
│   └── deployer.md                     # Phase 6: TestFlight 배포
├── skills/
│   ├── orchestrator/                   # 파이프라인 조율
│   │   ├── SKILL.md                    #   스펙 기반 오케스트레이션 설명
│   │   └── references/
│   │       ├── phase-gates.md          #   Gate check 구현 메모
│   │       ├── architecture-template.md# architecture.md 정형 템플릿
│   │       ├── planning-patterns.md    #   아이디어 분석 패턴
│   │       ├── agent-dispatch.md       #   병렬 에이전트 전략
│   │       └── troubleshooting.md      #   증상별 진단 + 해결법
│   ├── ios-scaffold/                   # Xcode 프로젝트 생성
│   │   ├── SKILL.md
│   │   ├── references/project-templates.md
│   │   └── scripts/
│   │       ├── create-xcode-project.sh # 프로젝트 생성 (xcodegen 우선, fallback)
│   │       └── generate-pbxproj.py     # xcodegen 없이 .xcodeproj 생성
│   ├── testflight-deploy/              # TestFlight 배포
│   │   ├── SKILL.md
│   │   ├── references/signing-guide.md
│   │   └── scripts/archive-upload.sh
│   └── retrospective/                  # 자기 개선 학습
│       ├── SKILL.md
│       └── references/learning-schema.md
├── hooks/hooks.json                    # SessionStart 훅
├── spec/
│   └── pipeline.json                   # 실행 가능한 Phase/Transition/Retry/Gate 규격
└── scripts/
    ├── pipeline.sh                     # 모든 mutating 명령의 단일 진입점 (advance-phase/run-gate/set-flag/append-log 등)
    ├── runtime.py                      # CLI entrypoint + 외부 import 호환 facade (66L)
    ├── spec_loader.py                  # pipeline.json 로드 + 구조 검증
    ├── state_store.py                  # build-state.json I/O + 스키마 검증된 mutation
    ├── event_log.py                    # build-log.jsonl 이벤트 검증 + append
    ├── transitions.py                  # 상태 전이 + retry + circuit breaker
    ├── gate_persistence.py             # gate 실행 결과의 state 기록 + 자동 복구 helpers
    ├── cli.py                          # argparse + 모든 command handler
    ├── gate_runner.py                  # gate 체크 평가 (declarative descriptor + procedural hooks)
    ├── sandbox_runner.py               # spec.fileOwnership 기반 파일 소유권 enforcement
    ├── snapshot_runner.py              # spec.fileOwnership 기반 phase별 snapshot save/restore
    ├── detect-plugins.sh               # 플러그인/도구 감지
    ├── load-learnings.sh               # SessionStart 요약 (학습 데이터 + 빌드 상태)
    ├── render-active-learnings.py      # active/phase learnings 렌더링
    ├── snapshot-contracts.sh           # Models/ snapshot 진입점 (Phase-level은 snapshot_runner.py로 위임)
    ├── build-log.sh                    # 검증된 이벤트 로그 append (runtime.py append-log 위임)
    ├── validate-state.sh               # 진단 전용: schema/transition/list-checks/verify-docs/render-docs (read-only)
    ├── agent-sandbox.sh                # sandbox_runner.py 위임 wrapper
    ├── render_pipeline_docs.py         # spec → README/SKILL 자동 렌더링 블록
    └── verify_spec_docs.py             # spec ↔ 문서 일관성 검증
```

## 빌드 인프라

파이프라인의 신뢰성과 관찰 가능성을 높이는 스크립트:

| 스크립트 | 용도 |
|---------|------|
| `pipeline.sh` | mutating 명령의 단일 진입점. `advance-phase`(gate 실행 + 통과 시 완료 마킹), `run-gate`, `set-flag`, `record-environment`, `start-phase`, `fail-phase`, `append-log` |
| `build-log.sh` | `.autobot/build-log.jsonl`에 검증된 이벤트 append. event 이름과 필수 필드는 `spec/pipeline.json`의 `logEvents`가 SSOT |
| `validate-state.sh` | 진단 전용 read-only: 스키마 검증, transition 검증, gate 체크 목록, 문서 일관성 검증 |
| `agent-sandbox.sh` | `spec.fileOwnership`을 읽어 에이전트 파일 소유권 enforcement. 위반은 `phases.<id>.sandbox.violations`에 자동 기록 → Gate 4→5의 `sandbox_clean` 체크가 평가 |
| `snapshot-contracts.sh` | Models/ 무결성 + Phase-level 스냅샷 — Phase 5 실패 시 Phase 4 복원 |
| `build.lock` | 동시 빌드 실행 방지 — PID 기반 잠금 |

### 단일 truth source 원칙

- **상태**(`build-state.json`): runtime.py의 atomic write만 허용. gate 결정은 오직 state에서만 입력을 읽는다.
- **로그**(`build-log.jsonl`): append-only audit. gate가 절대 참조하지 않음. 이벤트 스키마는 `spec/pipeline.json`의 `logEvents`가 강제.
- **파일 소유권**(`spec.fileOwnership`): agent-sandbox.sh의 단일 권위 위치. agent 시스템 프롬프트는 spec을 따른다.

## 자기 개선

매 빌드마다 `.autobot/learnings.json`에 학습 데이터가 축적됩니다:

- 반복되는 빌드 에러 패턴 및 해결법
- 효과적인 아키텍처 패턴 (앱 유형별)
- 배포 팁 및 사이닝 트러블슈팅
- 에이전트 전략 개선점

다음 빌드 시 `SessionStart` 훅이 `.autobot/active-learnings.md`와 `.autobot/phase-learnings/*.md` 압축본을 자동 생성하고, build/resume/에이전트가 현재 Phase에 맞는 파일을 먼저 읽어 과거 실패 방지 규칙과 proven pattern을 바로 반영합니다.

Phase learning 파일 매핑:
- Phase 1 → `architecture.md`
- Phase 4 → `parallel_coding.md`
- Phase 5 → `quality.md`
- Phase 6 → `deploy.md`

## Safety Policy

Autobot은 위험도 기준으로 동작합니다:

- `autonomous`: 로컬 코드 생성, 수정, 빌드, 테스트, archive
- `warn`: Stitch 미설치, ASC 미설정, fastlane 미설치처럼 결과만 달라지는 상황
- `require_confirmation`: 원격 저장소 생성/푸시처럼 되돌리기 어려운 외부 변경

기본 build/resume 파이프라인은 원격 저장소 생성/푸시를 포함하지 않습니다.

## 트러블슈팅

자세한 증상별 진단은 `skills/orchestrator/references/troubleshooting.md` 참조.

| 상황 | 해결 |
|------|------|
| Phase 실패 | `/autobot:resume` (자동 재개) 또는 `/autobot:resume <N>` (특정 Phase부터) |
| 빌드 에러 반복 | `/autobot:resume 4` (코드 재생성부터) |
| 배포만 재시도 | `/autobot:resume 6` |
| 전체 초기화 | `rm -rf .autobot/build-state.json` 후 `/autobot:make` |

## 라이선스

MIT
