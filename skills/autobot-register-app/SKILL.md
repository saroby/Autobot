---
name: autobot-register-app
user-invocable: false
description: Use when registering a new iOS app on App Store Connect (creating the App ID on Apple Developer Portal + app record on ASC) via `fastlane produce`. Auto-called by `/autobot:testflight` (deployer agent Step 1) as the first step before archive, AND can be invoked standalone for pre-flight bundle-ID/name validation. Bundle-ID re-runs are idempotent for the same team; app-name collisions surface as explicit failures so the caller can rename instead of silently continuing. AUTH IS DIFFERENT from every other deploy step — app creation goes through Apple's private API, so it needs an Apple ID web session (`fastlane spaceauth`, ~30-day TTL), NOT the ASC API key. Also use when troubleshooting "The bundle identifier is not available", "App Name you entered is already being used", "Unauthorized Access" / session expiry (`asc_session_expired`), or when an app needs to exist on ASC before the first TestFlight upload.
---

# iOS App Registration (App Store Connect)

새로 만든 iOS 앱을 App Store Connect 에 등록한다. `fastlane produce create` 가 Apple Developer Portal 에 App ID 를, ASC 에 앱 레코드를 동시에 생성한다.

**호출 경로 (2가지):**

1. **자동 (`/autobot:testflight` 안에서)** — deployer agent 의 Step 1 으로 archive 직전에 호출된다. 멱등이라 매번 안전. 충돌 시 archive 시작 전에 사용자에게 보고하고 중단.
2. **단독 (standalone)** — 사용자가 `/autobot:mvp` 시작 전이나, ASC 충돌 사전 검증, troubleshooting 용도로 직접 호출. `--dry-run` 으로 입력만 검증 가능.

**`/autobot:mvp` 는 이 스킬을 부르지 않는다** — make 는 로컬 빌드까지만이고, ASC 와 무관.

**Single Responsibility:** ASC 등록 하나만 한다. archive/upload/테스터 초대는 각각 `autobot-archive-build`, `autobot-upload-build`, `autobot-invite-testers` 가 담당한다.

## When to use

- **자동 호출**: `/autobot:testflight` 의 Step 1 — 사용자가 별도 명령으로 부를 필요 없음 (멱등이므로 매번 부름)
- **단독 호출 시나리오**:
  - `/autobot:mvp` 시작 전에 bundle ID/name 충돌 여부 사전 검증 (`--dry-run`)
  - `/autobot:testflight` 가 등록 충돌로 중단됐을 때 재시도 (메시지 변경 후)
  - 동일 팀에서 이미 등록된 앱인지 확인 (멱등 — `already_exists` 응답)

## Prerequisites

### 1. Apple ID 웹 세션 (필수 — ASC API Key 로 대체 불가)

**앱 레코드 생성은 Apple 의 비공개(iris) API 를 통한다.** 공개 App Store Connect API 에는 앱 생성 endpoint 가 없어 ASC API Key 로는 이 단계를 인증할 수 없다 (`--api_key_path` 는 `produce` 에 존재한 적 없는 옵션이다 — fastlane 이 invalid option 으로 즉사한다). 유일한 비대화형 인증은 캐시된 spaceship 웹 세션:

```bash
fastlane spaceauth -u <apple-id>   # 대화형 2FA 1회 — 세션은 ~30일 유효
```

이것이 **파이프라인 전체에서 프로그래밍으로 제거 불가능한 인간 개입 지점**이다 (2FA 는 설계상 사람만 통과 가능). 세션이 살아있는 동안(~30일)은 완전 무인으로 동작한다. `FASTLANE_SESSION` 환경변수로 세션을 주입할 수도 있다 (CI 용).

Apple ID 해석 우선순위: `--apple-id` flag → `$FASTLANE_USER` → `$APPLE_ID` → `config.json:appleId`.

**Apple ID 의 ASC role 은 "App Manager" 이상**이어야 한다 (Developer role 은 앱 생성 불가 — 스크립트가 `asc_permission_denied` 로 분류).

> 업로드/메타데이터 단계(`autobot-upload-build`, `autobot-upload-metadata`)는 반대로 **ASC API Key 를 쓴다** — 그쪽은 공개 API 로 충분하기 때문. 두 인증 모델을 혼동하지 말 것.

### 2. fastlane

미설치 시 스크립트가 `brew install fastlane` 으로 자동 설치한다. Homebrew 가 없거나 설치가 실패하면 exit 3 으로 중단한다.

### 3. python3

JSON 출력(API Key JSON, status 파일)을 안전하게 직렬화하기 위해 `python3` 가 필요하다. 미설치 시 exit 1.

### 4. Apple Developer Team ID (권장)

다음 우선순위로 결정된다 (`autobot-setup` 의 규약과 동일):

1. `--team-id` flag
2. `$DEVELOPMENT_TEAM` 환경변수
3. `~/.autobot/config.json:developmentTeam` (`skills/autobot-setup/scripts/config.sh` 경유)

모두 비어있으면 fastlane 이 계정에 연결된 첫 팀을 사용한다 — 멀티-팀 계정이면 명시하는 편이 안전하다.

## Usage

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-register-app/scripts/register-app.sh" \
  --bundle-id "com.axi.appname" \
  --display-name "앱 이름"
```

`CLAUDE_PLUGIN_ROOT` 가 없는 환경에서도 동작한다 — 스크립트 자체 위치(`${BASH_SOURCE[0]}`)에서 plugin root 를 추론한다.

선택 인자:

| Flag | 기본값 | 설명 |
|------|--------|------|
| `--apple-id` | `$FASTLANE_USER` → `$APPLE_ID` → `config.json:appleId` | ASC 웹 세션에 쓸 Apple ID |
| `--team-id` | `$DEVELOPMENT_TEAM` → `config.json:developmentTeam` | 10자 영숫자 대문자 |
| `--sku` | bundle ID 와 동일 | `[A-Za-z0-9._-]{1,100}` |
| `--language` | `ko` | BCP-47 short form (`ko`, `en-US` 등) |
| `--app-version` | `1.0.0` | 점-구분 숫자 (`1.0`, `1.2.3`) |
| `--dry-run` | off | 입력 검증만 수행하고 resolved fastlane 호출을 출력. fastlane/brew/세션 없는 환경에서도 동작 (세션 검사는 실 호출 시에만). |

각 flag 는 값이 빠지거나 다른 flag 가 곧바로 따라오면 exit 1 (`ERROR: --xxx requires a value`).

### `--dry-run` 예시

```bash
$ bash .../register-app.sh --bundle-id "com.axi.testapp" --display-name "테스트 앱" --team-id "A1B2C3D4E5" --dry-run
INFO: registering: com.axi.testapp (테스트 앱)
INFO: team:        A1B2C3D4E5
INFO: sku:         com.axi.testapp
INFO: language:    ko
INFO: version:     1.0.0
INFO: DRY RUN — would invoke:
fastlane produce create \
  --username user@example.com \
  --app_identifier com.axi.testapp \
  --app_name '테스트 앱' \
  --language ko \
  --app_version 1.0.0 \
  --sku com.axi.testapp \
  --team_id A1B2C3D4E5
OK: dry-run validation passed
```

### Status file (선택)

`AUTOBOT_REGISTER_STATUS_FILE` 환경변수를 지정하면 JSON 결과를 그 경로에 **원자적으로(temp+rename)** 기록한다:

```bash
AUTOBOT_REGISTER_STATUS_FILE=".autobot/register-status.json" \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-register-app/scripts/register-app.sh" \
  --bundle-id "com.axi.appname" --display-name "앱 이름"
```

```json
{
  "app_version": "1.0.0",
  "bundle_id": "com.axi.appname",
  "display_name": "앱 이름",
  "language": "ko",
  "reason": "",
  "result": "created",
  "sku": "com.axi.appname",
  "team_id": "A1B2C3D4E5",
  "timestamp": "2026-05-18T12:00:00Z"
}
```

`result` 는 `created` / `already_exists` / `failed` 중 하나. JSON 은 모두 `python3 -c json.dumps` 로 직렬화되므로 따옴표·줄바꿈·유니코드가 들어있어도 깨지지 않는다.

## Behavior

### Idempotency 분류 (CRITICAL — 잘못 분류 시 실패가 성공으로 위장됨)

| fastlane 출력 | 의미 | 결과 |
|---------------|------|------|
| `App ID ... already exists`, `bundle ID has already been used`, `already registered to your account` | **내 팀에 이미 등록된 번들 ID** | exit 0, `already_exists` |
| `App Name ... already being used`, `name you entered is already being used` | **다른 개발자가 같은 이름 선점** — 등록 실패 | exit 4, `name_collision` |
| `Identifier ... is not available`, `App ID ... not available` | **다른 팀이 번들 ID 선점** | exit 4, `bundle_id_taken` |
| `Unauthorized Access`, `Could not login`, `session ... expired`, 2FA 요구 | **ASC 웹 세션 만료/무효** — `fastlane spaceauth` 재실행 필요 | exit 4, `asc_session_expired` |
| `Could not create application`, `insufficient privileges`, `not authorized` | **Apple ID 의 ASC role 부족** | exit 4, `asc_permission_denied` |
| 그 외 비정상 종료 | 알 수 없는 fastlane 에러 | exit 4, `fastlane_exit_<N>` |

빌드 파이프라인이 status 의 `result`+`reason` 만 보고 다음 단계 진입 여부를 결정할 수 있다.

### Input validation (fastlane 호출 전에 차단)

- Bundle ID 는 **prefix segment 만** lowercase 로 정규화되고 **마지막 segment(앱 이름)는 케이스 보존** — `Com.AXI.MyApp` → `com.axi.MyApp`. PascalCase 앱 이름이 round-trip 으로 살아남는다. 검증 regex: `^[a-z][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)*\.[A-Za-z0-9][A-Za-z0-9-]*$`
- Display name: **문자(character) 수** 2..30. `${#var}` 가 locale 의존이라 LANG=C 환경에서 한글이 byte 로 세어지는 버그를 피하기 위해 python3 로 측정.
- Team ID 가 명시되면 `^[A-Z0-9]{10}$` 검증
- SKU: `^[A-Za-z0-9._-]{1,100}$`
- Language: `^[a-z]{2,3}(-[A-Z]{2})?$` (BCP-47 short form)
- App version: `^[0-9]+(\.[0-9]+){0,2}$`
- Apple ID 미해석 시 exit 2. 세션(쿠키/`FASTLANE_SESSION`) 부재 시 exit 2 (`--dry-run` 에서는 세션 검사 건너뜀)
- python3 미존재 시 exit 1, fastlane 미설치 + brew 부재 시 exit 3 (`--dry-run` 에서는 fastlane 검사 건너뜀)

### Security

- `trap cleanup EXIT INT TERM HUP` — 중간에 죽으면 status `*.tmp.$$` orphan 정리
- 모든 JSON 출력은 `python3 -c json.dumps` 경유 — 사용자 문자열의 따옴표/제어문자가 JSON 을 깨거나 다른 필드를 주입할 수 없음 (테스트로 검증)
- Status 파일은 temp+rename 으로 원자적 쓰기 (CONVENTIONS.md §Atomicity rules)
- 로그는 `OK:` / `INFO:` / `WARN:` / `ERROR:` / `FATAL:` prefix 정책 준수 (CONVENTIONS.md §Output prefix policy)
- fastlane changelog/banner/GitHub-이슈 제안 환경변수로 강제 침묵 (`FASTLANE_SKIP_UPDATE_CHECK=1`, `FASTLANE_HIDE_CHANGELOG=1`, `FASTLANE_HIDE_GITHUB_ISSUES=1` 등) → 임의 텍스트(이슈 제목의 "already being used" 등)가 결과 분류기를 오염시키지 않음
- stdin 차단 (`< /dev/null`) — CI 환경에서 fastlane 의 대화형 prompt 로 인한 hang 방지 (세션 만료 시 hang 대신 `asc_session_expired` 로 분류됨)
- 플러그인 심볼릭 링크 환경(`~/.claude/plugins/cache/...`)에서도 정확한 plugin root 추론 (`readlink` 루프)

## Exit codes

| Code | 의미 | 대응 |
|------|------|------|
| 0 | 등록 성공 또는 이미 내 팀에 존재 | 다음 단계 진행 |
| 1 | 사용법/입력값 오류 또는 python3 누락 | 인자/포맷 수정, `brew install python3` |
| 2 | Apple ID 미해석 또는 ASC 웹 세션 없음 | `--apple-id`/`FASTLANE_USER` 설정, `fastlane spaceauth -u <apple-id>` |
| 3 | fastlane 설치 실패 | 수동 설치 (`brew install fastlane`) |
| 4 | fastlane 등록 실패 | status.reason 으로 분기 — 아래 표 참조 |

## Troubleshooting

| 에러 메시지 | status reason | 해결 |
|-------------|---------------|------|
| "The App Name you entered is already being used" | `name_collision` | `--display-name` 을 고유하게 변경 (회사명 prefix, 미세 변형) |
| "An App ID with Identifier is not available" | `bundle_id_taken` | 번들 ID 마지막 segment 변경 또는 prefix 교체 |
| "Unauthorized Access" / "Could not login" | `asc_session_expired` | `fastlane spaceauth -u <apple-id>` 로 세션 갱신 (2FA 1회, ~30일 유효). 갱신 후 재실행하면 멱등으로 이어짐 |
| "Could not create application" | `asc_permission_denied` | Apple ID 의 ASC role 을 App Manager/Admin 으로 승격 후 재시도 |
| 일시적 ASC 5xx | `fastlane_exit_N` | 재시도 — 멱등이므로 안전 |
| "fastlane not found" + brew 없음 | (exit 3) | `sudo gem install fastlane -NV` 로 직접 설치 |

## Fallback: 수동 등록

자동 등록이 반복적으로 실패하면 ASC 웹에서 1분이면 등록된다:

1. https://appstoreconnect.apple.com → My Apps → "+" → New App
2. Platform: iOS, Name: `<display name>`, Primary Language: 한국어, Bundle ID: drop-down 에서 선택, SKU: bundle ID 그대로
3. 이후 빌드/업로드 단계는 그대로 진행하면 된다 — 이 스킬을 재실행하면 `already_exists` 로 즉시 통과한다.

Bundle ID 가 drop-down 에 없으면 먼저 Apple Developer Portal 에서 App ID 를 등록해야 한다: https://developer.apple.com/account → Identifiers → "+".

## Integration with other Autobot skills

- **`autobot-setup`** — `developmentTeam`, `bundleIdPrefix`, `appleId` 의 출처. 이 스킬은 직접 JSON 파싱하지 않고 항상 `config.sh get-or` 경유.
- **`autobot-archive-build` / `autobot-upload-build`** — 이 스킬이 먼저 성공해야 호출된다. orchestrator 가 이 순서를 보장한다. archive/upload 스킬은 자체적으로 등록을 시도하지 않는다 — 미등록 상태면 fastlane/`xcodebuild` 에러로 명확히 실패한다.
- **`autobot-invite-testers`** — 업로드 성공 후 호출. 등록 단계와는 무관.

## Files

- `scripts/register-app.sh` — 단독 실행 가능한 등록 스크립트
- `tests/test_app_register.py` (repo root `tests/`) — 입력 검증, JSON injection 방어, `--dry-run` 경로의 회귀 테스트 (16개). 네트워크/fastlane 불필요 — `AUTOBOT_CONFIG_DIR` 샌드박스로 실 자격증명이 절대 새어들지 않음. 실행: `python3 -m unittest tests.test_app_register -v`
