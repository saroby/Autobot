---
name: autobot-upload-build
user-invocable: false
description: "Export/upload an existing iOS archive to a registered ASC app and diagnose upload failures."
---

# Export + Upload to App Store Connect

기존 `.xcarchive`를 `xcodebuild -exportArchive`의 `destination: upload`로 export/upload한다. 앱은 `autobot-register-app`으로 등록되어 있어야 한다. 인증/서명 상세는 필요할 때 [signing guide](references/signing-guide.md)를 읽는다. `xcrun altool`은 사용하지 않는다.

## Run and artifact binding

```bash
AUTOBOT_UPLOAD_STATUS_FILE=.autobot/upload-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-upload-build/scripts/upload.sh" \
  --archive-path "/path/to/AppName.xcarchive" \
  --build-state "/path/to/.autobot/build-state.json" \
  --archive-status "/path/to/.autobot/archive-status.json"
```

`--build-state`는 모든 export/upload에 필수이며 `buildId`, `bundleId`를 포함해야 한다. 업로드에는 같은 buildId와 archive digest를 증명하는 `--archive-status`도 필수 (`--no-upload`만 생략 가능). cwd/인접 checkout으로 소유권을 추론하지 않는다.

스크립트는 archive 패키지/서명과 build-state의 bundle ID, status의 buildId/digest, embedded `ITSAppUsesNonExemptEncryption`을 검증한다. 정상 export 뒤에는 IPA가 정확히 하나여야 하며 IPA의 bundle/version/build가 archive와 일치해야 한다.

| 선택 인자 | 기본값 / 계약 |
|-----------|---------------|
| `--export-path` | `<archive-dir>/export` |
| `--method` | `app-store-connect`; `app-store-connect` / `release-testing` / `development` |
| `--team-id` | 서명에 필요한 Developer Team ID (10자 대문자 영숫자) |
| `--no-internal-only` | 기본 내부 TestFlight 전용; 이 flag로 외부 배포 허용 |
| `--no-upload` | 로컬 IPA export만 수행 |
| `--retries` | transient upload 실패만 기본 2회 재시도, 30s/60s 선형 backoff. export/signing 실패는 재시도 안 함 |
| `--dry-run` | 입력/artifact 검증과 resolved 명령 출력만 |

## Authentication and export options

`scripts/release_env.sh`의 상속 env → 프로젝트 `.env` → `~/.autobot/.env`에서 다음 3개가 모두 있으면 API Key를 사용한다. 없으면 Xcode 저장 계정으로 fallback한다.

```text
APP_STORE_CONNECT_API_KEY_KEY_ID
APP_STORE_CONNECT_API_KEY_ISSUER_ID
APP_STORE_CONNECT_API_KEY_KEY_FILEPATH
```

Xcode 계정/API Key가 없으면 `--no-upload`로 export하고 Transporter/Organizer에서 수동 업로드한다. 자동 생성 ExportOptions는 `signingStyle=automatic`, `uploadSymbols=true`, `manageAppVersionAndBuildNumber=true`, 기본 `testFlightInternalTestingOnly=true`; `--no-upload`의 destination은 `export`다.

## Result and failure handling

`AUTOBOT_UPLOAD_STATUS_FILE`의 원자적 JSON에는 `schemaVersion=1`, `buildId`, `bundleId`, `version`, `buildNumber`, `artifactSha256`, `archiveSha256`, `ipaSha256`, `inputManifestHash`, `archive_path`, `export_path`, `ipa_path`, `method`, `auth_method`, `upload_success`, `result`, `reason`, `timestamp`와 archive/IPA 상세 증거를 기록한다. `auth_method`: `api_key` / `xcode_account` / `none`.

`result`: `uploaded` / `already_uploaded` / `build_number_conflict` / `exported_only` / `upload_failed` / `export_failed` / `dry_run` / `failed`.

ASC의 redundant binary 응답은 **이번 실행의 업로드 시도 이력**으로 판정한다:

- 첫 시도에서 중복: 이전 실행의 바이너리이므로 `build_number_conflict`, exit 6, `upload_success=false`. 빌드번호를 올려 re-archive한다.
- 이번 실행에서 업로드 개시 후 transient 실패를 재시도하다 중복: `already_uploaded`, exit 0, `upload_success=true`. **콘텐츠 일치는 미검증**; 코드가 도중에 바뀌었다면 빌드번호를 올려 re-archive한다.

| Exit | 의미 / 대응 |
|------|-------------|
| 0 | upload/already_uploaded/export-only/dry-run 성공. `result: uploaded` 또는 `already_uploaded`일 때만 `autobot-invite-testers` 호출 |
| 1 | 인자/build-state 입력 오류 |
| 2 | archive/xcodebuild 누락, archive identity/digest 또는 export compliance 검증 실패 |
| 4 | export/IPA 검증 실패; 로그와 signing 확인 |
| 5 | upload 실패, IPA는 존재; Transporter/Organizer로 수동 업로드 가능 |
| 6 | 빌드번호 충돌; 번호 변경 후 `autobot-archive-build`부터 재실행 |

ASC 앱 미등록은 등록 스킬로, authentication 실패는 API Key ID/issuer/`.p8` 일치 또는 Xcode 계정으로 복구한다. 업로드 성공은 ASC processing/심사 완료 증거가 아니다.
