---
name: autobot-invite-testers
user-invocable: false
description: Use when creating a TestFlight beta tester group on App Store Connect and inviting testers by email after an upload has succeeded. Single-responsibility skill — generates an ES256 JWT, calls `POST /v1/betaGroups` to create the internal group (idempotent), then `POST /v1/betaTesters` for each email. Idempotent on existing testers. Also use when troubleshooting "Bundle ID not found", "401 Unauthorized" JWT issues, or when invitations fail silently after a TestFlight upload.
---

# TestFlight Beta Tester Invitation

업로드가 끝난 앱에 내부 테스터 그룹을 만들고 이메일로 초대한다. ASC API 직접 호출(JWT) 방식 — fastlane 의존 없음.

**Single Responsibility:** 테스터 그룹 + 초대만 한다. ASC 등록은 `autobot-register-app`, archive 는 `autobot-archive-build`, upload 는 `autobot-upload-build` 가 각각 담당한다.

## When to use

- `autobot-upload-build` 가 `result: uploaded` 로 끝났고 내부 테스터에게 빌드를 공유하려 한다
- 기존 그룹에 새 이메일만 추가하고 싶다 (그룹 생성은 idempotent)
- "Bundle ID not found" / "401 Unauthorized" 진단

## Prerequisites

### ASC API Key (필수)

`autobot-register-app` 와 동일한 3개:

```bash
APP_STORE_CONNECT_API_KEY_KEY_ID="XXXXXXXXXX"
APP_STORE_CONNECT_API_KEY_ISSUER_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
APP_STORE_CONNECT_API_KEY_KEY_FILEPATH="$HOME/.appstoreconnect/private_keys/AuthKey_XXXXXXXXXX.p8"
```

Key role 은 **App Manager** 이상.

### openssl + python3 + curl

- `openssl` — JWT 서명 (ES256)
- `python3` — JSON 직렬화 + base64url + status 기록
- `curl` — ASC API 호출

### 앱이 ASC 에 등록돼 있어야 함

`autobot-register-app` 으로 미리 등록. `--bundle-id` 로 앱 ID 를 조회한다.

## Usage

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-invite-testers/scripts/invite.sh" \
  --bundle-id "com.axi.MyApp" \
  --emails "alice@example.com,bob@example.com"
```

선택 인자:

| Flag | 기본값 | 설명 |
|------|--------|------|
| `--group-name` | `내부` | 그룹 이름. 동일 이름이 이미 있으면 기존 그룹 재사용 |
| `--internal` | true | 내부 그룹 (`isInternalGroup: true`, `hasAccessToAllBuilds: true`) |
| `--first-name` | `Tester` | 초대 시 사용할 first name |
| `--last-name` | `User` | 초대 시 사용할 last name |
| `--dry-run` | off | JWT 만 생성하고 실제 API 호출 없이 종료 |

### Status file (선택)

`AUTOBOT_INVITE_STATUS_FILE` 지정 시 결과 JSON 원자적 기록:

```json
{
  "app_id": "1234567890",
  "bundle_id": "com.axi.MyApp",
  "emails_failed": [],
  "emails_invited": ["alice@example.com"],
  "emails_skipped": ["bob@example.com"],
  "group_id": "abcd-1234",
  "group_name": "내부",
  "group_result": "created",
  "reason": "",
  "result": "invited",
  "timestamp": "2026-05-18T12:00:00Z"
}
```

`result`: `invited` / `partial` / `dry_run` / `failed`.
`group_result`: `created` / `reused` / `failed`.

## Exit codes

| Code | 의미 |
|------|------|
| 0 | 그룹 생성/재사용 성공 + 모든 이메일 처리 성공 |
| 1 | 사용법/입력값 오류 |
| 2 | ASC 자격증명 누락 / openssl/curl/python3 미설치 |
| 3 | 앱 ID 조회 실패 (`bundle-id` 가 ASC 에 없음) |
| 4 | 그룹 생성 실패 |
| 5 | 한 명 이상 초대 실패 (status.emails_failed 참조) |

`partial` 결과는 exit 5 — 일부는 됐고 일부는 실패. `emails_invited` / `emails_skipped` / `emails_failed` 로 분류된다.

## Behavior

### JWT 생성 (ES256, 20분 유효)

```
header  = base64url({"alg":"ES256","kid":KEY_ID,"typ":"JWT"})
payload = base64url({"iss":ISSUER_ID,"iat":NOW,"exp":NOW+1200,"aud":"appstoreconnect-v1"})
signature = base64url(ECDSA-SHA256(.p8, header + "." + payload))
JWT = header + "." + payload + "." + signature
```

`base64url` 은 `=` 제거 + `+/` → `-_` 치환. python3 으로 처리해서 platform 별 `base64` 차이 흡수.

### API 호출 순서

1. `GET /v1/apps?filter[bundleId]=<BUNDLE_ID>` → app_id 추출 (없으면 exit 3)
2. `GET /v1/apps/<app_id>/betaGroups?filter[name]=<GROUP_NAME>` → 기존 그룹 확인
3. 기존 없으면 `POST /v1/betaGroups` → group_id (exit 4 가능)
4. 각 이메일에 대해:
   - 이미 존재하는 tester 인지 확인 (`GET /v1/betaTesters?filter[email]=...`)
   - 존재 → 그룹에 추가만 (`POST /v1/betaGroups/<group_id>/relationships/betaTesters`)
   - 없음 → 신규 초대 (`POST /v1/betaTesters` with relationships.betaGroups)

### Idempotency

- 같은 그룹 이름이 존재하면 재사용 (`group_result: reused`)
- 이미 그룹에 속한 tester 는 `emails_skipped` 에 기록되고 exit 5 가 아니라 0
- ASC 가 409 conflict 반환하면 skipped 로 분류

### Atomic status write + cleanup trap

다른 스킬과 동일. JWT 는 `WORK_DIR` 에 임시 저장하지 않고 변수로만 유지 (디스크 노출 차단).

## Troubleshooting

| 에러 | 원인 | 해결 |
|------|------|------|
| `exit 3` "no app found for bundle ID" | ASC 미등록 | `autobot-register-app` 먼저 |
| `exit 4` "group creation failed" + 403 | API Key role 부족 | App Manager 이상으로 승격 |
| `exit 2` "openssl not found" | 시스템에 openssl 없음 | `brew install openssl` |
| 401 Unauthorized | JWT 시계 어긋남 / Key 만료 | NTP 동기화, Key 갱신 |
| 일시적 5xx | ASC 서버 문제 | 재시도 — invite 자체는 멱등 |

## Integration with other Autobot skills

- **`autobot-upload-build`** — 이 스킬은 업로드 직후 호출된다. ASC processing 완료를 기다리지 않아도 그룹/테스터는 등록 가능.
- **`autobot-register-app`** — bundle-id 가 ASC 에 존재해야 함. 이 스킬은 등록을 자동으로 하지 않는다.
- **`autobot-setup`** — `testerEmails[]` 기본 목록을 `~/.autobot/config.json` 에서 읽는다 (orchestrator 가 `--emails` 로 전달).

## Files

- `scripts/invite.sh` — 단독 실행 가능한 invite 스크립트
