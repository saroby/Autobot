---
name: resume
description: "중단된 Autobot 빌드를 이어서 실행합니다. Phase 번호를 지정하면 해당 Phase부터, 생략하면 마지막 실패/중단 지점부터 재개합니다."
argument-hint: "[phase번호] (예: /autobot:resume 4)"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - Skill
  - TaskCreate
  - TaskUpdate
  - TaskList
  - WebSearch
  - WebFetch
  - mcp__github__create_repository
  - mcp__github__push_files
---

# Autobot Resume — 중단된 빌드 재개

중단되거나 실패한 빌드를 `.autobot/build-state.json` 상태 파일을 읽어 이어서 실행한다.

## CRITICAL RULES

1. **`.autobot/build-state.json`이 없으면 즉시 중단** — "이전 빌드 상태를 찾을 수 없습니다. `/autobot:build`로 새 빌드를 시작하세요." 출력
2. **상태 파일의 `projectPath`를 신뢰한다** — 해당 경로에 프로젝트가 실제 존재하는지 검증
3. **재개 시에도 각 Phase 완료마다 상태를 저장한다** — build 커맨드와 동일한 상태 저장 로직 사용
4. **이미 completed인 Phase는 건너뛴다** — 단, 사용자가 명시적으로 Phase 번호를 지정하면 해당 Phase부터 재실행

## Step 1: 빌드 상태 로드

```
Read .autobot/build-state.json
```

상태 파일이 없으면:
```
"이전 빌드 상태를 찾을 수 없습니다. `/autobot:build <앱 아이디어>`로 새 빌드를 시작하세요."
→ 종료
```

## Step 2: 재개 지점 결정

### 사용자가 Phase 번호를 지정한 경우

`/autobot:resume 4` → Phase 4부터 강제 재시작.
지정된 Phase 이전의 Phase들이 완료되어 있는지 검증:

| 재개 Phase | 필수 선행 조건 |
|-----------|--------------|
| 0 | 없음 (처음부터) |
| 1 | Phase 0 completed |
| 1.5 | Phase 1 completed + `.autobot/architecture.md` 존재 + `<AppName>/Models/*.swift` 존재 |
| 2 | Phase 1 completed (Phase 1.5는 조건부 — completed 또는 skipped) |
| 3 | Phase 2 completed + `.xcodeproj` 존재 |
| 4 | Phase 3 completed + `<AppName>/Views/` 및 `<AppName>/Services/` 디렉토리에 .swift 파일 존재 |
| 5 | Phase 4 completed + 마지막 빌드 성공 |
| 6 | Phase 5 completed 또는 failed (회고는 항상 가능) |

선행 조건이 충족되지 않으면:
```
"Phase {N}을 시작하려면 Phase {N-1}이 완료되어야 합니다.
현재 상태: Phase {X} — {status}
`/autobot:resume {올바른_Phase}`로 다시 시도하세요."
→ 종료
```

### 사용자가 Phase 번호를 생략한 경우

`build-state.json`의 `phases` 배열을 순회하여 재개 지점을 자동 결정:

```
1. status가 "failed"인 Phase 찾기 → 해당 Phase부터 재시작
2. "failed"가 없으면, "in_progress"인 Phase 찾기 → 해당 Phase부터 재시작
3. 둘 다 없으면, 마지막 "completed" Phase 다음부터 시작
4. 모든 Phase가 completed이면 → "빌드가 이미 완료되었습니다." 출력 후 종료
```

## Step 3: 컨텍스트 복원

재개 전에 필수 컨텍스트를 로드:

```
1. Read .autobot/build-state.json → appName, displayName, bundleId, projectPath 추출
2. Read .autobot/architecture.md (Phase 2 이후 재개 시)
3. Read .autobot/learnings.json (있으면)
4. 프로젝트 디렉토리로 이동하여 현재 파일 상태 확인
```

재개 시 사용자에게 현재 상태를 간결하게 보고:

```
## Autobot Resume
- **앱**: {displayName} ({appName})
- **프로젝트**: {projectPath}
- **이전 중단**: Phase {N} — {phaseName} ({status})
- **재개 지점**: Phase {resumeFrom} — {phaseName}
{실패 사유가 있으면: "- **실패 사유**: {error}"}

Phase {resumeFrom}부터 실행합니다.
```

## Step 4: Phase 실행

재개 지점부터 build 커맨드와 **동일한 Phase 로직**을 실행한다.

각 Phase의 상세 구현은 `/autobot:build` 커맨드를 참조한다. 여기서는 재개 시 주의사항만 기술:

### Phase 0 재개

- 환경 준비를 다시 수행 (플러그인 감지, 학습 데이터 로드)
- 앱 이름은 `build-state.json`에서 가져온다 (재생성하지 않음)

### Phase 1 재개

- architect 에이전트를 다시 실행
- 기존 `.autobot/architecture.md`와 `Models/` 파일은 **덮어쓴다** (architect가 처음부터 다시 설계)

### Phase 1.5 재개

- `build-state.json.environment.stitch == true`일 때만 실행
- ux-designer 에이전트를 다시 실행
- 기존 `.autobot/designs/`와 `.autobot/design-spec.md`는 **덮어쓴다**
- Stitch 프로젝트 ID가 `build-state.json.stitch.projectId`에 있으면 기존 프로젝트 재사용 시도

### Phase 2 재개

- 기존 `.xcodeproj`가 있으면 삭제 후 재생성
- 디렉토리 구조는 유지 (기존 소스 파일 보존)

### Phase 3 재개

- ui-builder와 data-engineer를 다시 병렬 실행
- 기존 `<AppName>/Views/`, `<AppName>/ViewModels/`, `<AppName>/Services/`, `<AppName>/Utilities/` 파일은 **덮어쓴다**
- `<AppName>/Models/`는 건드리지 않는다 (Phase 1의 타입 계약)

### Phase 4 재개 (가장 흔한 재개 지점)

- 빌드 검증만 다시 실행
- quality-engineer 에이전트가 컴파일 에러 수정 + 테스트 작성
- **이전 실패 사유**를 에이전트 프롬프트에 포함하여 같은 실수 방지:
  ```
  이전 빌드에서 다음 에러로 실패했습니다:
  {build-state.json의 phases[4].error}
  이 문제를 우선적으로 해결하세요.
  ```

### Phase 5 재개

- deployer 에이전트를 다시 실행
- **이전 실패 사유**를 에이전트 프롬프트에 포함
- 앱 등록(fastlane produce)은 멱등하므로 안전하게 재실행

### Phase 6 재개

- 회고만 다시 실행
- 이전 빌드 과정의 에러/성공을 모두 포함하여 학습 데이터 갱신

## Step 5: 상태 저장

각 Phase 완료/실패 시 build 커맨드와 동일하게 `.autobot/build-state.json`을 갱신한다.

### Phase 완료 시

```json
{
  "phase": N,
  "status": "completed",
  "completedAt": "2026-03-16T15:30:00Z"
}
```

### Phase 실패 시

```json
{
  "phase": N,
  "status": "failed",
  "error": "구체적인 에러 메시지",
  "failedAt": "2026-03-16T15:30:00Z",
  "retryCount": 1
}
```

## 완료 보고

모든 Phase 완료 시 build 커맨드와 동일한 완료 보고를 출력한다.

부분 완료 시 (Phase 중간에 다시 실패):
```
## Autobot Resume 결과
- **재개**: Phase {resumeFrom} → Phase {lastCompleted}까지 완료
- **실패**: Phase {failedPhase} — {error}
- **다음**: `/autobot:resume` 또는 `/autobot:resume {failedPhase}`로 다시 시도

{실패 원인에 따른 조치 안내}
```
