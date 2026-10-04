---
name: autobot-upload-metadata
user-invocable: false
description: "Upload existing fastlane/metadata text to a registered ASC app."
---

# Fastlane Metadata Upload

기존 `fastlane/metadata/` 텍스트와 선택적인 연령등급 설정을 등록된 ASC 앱에 업로드한다. 호출자의 업로드 승인 계약을 따른다 (`/autobot:meta`의 명시적 확인 또는 `--upload`).

## Prerequisites

App Manager 이상 **ASC API Key**의 다음 env가 필요하다. 앱 등록의 Apple ID 웹 세션과 별개다.

```text
APP_STORE_CONNECT_API_KEY_KEY_ID
APP_STORE_CONNECT_API_KEY_ISSUER_ID
APP_STORE_CONNECT_API_KEY_KEY_FILEPATH
```

`scripts/release_env.sh`는 상속 env → 프로젝트 `.env` → `~/.autobot/.env` 순으로 해석한다. `.p8`은 읽을 수 있어야 한다. fastlane이 없으면 스크립트가 `brew install fastlane`을 시도한다.

ASC 앱이 존재해야 하며 (`autobot-register-app`), metadata 디렉토리 아래 `.txt` 파일이 하나 이상 필요하다 (`autobot-generate-metadata`). `app_store_rating_config.json`이 있으면 자동 감지해 `--app_rating_config_path`로 전달한다.

## Run

```bash
AUTOBOT_METADATA_UPLOAD_STATUS_FILE=.autobot/metadata-upload-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-upload-metadata/scripts/upload-metadata.sh" \
  --bundle-id "com.axi.MyApp"
```

| 선택 인자 | 기본값 / 계약 |
|-----------|---------------|
| `--team-id` | `$DEVELOPMENT_TEAM` → `config.json:developmentTeam`; 10자 대문자 영숫자 |
| `--metadata-path` | `fastlane/metadata` |
| `--platform` | `ios`; `ios` / `appletvos` / `xros` |
| `--dry-run` | 검증과 resolved fastlane 명령 출력만; 호출 안 함 |

스크립트는 `fastlane deliver`에 `--skip_binary_upload --skip_screenshots --skip_app_version_update --force --precheck_include_in_app_purchases false`를 전달한다. API Key JSON은 임시 디렉토리(700)/파일(600)에 생성 후 정리하고 stdin은 차단한다.

## Result and failure handling

`AUTOBOT_METADATA_UPLOAD_STATUS_FILE`의 원자적 JSON 필드: `bundle_id`, `metadata_path`, `reason`, `result`, `team_id`, `timestamp`. `result`: `uploaded` / `dry_run` / `failed`.

| Exit / reason | 처리 |
|---------------|------|
| 0 | 업로드 또는 dry-run 성공 |
| 1 | 사용법/입력값 수정 |
| 2 | metadata/.txt, ASC creds 또는 읽을 수 있는 `.p8` 확인 |
| 3 | fastlane 설치 실패; 수동 설치 |
| 4 / `app_not_registered` | `autobot-register-app`으로 등록 |
| 4 / `metadata_length` | 생성 스킬로 길이 재검증 |
| 4 / `auth_failed` | API Key와 role 확인 |
| 4 / `asc_state_locked` | ASC 버전의 심사/편집 가능 상태 확인 |
| 4 / `fastlane_exit_<N>` | 로그 확인; 일시적 타임아웃이면 재시도 |

첫 버전의 [fastlane #20538](https://github.com/fastlane/fastlane/issues/20538) 예외는 **로컬라이즈 업로드 로그 + `No data` + `fetch_app_store_review_detail`/`review_attachment_file`**가 모두 있을 때만 `uploaded`, `reason=first_version_review_detail_bug`, exit 0으로 처리한다. Rating config가 있으면 `Setting the app's age rating...` 로그도 필수다. 단순 `No data`를 성공으로 간주하지 않는다.
