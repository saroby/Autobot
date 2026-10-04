---
name: autobot-register-app
user-invocable: false
description: "Register an iOS app on ASC or diagnose name/bundle collisions; requires an Apple ID web session."
---

# iOS App Registration

`fastlane produce create`로 Developer Portal App ID와 ASC 앱 레코드를 등록한다. `/autobot:testflight`에서 archive 전에 실행하며, `/autobot:mvp`는 호출하지 않는다. 등록 충돌이면 archive/upload를 진행하지 않는다.

## Prerequisites

등록은 **Apple ID 웹 세션**(비공개 iris API)을 사용한다. ASC API Key나 `produce --api_key_path`로 대체할 수 없다. Apple ID의 ASC role은 App Manager 이상이어야 한다.

- 세션 생성/갱신: `fastlane spaceauth -u <apple-id>` (대화형 2FA). 캐시 세션 또는 `FASTLANE_SESSION` 사용.
- Apple ID: `--apple-id` → `$FASTLANE_USER` → `$APPLE_ID` → `config.json:appleId`.
- Team ID: `--team-id` → `$DEVELOPMENT_TEAM` → `config.json:developmentTeam`; 없으면 fastlane 첫 팀. 멀티 팀이면 명시한다.
- config 값은 `autobot-setup/scripts/config.sh`로 해석한다. `scripts/release_env.sh`의 env 우선순위는 상속 env → 프로젝트 `.env` → `~/.autobot/.env`.
- python3 필수. fastlane이 없으면 스크립트가 `brew install fastlane`을 시도한다.

## Run

```bash
AUTOBOT_REGISTER_STATUS_FILE=.autobot/register-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-register-app/scripts/register-app.sh" \
  --bundle-id "com.axi.MyApp" --display-name "앱 이름"
```

`CLAUDE_PLUGIN_ROOT`가 없으면 스크립트 위치에서 추론한다.

| 선택 인자 | 기본값 / 계약 |
|-----------|---------------|
| `--apple-id`, `--team-id` | 위 우선순위; Team ID는 `^[A-Z0-9]{10}$` |
| `--sku` | bundle ID; `^[A-Za-z0-9._-]{1,100}$` |
| `--language` | `ko`; `^[a-z]{2,3}(-[A-Z]{2})?$` |
| `--app-version` | `1.0.0`; `^[0-9]+(\.[0-9]+){0,2}$` |
| `--dry-run` | 입력 검증과 resolved 명령 출력만. fastlane/brew/세션 불필요 |

Bundle ID는 prefix만 소문자화하고 마지막 segment의 대소문자는 보존한다 (`Com.AXI.MyApp` → `com.axi.MyApp`). 검증: `^[a-z][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)*\.[A-Za-z0-9][A-Za-z0-9-]*$`. Display name은 python3 문자 수로 2..30자.

## Result and failure handling

`AUTOBOT_REGISTER_STATUS_FILE`에 원자적으로 기록하는 JSON 필드: `app_version`, `bundle_id`, `display_name`, `language`, `reason`, `result`, `sku`, `team_id`, `timestamp`. `result`는 `created` / `already_exists` / `dry_run` / `failed`. 다음 단계는 `result`와 `reason`으로 판정한다.

| 결과/이유 | 처리 |
|-----------|------|
| `created` / `already_exists` | exit 0. **같은 팀**의 기존 bundle ID만 멱등 성공 |
| `name_collision` | exit 4. 다른 개발자가 이름 사용 중; display name 변경 |
| `bundle_id_taken` | exit 4. 다른 팀의 bundle ID; ID 변경 |
| `asc_session_expired` | exit 4. `spaceauth` 갱신 후 재실행; 자동 재시도로 2FA를 해결하지 않음 |
| `asc_permission_denied` | exit 4. Apple ID role을 App Manager 이상으로 변경 |
| `fastlane_exit_<N>` | exit 4. 로그 확인; 일시적 ASC 오류 재시도는 호출자의 정책을 따름 |

그 밖의 exit: **1** 입력/값 누락 또는 python3 없음, **2** Apple ID 미해석/세션 없음, **3** fastlane 설치 실패. 이름 충돌을 `already_exists`로 처리하지 않는다. 스크립트는 stdin을 차단하고 fastlane 배너를 억제해 결과 분류 오염을 막는다.

자동 등록 실패 시 [ASC](https://appstoreconnect.apple.com)에서 iOS 앱을 같은 name/bundle ID/SKU로 등록한다. Bundle ID가 없으면 [Developer Portal](https://developer.apple.com/account)의 Identifiers에서 먼저 생성한다. 재실행 시 `already_exists`로 이어진다.
