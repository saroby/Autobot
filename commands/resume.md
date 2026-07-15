---
name: resume
description: "중단된 Autobot 빌드를 이어서 실행합니다. Phase 번호를 지정하면 해당 Phase부터, 생략하면 마지막 실패/중단 지점부터 재개합니다."
argument-hint: "[phase번호] [--force] [--regenerate-contracts] [--allow-visual-drift] (예: /autobot:resume 5, /autobot:resume 1 --regenerate-contracts, /autobot:resume 5 --allow-visual-drift)"
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
---

# Autobot Resume — 중단된 빌드 재개

중단되거나 실패한 빌드를 `.autobot/build-state.json` 상태 파일을 읽어 이어서 실행한다.
Phase 정의와 상태 의미는 `spec/pipeline.json`이 SSOT이며, 이 문서는 재개 절차만 요약한다.

## CRITICAL RULES

1. **`.autobot/build-state.json`이 없으면 즉시 중단** — "이전 빌드 상태를 찾을 수 없습니다. `/autobot:mvp`로 새 빌드를 시작하세요." 출력
2. **상태 파일의 `projectPath`를 신뢰한다** — 해당 경로에 프로젝트가 실제 존재하는지 검증
3. **재개 시에도 각 Phase 완료마다 상태를 저장한다** — build 커맨드와 동일한 상태 저장 로직 사용
4. **이미 completed인 Phase는 건너뛴다** — 단, 사용자가 명시적으로 Phase 번호를 지정하면 `pipeline.sh start-phase --allow-terminal-restart` 규칙으로 해당 Phase부터 재실행

## Phase Learning Map

재개 시 사용할 phase learning 파일은 숫자 기반 추론이 아니라 아래 매핑을 따른다:

- Phase 1 → `.autobot/phase-learnings/architecture.md`
- Phase 4 → `.autobot/phase-learnings/parallel_coding.md`
- Phase 5 → `.autobot/phase-learnings/quality.md`
- Phase 6 → `.autobot/phase-learnings/deploy.md`

Phase 0, 2, 3, 7은 phase 전용 파일 대신 `.autobot/active-learnings.md`를 사용한다.

## Step 0: 빌드 잠금 확인

기존 build state의 `buildId`로 canonical JSON lock을 재획득한다. 잠금 파일을 직접 읽거나 덮어쓰지 않는다:

```bash
if [ ! -f .autobot/build-state.json ]; then
  echo "ERROR: .autobot/build-state.json not found. Run /autobot:mvp first."
  exit 1
fi
BUILD_ID=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('buildId',''))")
if [ -z "$BUILD_ID" ]; then
  echo "ERROR: build-state.json has no buildId."
  exit 1
fi
LOCK_STATUS=$(bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" build-lock status)
LOCK_TOKEN=$(printf '%s' "$LOCK_STATUS" | python3 -c "import json,sys; s=json.load(sys.stdin); print(s.get('lockToken','') if s.get('buildId') == '$BUILD_ID' and s.get('holderAlive') else '')")
# 아래 takeover 분기는 사용자가 /autobot:resume에 --force를 명시한 경우에만 실행한다.
# 보통 재개는 살아 있는 same-build lease를 차단해 활성 세션과 겹치지 않는다.
if [ -n "$LOCK_TOKEN" ] && [[ " ${ARGUMENTS:-} " == *" --force "* ]]; then
  ACQUIRE_RESULT=$(bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" build-lock acquire \
    --build-id "$BUILD_ID" --takeover-same-build --expected-token "$LOCK_TOKEN" \
    --format json) || exit $?
else
  ACQUIRE_RESULT=$(bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" build-lock acquire \
    --build-id "$BUILD_ID" --format json) || exit $?
fi
OWNED_LOCK_TOKEN=$(printf '%s' "$ACQUIRE_RESULT" | \
  python3 -c "import json,sys; print(json.load(sys.stdin).get('lockToken',''))")
if [ -z "$OWNED_LOCK_TOKEN" ]; then
  echo "ERROR: acquired build lock generation could not be confirmed."
  exit 1
fi
```

## Step 0.5: override 플래그 처리 (`--allow-visual-drift`)

사용자가 `--allow-visual-drift` 와 함께 호출했으면, **Phase 5 를 재실행하기 전에** override 플래그를 **현재 빌드 id 로** 세팅한다(boolean `true` 가 아니다 — 아래 *왜 buildId-scoped 인가* 참조). 이 플래그는 Gate 5→6 의 `visual_judge` 체크가 읽어, 빌드된 앱이 디자인 의도와 어긋난다는 vision judge 판정(verdict=fail)을 **DEGRADED 대신 통과(green)**로 강등한다 — 운영자가 그 드리프트를 의도적으로 수용하고 출하하겠다는 선언이다.

```bash
# (resume 호출 인자를 직접 확인해 아래를 채운다 — 환경변수가 아니라 사용자 입력 기준.)
# 사용자가 --allow-visual-drift 를 줬으면 다음을 실행한다 (안 줬으면 건너뛴다):
BUILD_ID=$(python3 -c "import json,sys; print(json.load(open('.autobot/build-state.json')).get('buildId',''))")
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" set-flag \
  --key allowVisualDrift --value "$BUILD_ID" \
  --reason "operator accepted visual drift for build $BUILD_ID via /autobot:resume --allow-visual-drift"
```

> **왜 buildId-scoped 인가** (release-scoped exception): `/autobot:testflight` 의 anti-laundering 단계가 업로드 직전 Gate 5→6 을 **플래그 없이 신선 재실행**한다. override 가 build-state 에 남아 있어야 그 재실행이 존중되는데, 영속 boolean `true` 는 *이후의 모든 빌드까지* 조용히 면제해 세탁 위험이 된다. 그래서 override 를 **현재 빌드 id 에 바인딩**한다: `visual_judge` 는 `allowVisualDrift == buildId` 일 때만 면제하므로 — **같은 빌드의 testflight 재검증은 그대로 통과**(업로드 진행), **새 빌드(새 buildId)는 자동으로 면제가 만료**(다시 의도적으로 `--allow-visual-drift` 를 줘야 함). 세팅은 `flag_changed` 이벤트로 감사된다.
>
> 드리프트 수용을 **즉시 취소**하려면 `set-flag --key allowVisualDrift --value false` 로 되돌린다(어떤 buildId 와도 매칭되지 않아 면제가 사라진다).

## Step 1: 빌드 상태 로드

```
Read .autobot/build-state.json
```

**스키마 검증:**
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" schema
```

상태 파일이 없으면:
```
"이전 빌드 상태를 찾을 수 없습니다. `/autobot:mvp <앱 아이디어>`로 새 빌드를 시작하세요."
→ 종료
```

## Step 2: 재개 지점 결정

### 사용자가 Phase 번호를 지정한 경우

`/autobot:resume 5` → Phase 5부터 강제 재시작.
지정된 Phase 이전의 Phase들이 완료되어 있는지 검증:

| 재개 Phase | 필수 선행 조건 |
|-----------|--------------|
| 0 | 없음 (처음부터) |
| 1 | Phase 0 completed |
| 2 | Phase 1 completed + `.autobot/architecture.md` 존재 + `<AppName>/Models/*.swift` 존재 |
| 2.5 | Phase 2 completed 또는 fallback — `/autobot:plan` 만 트리거하는 manual phase. 자동 resume 흐름은 Phase 2.5 를 skip 하고 Phase 3 로 진입한다. 사용자가 `/autobot:resume 2.5` 를 명시 호출하면 그때만 진입. |
| 3 | Phase 2 completed 또는 fallback (Phase 2.5 는 pending 이어도 무방 — manual) |
| 4 | Phase 3 completed + `.xcodeproj` 존재 |
| 5 | Phase 4 completed + `<AppName>/Views/` 및 `<AppName>/Services/` 디렉토리에 .swift 파일 존재 |
| 6 | Phase 5 completed + 마지막 빌드 성공 — 단, **Phase 6는 manual phase 이므로 자동 resume 대상이 아니다**. resume 이 자동 진행할 때 Phase 5 다음은 Phase 7. 사용자가 명시적으로 `/autobot:resume 6` 또는 `/autobot:testflight` 를 호출했을 때만 진입. |
| 7 | Phase 5 completed (Phase 6 는 manual 이므로 pending 이어도 무방). 또는 Phase 6 completed/failed |

선행 조건이 충족되지 않으면:
```
"Phase {N}을 시작하려면 Phase {N-1}이 완료되어야 합니다.
현재 상태: Phase {X} — {status}
`/autobot:resume {올바른_Phase}`로 다시 시도하세요."
→ 종료
```

### Circuit breaker가 트립된 빌드 재개

`build-state.json.phases`에 `skipReason`을 가진 phase가 다수 존재하고, retrospective(7)가 `in_progress`라면 circuit breaker가 트립한 상태다. 자동 동작:

- trip을 일으킨 phase는 `failed` 상태로 보존 (포렌식)
- 그 외 미완료 phase는 `skipped` + `skipReason: "circuit breaker tripped on phase N"`
- retrospective는 `in_progress` (즉시 회고 진입 가능)

이 상태에서 `/autobot:resume`은 **retrospective만 실행**한다. trip 원인을 분석한 뒤, 사용자가 의도적으로 다시 시도하려면:
- `rm -rf .autobot/build-state.json` 후 `/autobot:mvp` (전체 초기화), 또는
- `/autobot:resume <N>`로 특정 phase부터 강제 재시작 (`--allow-terminal-restart` 의미). 단, `skipped` phase에서 시작하려면 dependency 충족 여부를 운영자가 책임진다.

### 사용자가 Phase 번호를 생략한 경우

`build-state.json`의 `phases` 배열을 순회하여 재개 지점을 자동 결정:

```
1. status가 "failed"인 Phase 찾기 → 해당 Phase부터 재시작
2. "failed"가 없으면, "in_progress"인 Phase 찾기 → 해당 Phase부터 재시작
   (크래시 잔류 상태 — Step 4 의 start-phase 에 `--allow-terminal-restart` 를 붙여 reclaim)
3. 둘 다 없으면, 마지막 "completed" Phase 다음부터 시작
4. 모든 Phase가 completed이면 → "빌드가 이미 완료되었습니다." 출력 후 종료
```

### Idempotent skip — input_hash 기반

재개 지점이 결정되면 그 phase 부터 다음 미완료 phase 까지 순회하면서, 각 phase 의 input 이 마지막 성공 시점과 동일하면 **재실행 없이 skip** 한다. 사용자 아이디어 / spec 슬라이스 / owned 파일 체크섬 / upstream 파일 체크섬 중 하나라도 바뀌었으면 그 phase 부터 재실행.

```bash
# 사용자가 resume 를 --force 또는 --regenerate-contracts 와 함께 호출했으면 skip 을 비활성화한다.
# (resume 호출 인자를 직접 확인해 아래 SKIP_FORCE 를 채운다 — 환경변수가 아니라 사용자 입력 기준.)
# --regenerate-contracts 는 새 계약을 의도하므로 전체 재빌드가 필요 → force 와 동일 효과.
# 이게 없으면 입력 불변 시 Phase 1 이 skip 되어 freeze-contracts 가 호출조차 안 되고,
# --regenerate-contracts 가 조용한 no-op 이 된다.
SKIP_FORCE=""   # 사용자가 --force 또는 --regenerate-contracts 를 줬으면 "--force" 로 설정

# 후보 phase 가 정말 다시 돌릴 필요가 있는지 먼저 확인
for PHASE_ID in $(seq "$RESUME_FROM" 7); do
  RESULT=$(bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" input-hash should-skip --phase "$PHASE_ID" $SKIP_FORCE)
  if echo "$RESULT" | grep -q '"skip": true'; then
    echo "INFO: Phase $PHASE_ID skipped — $(echo $RESULT | python3 -c 'import json,sys;print(json.load(sys.stdin)[\"reason\"])')"
    continue
  fi
  # 입력이 변했거나 hash 미저장 → 정상적으로 phase 실행
  RESUME_FROM="$PHASE_ID"
  break
done
```

`--force` 옵션 (`/autobot:resume <N> --force` 또는 운영자 의도가 명확할 때) 은 skip 을 비활성화하고 무조건 재실행한다. `--regenerate-contracts` 도 동일하게 skip 을 끈다 — 끄지 않으면 입력 불변 시 Phase 1 이 skip 되어 계약 재생성 요청이 조용히 무시된다. phase 가 성공으로 마킹되는 시점에 `pipeline.sh advance-phase` 가 새 hash 를 다시 기록하므로, 다음 resume 부터 다시 cache 가 적중한다.

## Step 2.5: 오프파이프라인 드리프트 감지 (항상 실행, 파라미터 불필요)

`RESUME_FROM` **이전의** completed/fallback phase 들 (`0 .. RESUME_FROM-1`)은 이번 resume 에서 재실행되지 않는다. 하지만 그 phase 들의 owned 파일이 완료 마킹 이후 **파이프라인을 거치지 않고**(직접 Read/Edit, 수동 세션 등) 바뀌었다면 — 예를 들어 Phase 4 완료 후 Views 를 손으로 계속 고쳤다면 — 그 사실을 사용자가 모른 채 다음 resume 가 진행된다. 이건 안전(override skip)이 아니라 **가시성** 문제이므로 flag 없이 항상 점검한다:

```bash
DRIFTED=()
for PHASE_ID in $(seq 0 $((RESUME_FROM - 1))); do
  STATUS=$(python3 -c "
import json
d = json.load(open('.autobot/build-state.json'))
print(d.get('phases', {}).get('$PHASE_ID', {}).get('status', ''))
")
  if [ "$STATUS" != "completed" ] && [ "$STATUS" != "fallback" ]; then continue; fi
  RESULT=$(bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" input-hash should-skip --phase "$PHASE_ID")
  if echo "$RESULT" | grep -q "inputHash mismatch"; then
    DRIFTED+=("$PHASE_ID")
  fi
done
```

`should-skip` 은 이미 존재하는 idempotent-skip 계산을 그대로 재사용한다 — 새 스크립트나 새 체크섬 로직을 추가하지 않는다. `DRIFTED` 가 비어있지 않으면 **재개를 막지 않고** Step 3 보고에 다음 경고를 끼워 넣는다 (phase 별로 한 줄):

```
⚠️ Phase {N} 은 completed 로 마킹된 뒤 파이프라인 밖에서 파일이 수정된 것으로 보입니다 (input hash mismatch).
   Phase 2 라면: 검토했던 Stitch 목업/디자인과 지금 파일이 다를 수 있습니다 → `/autobot:resume 2.5 --force` 로 preview 를 새로 만들어 다시 확인하세요.
   Phase 4 라면: Views/Services 가 ui-builder 산출물과 달라졌습니다. 의도된 수동 수정이면 무시해도 되지만, 이후 `/autobot:resume 4 --force` 를 실행하면 그 수동 수정이 덮어써진다는 점을 알고 있어야 합니다.
   그 외 Phase: build-log.jsonl 에서 해당 phase 이후 이벤트가 끊겼는지 확인하세요 — 끊겼다면 수동 편집 구간입니다.
```

이 단계는 **아무것도 재실행하거나 덮어쓰지 않는다** — `--force`/`--regenerate-contracts`/`--allow-visual-drift` 의 opt-in 안전장치는 그대로 유지된다. 목적은 "resume 만 쳐도 무슨 일이 있었는지 알 수 있게" 하는 것뿐이다.

## Step 3: 컨텍스트 복원

재개 전에 필수 컨텍스트를 로드:

```
1. Read .autobot/build-state.json → appName, displayName, bundleId, projectPath 추출
2. Read .autobot/architecture.md (Phase 3 이후 재개 시)
3. Read the mapped `.autobot/phase-learnings/*.md` file for the resume phase first (있으면)
4. Read .autobot/active-learnings.md (있으면, 없으면 learnings.json의 관련 섹션만 요약)
5. 프로젝트 디렉토리로 이동하여 현재 파일 상태 확인
```

해당 Phase에 매핑된 `.autobot/phase-learnings/*.md`가 있으면 그 파일의 규칙을 우선 적용하고, 이후 `.autobot/active-learnings.md`로 공통 규칙을 보강한다.

재개 시 사용자에게 현재 상태를 간결하게 보고:

```
## Autobot Resume
- **앱**: {displayName} ({appName})
- **프로젝트**: {projectPath}
- **이전 중단**: Phase {N} — {phaseName} ({status})
- **재개 지점**: Phase {resumeFrom} — {phaseName}
{실패 사유가 있으면: "- **실패 사유**: {error}"}
{DRIFTED 가 비어있지 않으면 Step 2.5 의 경고 블록을 phase 별로 여기에 나열}

Phase {resumeFrom}부터 실행합니다.
```

## Step 4: Phase 실행

**Phase 재시작 기록 (검증 + 상태 저장 + 로그를 한 번에 수행):**
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase <N> --detail "Resume from Phase <N>"
# --allow-terminal-restart 가 필요한 경우 (아래 셋 모두):
#   1. 사용자가 completed/fallback/skipped 상태 Phase 를 명시적으로 재시작
#   2. 크래시로 in_progress 에 남은 Phase 를 reclaim (in_progress → in_progress)
#   3. retry 소진(failed, retryCount ≥ maxRetry) Phase 의 운영자 강제 재시작
# 주의: 이 플래그는 해당 start-phase 호출 1회에 한해 circuit breaker 와 retry-소진
# 검사도 함께 우회한다 (operator override). /autobot:resume 은 인간 호출 전용이라
# 의도된 동작 — 자동화 경로에서는 절대 붙이지 않는다.
# bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase <N> --detail "Resume from Phase <N>" --allow-terminal-restart
```

재개 지점부터 build 커맨드와 **동일한 Phase 로직**을 실행한다.

각 Phase의 상세 구현은 `/autobot:mvp` 커맨드를 참조한다. 여기서는 재개 시 주의사항만 기술:

### Phase 0 재개

- 환경 준비를 다시 수행 (플러그인 감지, 학습 데이터 로드)
- 앱 이름은 `build-state.json`에서 가져온다 (재생성하지 않음)

### Phase 1 재개 — 계약 동결 (frozen-by-default)

Phase 1 은 타입 계약(`<App>/Models/*.swift` + `Models/ServiceProtocols.swift`)을 만들고, 이후 Phase 4 코드(Views/ViewModels/App/Services/Utilities)가 그 심볼명에 의존한다. architect 출력은 **비결정적**이라, 이미 downstream 코드가 작성된 상태에서 architect 를 다시 돌리면 필드명이 미묘하게 바뀌어 **조용한 컴파일 깨짐**이 나고 snapshot 까지 덮어써 되돌릴 수 없다. 그래서 resume 는 **기본적으로 계약을 동결**한다.

architect 를 다시 실행하기 **전에** 먼저 동결 여부를 결정한다:

```bash
# 사용자가 resume 를 --regenerate-contracts 와 함께 호출했으면 REGEN="--regenerate", 아니면 빈 값.
# (호출 인자를 직접 확인해 채운다 — 위 skip 루프의 SKIP_FORCE 와 같은 판단.)
REGEN=""   # 사용자가 --regenerate-contracts 를 줬으면 "--regenerate" 로 설정

FREEZE=$(bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" freeze-contracts apply --phase 1 $REGEN)
echo "$FREEZE"
```

결과의 `action` 에 따라 분기:

- **`"frozen": true`** (snapshot 존재 + downstream 코드 존재 + `--regenerate-contracts` 없음): `Models/` 가 snapshot 에서 복원됐고 architect 는 **재실행하지 않는다**. 이미 작성된 Views/Services 가 의존하는 계약이 그대로 유지된다(`contracts_frozen` 이벤트 기록). architect dispatch 를 건너뛴다. 이때 Phase 1 은 Step 4 의 `start-phase --phase 1 ... --allow-terminal-restart`(completed→in_progress) 를 이미 거친 상태여야 하며, 그 위에서 `advance-phase 1` 로 gate 1→2 를 재검증한다 (`completed` 에서 `advance-phase` 를 직접 호출하면 transition 이 거부된다). 통과 후 Phase 2 로 진행.
  - 사용자 보고: *"기존 타입 계약을 유지했습니다(downstream 보호). 아이디어를 바꿔 계약을 새로 설계하려면 `/autobot:resume 1 --regenerate-contracts` 로 재실행하세요 — 이 경우 Phase 4 가 새 계약에 맞춰 코드를 다시 생성합니다."*
- **`"action": "regenerate"`** (downstream 없음 · `--regenerate-contracts` 명시 · snapshot 없음 중 하나): architect 를 다시 실행한다. 기존 `.autobot/architecture.md`/`Models/` 를 덮어쓰고, 완료 후 `.autobot/contracts/phase-1-models/` snapshot 과 체크섬을 재저장한다.
- **`"action": "error"`** (동결해야 하는데 snapshot 복원 실패): **중단**하고 사용자에게 복원 실패를 알린다. architect 가 계약을 덮어쓰게 두지 않는다.

> input_hash skip 과 직교한다 — 입력이 안 바뀌었으면 input_hash 가 Phase 1 자체를 skip 하므로 architect 가 애초에 안 돈다. 동결은 `--force`/입력 변경/구 빌드(hash 미저장)처럼 **architect 가 재실행될 상황에서 downstream 을 보호**한다.

### Phase 2 재개

- `build-state.json.environment.stitch == true`일 때만 실행
- ux-designer 에이전트를 다시 실행
- 기존 `.autobot/designs/`와 `.autobot/design-spec.md`는 **덮어쓴다**
- Stitch 프로젝트 ID가 `build-state.json.stitch.projectId`에 있으면 기존 프로젝트 재사용 시도

### Phase 3 재개

- 기존 `.xcodeproj`를 재생성
- 디렉토리 구조는 유지 (기존 소스 파일 보존)

### Phase 4 재개

- ui-builder와 data-engineer를 다시 병렬 실행
- 기존 `<AppName>/Views/`, `<AppName>/ViewModels/`, `<AppName>/Services/`, `<AppName>/Utilities/` 파일은 **덮어쓴다**
- `<AppName>/Models/`는 건드리지 않는다 (Phase 1의 타입 계약)
- 무결성 불일치가 있으면 git이 아니라 `.autobot/contracts/phase-1-models/` snapshot으로 복원한다

### Phase 5 재개 (가장 흔한 재개 지점)

- 빌드 검증만 다시 실행
- quality-engineer 에이전트가 컴파일 에러 수정 + 테스트 작성
- **이전 실패 사유**를 에이전트 프롬프트에 포함하여 같은 실수 방지:
  ```
  이전 빌드에서 다음 에러로 실패했습니다:
  {build-state.json의 phases[5].error}
  이 문제를 우선적으로 해결하세요.
  ```
- **Phase 5가 2회 실패한 후 재개할 때**: Phase 4 스냅샷이 존재하면 복원하여 깨끗한 상태에서 재시도:
  ```bash
  bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" restore-phase --phase 4 --app-name "<AppName>"
  bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event snapshot_restore --detail "phase-4-snapshot restored on resume"
  ```

### Phase 6 재개

- Phase 6 는 **manual phase** — `/autobot:resume` 의 자동 진행 흐름에서는 건너뛴다. 사용자가 명시적으로 `/autobot:resume 6` 또는 (권장) `/autobot:testflight` 를 호출한 경우에만 진입한다.
- 진입 시 deployer 에이전트를 다시 실행. **이전 실패 사유**를 에이전트 프롬프트에 포함.
- archive 는 idempotent 하지 않다 — 새 빌드 변경이 있으면 다시 archive. 이전 archive 가 있고 코드 변경 없으면 그대로 재업로드 가능.
- 미등록 앱이면 deployer 가 upload 실패 + `autobot-register-app` 안내. 등록은 이 agent 가 자동으로 하지 않는다.

### Phase 7 재개

- 회고만 다시 실행
- 이전 빌드 과정의 에러/성공을 모두 포함하여 학습 데이터 갱신

## Step 5: 상태 저장

각 Phase 완료/실패 시 build 커맨드와 동일하게 `.autobot/build-state.json`을 갱신한다.
직접 JSON을 덮어쓰지 말고 runtime 엔진을 통해 기록한다.

`advance-phase`가 outgoing gate 실행 + 통과 시 `completed`/`fallback` 마킹 + 실패 시 `failed` 마킹을 한 번에 처리한다:

```bash
# 성공 (Gate 자동 검증)
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase <N>

# fallback (예: Phase 2 Stitch unavailable)
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase <N> \
  --status fallback --detail "<reason>"

# Phase 5는 빌드 성공 + peer review metadata가 필수
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 5 \
  --metadata build_succeeded=true \
  --metadata 'peerReview={"host":"codex","peer":"claude","verdict":"skipped","skipReason":"peer_cli_unavailable"}'

# 명시적 실패 (gate 도달 전 단계에서 에이전트가 실패한 경우)
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" fail-phase --phase <N> \
  --error "<error>" --increment-retry
```

> Phase 완료는 `advance-phase`만 사용한다. Gate 없는 완료 명령은 공개 CLI에서 제거됐다.

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

**빌드 잠금 해제:**
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" build-lock release \
  --build-id "$BUILD_ID" --expected-token "$OWNED_LOCK_TOKEN"
```

모든 Phase 완료 시 build 커맨드와 동일한 완료 보고를 출력한다.

부분 완료 시 (Phase 중간에 다시 실패):
```
## Autobot Resume 결과
- **재개**: Phase {resumeFrom} → Phase {lastCompleted}까지 완료
- **실패**: Phase {failedPhase} — {error}
- **다음**: `/autobot:resume` 또는 `/autobot:resume {failedPhase}`로 다시 시도

{실패 원인에 따른 조치 안내}
```
