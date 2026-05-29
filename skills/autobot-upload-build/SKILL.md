---
name: autobot-upload-build
description: 'Use when uploading an iOS `.xcarchive` to App Store Connect for TestFlight. Single-responsibility skill — runs `xcodebuild -exportArchive` with `destination: upload` so export+upload happen in one official Apple step (`xcrun altool` is deprecated). Requires the app to already be registered on ASC (`autobot-register-app`) and the archive to already exist (`autobot-archive-build`). Also use when troubleshooting "Authentication failed", "The bundle identifier is not available", export/upload failures, or when picking between ASC API Key and Xcode-stored credentials.'
---

# Export + Upload to App Store Connect

`.xcarchive` 를 `.ipa` 로 export 하면서 동시에 ASC 에 업로드한다. `xcrun altool` 은 deprecated — `xcodebuild -exportArchive` 의 `destination: upload` 모드가 공식 대체.

**Single Responsibility:** export+upload 하나만 한다. ASC 등록은 `autobot-register-app`, archive 생성은 `autobot-archive-build`, 테스터 초대는 `autobot-invite-testers` 가 각각 담당한다.

## When to use

- archive 가 이미 만들어졌고 TestFlight 으로 보내야 한다
- export 와 upload 를 한 단계로 처리하고 싶다 (Apple 의 권장 방식)
- "Authentication failed" / "bundle identifier is not available" 진단
- 자동 업로드 실패 시 IPA 만 export 하고 수동 업로드(Transporter)로 넘기려 한다

## Prerequisites

### ASC API Key (권장)

`.env` 에:

```bash
ASC_API_KEY_ID="XXXXXXXXXX"
ASC_API_ISSUER_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
ASC_API_KEY_PATH="$HOME/.appstoreconnect/private_keys/AuthKey_XXXXXXXXXX.p8"
```

3개가 모두 있으면 API Key 인증. 없으면 Xcode 저장 계정으로 fallback (Xcode → Settings → Accounts 에 Apple ID 로그인 필요).

### Archive 존재

`autobot-archive-build` 의 출력 (`.xcarchive` 디렉토리) 이 있어야 한다. 없으면 exit 2.

### 사전 등록

ASC 에 앱이 등록돼 있어야 한다 (`autobot-register-app` 으로 미리 처리). 미등록 상태로 호출하면 `xcodebuild` 가 "The bundle identifier is not available" 로 실패한다.

## Usage

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-upload-build/scripts/upload.sh" \
  --archive-path "/path/to/AppName.xcarchive"
```

선택 인자:

| Flag | 기본값 | 설명 |
|------|--------|------|
| `--export-path` | `<archive-dir>/export` | IPA 출력 디렉토리 |
| `--method` | `app-store-connect` | export method (`app-store-connect` / `release-testing` / `development`) |
| `--internal-only` | on | TestFlight 내부 테스트 전용 (외부 배포 차단) |
| `--no-upload` | off | export 만 하고 업로드 안 함 (IPA 파일만 생성) |
| `--dry-run` | off | resolved invocation 출력 후 종료 |

### Status file (선택)

`AUTOBOT_UPLOAD_STATUS_FILE` 지정 시 JSON 원자적 기록:

```json
{
  "archive_path": "/.../AppName.xcarchive",
  "auth_method": "api_key",
  "export_path": "/.../export",
  "ipa_path": "/.../export/AppName.ipa",
  "method": "app-store-connect",
  "reason": "",
  "result": "uploaded",
  "timestamp": "2026-05-18T12:00:00Z",
  "upload_success": true
}
```

`result`: `uploaded` / `exported_only` / `upload_failed` / `export_failed` / `dry_run` / `failed`.
`auth_method`: `api_key` / `xcode_account` / `none`.

## Exit codes

| Code | 의미 | 대응 |
|------|------|------|
| 0 | export+upload 성공, export-only 성공, 또는 dry-run 통과 | 다음 단계 (`autobot-invite-testers`) |
| 1 | 사용법/입력값 오류 | 인자 확인 |
| 2 | archive 미존재 또는 xcodebuild 미설치 | `autobot-archive-build` 먼저 실행 |
| 4 | export 실패 (IPA 도 안 만들어짐) | 로그/signing 확인 |
| 5 | export 는 됐는데 upload 실패 — IPA 는 존재 | Transporter 수동 업로드 |

exit 5 는 부분 성공: IPA 는 손에 있으니 Xcode Organizer 나 Apple Transporter 로 수동 업로드 가능.

## Behavior

### Authentication 자동 선택

```
ASC_API_KEY_ID + ASC_API_ISSUER_ID + ASC_API_KEY_PATH 모두 설정?
├── Yes → API Key (-authenticationKey* 파라미터 추가) [CI/CD 권장]
└── No  → Xcode 저장 계정 fallback
         ├── Xcode 에 Apple ID 로그인됨 → 자동 처리
         └── 미로그인 → 자동 업로드 불가, IPA 만 export
```

### ExportOptions.plist 자동 생성

```xml
<key>method</key>                              → --method
<key>destination</key>                         → upload (--no-upload 시 export)
<key>signingStyle</key>                        → automatic
<key>uploadSymbols</key>                       → true
<key>manageAppVersionAndBuildNumber</key>      → true
<key>testFlightInternalTestingOnly</key>       → true (--internal-only off 시 제거)
```

`destination: upload` 가 export+upload 통합의 핵심. `manageAppVersionAndBuildNumber: true` 가 빌드 번호 충돌을 자동 해결.

### Atomic status write + cleanup trap

status JSON 은 `python3 -c json.dumps` + temp+rename. 도중에 죽어도 orphan tmp 정리.

## Troubleshooting

| 에러 | 원인 | 해결 |
|------|------|------|
| "The bundle identifier is not available" | ASC 미등록 | `autobot-register-app --bundle-id X --display-name Y` 먼저 |
| "Authentication failed" | API Key 값 오류 | `ASC_API_KEY_ID` / `ISSUER_ID` / `.p8` 일치 확인 |
| "No matching provisioning profile" | 자동 프로비저닝 실패 | `--team-id` 명시 + ASC 에 device 등록 |
| 네트워크 타임아웃 | ASC 5xx | 재시도. archive 는 재사용 가능. |
| Xcode 미로그인 + API Key 없음 | 자동 업로드 경로 없음 | `.env` 채우거나 Xcode → Settings → Accounts 로그인 |

### Fallback: 수동 업로드

```bash
# IPA 위치 확인
ls -la <archive-dir>/export/*.ipa

# Option 1: Apple Transporter (Mac App Store, 무료)
# IPA 드래그 앤 드롭 → Deliver

# Option 2: Xcode Organizer
# Window → Organizer → 아카이브 선택 → Distribute App → TestFlight & App Store
```

`xcrun altool` 은 deprecated — 사용 금지.

## Integration with other Autobot skills

- **`autobot-register-app`** — 반드시 이 스킬보다 먼저 성공해야 한다. orchestrator 가 순서 보장.
- **`autobot-archive-build`** — 이 스킬의 `--archive-path` 인자는 archive-build 의 `archive_path` 출력을 그대로 받는다.
- **`autobot-invite-testers`** — 업로드 성공 (`result: uploaded`) 후에만 호출된다.

## Files

- `scripts/upload.sh` — 단독 실행 가능한 upload 스크립트
- `references/signing-guide.md` — 인증 방법, ExportOptions.plist 전문, troubleshooting 종합
