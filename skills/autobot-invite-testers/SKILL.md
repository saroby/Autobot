---
name: autobot-invite-testers
user-invocable: false
description: "Create a TestFlight group and invite testers after a successful upload."
---

# TestFlight Tester Invitation

`autobot-upload-build`의 `uploaded` / `already_uploaded` 후 TestFlight 그룹을 생성/재사용하고 지정 이메일을 초대한다. ASC processing 완료 전에도 그룹/테스터 등록은 가능하다. 앱은 등록되어 있어야 한다; 이 스킬이 자동 등록하지 않는다.

## Prerequisites

App Manager 이상 **ASC API Key**가 필요하다 (앱 등록의 Apple ID 웹 세션과 별개). `scripts/release_env.sh`는 상속 env → 프로젝트 `.env` → `~/.autobot/.env` 순으로 해석한다.

```text
APP_STORE_CONNECT_API_KEY_KEY_ID
APP_STORE_CONNECT_API_KEY_ISSUER_ID
APP_STORE_CONNECT_API_KEY_KEY_FILEPATH
```

`openssl`, `python3`, `curl` 필수. 스크립트는 ES256 JWT(20분 유효)를 생성해 ASC API를 직접 호출하며 fastlane은 사용하지 않는다. JWT는 변수로만 보관한다.

## Run

```bash
AUTOBOT_INVITE_STATUS_FILE=.autobot/invite-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-invite-testers/scripts/invite.sh" \
  --bundle-id "com.axi.MyApp" --emails "alice@example.com,bob@example.com"
```

이메일은 명시적인 콤마 구분 목록. orchestrator가 `autobot-setup`의 `config.json:testerEmails[]`를 `--emails`로 전달한다.

| 선택 인자 | 기본값 / 계약 |
|-----------|---------------|
| `--group-name` | `내부`; 같은 이름이면 기존 그룹 재사용 |
| `--no-internal` | 기본 내부 그룹(`isInternalGroup=true`, `hasAccessToAllBuilds=true`); flag로 외부 그룹 |
| `--first-name`, `--last-name` | 신규 tester의 이름: `Tester`, `User` |
| `--dry-run` | 자격증명 검증/JWT 생성만; API 호출 없음 |

스크립트는 bundle ID로 app을 조회하고 그룹을 생성/재사용한다. 기존 tester는 그룹에 연결하고 없는 tester는 신규 초대한다. 기존 그룹 회원/409 conflict는 `emails_skipped`로 멱등 처리한다.

## Result and failure handling

`AUTOBOT_INVITE_STATUS_FILE`의 원자적 JSON 필드: `app_id`, `bundle_id`, `emails_failed`, `emails_invited`, `emails_skipped`, `group_id`, `group_name`, `group_result`, `reason`, `result`, `timestamp`.

`result`: `invited` / `partial` / `dry_run` / `failed`; `group_result`: `created` / `reused` / `failed`.

| Exit | 의미 / 대응 |
|------|-------------|
| 0 | 그룹 준비와 모든 이메일 처리 성공 (skipped 포함), 또는 dry-run |
| 1 | 사용법/입력값 오류 |
| 2 | ASC creds/읽을 수 있는 `.p8` 또는 필수 도구 누락 |
| 3 | bundle ID의 ASC 앱 없음; `autobot-register-app` 먼저 |
| 4 | 그룹 생성 실패; 403이면 API Key role 확인 |
| 5 | 한 명 이상 초대 실패 (`partial`); `emails_failed` 확인 |

401이면 시스템 시각/JWT/Key 유효성을 확인한다. 일시적 5xx는 멱등 재시도가 가능하며, `partial`을 전체 성공으로 보고하지 않는다.
