---
name: autobot-check-name
user-invocable: false
description: Use when checking whether an app title is already registered/taken in a specific country's App Store BEFORE registering it on App Store Connect — a pre-flight guard against `autobot-register-app`'s `name_collision`. Queries the PUBLIC iTunes Search API per country (no auth, no dependency beyond curl+python3), so it needs no ASC session or API key. Supports multiple countries in one call (`--country kr,us,jp`). A "taken" verdict is reliable; a "clear" verdict is best-effort (the Search API sees only LIVE apps, not ASC-reserved-but-unpublished names, and only the top ~200 hits per term) — the authoritative registrability verdict is still register-app's `name_collision`. Also use when troubleshooting "The App Name you entered is already being used" before retrying registration with a new name, or when scouting whether a name is free across several territories.
---

# App Title Availability Check (per country)

앱을 App Store Connect 에 등록하기 **전에**, 특정 국가 스토어에서 그 앱 이름이 이미 선점됐는지 사전 검증한다. 공개 **iTunes Search API** 를 국가별로 조회해 `autobot-register-app` 의 `name_collision` 실패를 미리 피한다.

**인증 불필요** — 등록(`autobot-register-app`)은 Apple ID 웹 세션이 필요하지만, 이 사전 체크는 공개 API 라 ASC 세션도 API Key 도 없이 동작한다. `curl` + `python3` 만 있으면 된다.

**Single Responsibility:** 이름 선점 조회 하나만 한다. 실제 등록은 `autobot-register-app`, 아카이브/업로드는 각각의 스킬이 담당한다.

## When to use

- `/autobot:mvp` 나 `/autobot:testflight` 시작 전, 앱 이름을 정하는 단계에서 후보 이름이 타겟 국가에서 비어있는지 확인
- `autobot-register-app` 가 `name_collision` 으로 실패한 뒤, 새 이름 후보를 재시도 전에 여러 나라에서 미리 검증
- 하나의 이름이 여러 territory 에서 모두 자유로운지 스카우트 (`--country kr,us,jp,gb`)

## Data source & ceiling (반드시 이해할 것)

iTunes Search API 는 **게시된(live) 앱만** 본다. 두 가지 한계가 있다:

1. **예약-미출시 이름은 안 보인다** — ASC 에 이름만 예약하고 아직 출시 안 한 앱은 Search 결과에 없다.
2. **term 당 상위 ~200 개만** 반환한다 — 매우 흔한 단어면 정확히 같은 이름의 앱이 200위 밖에 있어 누락될 수 있다.

따라서:

- **`taken` 판정은 신뢰할 수 있다** — 같은 이름의 live 앱이 실재한다는 뜻.
- **`clear` 판정은 best-effort** — "아마 비어있음" 이지, `produce` 가 이 이름을 받아준다는 보장이 아니다. 최종 판정은 여전히 `autobot-register-app` 의 `name_collision` 이다.

이 스킬은 등록을 대체하지 않고, **값싼 사전 경고**를 준다.

## Usage

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-check-name/scripts/check-name.sh" \
  --name "앱 이름" \
  --country kr,us,jp
```

`CLAUDE_PLUGIN_ROOT` 가 없어도 스크립트가 자체 위치에서 동작한다.

| Flag | 기본값 | 설명 |
|------|--------|------|
| `--name` | (필수) | 검사할 앱 타이틀. 문자 수 1..100 (python3 로 측정 — 한글/일본어도 정확). |
| `--country` | `kr` | 콤마 구분 ISO 3166-1 alpha-2 코드. 대소문자 무관, 자동 dedupe. 예: `us,jp` / `kr,us,gb,jp` |
| `--exact` | off | 정확 일치(대소문자·공백 정규화)만 충돌로 간주하고 "유사 이름" 조언을 끈다. 기본은 유사 live 앱을 조언으로 나열하되 실패시키지 않는다. |

각 flag 는 값이 빠지거나 다른 flag 가 곧바로 따라오면 exit 1.

### 매칭 로직

- **exact (taken)**: 응답의 각 `trackName` 을 정규화(casefold + 공백 collapse, 구두점 보존)해 쿼리와 완전 일치하면 `taken`. `"Bear: Notes"` 와 `"Bear Notes"` 는 서로 다른 이름으로 취급.
- **similar (advisory)**: 완전 일치가 아니면서 토큰이 겹치거나 한쪽이 다른 쪽의 부분문자열이면 유사 후보로 카운트. **실패시키지 않고** 참고용으로만 표시. `--exact` 면 아예 계산하지 않는다.

### 출력 예시

```
INFO: checking "앱 이름" in kr, us, jp
FAIL: kr — TAKEN by "앱 이름" (id 123456, Some Developer)
PASS: us — available (no exact match; 2 similar: App Name, The App Name Pro)
PASS: jp — available (no exact match)
```

### Status file (선택)

`AUTOBOT_CHECKNAME_STATUS_FILE` 를 지정하면 JSON 결과를 그 경로에 **원자적으로(temp+rename)** 기록한다:

```json
{
  "name": "앱 이름",
  "exact": false,
  "overall": "taken",
  "countries": {
    "kr": { "status": "taken", "match": "앱 이름", "track_id": 123456, "seller": "Some Developer", "similar": 0 },
    "us": { "status": "available", "similar": 2 },
    "jp": { "status": "available", "similar": 0 }
  },
  "timestamp": "2026-07-20T12:00:00Z"
}
```

`overall` 은 `taken` / `clear` / `error` 중 하나. `countries.<cc>.status` 는 `taken` / `available` / `error`. 모든 JSON 은 python3 `json.dump` 경유 — 응답 속 앱 이름에 따옴표/제어문자가 있어도 status 파일을 깨거나 필드를 주입할 수 없다.

## Exit codes

| Code | 의미 | 대응 |
|------|------|------|
| 0 | 검사한 모든 국가에서 완전일치 없음 (`clear`) | 그 이름으로 등록 진행 (단 clear 는 best-effort — 위 ceiling 참조) |
| 1 | 사용법/입력값 오류, 또는 네트워크 fetch 실패 | 인자 수정, 네트워크 확인 후 재시도 |
| 2 | 한 곳 이상에서 이름이 이미 선점됨 (`taken`) | `--name` 을 고유하게 변경 (브랜드 prefix, 미세 변형) 후 재확인 |

fetch 실패(exit 1)와 선점(exit 2)이 섞이면 **선점(2)이 우선** — 이름 변경이 더 상위 액션이기 때문.

## Behavior & Security

- **인자 검증이 네트워크 호출 전에 차단**: 빈 이름, 100자 초과, alpha-2 아닌 국가코드는 curl 전에 exit 1.
- **국가 코드 정규화**: 소문자화·공백제거·중복제거. `KR, kr ,us` → `kr us`.
- **테스트 훅**: `AUTOBOT_CHECKNAME_FIXTURE_DIR` 지정 시 curl 대신 `<dir>/<cc>.json` 을 raw 응답으로 읽는다(파일 없으면 빈 결과=available). 네트워크 없이 오프라인 회귀 테스트 가능.
- **원자적 쓰기**: status 파일은 python `tempfile` + `os.replace` 로 temp+rename (CONVENTIONS.md §Atomicity rules).
- **JSON injection 방어**: 모든 JSON 은 python 이 소유·직렬화. 응답 속 임의 문자열이 출력/status 를 오염시킬 수 없음 (테스트로 검증).
- **정리**: `trap cleanup EXIT INT TERM HUP` — 임시 응답 디렉터리와 status tmp orphan 제거.
- 로그는 `OK:`/`INFO:`/`PASS:`/`FAIL:`/`ERROR:` prefix 정책 준수 (CONVENTIONS.md §Output prefix policy).

## Integration with other Autobot skills

- **`autobot-register-app`** — 이 스킬은 그 등록의 **사전 체크**다. `taken` 이 나오면 register-app 도 거의 확실히 `name_collision` 으로 실패하므로, 등록 전에 이름을 바꾸는 게 싸다. 반대로 `clear` 라도 register-app 이 최종 판정자다 (예약-미출시 이름은 여기서 안 보임).
- **`autobot-generate-metadata`** — 앱 이름(`name.txt`) 을 확정하기 전에 이 스킬로 타겟 국가 선점 여부를 확인할 수 있다.

## Files

- `scripts/check-name.sh` — 단독 실행 가능한 사전 체크 스크립트 (curl + python3)
- `tests/test_check_name.py` (repo root `tests/`) — 인자 검증, 국가코드 정규화, exact/similar 매칭, taken/available/error 분류, JSON injection 방어, status 원자성 회귀. 네트워크 불필요 — `AUTOBOT_CHECKNAME_FIXTURE_DIR` fixture 주입. 실행: `python3 -m unittest tests.test_check_name -v`
