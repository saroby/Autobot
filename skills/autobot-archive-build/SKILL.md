---
name: autobot-archive-build
description: Use when archiving an iOS app via `xcodebuild archive` to produce an `.xcarchive` ready for export/upload. Single-responsibility skill — does archive only, no ASC registration and no upload. Auto-detects DEVELOPMENT_TEAM from the .xcodeproj if not supplied. Also use when troubleshooting "No signing certificate found", "Provisioning profile doesn't match", "BUILD FAILED" during archive, or when an archive needs to be regenerated for a re-upload.
---

# iOS Archive Build

Xcode 프로젝트를 archive 하여 `.xcarchive` 번들을 생성한다. 업로드까지 가지 않고 archive 단계에서 멈춘다 — 후속 `autobot-upload-build` 가 그 결과를 받아 export+upload 한다.

**Single Responsibility:** 이 스킬은 archive 하나만 한다. ASC 등록은 `autobot-register-app` 가, 업로드는 `autobot-upload-build` 가, 테스터 초대는 `autobot-invite-testers` 가 각각 담당한다.

## When to use

- 새 빌드를 만들어야 하는데 ASC 업로드는 별도로 분리하고 싶다
- 업로드 실패 후 archive 만 보존하고 수동 업로드(Xcode Organizer/Transporter)로 넘어가려 한다
- "No signing certificate found" / "Provisioning profile doesn't match" 진단

업로드까지 한 번에 가려면 orchestrator 가 이 스킬 다음에 `autobot-upload-build` 를 호출한다.

## Prerequisites

### Apple Developer Team ID

자동 감지 우선순위:
1. `--team-id` flag
2. `$DEVELOPMENT_TEAM` 환경변수
3. `.xcodeproj/project.pbxproj` 의 `DEVELOPMENT_TEAM = XXXXXXXXXX`
4. `~/.autobot/config.json:developmentTeam`

모두 비어있으면 Xcode 의 자동 서명에 맡긴다.

### Signing identity

```bash
security find-identity -v -p codesigning   # 최소 1개 필요
```

미설치 시 Xcode → Settings → Accounts → Manage Certificates 에서 생성.

### xcodebuild

Xcode Command Line Tools 가 설치돼 있어야 한다 (`xcode-select -p`).

## Usage

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-archive-build/scripts/archive.sh" \
  --project-path "/path/to/project" \
  --scheme "AppName"
```

선택 인자:

| Flag | 기본값 | 설명 |
|------|--------|------|
| `--team-id` | auto-detect | 10자 영숫자 대문자 |
| `--archive-path` | `<project>/build/<scheme>.xcarchive` | 출력 archive 경로 |
| `--configuration` | `Release` | `Release` / `Debug` |
| `--dry-run` | off | resolved `xcodebuild` invocation 만 출력하고 종료 |

### Status file (선택)

`AUTOBOT_ARCHIVE_STATUS_FILE` 환경변수를 지정하면 결과를 JSON 으로 원자적 기록:

```json
{
  "archive_path": "/Users/.../build/AppName.xcarchive",
  "configuration": "Release",
  "reason": "",
  "result": "archived",
  "scheme": "AppName",
  "team_id": "A1B2C3D4E5",
  "timestamp": "2026-05-18T12:00:00Z"
}
```

`result`: `archived` / `dry_run` / `failed`.

## Exit codes

| Code | 의미 | 대응 |
|------|------|------|
| 0 | archive 성공 또는 dry-run 통과 | 다음 단계 (`autobot-upload-build`) 로 |
| 1 | 사용법/입력값 오류 | 인자/포맷 수정 |
| 2 | 프로젝트/scheme 누락 또는 xcodebuild 미설치 | `xcode-select -p`, `--project-path` 확인 |
| 4 | xcodebuild archive 실패 | 로그 확인, signing/provisioning 점검 |

## Behavior

### Input validation (xcodebuild 호출 전)

- `--project-path` 가 디렉토리이고 그 안에 `*.xcodeproj` 또는 `*.xcworkspace` 가 있는지
- `--scheme` 비어있지 않음, `[A-Za-z0-9._-]{1,100}$`
- `--team-id` 명시되면 `^[A-Z0-9]{10}$`
- `--configuration` 는 `Release` 또는 `Debug`
- `xcodebuild` 가 PATH 에 있는지 (`--dry-run` 에서는 건너뜀)

### xcodebuild invocation

```
xcodebuild archive \
  -project <project>/*.xcodeproj \
  -scheme "$SCHEME" \
  -archivePath "$ARCHIVE_PATH" \
  -configuration "$CONFIGURATION" \
  -destination 'generic/platform=iOS' \
  -allowProvisioningUpdates \
  CODE_SIGN_STYLE=Automatic \
  [DEVELOPMENT_TEAM=$TEAM_ID]
```

archive 디렉토리가 실제로 만들어졌는지 검증 후 종료한다 — `xcodebuild` 가 exit 0 를 반환해도 archive 가 없으면 실패로 분류.

### Export Compliance enforcement

`ITSAppUsesNonExemptEncryption` 가 누락된 빌드는 ASC 에서 "수출 규정 관련 문서 누락" 으로 마킹돼 테스터가 설치할 수 없다. 이 스킬은 두 단계로 강제한다:

1. archive 직전: `*.xcodeproj/project.pbxproj` 에 키가 없으면 `xcodebuild` 인자에 `INFOPLIST_KEY_ITSAppUsesNonExemptEncryption=NO` 를 자동 추가
2. archive 직후: `<archive>/Products/Applications/<App>.app/Info.plist` 에 키가 존재하는지 `plutil -extract` 로 검증, 없으면 exit 4 + `reason=missing_export_compliance`

기본값은 `NO` (HTTPS/TLS 만 사용하는 면제 대상). 자체 암호화를 쓰는 앱이라면 architect 가 빌드 설정에서 `YES` 로 명시해야 한다.

### Atomic status write

status JSON 은 `python3 -c json.dumps` + temp+rename 으로 원자적으로 기록된다. 다른 스킬과 동일한 안전성 보장.

## Troubleshooting

| 에러 | 원인 | 해결 |
|------|------|------|
| "No signing certificate found" | 코드 서명 인증서 없음 | Xcode → Settings → Accounts → Manage Certificates |
| "Provisioning profile doesn't match" | 자동 프로비저닝 실패 | `--team-id` 명시, ASC 에 device 등록 |
| "BUILD FAILED" | 컴파일 에러 | 빌드 로그 / `autobot-verify-build` 재실행 |
| "scheme is not currently configured for the archive action" | scheme 설정 누락 | Xcode → Edit Scheme → Archive → Build Configuration 확인 |

## Integration with other Autobot skills

- **`autobot-register-app`** — Phase 6 에서 이 스킬보다 먼저 호출된다. ASC 미등록 상태면 archive 는 성공해도 upload 가 실패한다.
- **`autobot-upload-build`** — 이 스킬의 `archive_path` 출력을 받아 export+upload 한다.
- **`autobot-verify-build`** — Phase 5 의 빌드 검증. archive 직전 단계.

## Files

- `scripts/archive.sh` — 단독 실행 가능한 archive 스크립트
