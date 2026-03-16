# Autobot

앱 아이디어 하나로 엔터프라이즈급 iOS 26+ 앱을 빌드하고 TestFlight에 배포하는 Claude Code 플러그인.

## 사용법

```
/autobot:build 소셜 피트니스 트래킹 앱
```

질문 없이 자동으로:
1. 앱 아키텍처 설계
2. Xcode 프로젝트 생성
3. 병렬 에이전트로 UI/데이터 레이어 동시 개발
4. 빌드 검증 및 테스트
5. TestFlight 배포 (코드 사이닝 → 아카이브 → 업로드)
6. '내부' 테스터 그룹 생성 및 초대

## 설치

```bash
claude --plugin-dir /path/to/Autobot
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

### 선택적 도구

- `xcodegen` — 더 안정적인 프로젝트 생성 (`brew install xcodegen`)

## 플러그인 연동

설치되어 있으면 자동으로 활용 (없어도 정상 동작):
- **Axiom** — iOS 개발 전문 스킬 (ios-ui, ios-data, ios-build 등)
- **Serena** — 시맨틱 코딩 도구
- **context7** — 최신 라이브러리 문서 조회

## 구성 요소

| 유형 | 이름 | 역할 |
|------|------|------|
| Command | `build` | 메인 진입점, 전체 파이프라인 오케스트레이션 |
| Agent | `architect` | 앱 아키텍처 설계 |
| Agent | `ui-builder` | SwiftUI 뷰 구현 |
| Agent | `data-engineer` | 데이터/네트워킹 레이어 구현 |
| Agent | `quality-engineer` | 빌드 검증 및 테스트 |
| Agent | `deployer` | 코드 사이닝 및 TestFlight 배포 |
| Skill | `orchestrator` | 파이프라인 조율 지식 |
| Skill | `ios-scaffold` | Xcode 프로젝트 생성 |
| Skill | `testflight-deploy` | TestFlight 배포 절차 |
| Skill | `retrospective` | 빌드 학습 및 자기 개선 |

## 자기 개선

매 빌드마다 `.autobot/learnings.json`에 학습 데이터가 축적됩니다:
- 반복되는 빌드 에러 패턴 및 해결법
- 효과적인 아키텍처 패턴
- 배포 팁
- 에이전트 전략 개선

다음 빌드 시 자동으로 과거 학습을 반영합니다.
