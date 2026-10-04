---
name: autobot-archive-build
user-invocable: false
description: "Create or repair an iOS .xcarchive for export/upload."
---

# iOS Archive Build

Xcode 프로젝트에서 `.xcarchive`를 생성한다. 배포 순서는 `autobot-register-app` → 이 스킬 → `autobot-upload-build`; Phase 5 검증은 `autobot-integration-build`가 담당한다.

## Run

```bash
AUTOBOT_ARCHIVE_STATUS_FILE=.autobot/archive-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-archive-build/scripts/archive.sh" \
  --project-path "/path/to/project" --scheme "AppName"
```

`--project-path` 디렉토리에 `.xcodeproj` 또는 `.xcworkspace`가 있어야 한다 (둘 다 있으면 workspace 우선). Scheme은 `^[A-Za-z0-9._ -]{1,100}$` (공백 허용). Xcode Command Line Tools와 코드 서명 identity가 필요하다 (`xcode-select -p`, `security find-identity -v -p codesigning`).

| 선택 인자 | 기본값 / 계약 |
|-----------|---------------|
| `--team-id` | flag → `$DEVELOPMENT_TEAM` → pbxproj → `config.json:developmentTeam`; `^[A-Z0-9]{10}$`. 없으면 Xcode 자동 서명 |
| `--archive-path` | `<project>/build/<scheme>.xcarchive` |
| `--configuration` | `Release`; `Release` / `Debug` |
| `--dry-run` | 입력 검증과 resolved 명령 출력만; xcodebuild/preflight 실행 안 함 |

## Archive invariants

- 실제 archive 전에 프로젝트 `.autobot/build-state.json`과 `pipeline.sh preflight-ship`의 **fresh Gate 5→6 clean pass**를 요구한다. persisted status로 우회하지 않는다.
- `xcodebuild archive`는 `generic/platform=iOS`, `-allowProvisioningUpdates`, `CODE_SIGN_STYLE=Automatic`, 해석된 `DEVELOPMENT_TEAM`을 사용한다.
- `ITSAppUsesNonExemptEncryption` 설정이 없으면 `INFOPLIST_KEY_ITSAppUsesNonExemptEncryption=NO`를 추가한다 (HTTPS/TLS만 쓰는 면제 대상 기본값). 명시된 `YES`는 보존한다. archive 후 embedded `Info.plist`에 키가 있는지 검증한다.
- xcodebuild exit 0만으로 성공 처리하지 않는다. 실제 archive와 정확히 하나의 embedded app, bundle identity, Mach-O 실행파일, 사용 가능한 codesign의 서명을 검증한다.

## Result and failure handling

`AUTOBOT_ARCHIVE_STATUS_FILE`에 원자적 JSON 기록. `result`: `archived` / `dry_run` / `failed`.

| 상태 필드 | 계약 |
|-----------|------|
| `schemaVersion`, `buildId`, `inputManifestHash` | schema 1과 해당 build/Phase 5 입력 |
| `bundleId`, `buildNumber`, `artifactSha256`, `archiveSha256` | 패키지 identity, app/전체 archive digest |
| `archive_path`, `scheme`, `configuration`, `team_id` | archive 입력/출력 |
| `app_path`, `bundle_id`, `version`, `build`, `artifact_digest`, `archive_digest`, `codesign_status` | 패키지 상세 증거 |
| `result`, `reason`, `timestamp` | 실행 결과 |

| Exit | 의미 / 대응 |
|------|-------------|
| 0 | archive 또는 dry-run 성공. **`archived`일 때만** `archive_path`를 upload에 전달 |
| 1 | 사용법/입력값 오류 |
| 2 | 프로젝트/scheme 또는 xcodebuild 누락 |
| 3 | build state 누락 또는 출하 preflight 차단. `missing_build_state` → `/autobot:mvp`; `preflight_ship_gate_failed` → `/autobot:resume 5`. upload 중단 |
| 4 | archive/검증 실패. `xcodebuild_exit_<N>`, `invalid_archive_artifact`, `missing_export_compliance`의 로그 확인 |

서명 오류는 Xcode Accounts의 인증서와 Team ID, 컴파일 오류는 Phase 5, archive action 오류는 Scheme의 Archive 설정을 확인한다. 업로드 실패 시 archive를 보존해 export/수동 업로드에 재사용한다.
