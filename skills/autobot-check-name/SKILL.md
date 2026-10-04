---
name: autobot-check-name
user-invocable: false
description: "Check an app title against public App Store listings before ASC registration."
---

# App Title Availability Check

인증 없는 공개 iTunes Search API로 국가별 **게시된 앱**의 이름을 확인한다 (`curl`, `python3` 필요). ASC 등록의 사전 경고이며 실제 등록은 `autobot-register-app`이 판정한다.

**`taken`은 동명의 live 앱 증거, `clear`는 best-effort다.** 예약 후 미출시 이름은 보이지 않고 term당 상위 약 200개만 조회하므로, `clear`도 등록 성공을 보장하지 않는다.

## Run and matching

```bash
AUTOBOT_CHECKNAME_STATUS_FILE=.autobot/check-name-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-check-name/scripts/check-name.sh" \
  --name "앱 이름" --country kr,us,jp
```

`CLAUDE_PLUGIN_ROOT`가 없으면 스크립트 위치에서 동작한다.

| 인자 | 기본값 / 계약 |
|------|---------------|
| `--name` | 필수, python3 문자 수 1..100 |
| `--country` | `kr`; 콤마 구분 ISO alpha-2, 소문자화/공백 제거/중복 제거 |
| `--exact` | 기본 off; on이면 유사 이름 조언 제외 |

- Exact: `trackName`과 query를 casefold + 공백 collapse 후 비교한다. 구두점은 보존 (`Bear: Notes` ≠ `Bear Notes`). 완전일치만 `taken`.
- Similar: 토큰 겹침/부분문자열 후보는 조언만 제공하고 실패시키지 않는다. `--exact`면 계산하지 않는다.
- 입력/값 누락/국가 형식 오류는 네트워크 호출 전에 거부한다.

## Result

`AUTOBOT_CHECKNAME_STATUS_FILE`에 원자적 JSON 기록:

```json
{
  "name": "앱 이름",
  "exact": false,
  "overall": "taken",
  "countries": {
    "kr": {"status": "taken", "match": "앱 이름", "track_id": 123456, "seller": "Developer", "similar": 0},
    "us": {"status": "available", "similar": 2}
  },
  "timestamp": "2026-07-20T12:00:00Z"
}
```

`overall`: `taken` / `clear` / `error`; `countries.<cc>.status`: `taken` / `available` / `error`.

| Exit | 의미 / 대응 |
|------|-------------|
| 0 | 모든 국가에서 완전일치 없음 (`clear`); 최종 등록 판정 필요 |
| 1 | 입력/도구/네트워크 fetch 오류; 수정 후 재시도 |
| 2 | 한 곳 이상 완전일치 (`taken`); 후보 이름 변경 |

fetch 실패와 선점이 섞이면 exit 2가 우선한다. `AUTOBOT_CHECKNAME_FIXTURE_DIR`를 지정하면 curl 대신 `<dir>/<cc>.json`을 읽는다 (누락 파일은 빈 결과=available). 이 fixture 결과를 live 조회 증거로 보고하지 않는다.
