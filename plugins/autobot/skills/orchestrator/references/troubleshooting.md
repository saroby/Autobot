# Autobot Troubleshooting Guide

## 증상별 진단

### Phase 0: 환경 문제

| 증상 | 원인 | 해결 |
|------|------|------|
| "xcode-select: error" | Command Line Tools 미설치 | `xcode-select --install` |
| "No available simulators" | Simulator 런타임 미설치 | Xcode → Settings → Platforms → iOS 다운로드 |
| ".env 로드 안됨" | SessionStart 훅이 .env를 못 찾음 | 작업 디렉토리에 `.env` 파일 확인, 또는 `~/.config/autobot/.env` |
| "build-state.json 없음" | /autobot:resume 실행했지만 이전 빌드 없음 | `/autobot:build`로 새 빌드 시작 |

### Phase 1: 아키텍처 실패

| 증상 | 원인 | 해결 |
|------|------|------|
| architect가 `<AppName>/Models/` 파일을 안 만듦 | 프롬프트 미준수 또는 경로 오류 | 에이전트가 `<AppName>/Models/`가 아닌 `Models/`에 파일을 생성했는지 확인 후 `/autobot:resume 1`로 재실행 |
| ServiceProtocols.swift 누락 | architect 프롬프트에서 놓침 | `/autobot:resume 1` |
| architecture.md가 불완전 | 아이디어가 너무 모호 | 더 구체적인 아이디어로 `/autobot:build` 재시작 |

### Phase 2: 프로젝트 생성 실패

| 증상 | 원인 | 해결 |
|------|------|------|
| ".xcodeproj not found" | xcodegen 없고 pbxproj 생성 실패 | `python3 --version` 확인 (3.8+ 필요) |
| "xcodegen generate failed" | project.yml 문법 오류 | `xcodegen` 없이 fallback으로 재시도: `rm project.yml && /autobot:resume 2` |
| 번들 ID 충돌 | 이미 다른 프로젝트에서 사용 중 | `build-state.json`의 bundleId 수정 후 `/autobot:resume 2` |

### Phase 3: 코드 생성 실패

| 증상 | 원인 | 해결 |
|------|------|------|
| `<AppName>/Models/` 파일이 변경됨 | 에이전트가 금지 규칙 위반 | Gate 3→4에서 자동 복원 (`git checkout -- <AppName>/Models/`) |
| `<AppName>/Views/` 비어있음 | ui-builder 에이전트 실패 또는 프로젝트 루트에 잘못 생성 | `Views/`가 `<AppName>/Views/`에 있는지 확인 후 `/autobot:resume 3` |
| `<AppName>/Services/` 비어있음 | data-engineer 에이전트 실패 또는 경로 오류 | `/autobot:resume 3` |
| 파일 소유권 위반 | 에이전트가 다른 에이전트 디렉토리에 쓴 경우 | 위반 파일 삭제 후 해당 에이전트 재실행 |
| 에이전트가 컨텍스트 초과 | 화면/모델이 너무 많아 에이전트 용량 초과 | architect가 기능을 줄이도록 아이디어를 단순화하여 재빌드 |

### Phase 4: 빌드 실패

| 증상 | 원인 | 해결 |
|------|------|------|
| "Cannot find type 'X'" | import 누락 또는 타입명 불일치 | quality-engineer가 자동 수정 (5회 반복) |
| "No such module 'X'" | SPM dependency 미해결 | `xcodebuild -resolvePackageDependencies` 실행 |
| 새 .swift 파일이 빌드에 안 잡힘 | pbxproj 재생성 안 함 | Phase 4 시작 시 자동 재생성 (Step 0) |
| ServiceStubs 남아있음 | Integration Wiring 실패 | `/autobot:resume 4` |
| 5회 재시도 후에도 실패 | 구조적 불일치 | Phase 3부터 재시도: `/autobot:resume 3` |

### Phase 5: 배포 실패

| 증상 | 원인 | 해결 |
|------|------|------|
| "No signing certificate" | 인증서 없음 | Xcode → Settings → Accounts → Manage Certificates |
| "Bundle ID not available" | App Store Connect에 미등록 | fastlane produce가 자동 등록하지만, 이름 충돌 시 수동 변경 |
| "Authentication failed" | ASC API Key 오류 | `.env`의 ASC_API_KEY_ID, ISSUER_ID, KEY_PATH 확인 |
| "Upload failed" | 네트워크 또는 ASC 서버 문제 | `/autobot:resume 5`로 재시도 |
| fastlane 설치 실패 | Homebrew 없음 | `brew` 설치 후 재시도, 또는 `gem install fastlane` |

## 긴급 복구

### 전체 초기화 (프로젝트는 유지, 빌드 상태만 리셋)
```bash
rm -rf .autobot/build-state.json
# 그 후 /autobot:resume 또는 /autobot:build 재실행
```

### Phase 3 결과만 폐기하고 재생성
```bash
rm -rf <AppName>/Views/ <AppName>/ViewModels/ <AppName>/Services/ <AppName>/Utilities/ <AppName>/App/ServiceStubs.swift
/autobot:resume 3
```

### 프로젝트 전체 폐기하고 재빌드
```bash
cd .. && rm -rf <AppName>/
/autobot:build <아이디어>
```

## 성능 문제

| 증상 | 원인 | 완화 |
|------|------|------|
| Phase 1이 5분 이상 | opus 모델 사용 + 복잡한 아이디어 | 아이디어를 단순화 |
| Phase 3이 10분 이상 | 에이전트가 너무 많은 파일 생성 시도 | architect에서 화면 수를 5개 이하로 제한 |
| Phase 4가 무한 루프 | 에이전트가 같은 에러를 반복 수정 | 5회 재시도 후 자동 중단됨, `/autobot:resume 3`으로 코드 재생성 |
