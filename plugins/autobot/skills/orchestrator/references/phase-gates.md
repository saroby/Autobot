# Phase Validation Gates

매 Phase 완료 후, 다음 Phase에 진입하기 전에 **산출물 검증(Validation Gate)**을 통과해야 한다.
Gate를 통과하지 못하면 Phase를 `failed`로 마킹하고 재시도하거나 사용자에게 안내한다.

> **경로 규칙**: `<AppName>`은 `build-state.json`의 `appName` 값. 모든 소스 파일은 `<AppName>/` 서브디렉토리 (Xcode 소스 그룹) 안에 있어야 빌드에 포함된다.

## Gate 정의

### Gate 0→1: 환경 준비 완료

```
CHECK:
  ✓ 프로젝트 디렉토리 존재
  ✓ git init 완료 (.git/ 존재)
  ✓ .autobot/ 디렉토리 존재
  ✓ .autobot/build-state.json 존재 & 유효한 JSON
  ✓ appName이 /^[A-Z][a-zA-Z0-9]*$/ 패턴 충족
FAIL → Phase 0 재실행
```

### Gate 1→2: 아키텍처 + 타입 계약 완료

```
CHECK:
  ✓ .autobot/architecture.md 존재 & 비어있지 않음
  ✓ <AppName>/Models/*.swift 파일이 1개 이상 존재
  ✓ <AppName>/Models/ServiceProtocols.swift 존재
  ✓ 모든 <AppName>/Models/*.swift에 'import SwiftData' 또는 'import Foundation' 포함
  ✓ architecture.md에 ## Screens 섹션 존재
  ✓ architecture.md에 ## Integration Map 섹션 존재
  ✓ architecture.md에 ## Privacy API Categories 섹션 존재
  ✓ (backend_required) architecture.md에 ## Backend Requirements 섹션 존재
  ✓ (backend_required) architecture.md에 ## API Contract 섹션 존재
  ✓ (backend_required) architecture.md에 ## iOS Configuration 섹션 존재
  ✓ (backend_required) <AppName>/Models/APIContracts.swift 존재
  ✓ (backend_required) docker --version 종료 코드 == 0
FAIL → architect 에이전트 재실행 (최대 2회)
FAIL (docker 미설치) → 사용자에게 Docker Desktop 설치 안내 후 빌드 중단
```

### Gate 2→3: UX 디자인 완료 (필수, fallback 포함)

```
CONDITION: build-state.json.environment.stitch == true
  → Phase 2 실행됨 (primary 경로):
    CHECK:
      ✓ .autobot/design-spec.md 존재
      ✓ .autobot/designs/ 디렉토리에 .png 파일 1개 이상 존재
    FAIL → 1회 재시도
    FAIL (재시도 후) → fallback 모드로 전환:
      - phases["2"].status = "fallback"
      - ⚠️ 경고 출력: "Stitch 디자인 생성 실패. architecture.md 기반 fallback 모드로 진행합니다."
      - Phase 3로 진행

CONDITION: build-state.json.environment.stitch == false
  → Phase 2 fallback (status: "fallback")
  → ⚠️ 경고 출력: "Stitch MCP 미설치. fallback 모드로 진행합니다."
  → Phase 3로 진행
```

### Gate 3→4: Xcode 프로젝트 생성 완료

```
CHECK:
  ✓ *.xcodeproj 디렉토리 존재
  ✓ *.xcodeproj/project.pbxproj 존재 & 크기 > 0
  ✓ <AppName>/App/<AppName>App.swift 존재
  ✓ <AppName>/Assets.xcassets 존재
  ✓ <AppName>/PrivacyInfo.xcprivacy 존재
  ✓ <AppName>/<AppName>.entitlements 존재
  ✓ .gitignore 존재
  ✓ (backend_required) Debug.xcconfig 존재 & API_BASE_URL 포함
  ✓ (backend_required) Release.xcconfig 존재 & API_BASE_URL 포함
  ✓ (backend_required) .gitignore에 backend/.env 포함
FAIL → scaffold 재실행
```

### Gate 4→5: 병렬 코드 생성 완료

```
CHECK:
  ✓ <AppName>/Views/ 디렉토리에 .swift 파일 1개 이상
  ✓ <AppName>/ViewModels/ 디렉토리에 .swift 파일 1개 이상
  ✓ <AppName>/Services/ 디렉토리에 .swift 파일 1개 이상
  ✓ <AppName>/App/<AppName>App.swift에 '.modelContainer' 문자열 포함
  ✓ <AppName>/Models/*.swift 파일이 Phase 1과 동일 (수정되지 않음 — checksum 비교)
  ✓ 에이전트 간 파일 소유권 위반 없음 (각자 지정 디렉토리에만 쓰기)
FAIL:
  - <AppName>/Models/ 변경됨 → git checkout으로 <AppName>/Models/ 복원 후 Phase 4 재실행
  - 파일 누락 → 해당 에이전트만 재실행
  ✓ (backend_required) backend/ 디렉토리 존재
  ✓ (backend_required) backend/Dockerfile 존재
  ✓ (backend_required) backend/docker-compose.yml 존재
  ✓ (backend_required) backend/app/main.py 존재
FAIL:
  - backend/ 누락 → backend-engineer만 재실행
```

### Gate 5→6: 빌드 성공

```
CHECK:
  ✓ xcodebuild build 종료 코드 == 0
  ✓ "BUILD SUCCEEDED" 문자열 출력에 포함
  ✓ <AppName>/App/ServiceStubs.swift 삭제됨 (실제 Repository로 교체 완료)
  ✓ <AppName>/PrivacyInfo.xcprivacy에 architecture.md의 모든 API 카테고리 반영
  ✓ (backend_required) docker compose build 종료 코드 == 0
  ✓ (backend_required) docker compose up -d --wait 종료 코드 == 0
  ✓ (backend_required) curl -f http://localhost:8080/health 종료 코드 == 0
  ✓ (backend_required) docker compose down 완료
FAIL → quality-engineer 에이전트 재실행 (최대 2회, 이전 에러 전달)
FAIL (Docker) → quality-engineer 에이전트 재실행 (Docker 에러 메시지 포함)
```

### Gate 6→7: 배포 완료 (soft gate — 실패해도 진행)

```
CHECK:
  ✓ .autobot/deploy-status.json 존재
  ✓ deploy-status.json에 archive_path 또는 upload_success 존재
SOFT FAIL → Phase 7 진행 (배포 실패도 학습 대상)
```

## Gate 실행 방법

각 Gate는 build.md의 Phase 완료 직후, 상태 저장 직전에 실행한다.

```
Phase N 완료
  ↓
Gate N→N+1 검증
  ↓ PASS
build-state.json에 "completed" 기록
  ↓
Phase N+1 시작
```

```
Phase N 완료
  ↓
Gate N→N+1 검증
  ↓ FAIL
재시도 가능? (retryCount < maxRetry)
  ├─ Yes → Phase N 재실행
  └─ No  → build-state.json에 "failed" 기록, Phase 7으로 건너뜀
```

## Gate에서 사용하는 검증 명령

```bash
# 파일 존재 확인
test -f "<path>"

# 디렉토리에 .swift 파일 존재 확인
ls <AppName>/<dir>/*.swift &>/dev/null

# 파일에 특정 문자열 포함 확인
grep -q "<pattern>" "<file>"

# <AppName>/Models/ 무결성 (Phase 1 완료 시 체크섬 저장)
find <AppName>/Models/ -name "*.swift" -exec md5 {} \; | sort | md5

# xcodebuild 결과 확인
xcodebuild build ... 2>&1 | tail -1 | grep -q "BUILD SUCCEEDED"

# Docker 설치 확인 (Gate 1→2)
docker --version &>/dev/null

# xcconfig 확인 (Gate 3→4)
grep -q "API_BASE_URL" Debug.xcconfig

# Docker 빌드 + 기동 확인 (Gate 5→6)
cd backend && docker compose build && docker compose up -d --wait
curl -f http://localhost:8080/health
docker compose down && cd ..
```

## <AppName>/Models/ 무결성 보호

Phase 1 완료 시 `<AppName>/Models/` 디렉토리의 체크섬을 `build-state.json`에 저장:

```json
{
  "phases": {
    "1": {
      "status": "completed",
      "modelsChecksum": "a1b2c3d4e5f6..."
    }
  }
}
```

Phase 4 완료 후 Gate 4→5에서 체크섬을 재계산하여 비교. 불일치 시 `git checkout -- <AppName>/Models/`로 복원.
