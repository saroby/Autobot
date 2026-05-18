---
name: autobot-generate-metadata
description: Use when generating or updating the `fastlane/metadata/` folder for an iOS app — App Store name, subtitle, description, keywords, promotional text, release notes, copyright, and categories. The LLM drafts each field from app context (architecture.md / build-state.json / build-report.md) and pipes the result as JSON to `write-metadata.sh`, which validates ASC character limits and writes each field atomically. Also use when refreshing metadata for an existing app, drafting localized variants, or troubleshooting "metadata too long" / "invalid metadata" errors before `autobot-upload-metadata`.
---

# Fastlane Metadata Generator

App Store Connect 의 텍스트 메타데이터(name, subtitle, description, keywords 등) 를 `fastlane/metadata/` 구조로 생성한다. 이후 `autobot-upload-metadata` 가 `fastlane deliver --skip_binary_upload` 로 ASC 에 올린다.

**Single Responsibility:** 텍스트 메타데이터 파일 생성만 한다. 스크린샷, 앱 아이콘, 바이너리 업로드, App Privacy 답변은 별도 책임. ASC 업로드도 별도 (`autobot-upload-metadata`).

## When to use

- `/autobot:meta` 가 호출됐을 때 — `/autobot:testflight` 로 빌드를 올린 뒤 ASC 의 텍스트 메타데이터를 채울 때
- 기존 메타데이터를 다시 만들고 싶을 때 (앱 설명/키워드 개선)
- 새 로케일 추가 (예: ko 기본 → en-US 추가)
- 업로드 전 길이 제한 사전 검증

## ASC 길이 제한 (필수 enforce — 초과 시 거부)

| 필드 | 최대 (chars) | 비고 |
|------|--------------|------|
| `name` | 30 | display name. CFBundleDisplayName 과 별개 — App Store 표시명 |
| `subtitle` | 30 | name 아래 한 줄 |
| `description` | 4000 | 본문. 줄바꿈 허용 |
| `keywords` | 100 | comma-separated, **total 100자** (이 안에 모든 키워드 + 콤마 포함) |
| `promotional_text` | 170 | 출시 후 변경 가능 — "새 기능" 같은 동적 안내용 |
| `release_notes` | 4000 | 새 버전 변경사항 |
| `marketing_url` | URL | 선택. 마케팅 페이지 |
| `privacy_url` | URL | 권장 — 개인정보 처리방침 |
| `support_url` | URL | 권장 — 고객 지원 |

문자 수는 **character count** (locale-independent). python3 로 측정하여 `${#var}` 의 LANG=C 바이트 카운트 버그 회피.

## 파일 구조

```
fastlane/metadata/
├── ko/
│   ├── name.txt
│   ├── subtitle.txt
│   ├── description.txt
│   ├── keywords.txt
│   ├── promotional_text.txt
│   ├── release_notes.txt
│   ├── marketing_url.txt   (optional)
│   ├── privacy_url.txt     (optional)
│   └── support_url.txt     (optional)
├── en-US/                  (locale 추가 시)
│   └── ...
├── copyright.txt
├── primary_category.txt
└── secondary_category.txt  (optional)
```

`ko` 가 기본 로케일. `en-US`, `ja`, `zh-Hans` 등 추가 가능.

## LLM 워크플로우

`/autobot:meta` 슬래시 커맨드가 다음을 수행한다:

1. **컨텍스트 수집**
   - `.autobot/build-state.json` — `appName`, `displayName`, `bundleId`
   - `.autobot/architecture.md` — 앱 아이디어/주요 기능
   - `.autobot/build-report.md` (있으면) — 변경 내역 (release_notes 초안용)
   - `~/.autobot/config.json` (autobot-setup) — `companyName` (copyright 용)

2. **각 필드 초안 작성 (LLM 책임)**
   각 필드는 ASC 한도를 **반드시** 지킬 것:
   - `name`: 30자 이하. displayName 을 우선 사용, 너무 길면 줄임
   - `subtitle`: 30자 이하. 한 줄 핵심 가치 ("운동을 기록하고 공유")
   - `description`: 4000자 이하. 첫 3줄이 App Store 리스트에 보이는 hook 임을 의식하고 작성
   - `keywords`: 100자 이하, comma-separated. 공백 최소화 (Apple 이 자동으로 띄어쓰기 무시)
   - `promotional_text`: 170자 이하. "최근 업데이트" 류 짧은 메시지
   - `release_notes`: 4000자 이하. build-report.md 의 변경사항을 사용자 관점으로 풀어쓰기. 초기 버전이면 "첫 출시" 류
   - `copyright`: 형식 `© <year> <companyName>`. config.json 의 companyName 사용
   - `primary_category`: ASC 카테고리 코드 (예: `HEALTH_AND_FITNESS`, `PRODUCTIVITY`, `SOCIAL_NETWORKING`). architecture.md 도메인으로 결정

3. **JSON 직렬화 후 `write-metadata.sh` 호출**

   ```bash
   cat > /tmp/meta-input.json <<'JSON'
   {
     "locales": {
       "ko": {
         "name": "런타임",
         "subtitle": "운동을 기록하고 공유하는 가장 빠른 길",
         "description": "...",
         "keywords": "운동,러닝,피트니스,트래커,...",
         "promotional_text": "...",
         "release_notes": "..."
       }
     },
     "root": {
       "copyright": "© 2026 Axiom",
       "primary_category": "HEALTH_AND_FITNESS"
     }
   }
   JSON

   bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-generate-metadata/scripts/write-metadata.sh" \
     --metadata-json /tmp/meta-input.json \
     --output-dir fastlane/metadata
   ```

## Usage (script)

```
write-metadata.sh --metadata-json <path> [--output-dir <dir>] [--dry-run]
```

| Flag | 기본값 | 설명 |
|------|--------|------|
| `--metadata-json` | (필수) | JSON 입력 파일 경로 |
| `--output-dir` | `fastlane/metadata` | 출력 디렉토리 |
| `--dry-run` | off | 검증만 수행하고 파일 쓰지 않음. 결과 요약을 stdout |

### Status file (선택)

`AUTOBOT_METADATA_STATUS_FILE` 환경변수 지정 시 결과 JSON 원자적 기록:

```json
{
  "fields_written": ["ko/name", "ko/description", "copyright", ...],
  "fields_skipped": [],
  "result": "generated",
  "reason": "",
  "locales": ["ko"],
  "output_dir": "fastlane/metadata",
  "timestamp": "2026-05-18T12:00:00Z"
}
```

`result`: `generated` / `dry_run` / `failed`.

## Exit codes

| Code | 의미 |
|------|------|
| 0 | 모든 필드 검증 통과, 파일 작성 완료 (또는 dry-run) |
| 1 | 사용법/JSON 파싱 오류 |
| 2 | python3 누락 |
| 3 | 길이 제한 위반 — `reason` 에 `field=X locale=Y len=N max=M` 형태로 기록 |
| 4 | 알 수 없는 필드명 또는 locale 코드 |

길이 위반 시 즉시 중단. 부분 쓰기 없음 — 모든 필드를 메모리에서 검증한 뒤에야 쓰기 시작.

## Validation rules

- **필드명 화이트리스트** — 알 수 없는 필드는 exit 4
- **locale 형식**: `^[a-z]{2}(-[A-Z]{2})?$` (BCP-47 short form)
- **문자 수 측정**: python3 `len(str)`. UTF-8 byte 가 아니라 코드 포인트.
- **빈 값**: 빈 문자열은 허용하지 않음 (해당 필드는 JSON 에서 생략하면 됨). 빈 값을 명시적으로 보내면 exit 4
- **URL 필드**: `^https?://` 로 시작해야 함 (생략 가능)
- **원자적 쓰기**: 각 파일은 `tmp + rename`. 한 필드 실패해도 다른 필드가 잘못 쓰이지 않음 (이미 검증된 뒤이므로 실제로는 발생 안 함)
- **기존 파일 덮어쓰기**: 동의 없이 덮어씀 (재실행 가능성을 전제로 함)

## Security

- JSON 파싱은 `python3 -c json.load` — shell injection 방어
- 파일 경로는 `--output-dir` 아래로만 한정 — `..` 같은 path traversal 차단 (validator 가 field name 화이트리스트로 보장)
- 로그는 `OK:` / `INFO:` / `WARN:` / `ERROR:` prefix 정책

## Integration with other Autobot skills

- **`autobot-setup`** — `companyName` (copyright 용) 출처. `bash config.sh get-or companyName ''`
- **`autobot-upload-metadata`** — 이 스킬의 출력 (`fastlane/metadata/`) 를 받아 `fastlane deliver` 로 ASC 업로드
- **`/autobot:meta`** — 이 스킬과 `autobot-upload-metadata` 를 orchestrate

## Files

- `scripts/write-metadata.sh` — JSON 입력 검증/원자적 쓰기
