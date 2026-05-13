---
name: autobot-setup
description: Use when other Autobot skills need user-wide defaults (bundle ID prefix, Apple Team ID, company name, deployment target, tester emails, git remote prefix). Read/write via scripts/config.sh. Also use when /autobot:setup needs to (re)initialize the global config at ~/.autobot/config.json.
---

# Autobot Setup — Global Config

Autobot 빌드는 사용자별로 일정한 메타데이터 — bundle ID prefix(`com.xxx`), Apple Developer Team ID, 회사명, deployment target, 기본 TestFlight tester 이메일, git remote prefix — 를 반복 사용한다. 매 빌드마다 묻거나 LLM이 추측하지 않도록 **글로벌 1회 설정**을 두고 모든 스킬이 동일한 출처를 읽는다.

## Storage

- **위치**: `~/.autobot/config.json` (사용자 홈, 권한 600)
- **디렉토리 권한**: 700
- **환경변수 오버라이드**:
  - `AUTOBOT_CONFIG_DIR` — 디렉토리 변경 (테스트/샌드박스용)
  - `AUTOBOT_CONFIG_FILE` — 파일 경로 직접 지정
- **`.env`와의 관계**: `.env`는 **시크릿(ASC API Key, Apple ID 비밀번호 등)** 전용. `config.json`은 **공개 가능한 식별자/기본값** 전용. 두 파일은 절대 합치지 않는다.

## Schema (v1)

```json
{
  "version": 1,
  "bundleIdPrefix": "com.axi",
  "developmentTeam": "A1B2C3D4E5",
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
| `deploymentTarget` | string | **yes** | iOS 최소 버전. 기본 `26.0`. |
| `companyName` | string | no | 저작권/CFBundleDevelopmentRegion 등에 사용 |
| `testerEmails` | string[] | no | TestFlight 내부 그룹 기본 초대 목록. Phase 6에서 사용 |
| `gitRemotePrefix` | string | no | `github.com/<org>` 형태. 향후 git remote 자동화에서 사용 |

## CLI: `scripts/config.sh`

모든 스킬은 이 스크립트를 통해서만 config 를 다룬다. 직접 JSON 파싱 금지.

```bash
CONFIG_SH="$CLAUDE_PLUGIN_ROOT/skills/setup/scripts/config.sh"

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

`/autobot:make` 와 `/autobot:resume`, 그 외 빌드 진입점은 **무조건 첫 단계에서** validate 호출. 기본 validate는 로컬 빌드에 필요한 `bundleIdPrefix`, `deploymentTarget`만 요구한다:

```bash
CONFIG_SH="$CLAUDE_PLUGIN_ROOT/skills/setup/scripts/config.sh"

if ! bash "$CONFIG_SH" validate; then
  echo "⚠️ Autobot 글로벌 설정이 누락되었습니다."
  echo "   먼저 /autobot:setup 을 실행하여 bundle prefix·deployment target 을 등록하세요."
  exit 1
fi
```

이 검증은 `.autobot/build.lock` 획득 이후, 환경 검증(xcode-select 등) 직전에 수행한다.

### 2. Bundle ID 생성 — 추측 금지

`make.md` 의 `<BundleId>` placeholder 는 **반드시** `config.sh bundle-id <AppName>` 결과로 채운다:

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

`testflight-deploy` 가 내부 그룹 초대 시 명시적 입력이 없으면 이 목록을 기본으로 사용. `.env` 의 `TESTER_EMAIL` 보다 **우선**한다 (배열 vs 단일값).

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

## /autobot:setup 트리거 시점

다음 중 하나라도 해당하면 사용자에게 `/autobot:setup` 실행을 안내한다:

- `config.sh exists` 가 false
- `config.sh validate` 가 exit 3 (필수키 누락)
- `bundleIdPrefix` 형식 검증 실패
- 사용자가 명시적으로 prefix 변경 요청

`/autobot:setup` 자체는 [setup command](../../commands/setup.md) 참조.

## Files

- `scripts/config.sh` — 모든 read/write 의 단일 진입점
