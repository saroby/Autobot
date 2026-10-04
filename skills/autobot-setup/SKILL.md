---
name: autobot-setup
user-invocable: false
description: "Read or update user-wide Autobot defaults and initialize ~/.autobot/config.json (/autobot:setup)."
---

# Autobot Setup — Global Config

사용자 기본값의 SSOT는 `scripts/config.sh`다. 모든 config read/write는 이 CLI를 사용하며 JSON을 직접 파싱하지 않는다. 대화형 설정 절차는 [setup command](../../commands/setup.md).

## 저장·시크릿 경계

`~/.autobot/`은 권한 700, 아래 두 파일은 권한 600으로 유지한다:

- `config.json`: 공유 가능한 식별자·기본값만 저장한다.
- `.env`: ASC API Key의 `APP_STORE_CONNECT_API_KEY_KEY_ID` / `APP_STORE_CONNECT_API_KEY_ISSUER_ID` / `APP_STORE_CONNECT_API_KEY_KEY_FILEPATH`, Apple ID 비밀번호 등 시크릿만 저장한다. `config.sh set-env` / `get-env` / `env-path`로 관리한다. 형식은 `KEY='value'`(export 없음); `.p8` 자체 대신 경로만 기록한다.

두 파일을 합치거나 config에 시크릿을 넣지 않는다. Release/deploy 값 우선순위는 **상속한 환경변수 → 프로젝트 `.env` → 전역 `.env`**다. Runtime이 allowlist 키만 파싱하며 `.env`를 셸 코드로 실행하지 않는다.

경로 override: `AUTOBOT_CONFIG_DIR`은 두 파일의 디렉토리, `AUTOBOT_CONFIG_FILE`은 config 경로, `AUTOBOT_ENV_FILE`은 시크릿 경로를 지정한다.

## Schema v1

| 키 | 타입·필수 여부 | 계약 |
|----|----------------|------|
| `version` | int, 필수 | `1` |
| `bundleIdPrefix` | string, 필수 | `^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$`; 뒤에 `.<appname>` 추가 |
| `deploymentTarget` | string, 필수 | 기본 `26.0` |
| `developmentTeam` | string | Team ID 10자 영숫자; archive/deploy에 필요 |
| `appleId` | string | 앱 등록용 ASC 웹 세션 ID |
| `companyName` | string | 저작권 등 기본값 |
| `testerEmails` | string[] | Phase 6 기본 초대 목록 |
| `gitRemotePrefix` | string | `github.com/<org>` |

## CLI

```bash
CONFIG_SH="$CLAUDE_PLUGIN_ROOT/skills/autobot-setup/scripts/config.sh"
bash "$CONFIG_SH" path
bash "$CONFIG_SH" exists
bash "$CONFIG_SH" show
bash "$CONFIG_SH" get bundleIdPrefix
bash "$CONFIG_SH" get-or deploymentTarget 26.0
bash "$CONFIG_SH" set companyName "Axiom"
bash "$CONFIG_SH" set-json testerEmails '["a@b.com","c@d.com"]'
bash "$CONFIG_SH" validate
bash "$CONFIG_SH" validate --require bundleIdPrefix,developmentTeam,deploymentTarget,testerEmails
bash "$CONFIG_SH" bundle-id "$APP_NAME"
```

`init`은 비대화형이며 `/autobot:setup` 커맨드만 호출한다:

```bash
AUTOBOT_SETUP_BUNDLE_PREFIX="com.axi" \
AUTOBOT_SETUP_TEAM_ID="A1B2C3D4E5" \
AUTOBOT_SETUP_COMPANY="Axiom" \
AUTOBOT_SETUP_DEPLOYMENT_TARGET="26.0" \
AUTOBOT_SETUP_TESTER_EMAILS="tester@example.com,qa@example.com" \
AUTOBOT_SETUP_GIT_REMOTE="github.com/saroby" \
bash "$CONFIG_SH" init [--force]
```

Exit codes: `get` 0=값 있음, 1=없음/빈 값; `exists` 0=있음, 1=없음; `validate` 0=OK, 1=사용법 오류, 2=파일 없음, 3=필수키 누락.

## 통합 계약

- 빌드 진입점(`mvp`, `resume` 포함)은 build lock 획득 직후, 환경 검증 직전에 `config.sh validate`를 실행한다. 기본 필수키는 `bundleIdPrefix`, `deploymentTarget`; 실패하면 setup을 안내하고 중단한다.
- `BUNDLE_ID=$(bash "$CONFIG_SH" bundle-id "$APP_NAME")` 결과를 `build-state.json.bundleId`에 그대로 쓴다. placeholder를 추측하지 않는다.
- `DEPLOY_TARGET=$(bash "$CONFIG_SH" get-or deploymentTarget 26.0)`을 scaffold에 전달한다. architecture가 명시한 더 낮은 버전만 예외다.
- Phase 6 tester 우선순위: 명시적 `--emails` → config `testerEmails` → `.env`의 단일 `TESTER_EMAIL`.
- Team 우선순위: `.env`의 `DEVELOPMENT_TEAM` → config `developmentTeam` → 자동 감지. 감지에도 실패하면 archive/deploy를 중단한다. scaffold는 환경변수를 읽으므로 호출 전에 export한다:

```bash
export DEVELOPMENT_TEAM="${DEVELOPMENT_TEAM:-$(bash "$CONFIG_SH" get-or developmentTeam '')}"
```

앱 등록은 ASC API Key로 대체할 수 없는 Apple ID 웹 세션을 사용한다 ([autobot-register-app](../autobot-register-app/SKILL.md)). `config.sh set appleId <value>`로 식별자를 저장하고 `~/.fastlane/spaceship/<appleId>/cookie`가 존재하며 30일 이내인지 확인한다. 없거나 오래됐으면 `fastlane spaceauth -u <appleId>`의 대화형 2FA 갱신을 안내한다.

config가 없거나 필수키/`bundleIdPrefix` 형식이 잘못됐거나 사용자가 prefix 변경을 요청하면 `/autobot:setup`을 안내한다.
