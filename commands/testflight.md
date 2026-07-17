---
name: testflight
description: "현재 프로젝트 상태를 ASC 에 자동 등록(멱등) → archive → upload → TestFlight 내부 테스터 초대까지 일괄 수행합니다."
argument-hint: "(인자 없음 — 현재 디렉토리의 빌드 상태를 사용)"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - Skill
---

# Autobot TestFlight — 현재 버전을 TestFlight 에 업로드

출하 전에 공통 준비도 진단을 실행한다.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" doctor --profile ship --format json
```

`/autobot:mvp` 로 만든 MVP 를 사용자가 확인한 뒤, TestFlight 에 올릴 준비가 됐을 때 호출하는 명령. **register → archive → upload → invite-testers** 를 deployer 에이전트가 순차 실행한다. register 는 멱등이므로 첫 실행이면 자동 등록, 재실행이면 즉시 통과한다.

**`/autobot:mvp` 와 분리된 이유:**
- `/autobot:mvp` 는 로컬 빌드까지만 (시뮬레이터/디바이스에서 검증 가능).
- 사용자가 MVP 확인 후 의도적으로 TestFlight 트리거.
- name_collision / bundle_id_taken 같은 ASC 충돌은 빌드와 무관하게 등록 단계에서 잡힘 (`autobot-register-app`).

## CRITICAL RULES

1. **앱 등록은 자동(멱등)** — deployer 가 Step 1 에서 `autobot-register-app` 을 호출한다. 이미 등록된 앱이면 즉시 통과(`already_exists`), 미등록이면 archive 시작 전에 등록한다. name_collision/bundle_id_taken/asc_session_expired/asc_permission_denied 는 archive 시작 전에 사용자에게 보고하고 중단 — 긴 빌드를 낭비하지 않는다.
2. **`.autobot/build-state.json` 이 존재해야 한다** — 없으면 "이 디렉토리는 Autobot 프로젝트가 아닙니다. `/autobot:mvp`로 먼저 빌드하세요." 출력 후 중단.
3. **상태 전이 / Gate 실행은 `scripts/pipeline.sh` 만** — `spec/pipeline.json` 의 Phase 6 / Gate 6→7 머신을 그대로 사용.
4. **CWD 규칙**: 명령은 프로젝트 루트(`build-state.json` 이 있는 디렉토리)에서 실행한다고 가정. `cd` 로 이탈하지 않는다.

## Step 0: 사전 검증

```bash
# 0a. build-state.json 존재
if [ ! -f .autobot/build-state.json ]; then
  echo "ERROR: .autobot/build-state.json not found. Run /autobot:mvp first."
  exit 1
fi

# 0b. Phase 5 완료 여부 — 빌드가 끝나지 않은 상태로 TestFlight 가면 안 됨
PHASE_5_STATUS=$(python3 -c "
import json
s = json.load(open('.autobot/build-state.json'))
print(s.get('phases', {}).get('5', {}).get('status', ''))
")
if [ "$PHASE_5_STATUS" != "completed" ]; then
  echo "ERROR: Phase 5 (Integration & Build) not completed (status: $PHASE_5_STATUS)."
  echo "Run /autobot:mvp or /autobot:resume to finish the build first."
  exit 1
fi

# 0c. ASC 자격증명 — 전역(`~/.autobot/.env`, /autobot:setup 이 기록) → 프로젝트 .env 순으로 로드.
#     deployer 가 도는 register/upload/invite 스크립트도 같은 순서로 self-source 하므로,
#     이 사전 검사는 그들이 보게 될 값을 그대로 반영한다.
. "$CLAUDE_PLUGIN_ROOT/scripts/release_env.sh"
autobot_load_release_env .
if [ -z "${ASC_API_KEY_ID:-}" ] || [ -z "${ASC_API_ISSUER_ID:-}" ] || [ -z "${ASC_API_KEY_PATH:-}" ]; then
  echo "ERROR: ASC API credentials not found."
  echo "Required: ASC_API_KEY_ID, ASC_API_ISSUER_ID, ASC_API_KEY_PATH"
  echo "Set them once for all projects: /autobot:setup  (writes ~/.autobot/.env)"
  echo "Or per-project: create ./.env. See skills/autobot-upload-build/references/signing-guide.md"
  exit 1
fi

# 0d. app-name 추출
APP_NAME=$(python3 -c "
import json
s = json.load(open('.autobot/build-state.json'))
print(s.get('appName', ''))
")
DISPLAY_NAME=$(python3 -c "
import json
s = json.load(open('.autobot/build-state.json'))
print(s.get('displayName', ''))
")
echo "INFO: deploying $APP_NAME ($DISPLAY_NAME)"
```

## Step 1: Phase 6 시작

이미 Phase 6 가 completed/failed 면 사용자에게 재실행 의사 확인 (또는 `--force` 플래그가 있으면 통과). 그 외에는 `start-phase --phase 6` 으로 진입.

```bash
PHASE_6_STATUS=$(python3 -c "
import json
s = json.load(open('.autobot/build-state.json'))
print(s.get('phases', {}).get('6', {}).get('status', 'pending'))
")

case "$PHASE_6_STATUS" in
  pending|in_progress|failed)
    bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 6 \
      --detail "TestFlight Deploy (explicit /autobot:testflight)" \
      --allow-terminal-restart
    ;;
  completed)
    echo "INFO: Phase 6 already completed. Re-deploying current build state."
    bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 6 \
      --detail "TestFlight redeploy" \
      --allow-terminal-restart
    ;;
esac
```

## Step 1.5: 기능 검증 사전 차단 (anti-laundering)

Gate 5→6 은 archive가 실제 출하 산출물을 만들기 직전에 `archive.sh`가 `pipeline.sh preflight-ship`으로 한 번 신선하게 검증한다. 이 command에서 같은 gate를 미리 실행하지 않는다. 그래야 고비용 기능 테스트를 중복 실행하지 않으면서, 직접 skill 호출이나 Phase 6 resume도 archive 경계에서 동일하게 차단된다.

## Step 2: deployer 에이전트 디스패치

Agent 도구로 deployer 에이전트를 호출한다. deployer 는 다음을 수행한다:
1. **register** (`autobot-register-app`) — 멱등. 이미 등록된 앱이면 즉시 통과
2. **archive** (`autobot-archive-build`) — xcodebuild archive
3. **upload** (`autobot-upload-build`) — export + ASC 업로드
4. **invite-testers** (`autobot-invite-testers`) — `config.json:testerEmails` 가 있을 때만

각 스킬은 자체 status JSON 을 `.autobot/<phase>-status.json` 에 남긴다 (atomic write).

**deployer 가 사용자에게 보고해야 하는 경우:**
- register 실패 (`name_collision`) → display name 변경 안내. archive 시작 안 함.
- register 실패 (`bundle_id_taken`) → bundle ID 변경 안내. archive 시작 안 함.
- register 실패 (`asc_session_expired` 또는 exit 2) → `fastlane spaceauth -u <apple-id>` 세션 갱신 안내 (2FA 1회, ~30일 유효). archive 시작 안 함.
- register 실패 (`asc_permission_denied`) → Apple ID 의 ASC role 승격 안내. archive 시작 안 함.
- upload 가 export 성공 + ASC 5xx 로 실패 (`exit 5`) → IPA 경로 + Transporter/Organizer 안내
- archive 가 signing 실패 → Xcode → Settings → Accounts 안내

## Step 3: Phase 6 결과 기록

deployer 가 끝나면 결과에 따라 `advance-phase` 또는 `fail-phase` 호출:

```bash
# 성공 시 (Gate 6→7 검증은 soft — deployment_attempt_recorded 만 본다):
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 6

# 실패 시:
# bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" fail-phase --phase 6 --error "<deploy error>" --increment-retry
```

## Step 4: 사용자 보고

성공 시 출력 예시 (첫 빌드 — 신규 등록):
```
✅ TestFlight 업로드 완료

Bundle ID:    com.axi.MyApp
Register:     created (App Store Connect 에 신규 등록)
Archive:      build/MyApp.xcarchive
IPA:          build/export/MyApp.ipa
Build status: uploaded (upload_success: true)
Verification: ✅ VERIFIED (gate 5->6 passed)   ← 업로드는 functional_verification_passed 통과 시에만 도달
Testers:      alice@x.com (invited), bob@x.com (already in group)

⏳ ASC processing: 5분~1시간 후 TestFlight 에서 빌드 확인 가능
   https://appstoreconnect.apple.com → My Apps → TestFlight
```

성공 시 출력 예시 (반복 빌드 — 이미 등록됨):
```
✅ TestFlight 업로드 완료

Bundle ID:    com.axi.MyApp
Register:     already_exists (skipped)
Archive:      build/MyApp.xcarchive
IPA:          build/export/MyApp.ipa
Build status: uploaded
Testers:      alice@x.com (already in group)
```

실패 시 출력 예시 (등록 단계 — name_collision):
```
❌ TestFlight 배포 실패 (등록 단계): display name 충돌

display name "내 앱" 은 다른 개발자가 이미 사용 중입니다.
archive/upload 는 시도하지 않았습니다.

해결: build-state.json 의 displayName 을 고유하게 변경 (회사명 prefix 추천)
재실행: /autobot:testflight
```

실패 시 출력 예시 (등록 단계 — bundle_id_taken):
```
❌ TestFlight 배포 실패 (등록 단계): bundle ID 선점

com.axi.MyApp 은 다른 Apple Developer team 이 선점했습니다.

해결: bundle ID 의 마지막 segment 변경 또는 /autobot:setup 으로 bundleIdPrefix 갱신
재실행: 새 bundle ID 로 /autobot:mvp 재빌드 → /autobot:testflight
```

## Error Handling

- **Phase 5 미완료**: Step 0b 에서 차단. 사용자에게 `/autobot:resume` 안내.
- **ASC 자격증명 누락**: Step 0c 에서 차단. `/autobot:setup` (전역 `~/.autobot/.env`) 또는 프로젝트 `.env` 설정 안내. deployer 스크립트가 전역→프로젝트 순으로 self-source 하므로 한 번만 setup 하면 모든 프로젝트가 읽는다.
- **앱 미등록**: deployer 의 Step 1 (register) 이 자동 등록 시도. 충돌 시 archive 시작 전 즉시 중단 + 사용자 안내.
- **archive 실패**: signing/provisioning 진단. `xcodebuild` 로그 첨부.
- **upload 5xx**: archive 보존됨. 같은 archive 로 재호출하면 immediate retry (export 안 다시 함).
- **invite 부분 실패**: `emails_failed` 보고 + 부분 성공으로 마무리. 사용자가 ASC 웹에서 수동 추가 가능.

## Output

deployer 가 작성하는 status 파일들:
- `.autobot/register-status.json` — `result: registered`/`already_exists`/실패 reason
- `.autobot/archive-status.json` — `result: archived`, `archive_path`
- `.autobot/upload-status.json` — `result: uploaded`/`already_uploaded`/`upload_failed`/`export_failed`, `ipa_path`, `upload_success`
- `.autobot/invite-status.json` — `result: invited`/`partial`, `emails_invited`/`skipped`/`failed`
- `.autobot/deploy-status.json` — 위 4개의 집계 (`status: uploaded`/`archived`/`failed`)

이후 `/autobot:resume` 로 회고 보고서(`build-report.md`) 를 재생성하면 새 deploy 결과가 반영된다.

Do NOT ask any questions during deploy. Handle all decisions autonomously. Only stop on hard failures (Step 0 preconditions) and report them clearly.
