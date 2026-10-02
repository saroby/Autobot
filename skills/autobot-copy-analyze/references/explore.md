### Step 3 — 자율 탐험 루프 (기본)

사용자에게 "대상 앱을 열고 기기를 잠금 해제한 채 두세요" 한 번만 요청한 뒤, 에이전트가 아래 루프를 돈다. `NN` 은 00 부터 증가.

```bash
# (a) 현재 화면 덤프 — 스크린샷 + 접근성 트리 + 화면 정체성
CLONE_STATE_DIR=.autobot/copy-analysis \
  scripts/device_wda.sh screen "$sid" .autobot/copy-analysis/device <NN>-<screen>
#   → <NN>-<screen>.png, <NN>-<screen>.xml
#   → INFO: bounds <w>x<h> pt · INFO: scale <n>x · INFO: nodekey/statekey/sig
#     중복 판단은 nodekey/statekey 로 한다 (sig 는 스크롤만 해도 바뀐다 — 아래 참조)

# (b) 안전한 탭 후보만 추출
CLONE_STATE_DIR=.autobot/copy-analysis \
  scripts/device_wda.sh candidates .autobot/copy-analysis/device/<NN>-<screen>.xml

# (c) 후보 중 하나로 이동 — 좌표가 나온 트리를 반드시 함께 넘긴다.
#     tap 이 (1) 그 트리의 후보인지 (2) 지금 화면이 아직 그 트리인지 검사하고,
#     아니면 거부한다. 목록 밖 좌표·낡은 좌표는 애초에 실행되지 않는다.
CLONE_STATE_DIR=.autobot/copy-analysis \
  scripts/device_wda.sh tap "$sid" <x> <y> .autobot/copy-analysis/device/<NN>-<screen>.xml
CLONE_STATE_DIR=.autobot/copy-analysis \
  scripts/device_wda.sh swipe "$sid" <x1> <y1> <x2> <y2>        # 스크롤 — 포인트 좌표
CLONE_STATE_DIR=.autobot/copy-analysis \
  scripts/device_wda.sh swipefrac "$sid" 0.5 0.36 0.5 0.95 [tree.xml]   # 앱 프레임 비율 (권장)

# (c') 상세 화면에서 나오는 길 — 유일하게 candidates 밖을 누르는 명령
CLONE_STATE_DIR=.autobot/copy-analysis \
  scripts/device_wda.sh back "$sid"
```

접두사 규칙은 Step 2 와 같다 — **모든 `device_wda.sh` 호출에 붙이고, `export` 로 대신하지 않는다.** `candidates` 는 트리 파일만 읽어 상태와 무관하지만 예외를 두지 않는다: "어느 줄이 안전한가"를 매번 판단하게 만드는 것이 빠뜨리는 원인이다.

**뒤로 가기는 `back` 이다 — 좌표로 하지 않는다.** 상단 왼쪽의 chevron 은 라벨이 없어 라벨 기반 가드에 보이지 않고, 그래서 `candidates` 에 나오지 않는다. 그 chevron 이 유일한 출구인 상세 화면은 루프가 스스로 걸어 들어간 막다른 길이다. `back` 은 그 자리(leading nav 슬롯)만 누르는 별도 명령이고, 플랫폼 관례상 그 슬롯은 뒤로/닫기/취소이지 결제나 삭제가 아니다. 이것이 "후보 밖은 탭 금지" 의 **유일한 예외**이며, 예외인 만큼 실수로 닿지 않도록 별도 명령으로 분리돼 있다. 탭 예산은 똑같이 차감된다.

- `INFO: no leading nav control on this screen` → 그 자리는 탭 루트다. `back` 을 반복하지 말고 탭바로 이동한다.
- `INFO: screen did not change — that slot was not a back control` → 그 슬롯은 뒤로가 아니었다. 다시 부르지 않는다.

**탐색 순서** — 탭바 항목을 먼저 한 바퀴(앱의 최상위 구조), 그다음 각 탭의 첫 리스트 항목(상세 화면), 생성/추가(+) 버튼, 마지막에 설정. 각 화면 이름은 `<NN>-<tab>-<purpose>` 로 짓는다.

**캡처는 화면이 멈춘 뒤에 찍힌다** — `screen` 은 트리를 두 번 연속 같게 읽을 때까지 기다린 뒤 캡처한다(최대 `CLONE_SCREEN_SETTLE_TRIES`회). 네트워크로 채워지는 화면(검색 결과·피드·상세)은 즉시 캡처하면 **비어 있는 것처럼 보인다** — 실측 2026-08-27: 검색 후 1초 뒤 캡처에 자동완성이 0줄이었고, 같은 화면을 나중에 읽으니 6줄이 있었다. 그때 이 스킬은 "결과 화면이 안 열렸다"고 기록했다.

`WARN: the screen never settled` 가 나오면 그 캡처는 **로딩 중일 수 있다**. 비어 보인다고 "빈 화면"으로 결론 내리지 말고, 다시 `screen` 을 찍어 비교한다.

**어디까지 했는지는 로그가 안다** — `device_wda.sh` 는 `screen`·`tap`·`swipe`·`back` 마다 `.autobot/copy-analysis/flow.jsonl` 에 한 줄씩 남긴다. 무엇을 눌렀고 어디로 갔는지가 전부 거기 있으므로, 프론티어를 머리로 관리하지 말고 물어본다:

```bash
scripts/device_flow.py todo .autobot/copy-analysis/flow.jsonl <현재 tree.xml>    # 이 화면에서 아직 안 눌러본 후보
scripts/device_flow.py next-tap .autobot/copy-analysis/flow.jsonl <현재 tree.xml>  # 다음에 칠 단 하나
scripts/device_flow.py next .autobot/copy-analysis/flow.jsonl                    # 남은 미탐 화면 전체(사람이 읽는 요약)
scripts/device_flow.py stats .autobot/copy-analysis/flow.jsonl                   # 커버리지
```

`next-tap` 은 현재 화면이 소진되면 로그의 전이를 따라 미탐 화면까지의 **첫 홉**을 돌려준다 — 좌표는 넘겨준 최신 트리에서 읽으므로 탭 게이트를 그대로 통과한다.

**로그를 언제 비우나** — 로그는 세션 간 누적된다. 같은 앱을 이어서 파는 것이면 그대로 두면 중복 탐색을 피하고 재개가 된다. **다른 앱을 분석하거나 처음부터 다시 하는 것이면 시작 전에 로그와 센티넬을 지운다:**

```bash
rm -f .autobot/copy-analysis/flow.jsonl .autobot/copy-analysis/broken-*
```

`flow.jsonl` 만 지우면 안 된다 — 탭이 로그에 안 써졌을 때 남는 `broken-<해시>` 센티넬이 그대로 남아 다음 대상에서 첫 탭부터 거부된다. 상태 폴더를 옮겨놨기 때문에 두 줄이 이 실행의 탐험 상태 전부다.

**어떤 경우에도 `rm -rf .autobot/clone` 을 실행하지 않는다** — 그건 `/autobot:clone` 의 작업 전부(`raw/`·`specs/`·`Sources/`·`scores.jsonl`)와 그쪽 세션 기술자·기기 프로필을 날린다. 이 스킬이 지울 것은 자기 폴더 안에만 있다.

### 스와이프 좌표는 스크린샷에서 재지 않는다

탭 좌표는 항상 `candidates` 가 **포인트**로 준다. 스와이프만 에이전트가 좌표를 직접 정해야 하고, 여기서 단위를 틀린다.

스크린샷은 **디바이스 픽셀**(예: 1178×852pt 화면이면 1178×2556px, 3배)이고, 이미지를 읽는 도구가 표시용으로 한 번 더 축소해 보여주기도 한다. 즉 화면에서 눈으로 잰 y 를 쓰려면 **표시 → 원본 px → 포인트** 두 번을 변환해야 한다. 실측 2026-08-27: 시트 핸들이 307pt 인데 한 단계를 빠뜨려 240pt 로 계산했고, 240pt 는 시트 **위쪽 스크림**이라 두 번의 닫기 시도가 아무 일도 하지 않았다. 탐험은 드래그 한 번이면 계속될 화면에서 중단됐다.

**규칙 — 둘 중 하나만 쓴다:**

1. **`swipefrac`** — 앱 프레임 비율(0..1)로 준다. 단위가 없어 틀릴 여지가 없다. 스크린샷을 보고 "핸들은 화면의 36% 지점"이라고 읽는 것은 어떤 배율에서도 맞다.
   ```bash
   scripts/device_wda.sh swipefrac "$sid" 0.5 0.36 0.5 0.95   # 시트 닫기
   scripts/device_wda.sh swipefrac "$sid" 0.5 0.75 0.5 0.25   # 아래로 스크롤
   scripts/device_wda.sh swipefrac "$sid" 0.01 0.5 0.9 0.5    # 좌측 엣지 → 뒤로
   ```
   변환 결과를 `INFO: swipefrac ... = <x1> <y1> <x2> <y2>` 로 찍으므로 검산할 수 있다.
2. **트리에서 읽은 포인트 좌표** — 요소의 `x/y/width/height` 는 이미 포인트다. 그대로 `swipe` 에 넘긴다.

`screen` 은 매 캡처마다 `INFO: bounds <w>x<h> pt` · `INFO: scale <n>x` 를 출력한다. 그래도 스크린샷 픽셀에서 직접 환산하지 말고 위 둘을 쓴다.

**사용자 데이터를 만들지 않는다** — 대상은 사용자의 실제 앱이다. 항목 생성·전송·공유처럼 데이터를 남기는 동작은 화면 구조 확인이 끝나면 저장하지 말고 빠져나온다. 파괴적 라벨은 애초에 후보에서 빠진다.

**STOP 조건 — 하나라도 걸리면 루프를 끝내고 사용자에게 넘긴다:**

| 조건 | 신호 | 행동 |
|------|------|------|
| 탭 예산 소진 | `ERROR: tap budget spent (N/25 cumulative)` — `tap` 이 거부한다 | 정상 종료 → Step 4 |
| 새 화면 고갈 | `device_flow.py next` 가 `frontier empty` | 정상 종료 → Step 4 |
| 시스템 다이얼로그 | `WARN: alert/sheet on screen` (후보 0개로 강제) | **즉시 중단**, 사용자에게 처리 요청 |
| 앱 자신의 시트 | `WARN: sheet on screen` (나가는 길만 후보로 나옴) | 중단 아님. 그 후보를 눌러 빠져나온다. 시트 안이 필요하면 사용자에게 다시 열어달라 한다 |
| 기기 이탈·잠김 | 어떤 명령이든 `ERROR:` | **즉시 중단**, 재시도 루프 금지 |
| 예상과 다른 화면 | `ERROR: screen changed since <tree>` | 낡은 좌표로 이어 치지 말고 **다시 `screen` 부터**. 앱 밖으로 나갔으면 사용자에게 복귀 요청 |
| 로그인·페이월 도달 | 화면에 로그인/구독 입력 요소 | 중단하고 사용자에게 통과 요청 후 재개 |
| 후보 0개 | `OK: 0 tappable` | 스와이프해서 화면을 움직여 본다. 그래도 0이면 `back` 으로 빠져나온다. 그래도 갈 곳이 없으면 종료 |
| 역할 없는 앱 | `WARN: role-blind screen` | **중단 아님.** 라벨-리프 티어로 계속하되, 탭마다 스크린샷을 읽고 화면 종류를 판단한다 (위 role-blind 절) |
| 로그인·페이월 화면으로 판단 | 스크린샷/라벨이 로그인·구독·결제·연령확인 | 후보가 남아 있어도 **탭하지 않고 중단**, 사용자에게 넘긴다 |

**`sig` 로 같은 화면인지 판단하지 않는다.** `sig` 는 라벨 집합 해시라 피드를 한 칸만 스크롤해도 바뀐다 — 같은 화면이 매번 새 화면으로 보인다. 화면 정체성은 `statekey` 이고(`nodekey` + 상호작용 상태), 커버리지·재개·흐름도가 전부 그걸 쓴다. `screen` 이 셋을 다 출력하니 **`INFO: nodekey`/`statekey` 를 보고** 중복을 판단한다. `sig` 는 "직전 캡처와 화면이 실제로 움직였나"를 눈으로 확인할 때만 쓴다.

모달을 만나면 `candidates` 가 후보를 **0개로 강제**하므로 "허용/Allow" 같은 시스템 버튼을 실수로 탭할 수 없다. 앱 자신의 시트는 다르다 — `WARN: sheet on screen` 과 함께 **그 시트 안의 나가는 길만**(`취소`/`닫기`/`뒤로`) 후보로 나온다. `확인`/`완료`/`OK` 는 시트에서 닫기가 아니라 확정이라 후보가 아니다.

접근성 트리를 못 받으면(`WARN: captured <png> but the accessibility tree failed`) 스크린샷만 남는다. `screen` 은 그때 exit 0 으로 끝나므로 **성공과 구분되지 않는다 — 경고 줄을 읽어야 안다.** 트리가 없으면 그 캡처는 흐름 로그에도 기록되지 않아 커버리지·흐름도에서 빠진다. **이때만 사람 주도로 내려간다**: 사용자에게 핵심 화면을 순서대로 열어달라 요청하고 `CLONE_STATE_DIR=.autobot/copy-analysis scripts/device_wda.sh screen`(트리 없이 PNG 만 남는다) 또는 세션이 죽었으면 `scripts/device_capture.sh shot <udid> <out.png>`(devicectl, 트리 없음) 을 반복한다. 트리가 실패한 상태에서 같은 명령이 저절로 낫기를 기대하고 재시도하지 않는다.

최소 핵심 화면(홈/메인, 상세, 생성/입력, 설정, empty state 하나)을 목표로 한다. 완주보다 **핵심 흐름 커버**가 중요하다.
