---
name: setup
description: "Autobot 글로벌 설정을 초기화합니다. bundle ID prefix·deployment target 등 모든 빌드가 공유하는 기본값을 ~/.autobot/config.json 에 기록합니다."
argument-hint: "[--show | --reset | --set <key>=<value>]"
allowed-tools:
  - Read
  - Write
  - Bash
  - AskUserQuestion
  - Skill
---

# Autobot Setup

`/autobot:mvp` 와 다른 모든 autobot 스킬이 공유할 사용자별 기본값을 등록한다.
저장 위치는 `~/.autobot/config.json` (권한 600). 스키마와 통합 규약은 `autobot-setup` 스킬 참조.

## 0. 사전 준비

```bash
CONFIG_SH="$CLAUDE_PLUGIN_ROOT/skills/autobot-setup/scripts/config.sh"
```

## 1. 인자 분기

| 인자 | 동작 |
|------|------|
| (없음) | 대화형 초기 설정. 기존 파일이 있으면 현재값을 보여주고 변경 확인. |
| `--show` | `bash "$CONFIG_SH" show` 후 종료 |
| `--reset` | 사용자에게 1회 확인 후 `rm -f "$(bash "$CONFIG_SH" path)"`. 이후 대화형 초기 설정 진행 |
| `--set key=value` | `bash "$CONFIG_SH" set "<key>" "<value>"` 만 수행하고 종료 |

## 2. 현재 상태 표시

```bash
if bash "$CONFIG_SH" exists; then
  echo "현재 설정:"
  bash "$CONFIG_SH" show
else
  echo "설정 파일이 아직 없습니다: $(bash "$CONFIG_SH" path)"
fi
```

## 3. 대화형 입력

다음 6개 항목을 `AskUserQuestion` 으로 수집한다. 기존 값이 있으면 그 값을 **첫 옵션의 default 로 노출**한다.
사용자가 "Other"로 직접 입력한 경우 그 값을 검증 후 사용한다.

### 3.1 Bundle ID prefix (필수)

- 질문: "앱 bundle ID 의 prefix 를 입력하세요. 마지막 segment 뒤에 `.<appname>` 이 자동으로 붙습니다."
- 검증 정규식: `^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$`
- 예시 옵션: `com.axi`, `com.<username>`, `dev.<username>`
- 실패 시 재질문 (최대 3회). 3회 실패하면 빌드 중단 안내.

### 3.2 Apple Developer Team ID (권장, TestFlight 배포 시 필수)

- 질문: "Apple Developer Team ID 를 입력하세요 (Xcode → Settings → Accounts → Team 에서 확인). TestFlight 배포·실기기 서명에 사용됩니다. 로컬 시뮬레이터만 빌드한다면 'Skip'."
- 검증: 정확히 10자 영숫자 대문자 (`^[A-Z0-9]{10}$`)
- 자유 입력 (AskUserQuestion 의 "Other" 경로). 미입력 시 저장 생략.
- **Team ID 가 없으면** 빌드 자체는 가능하지만 TestFlight Phase 6 가 자동으로 건너뛰어진다. 사용자에게 명시적으로 안내한다:
  ```
  ℹ️  Team ID 없이 진행합니다. archive/TestFlight 배포는 비활성화됩니다.
     나중에 추가하려면: /autobot:setup --set developmentTeam=<TEAM_ID>
  ```

### 3.3 Company / Developer name (선택)

- 질문: "회사/개발자 이름을 입력하세요. 저작권 표기 등에 사용됩니다. 건너뛰려면 'Skip'."
- 검증 없음. 빈 값이면 저장하지 않음.

### 3.4 Deployment target (선택, 기본 26.0)

- 질문: "기본 iOS 최소 버전?"
- 옵션: `26.0 (Recommended)`, `18.0`, `17.0`
- 검증: `^[0-9]+\.[0-9]+$`

### 3.5 기본 TestFlight tester emails (선택)

- 질문: "TestFlight 내부 그룹에 자동 초대할 이메일을 콤마로 구분해 입력하세요. 건너뛰려면 'Skip'."
- 검증: 각 항목에 `@` 포함 여부만 확인
- 저장: JSON 배열로

### 3.6 Git remote prefix (선택)

- 질문: "git remote URL prefix 를 입력하세요 (예: `github.com/saroby`). 건너뛰려면 'Skip'."
- 검증: 공백 없는 문자열

### 3.7 App Store Connect API 자격증명 (선택, TestFlight 업로드·심사 제출 시 필수)

ASC API Key 3종은 **시크릿**이라 `config.json` 이 아니라 전역 `.env`(`~/.autobot/.env`, 권한 600)에 기록한다 — `config.json` 은 공유 가능한 식별자 전용이라는 경계를 지킨다. 한 번 넣으면 **모든 프로젝트의 deploy(register/upload/invite)가 읽는다** (매 프로젝트 `.env` 불필요). Key 는 App Store Connect → Users and Access → Integrations → App Store Connect API 에서 생성(역할 ≥ App Manager).

- 질문: "App Store Connect API Key 를 입력하시겠습니까? TestFlight 업로드·심사 제출에 필요합니다. 로컬 시뮬레이터 빌드만 한다면 'Skip'."
  - **Key ID** — 10자 영숫자 대문자 (예: `ABC123XYZ0`)
  - **Issuer ID** — UUID (예: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)
  - **`.p8` 경로** — 다운로드한 AuthKey 파일 경로 (예: `~/.appstoreconnect/private_keys/AuthKey_ABC123XYZ0.p8`). 파일 자체는 그 자리에 두고 **경로만** 기록한다.
- 검증: Key ID `^[A-Z0-9]{10}$` 권장, Issuer ID UUID 형태, `.p8` 경로는 `~` 확장 후 `[ -r ]` 로 읽기 가능 확인. 셋 중 하나라도 비면 전체 Skip(부분 자격증명은 무의미).

### 3.8 Apple ID + ASC 웹 세션 (선택, 신규 앱 등록 시 필수)

**앱 레코드 생성(`autobot-register-app`)은 ASC API Key 로 인증 불가** — Apple 비공개 API 라 Apple ID 웹 세션이 필요하다 (자세히: `skills/autobot-register-app/SKILL.md` §Prerequisites).

- 질문: "ASC 로그인용 Apple ID 를 입력하세요 (신규 앱 등록에 필요). 이미 등록된 앱만 다룬다면 'Skip'."
- 기록: `bash "$CONFIG_SH" set appleId "<입력값>"` (시크릿 아님 — config.json OK)
- 세션 점검: `~/.fastlane/spaceship/<appleId>/cookie` 가 없거나 mtime 이 25일 이상이면 안내:

  ```
  ⚠️  ASC 웹 세션이 없거나 곧 만료됩니다. 지금 갱신하면 ~30일간 앱 등록이 완전 무인으로 돕니다:
      fastlane spaceauth -u <appleId>    (대화형 2FA 1회)
  ```

  spaceauth 실행 자체는 사용자 몫(2FA 는 사람만 가능) — setup 은 안내만 하고 블로킹하지 않는다.

## 4. 기록

수집한 값을 환경변수로 export 후 `config.sh init --force` 호출:

```bash
export AUTOBOT_SETUP_BUNDLE_PREFIX="<입력값>"
[ -n "<team id>" ] && export AUTOBOT_SETUP_TEAM_ID="<입력값>"
[ -n "<company>" ] && export AUTOBOT_SETUP_COMPANY="<입력값>"
export AUTOBOT_SETUP_DEPLOYMENT_TARGET="<입력값 or 26.0>"
[ -n "<emails>" ] && export AUTOBOT_SETUP_TESTER_EMAILS="<콤마 구분>"
[ -n "<git>" ] && export AUTOBOT_SETUP_GIT_REMOTE="<입력값>"

bash "$CONFIG_SH" init --force
```

§3.7 의 ASC 자격증명은 **시크릿이라 config.json 이 아니라 전역 `.env`** 에 기록한다 (3종 모두 입력됐을 때만):

```bash
# config.sh set-env 가 ~/.autobot/.env 에 KEY='value' 로 upsert (권한 600).
bash "$CONFIG_SH" set-env ASC_API_KEY_ID    "<key id>"
bash "$CONFIG_SH" set-env ASC_API_ISSUER_ID "<issuer id>"
bash "$CONFIG_SH" set-env ASC_API_KEY_PATH  "<.p8 경로>"
```

`--force` 는 기존 파일을 덮어쓰기 위함. `--reset` 분기가 아니더라도 부분 변경 시 사용한다 (현재값이 모두 환경변수로 export 되므로 손실 없음).

**부분 수정 시 안전망**: 사용자가 일부 항목만 변경한다면, 먼저 기존 값을 `config.sh get` 으로 읽어 환경변수에 채운 뒤 변경분만 덮어쓴다. init 은 항상 전체를 다시 기록한다.

```bash
EXISTING_PREFIX="$(bash "$CONFIG_SH" get bundleIdPrefix 2>/dev/null || echo '')"
EXISTING_TEAM="$(bash "$CONFIG_SH" get developmentTeam 2>/dev/null || echo '')"
# ... 나머지 동일하게 채움 ...
```

## 5. 결과 확인

```bash
echo ""
echo "✅ 설정 저장됨: $(bash "$CONFIG_SH" path)"
bash "$CONFIG_SH" show
bash "$CONFIG_SH" validate
echo ""
echo "이제 /autobot:mvp 로 빌드를 시작할 수 있습니다."
```

## 안전 정책

- `~/.autobot/config.json` 외 다른 경로에 절대 쓰지 않는다.
- 시크릿 (.p8 키, app-specific password, ASC API Issuer ID) 은 **저장 금지**. 그 값들은 `.env` 의 책임.
- 사용자가 시크릿을 답변에 포함하면 거부하고 `.env.example` 사용을 안내한다.
- `--reset` 은 파일 삭제 전 1회 확인 후에만 진행한다.

## Troubleshooting

| 증상 | 원인 | 해결 |
|------|------|------|
| `python3 not found` | Python 3 미설치 | `brew install python3` |
| validate 가 exit 3 | 필수키 누락 | `/autobot:setup` 재실행하여 누락 항목 채움 |
| bundle-id 결과에 한글 포함 | AppName 이 ASCII PascalCase 아님 | orchestrator 단계에서 identifier name 재생성 |
| 권한 거부 | `~/.autobot` 디렉토리 권한 문제 | `chmod 700 ~/.autobot && chmod 600 ~/.autobot/config.json` |
