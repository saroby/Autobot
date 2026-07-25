---
name: autobot-upload-metadata
user-invocable: false
description: Use when uploading App Store metadata (name, subtitle, description, keywords, etc.) from `fastlane/metadata/` to App Store Connect via `fastlane deliver --skip_binary_upload --skip_screenshots`. Single-responsibility skill — does ASC metadata upload only, no generation and no binary upload. Requires the app to be registered on ASC and `fastlane/metadata/` to exist (produced by `autobot-generate-metadata`). Also use when retrying metadata upload after fixing length violations, troubleshooting "Could not edit App Store information", or pushing localized text without touching the binary.
---

# Fastlane Metadata Upload (ASC)

`fastlane/metadata/` 의 텍스트 메타데이터를 App Store Connect 에 업로드한다. 바이너리/스크린샷은 건드리지 않는다 (`fastlane deliver --skip_binary_upload --skip_screenshots --skip_app_version_update`).

**Single Responsibility:** ASC 메타데이터 업로드만 한다. 메타데이터 생성은 `autobot-generate-metadata`, 바이너리 업로드는 `autobot-upload-build`, 테스터 초대는 `autobot-invite-testers` 가 각각 담당.

## When to use

- `autobot-generate-metadata` 가 `fastlane/metadata/` 를 만든 직후 (`/autobot:meta` 의 두번째 단계)
- 길이 제한 위반 fix 후 재시도
- localized 텍스트만 갱신 (바이너리 새 빌드 없이)

## Prerequisites

### 1. ASC API Key

`autobot-register-app` 과 동일한 3개:

```bash
APP_STORE_CONNECT_API_KEY_KEY_ID
APP_STORE_CONNECT_API_KEY_ISSUER_ID
APP_STORE_CONNECT_API_KEY_KEY_FILEPATH
```

fastlane `app_store_connect_api_key` 액션과 동일한 업계표준 이름이라, 기존 fastlane 환경이 그대로 동작한다.

Key role 은 **App Manager** 이상.

### 2. fastlane

미설치 시 스크립트가 `brew install fastlane` 시도. 실패하면 exit 3.

### 3. `fastlane/metadata/` 존재

- `fastlane/metadata/<locale>/*.txt` 가 최소 한 locale 이상 존재해야 함
- 또는 root-level `copyright.txt` / `primary_category.txt`

없으면 exit 2 (`autobot-generate-metadata` 먼저 호출 안내).

### 4. ASC 에 앱 등록됨

미등록이면 `fastlane deliver` 가 "Could not find app" 으로 실패. `/autobot:testflight` 가 register 까지 해주므로 이 스킬을 단독 호출하기 전에 testflight 한 번은 돌려야 한다.

## Usage

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-upload-metadata/scripts/upload-metadata.sh" \
  --bundle-id "com.axi.MyApp"
```

선택 인자:

| Flag | 기본값 | 설명 |
|------|--------|------|
| `--team-id` | `$DEVELOPMENT_TEAM` → config.json:developmentTeam | 10자 영숫자 대문자 |
| `--metadata-path` | `fastlane/metadata` | 입력 디렉토리 |
| `--platform` | `ios` | `ios` / `appletvos` / `xros` |
| `--dry-run` | off | resolved fastlane 명령만 출력, 호출 안 함 |

### Status file (선택)

`AUTOBOT_METADATA_UPLOAD_STATUS_FILE` 지정 시 결과 JSON 원자적 기록:

```json
{
  "bundle_id": "com.axi.MyApp",
  "metadata_path": "fastlane/metadata",
  "reason": "",
  "result": "uploaded",
  "team_id": "A1B2C3D4E5",
  "timestamp": "2026-05-18T12:00:00Z"
}
```

`result`: `uploaded` / `dry_run` / `failed`.

## Exit codes

| Code | 의미 | 대응 |
|------|------|------|
| 0 | 업로드 성공 (또는 dry-run 통과) | 끝 |
| 1 | 사용법/입력값 오류 | 인자 확인 |
| 2 | metadata 디렉토리 누락 / ASC creds 누락 / `.p8` 없음 | `autobot-generate-metadata` 먼저, `.env` 확인 |
| 3 | fastlane 설치 실패 | 수동 설치 |
| 4 | `fastlane deliver` 실패 | status.reason 으로 분기 |

### Failure 분류

| fastlane 출력 패턴 | reason | 의미 |
|-----------------|--------|------|
| `Could not find app`, `Application not found` | `app_not_registered` | `/autobot:testflight` 먼저 (register-app) |
| `metadata is too long`, `value is too long` | `metadata_length` | `autobot-generate-metadata` 재실행, 한도 검증 |
| `Authentication failed`, `not authorized` | `auth_failed` | API key 확인 |
| `Could not edit App Store information` | `asc_state_locked` | 이미 심사 중인 버전이 있는지 확인 |
| `No data` + `fetch_app_store_review_detail` (로컬라이즈 업로드 **후**, 연령 등급 적용 확인 시) | `first_version_review_detail_bug` | **성공으로 처리(exit 0)** — 첫 버전에서 fastlane 이 심사정보 조회 중 크래시하는 알려진 버그([#20538](https://github.com/fastlane/fastlane/issues/20538)). 연령 등급 설정 파일이 있으면 `Setting the app's age rating...` 로그도 확인해야 함 |
| 그 외 | `fastlane_exit_<N>` | 로그 확인 |

## fastlane deliver invocation

```
fastlane deliver \
  --api_key_path <tempdir>/fastlane_api_key.json \
  --app_identifier com.axi.MyApp \
  --metadata_path fastlane/metadata \
  --platform ios \
  --skip_binary_upload \
  --skip_screenshots \
  --skip_app_version_update \
  --force \
  --precheck_include_in_app_purchases false \
  [--team_id A1B2C3D4E5]
```

- `--skip_binary_upload`: 바이너리 안 올림 (이미 testflight 로 올렸음)
- `--skip_screenshots`: 스크린샷은 별도 책임
- `--skip_app_version_update`: 버전 번호 자동 변경 차단
- `--force`: 대화형 prompt 차단 (CI 호환)
- `--precheck_include_in_app_purchases false`: IAP precheck 끔 (없는 앱이 대부분)

## Security

- API Key JSON 은 `mktemp -d` (700) + `umask 077` + `chmod 600` + `trap cleanup` (register-app 과 동일 패턴)
- fastlane 환경변수로 changelog/banner/2FA prompt 침묵
- stdin 차단 (`</dev/null`)
- Status 파일 atomic temp+rename

## Troubleshooting

| 증상 | 해결 |
|------|------|
| `Could not find app for bundle ID` | `/autobot:testflight` 먼저 — register-app 단계가 앱을 ASC 에 생성 |
| `metadata.<locale>.name.length must be less than 30` | `autobot-generate-metadata` 재실행 — LLM 이 한도 안 지킴 |
| `Could not edit App Store information` | ASC 웹에서 현재 버전 상태 확인. "Ready for Submission" 또는 "Prepare for Submission" 일 때만 편집 가능 |
| `Apple's API timed out` | 일시적 — 재시도. fastlane deliver 는 멱등 |

## Integration with other Autobot skills

- **`autobot-generate-metadata`** — 입력 `fastlane/metadata/` 의 생산자. 이 스킬 호출 전에 반드시 통과
- **`autobot-register-app`** (간접) — 앱이 ASC 에 존재해야 한다. `/autobot:testflight` 가 자동으로 보장
- **`/autobot:meta`** — 이 스킬과 `autobot-generate-metadata` 를 orchestrate

## Files

- `scripts/upload-metadata.sh` — fastlane deliver wrapper
