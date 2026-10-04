---
name: autobot-generate-metadata
user-invocable: false
description: "Generate or revise localized fastlane/metadata text and validate ASC character limits."
---

# Fastlane Metadata Generator

텍스트 메타데이터를 로컬 `fastlane/metadata/`에 생성/갱신한다. 업로드는 `autobot-upload-metadata`가 담당한다.

## Context and input

`.autobot/build-state.json`의 `appName`, `displayName`, `bundleId`, `.autobot/architecture.md`의 기능, 선택적인 `.autobot/build-report.md`의 변경 내역을 사용한다. `companyName`은 `autobot-setup/scripts/config.sh get-or companyName ''`로 읽는다.

기본 locale은 `ko`. `name`은 displayName을 우선하고 `release_notes`는 실제 변경 내역(초기 버전은 첫 출시)을 사용한다. Copyright는 `© <year> <companyName>`, 카테고리는 architecture의 도메인에 맞는 ASC 코드로 작성한다.

입력 JSON 계약:

```json
{
  "locales": {"ko": {"name": "앱 이름", "subtitle": "핵심 가치", "description": "앱 설명", "keywords": "키워드,목록", "promotional_text": "안내", "release_notes": "첫 출시"}},
  "root": {"copyright": "© 2026 Company", "primary_category": "PRODUCTIVITY"}
}
```

| locale 필드 | 최대 문자 수 |
|-------------|-------------:|
| `name`, `subtitle` | 30 |
| `description`, `release_notes` | 4000 |
| `keywords` | 100 (콤마 포함 총합) |
| `promotional_text` | 170 |
| `marketing_url`, `privacy_url`, `support_url` | `http://` 또는 `https://`로 시작; 선택 |

`root` 허용 필드: `copyright`, `primary_category`, `secondary_category`, `primary_first_sub_category`, `primary_second_sub_category`, `secondary_first_sub_category`, `secondary_second_sub_category`.

## Run and validation

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-generate-metadata/scripts/write-metadata.sh" \
  --metadata-json /tmp/meta-input.json --output-dir fastlane/metadata
```

`--metadata-json` 필수, `--output-dir` 기본 `fastlane/metadata`, `--dry-run`은 검증만 수행한다. python3가 필요하다.

- Locale 형식: `^[a-z]{2}(-[A-Z]{2})?$` (`ko`, `en-US`, `ja` 등).
- 값은 문자열이어야 한다. 빈 값은 생략하고, 알 수 없는 필드/locale은 거부한다.
- 길이는 python3 `len(str)` 코드 포인트로 측정한다. UTF-8 바이트 수를 사용하지 않는다.
- 전체 입력 검증을 통과한 후 `<output>/<locale>/<field>.txt`, `<output>/<root-field>.txt`에 쓴다. 각 파일은 temp+rename으로 원자적 교체; 기존 파일은 덮어쓴다. 검증 실패 시 부분 쓰기 없음.

## Result

`AUTOBOT_METADATA_STATUS_FILE` 지정 시 원자적 JSON 상태 기록: `result`, `timestamp`, 성공 시 `fields_written`, `locales`, `output_dir`; dry-run은 `fields_written: []`와 `fields_validated`, 실패 시 `reason`. `result`: `generated` / `dry_run` / `failed`.

| Exit | 의미 |
|------|------|
| 0 | 작성 완료 또는 dry-run 통과 |
| 1 | 사용법/JSON 파싱/값 타입 오류 또는 입력 없음 |
| 2 | python3 누락 |
| 3 | 길이 초과; `reason`은 `field=X locale=Y len=N max=M` |
| 4 | 알 수 없는 필드/locale, 빈 locale 값 또는 URL 형식 오류 |

`/autobot:meta`가 생성과 업로드를 연결한다. 업로드 승인과 연령등급 설정은 해당 커맨드/`autobot-app-review` 계약을 따른다.
