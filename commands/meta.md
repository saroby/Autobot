---
name: meta
description: "App Store 텍스트 메타데이터(이름·설명·키워드·릴리스 노트 등)를 앱 컨텍스트로 자동 생성하여 `fastlane/metadata/` 에 저장합니다. 작성 후 결과를 보고하고 ASC 업로드 여부를 묻습니다."
argument-hint: "(인자 없음 — 현재 디렉토리의 build-state.json 컨텍스트 사용)"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
---

# Autobot Meta — App Store 메타데이터 생성 + 선택적 업로드

`/autobot:mvp` 로 만든 앱 컨텍스트(architecture.md, build-state.json, build-report.md) 를 읽어 ASC 의 텍스트 메타데이터를 LLM 이 작성하고 `fastlane/metadata/` 에 원자적으로 기록한다. 작성 직후 결과를 사용자에게 보고하고, **`AskUserQuestion`** 으로 ASC 업로드 여부를 묻는다.

**스크린샷 / 앱 아이콘 / 바이너리는 다루지 않는다** — 텍스트 메타데이터만.

## CRITICAL RULES

1. **`.autobot/build-state.json` 이 있어야 한다** — 없으면 "이 디렉토리는 Autobot 프로젝트가 아닙니다." 출력 후 중단.
2. **ASC 길이 한도 enforce** — `autobot-generate-metadata/scripts/write-metadata.sh` 가 모든 필드를 검증. 한 개라도 초과면 어떤 파일도 안 쓰임 (atomic-all-or-nothing).
3. **업로드는 사용자 확인 후** — `AskUserQuestion` 으로 명시적 yes 받은 뒤에만 `autobot-upload-metadata` 호출.
4. **CWD 규칙**: 프로젝트 루트(`build-state.json` 위치)에서 실행. `cd` 로 이탈하지 않음.

## Step 0: 사전 검증

```bash
if [ ! -f .autobot/build-state.json ]; then
  echo "ERROR: .autobot/build-state.json not found. Run /autobot:mvp first."
  exit 1
fi

APP_NAME=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json'))['appName'])")
DISPLAY_NAME=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json'))['displayName'])")
BUNDLE_ID=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('bundleId',''))")

if [ -z "$BUNDLE_ID" ]; then
  echo "ERROR: bundleId missing in build-state.json. Run /autobot:mvp or /autobot:setup first."
  exit 1
fi

COMPANY=$(bash "$CLAUDE_PLUGIN_ROOT/skills/setup/scripts/config.sh" get-or companyName '')
```

## Step 1: 컨텍스트 수집 (LLM 책임)

다음 파일을 읽고 메타데이터 작성에 활용:

| 파일 | 용도 |
|------|------|
| `.autobot/build-state.json` | `appName`, `displayName`, `bundleId`, `idea` |
| `.autobot/architecture.md` | 앱 컨셉 + 주요 기능 → description / subtitle / keywords |
| `.autobot/build-report.md` (있으면) | 변경 내역 → release_notes 초안 |
| `~/.autobot/config.json` | `companyName` → copyright |

## Step 2: 메타데이터 초안 작성 (LLM 책임)

각 필드는 **반드시 ASC 한도를 지킬 것** (한도 초과 시 write-metadata.sh 가 exit 3 로 거부함):

| 필드 | 한도 | 작성 가이드 |
|------|------|------------|
| `name` | 30 | `displayName` 우선. 너무 길면 줄임 |
| `subtitle` | 30 | 한 줄 핵심 가치. App Store 리스트에서 name 아래 표시 |
| `description` | 4000 | 첫 3줄이 hook. 나머지는 기능 bullet + 사용 시나리오. 자연스러운 단락 |
| `keywords` | 100 | comma-separated, **합쳐서** 100자. 공백 최소화 (Apple 이 띄어쓰기 무시) |
| `promotional_text` | 170 | 출시 후도 변경 가능. "최근 업데이트" 류 짧은 hook |
| `release_notes` | 4000 | 첫 출시면 "첫 공개" 류, 이후 build-report.md 의 변경사항을 사용자 관점으로 |
| `copyright` | — | 형식: `© <year> <companyName>` |
| `primary_category` | — | ASC 카테고리 코드 (예: `HEALTH_AND_FITNESS`, `PRODUCTIVITY`, `SOCIAL_NETWORKING`, `EDUCATION`, `UTILITIES`, `FINANCE`, `BUSINESS`, `LIFESTYLE`, `ENTERTAINMENT`, `GAMES`) |

**로케일 정책:**
- 기본 `ko` (autobot 의 1차 로케일). architecture.md 가 영어권 타겟이면 `en-US` 도 함께 작성.
- 다국어가 명시되지 않았으면 `ko` 하나만 작성하고 사용자에게 다른 로케일 추가 안내 (별도 호출).

## Step 3: write-metadata.sh 호출

JSON 으로 직렬화 후 한 번에 전달 (atomic-all-or-nothing 보장):

```bash
cat > /tmp/autobot-meta-$$.json <<'JSON'
{
  "locales": {
    "ko": {
      "name": "...",
      "subtitle": "...",
      "description": "...",
      "keywords": "...,...,...",
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

AUTOBOT_METADATA_STATUS_FILE=.autobot/metadata-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-generate-metadata/scripts/write-metadata.sh" \
  --metadata-json "/tmp/autobot-meta-$$.json" \
  --output-dir fastlane/metadata

rm -f "/tmp/autobot-meta-$$.json"
```

`metadata-status.json` 의 `result` 분기:
- `generated` → Step 4 진행
- `failed` (`reason: field=X len=N max=M`) → 해당 필드 줄여서 LLM 이 재작성 후 재호출 (최대 2회)
- `failed` (다른 reason) → 사용자에게 보고하고 중단

## Step 4: 결과 보고

`fastlane/metadata/` 를 스캔하고 사용자에게 출력. 각 필드의 character count + 한도까지 함께:

```
📝 메타데이터 작성 완료 — fastlane/metadata/

ko/
  name              "런타임" (3/30)
  subtitle          "운동을 기록하고 공유하는 가장 빠른 길" (20/30)
  description       (489/4000)
  keywords          "운동,러닝,사이클,등산,피트니스,트래커,챌린지" (32/100)
  promotional_text  "친구와 함께 달리세요..." (24/170)
  release_notes     "첫 출시. 러닝/사이클링/등산..." (76/4000)

root/
  copyright         "© 2026 Axiom"
  primary_category  HEALTH_AND_FITNESS

description 미리보기 (첫 3줄):
  런타임은 러닝, 사이클링, 등산을 한 곳에서 기록하고
  친구와 비교할 수 있는 피트니스 앱입니다.
  ...
```

## Step 5: 업로드 여부 확인 — `AskUserQuestion`

**필수**: 사용자 명시 yes 받기 전엔 절대 자동 업로드하지 않는다.

```
Question: "메타데이터를 지금 App Store Connect 에 업로드할까요?"
Header:   "Upload?"
Options:
  A) 지금 업로드 (`autobot-upload-metadata` 호출)
     description: ASC 에 즉시 반영됨. 이미 심사 중인 버전이 있으면 거부될 수 있음.
  B) 업로드 안 함 (파일만 디스크에 남김)
     description: 검토 후 나중에 단독 호출:
       bash $CLAUDE_PLUGIN_ROOT/skills/autobot-upload-metadata/scripts/upload-metadata.sh
         --bundle-id <bundle-id>
```

## Step 6 (A 선택 시): 업로드 실행

```bash
AUTOBOT_METADATA_UPLOAD_STATUS_FILE=.autobot/metadata-upload-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-upload-metadata/scripts/upload-metadata.sh" \
  --bundle-id "$BUNDLE_ID" \
  --metadata-path fastlane/metadata
```

`metadata-upload-status.json` 의 `result` 분기:
- `uploaded` → "✅ ASC 업로드 완료" 보고 + ASC 페이지 링크
- `failed` (`reason: app_not_registered`) → "이 앱이 ASC 에 미등록입니다. `/autobot:testflight` 먼저 실행하세요." 안내
- `failed` (`reason: metadata_length`) → write-metadata.sh 가 한도를 잡았어야 함 — 회귀 신호로 보고
- `failed` (`reason: auth_failed`) → ASC API key 확인 안내
- `failed` (`reason: asc_state_locked`) → "ASC 에 심사 중인 버전이 있는지 확인하세요." 안내
- 그 외 → fastlane 로그 첨부

## Step 7 (B 선택 시): 종료 보고

```
✅ 메타데이터 파일 생성 완료. 업로드는 건너뛰었습니다.

위치: fastlane/metadata/

검토 후 업로드하려면:
  bash $CLAUDE_PLUGIN_ROOT/skills/autobot-upload-metadata/scripts/upload-metadata.sh \
    --bundle-id <BUNDLE_ID>

또는 /autobot:meta 를 다시 호출하면 새로 생성 + 업로드 옵션을 다시 묻습니다 (파일은 덮어쓰기).
```

## Error Handling

- **`.autobot/build-state.json` 없음**: Step 0 에서 중단. `/autobot:mvp` 안내.
- **bundleId 누락**: Step 0 에서 중단. `/autobot:setup` 안내.
- **write-metadata 검증 실패**: LLM 이 한도 초과 필드 줄여서 최대 2회 재시도. 그래도 실패면 사용자에게 어떤 필드가 길었는지 명시.
- **upload 단계 app_not_registered**: `/autobot:testflight` 안내. 메타데이터 파일은 디스크에 남아있으므로 testflight 후 단독 upload-metadata.sh 재호출 가능.

## Output

- `fastlane/metadata/<locale>/*.txt` + `fastlane/metadata/*.txt` (root) — 실제 메타데이터 파일
- `.autobot/metadata-status.json` — 생성 결과 (atomic write)
- `.autobot/metadata-upload-status.json` — 업로드 결과 (업로드 단계 진행 시만)

Do NOT ask questions during Step 1-4. The single `AskUserQuestion` is at Step 5 (upload decision). All other decisions (locale, field content, retry on length violation) are autonomous.
