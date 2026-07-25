---
name: autobot-setup
user-invocable: false
description: Use when other Autobot skills need user-wide defaults (bundle ID prefix, Apple Team ID, company name, deployment target, tester emails, git remote prefix). Read/write via scripts/config.sh. Also use when /autobot:setup needs to (re)initialize the global config at ~/.autobot/config.json.
---

# Autobot Setup — Global Config

Autobot 빌드는 사용자별로 일정한 메타데이터 — bundle ID prefix(`com.xxx`), Apple Developer Team ID, 회사명, deployment target, 기본 TestFlight tester 이메일, git remote prefix — 를 반복 사용한다. 매 빌드마다 묻거나 LLM이 추측하지 않도록 **글로벌 1회 설정**을 두고 모든 스킬이 동일한 출처를 읽는다.

## Storage

두 파일을 같은 디렉토리(`~/.autobot/`, 권한 700)에 둔다 — 역할이 다르므로 절대 합치지 않는다:

- **`~/.autobot/config.json`** (권한 600): **공개 가능한 식별자/기본값** — bundleIdPrefix, developmentTeam, companyName, deploymentTarget, testerEmails, gitRemotePrefix.
- **`~/.autobot/.env`** (권한 600): **시크릿** — ASC API Key(`APP_STORE_CONNECT_API_KEY_KEY_ID` / `APP_STORE_CONNECT_API_KEY_ISSUER_ID` / `APP_STORE_CONNECT_API_KEY_KEY_FILEPATH`), Apple ID 비밀번호 등. `config.sh set-env`/`get-env`/`env-path` 로 관리. `KEY='value'` 형식(no `export`)이라 `set -a` source + `^KEY=` 탐지 둘 다 호환. `.p8` 파일 자체는 디스크에 두고 **경로만** 기록.

- **환경변수 오버라이드**:
  - `AUTOBOT_CONFIG_DIR` — 디렉토리 변경 (config.json + .env 둘 다 따라감; 테스트/샌드박스용)
  - `AUTOBOT_CONFIG_FILE` — config.json 경로 직접 지정
  - `AUTOBOT_ENV_FILE` — .env 경로 직접 지정

- **시크릿 경계 (불변)**: 시크릿은 **`.env` 에만**, 식별자는 **`config.json` 에만**. 두 파일을 합치지 않는다. `config.json` 에 시크릿(API Key id/issuer 등)을 넣지 않는다 — `config.json` 의 "공유 가능" 전제가 깨지기 때문.
- **set-once / 전역 우선**: `/autobot:setup` 이 `~/.autobot/.env` 를 한 번 채우면, 모든 프로젝트의 deploy(register/upload/invite, `/autobot:testflight`, `/autobot:app-review`)가 **전역 `.env` → 프로젝트 `.env`** 순으로 source 해 읽는다(프로젝트가 override). 매 프로젝트 `.env` 를 다시 만들 필요가 없다.

## Schema (v1)

```json
{
  "version": 1,
  "bundleIdPrefix": "com.axi",
  "developmentTeam": "A1B2C3D4E5",
  "appleId": "user@example.com",
  "companyName": "Axiom",
  "deploymentTarget": "26.0",
  "testerEmails": ["tester@example.com"],
  "gitRemotePrefix": "github.com/saroby"
}
```

| 키 | 타입 | 필수 | 설명 |
|----|------|-----|------|
| `version` | int | yes | 스키마 버전. 현재 `1` |
| `bundleIdPrefix` | string | **yes** | `^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$` — 도메인 역순. 마지막 segment 뒤에 `.<appname>` 가 붙는다. |
| `developmentTeam` | string | no | Apple Developer Team ID. 10자 영숫자. Archive/TestFlight 단계에서 필요. |
| `appleId` | string | no | ASC 웹 세션용 Apple ID. `autobot-register-app` 이 앱 등록 시 사용 (앱 생성은 비공개 API 라 ASC API Key 로 대체 불가 — 해당 SKILL.md §Prerequisites). |
| `deploymentTarget` | string | **yes** | iOS 최소 버전. 기본 `26.0`. |
| `companyName` | string | no | 저작권/CFBundleDevelopmentRegion 등에 사용 |
| `testerEmails` | string[] | no | TestFlight 내부 그룹 기본 초대 목록. Phase 6에서 사용 |
| `gitRemotePrefix` | string | no | `github.com/<org>` 형태. 향후 git remote 자동화에서 사용 |

## CLI: `scripts/config.sh`

모든 스킬은 이 스크립트를 통해서만 config 를 다룬다. 직접 JSON 파싱 금지.

```bash
CONFIG_SH="$CLAUDE_PLUGIN_ROOT/skills/autobot-setup/scripts/config.sh"

bash "$CONFIG_SH" path                       # 경로 출력
bash "$CONFIG_SH" exists                     # exit 0/1
bash "$CONFIG_SH" show                       # pretty-print
bash "$CONFIG_SH" get bundleIdPrefix         # 값 출력, 없으면 exit 1
bash "$CONFIG_SH" get-or deploymentTarget 26.0   # 없으면 fallback
bash "$CONFIG_SH" set companyName "Axiom"
bash "$CONFIG_SH" set-json testerEmails '["a@b.com","c@d.com"]'
bash "$CONFIG_SH" validate                   # 기본 필수키 검증
bash "$CONFIG_SH" validate --require bundleIdPrefix,developmentTeam,deploymentTarget,testerEmails
bash "$CONFIG_SH" bundle-id MyApp            # → com.axi.myapp
```

`init` 은 비대화형(env-driven). `/autobot:setup` 커맨드만 호출한다:

```bash
AUTOBOT_SETUP_BUNDLE_PREFIX="com.axi" \
AUTOBOT_SETUP_TEAM_ID="A1B2C3D4E5" \
AUTOBOT_SETUP_COMPANY="Axiom" \
AUTOBOT_SETUP_DEPLOYMENT_TARGET="26.0" \
AUTOBOT_SETUP_TESTER_EMAILS="tester@example.com,qa@example.com" \
AUTOBOT_SETUP_GIT_REMOTE="github.com/saroby" \
bash "$CONFIG_SH" init [--force]
```

### Exit codes

| 명령 | 0 | 1 | 2 | 3 |
|------|---|---|---|---|
| `get` | 값 있음 | 키 없음/빈 값 | — | — |
| `validate` | OK | 사용법 오류 | 파일 없음 | 필수키 누락 |
| `exists` | 파일 있음 | 파일 없음 | — | — |

## Integration Contract

다른 autobot 스킬/커맨드는 **다음 규칙**을 따라야 한다:

### 1. Phase 0 (또는 진입 직후) — validate 먼저

`/autobot:mvp` 와 `/autobot:resume`, 그 외 빌드 진입점은 **무조건 첫 단계에서** validate 호출. 기본 validate는 로컬 빌드에 필요한 `bundleIdPrefix`, `deploymentTarget`만 요구한다:

```bash
CONFIG_SH="$CLAUDE_PLUGIN_ROOT/skills/autobot-setup/scripts/config.sh"

if ! bash "$CONFIG_SH" validate; then
  echo "⚠️ Autobot 글로벌 설정이 누락되었습니다."
  echo "   먼저 /autobot:setup 을 실행하여 bundle prefix·deployment target 을 등록하세요."
  exit 1
fi
```

이 검증은 `.autobot/build.lock` 획득 이후, 환경 검증(xcode-select 등) 직전에 수행한다.

### 2. Bundle ID 생성 — 추측 금지

`mvp.md` 의 `<BundleId>` placeholder 는 **반드시** `config.sh bundle-id <AppName>` 결과로 채운다:

```bash
APP_NAME="SocialFitness"
BUNDLE_ID="$(bash "$CONFIG_SH" bundle-id "$APP_NAME")"   # → com.axi.socialfitness
```

`build-state.json` 의 `bundleId` 필드는 이 값을 그대로 쓴다. LLM 이 `com.example.*` 같은 placeholder 를 생성하지 않는다.

### 3. Deployment target

`ios-scaffold` 등에서 `--deployment-target` 기본값:

```bash
DEPLOY_TARGET="$(bash "$CONFIG_SH" get-or deploymentTarget 26.0)"
```

architecture.md 에서 명시적으로 더 낮은 버전을 요구하지 않는 한 이 값을 사용한다.

### 4. Tester emails — Phase 6

`autobot-invite-testers` 가 명시적 `--emails` 인자가 없을 때 이 목록을 기본으로 사용. `.env` 의 `TESTER_EMAIL` 보다 **우선**한다 (배열 vs 단일값).

### 5. Development Team — 우선순위

```
1) .env 의 DEVELOPMENT_TEAM (명시적 오버라이드)
2) config.json 의 developmentTeam  (기본값)
3) 자동 감지 실패 → archive/deploy 단계에서 중단
```

`create-xcode-project.sh` 가 `DEVELOPMENT_TEAM` 환경변수를 받지 않으므로, 호출 직전에 export 한다:

```bash
export DEVELOPMENT_TEAM="${DEVELOPMENT_TEAM:-$(bash "$CONFIG_SH" get-or developmentTeam '')}"
```

### 6. Apple ID + ASC 웹 세션 — 앱 등록 전용

`autobot-register-app` 은 ASC API Key 가 아니라 **Apple ID 웹 세션**을 쓴다 (앱 레코드 생성은 Apple 비공개 API — 공개 API 에 생성 endpoint 없음). setup 은:

1. `appleId` 를 config.json 에 저장 (`config.sh set appleId <value>`)
2. 세션 상태 점검: `~/.fastlane/spaceship/<appleId>/cookie` 존재 + 30일 이내면 OK
3. 세션이 없거나 오래됐으면 안내: `fastlane spaceauth -u <appleId>` (대화형 2FA 1회, ~30일 유효). **이것이 파이프라인에서 프로그래밍으로 제거 불가능한 유일한 주기적 인간 개입이다** — setup 시점에 미리 갱신해 두면 이후 ~30일간 등록이 완전 무인으로 돈다.

## /autobot:setup 트리거 시점

다음 중 하나라도 해당하면 사용자에게 `/autobot:setup` 실행을 안내한다:

- `config.sh exists` 가 false
- `config.sh validate` 가 exit 3 (필수키 누락)
- `bundleIdPrefix` 형식 검증 실패
- 사용자가 명시적으로 prefix 변경 요청

`/autobot:setup` 자체는 [setup command](../../commands/setup.md) 참조.

## Files

- `scripts/config.sh` — 모든 read/write 의 단일 진입점
