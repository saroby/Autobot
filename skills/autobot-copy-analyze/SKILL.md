---
name: autobot-copy-analyze
user-invocable: false
description: "Analyze an installed iOS app on a connected iPhone into an original product brief (/autobot:copy)."
---

# Autobot Copy Analyze

Analyze an installed app on a connected iPhone into `.autobot/copy-analysis/brief.md` for an original implementation. The accessibility tree is primary evidence; screenshots and App Store data supplement it. This task produces a brief, not clone code or a published app.

## Device safety

## 누가 조작하나 — 에이전트 주도가 기본

에이전트가 `capture → candidates → tap/swipe` 루프를 스스로 돌려 앱을 탐험한다. 사용자는 대상 앱을 포그라운드로 열어두고 기기를 잠금 해제해두는 것까지만 한다.

블라인드 탐색의 위험(로그인·결제·삭제)은 **탭 후보를 만드는 지점에서** 막는다: `device_wda.sh candidates <tree.xml>` 가 접근성 트리를 읽어 탭 가능한 요소만 `INFO: tap <x> <y>` 로 내보내고, 파괴적 라벨(삭제·구매·구독·로그아웃·탈퇴·결제 / delete·purchase·subscribe·sign out…)은 `WARN: withheld` 로 **후보에서 제외**한다. 에이전트는 이 목록 밖을 탭하지 않는다 — 좌표를 직접 지어내지 말 것.

사람에게 넘기는 순간(아래 STOP 조건)에만 "이 화면을 열어주세요"를 요청한다.

### 광고는 후보가 아니다

무료 앱의 화면 안에는 **앱의 UI가 아닌 것**이 섞여 있다. AdMob 배너를 탭하면 App Store 나 브라우저로 튕겨 나가 탐험이 끊기고(`ERROR: ... left the app for <bundle>`), 사람이 누르지 않은 클릭이 광고주에게 과금된다. 그래서 `candidates` 는 광고 크리에이티브에 속한 요소를 **후보 목록에서 아예 뺀다**. 화면에 광고가 있으면 한 줄로 알려준다:

```
WARN: 49 element(s) belong to an ad creative and are not offered — tapping one leaves the app and bills a false click
```

판정 근거 두 가지(실측 2026-08-29):

- **`virtual_root`** — Google Mobile Ads SDK 가 크리에이티브를 별도 가상 접근성 트리로 노출할 때 쓰는 루트 이름. 그 아래 노드는 전부 16진수 이름(`d4e359`…)이라 라벨로는 아무것도 판단할 수 없다.
- **광고 고지 배지** — `광고`/`Ad`/`Sponsored`/`AdChoices` 등. 배지에서 위로 올라가며 **화면 크기 미만인 마지막 조상**을 배너로 본다(웹뷰 크리에이티브처럼 SDK 마커가 없는 경우). 패턴은 앵커링돼 있어 앱 자신의 `광고 제거` 결제 행은 걸리지 않는다.

**한계** — 트리에 광고가 아예 안 나오는 경우(측정한 4개 화면 중 2개가 그랬다)는 막을 것도 없지만, **마커도 배지도 없이 트리에 노출되는 광고는 여전히 후보로 나온다.** 아래 "거부 목록이지 허용 목록이 아니다"가 여기에도 그대로 적용된다 — 탭 전에 스크린샷을 읽고, 광고처럼 보이면 후보에 있어도 누르지 않는다.

### 이 가드가 무엇을 보장하지 않는가 (상시 한계)

**분류는 거부 목록이지 허용 목록이 아니다.** `DESTRUCTIVE`/`STATE_CHANGING` 은 아는 단어를 막는다 — 모르는 단어는 `navigation` 으로 통과한다. 즉 **이름을 처음 보는 파괴적 컨트롤은 막히지 않는다.** 어휘는 한국어·영어뿐이고, 같은 뜻의 다른 표현·다른 언어·아이콘만 있는 버튼은 사각지대다. 실제로 이번 라운드에만 `충전`·`등록`·`임시저장`·`대화방 나가기`·`N피스`·`~으로 전환` 여섯 개가 뒤늦게 발견됐다 — 목록은 원리상 늘 미완성이다.

그래서:

- **사람이 없는 자동 실행에 쓰지 않는다.** 이 스킬은 화면을 읽는 에이전트가 루프를 도는 것을 전제한다. 눈 없는 `explore` 가 `source=label` 후보를 거부하는 이유가 이것이다.
- **남의 계정·결제 수단이 붙은 기기에서 무인으로 돌리지 않는다.** 누적 탭 상한(25)은 피해의 크기를 줄일 뿐 종류를 막지 못한다.
- **탭하기 전 스크린샷을 읽는 규칙은 장식이 아니라 이 한계를 메우는 유일한 장치다.** 기계적으로 강제되지 않으며, 강제하는 척하는 확인 플래그를 넣지 않는다 — 그건 규칙을 세탁할 뿐이다.

### 역할을 안 알려주는 앱 — role-blind 티어

커스텀 렌더러로 만든 앱은 화면 전체를 trait 없는 `XCUIElementTypeOther` 로 내보낸다. 그러면 역할 기반 후보 추출이 **위험해서가 아니라 메타데이터가 없어서** 0개를 내고, 탭바조차 후보에서 빠져 탐험이 첫 화면에서 멈춘다(실측: zeta 3.47.0 홈 — 요소 144개, 라벨 60개, 후보 0개).

그래서 `candidates` 는 **역할 후보와 라벨-리프 후보를 항상 함께** 낸다. 리프란 **자기 라벨을 소유한 최말단 요소**다. 조상 컨테이너는 자식들의 라벨을 이어 붙인 문자열을 갖기 때문에(예: `홈 대화 만들기 마이페이지`) 후보에서 빠진다 — 그 중심점은 사용자가 보는 컨트롤이 아니다. 화면을 덮는 배경 크기 리프도 제외된다.

**티어 판정은 화면 단위 all-or-nothing 이 아니다.** "역할 티어가 하나라도 찾았으면 성공"으로 두면 운 좋은 요소 하나가 나머지를 가린다 — 실측: 검색 화면은 `AXTextField` 를 딱 하나 보고하고, 그것 때문에 태그 칩 15개가 통째로 안 보여 화면이 막다른 길이 됐다. 39개 화면을 측정한 결과 병합은 역할이 잘 나오는 화면에서 **아무것도 늘리지 않고**(채팅방 +0), 나머지에서 진짜 컨트롤을 되찾는다(`더보기` 메뉴, 모델 카드 3장, 그 칩 15개).

`WARN: role-blind screen` 은 **역할이 하나도 없는 화면**에서만 나온다. 그 화면의 후보는 전부 라벨에서만 나왔다는 뜻이다.

파괴·상태변경 분류(`DESTRUCTIVE`/`STATE_CHANGING`)는 이 티어에서도 **그대로 라벨에 적용된다**. 구독·결제·삭제 라벨은 여전히 `WARN: withheld` 다.

**라벨에서 온 후보는 역할에서 온 후보보다 약하고, 그 차이를 LLM 이 메운다.** 라벨이 없는 컨트롤은 후보로 나오지도, 검사되지도 않는다.

어느 후보가 약한지는 화면 단위가 아니라 **후보 단위로** 표시된다 — `candidate-meta` 의 `source=` 를 본다:

```
INFO: candidate-meta 148 793 | ... | source=label | state_changing=false | withheld=false
INFO: candidate-meta 197 85  | ... | source=role  | ...
```

`source=role` 은 역할이 보증한 컨트롤이다. **`source=label` 은 그 요소의 말 말고는 아무것도 그것을 분류하지 않았다는 뜻이다.** 혼합 화면(역할을 보고하는 요소가 하나라도 있으면 `WARN: role-blind screen` 은 안 나온다)에서도 대부분이 `source=label` 일 수 있다 — 실측: 검색 화면은 역할 후보 1개, 라벨 후보 15개다.

`source=label` 후보를 누르기 전에는 매번:

1. **스크린샷을 읽는다.** 트리만 보고 탭하지 않는다 — 라벨 없는 결제·로그인 버튼은 픽셀에만 있다.
2. **화면 종류를 판단한다.** 로그인·회원가입·페이월·구독·결제·연령확인 화면이면 **탭하지 말고 STOP**, 사용자에게 넘긴다. 후보 목록이 비어 보이더라도 마찬가지다.
3. **후보 라벨이 정말 그 뜻인지 확인한다.** 라벨이 좌표와 어긋나거나(스크린샷의 그 위치에 다른 것이 보임), 라벨이 의미 불명(`view_12`, 빈 문자열에 가까운 기호)이면 그 후보는 건너뛴다.
4. **탐색 목적에 맞는 것만 고른다.** 탭바·상단 네비·리스트 항목·상세 진입이 목표다. 광고·프로모션 배너는 앱 밖으로 나가므로 건너뛴다 — `candidates` 가 마커로 잡아내지만 마커 없는 광고는 눈으로 걸러야 한다(위 "광고는 후보가 아니다").

판단 결과 탭할 것이 없으면 스와이프하거나 종료한다. `candidates` 목록 **밖**을 탭하는 것은 이 티어에서도 여전히 금지다 — 티어가 바뀐 것이지 규칙이 풀린 게 아니다.

## Workflow routing

Read the current step only. Complete reachable analysis and the brief within the authorized scope. Project paths resolve from the project root; runtime scripts are under `$CLAUDE_PLUGIN_ROOT/scripts/`.

| Step | Reference | Work |
|------|-----------|------|
| Initial setup only | [Setup](references/setup.md) | Appium, driver, signing prerequisites |
| 1 | [Store](references/store.md) | Bind the target and collect available App Store evidence |
| 2 | [Device](references/device.md) | Physical device/session gate; abort if never established |
| 3 | [Explore](references/explore.md) | Safe autonomous exploration and partial-evidence capture |
| 4 | [Analyze](references/analyze.md) | Reconstruct observed screen structure |
| 5 | [Brief](references/brief.md) | Product brief with provenance and unsupported gaps |
| 6 | [Handoff](references/handoff.md) | Review and plan/mvp handoff |
| Diagnostics/reporting | [Operations](references/operations.md) | Knobs, alternatives, artifact paths |

## 중지 vs 열화 (무엇이 스킬을 끝내나)

**중지(abort)** — 기기 경로가 **한 번도** 성립하지 않은 경우. 브리프를 만들지 않고 끝낸다:

- 실기기 미연결 / 여러 대 연결 / Appium·서명·UI 자동화 미비 → Step 2 게이트
- 게이트를 통과하기 전에 세션이 죽는 경우

**루프 중단, 그러나 브리프는 쓴다** — 게이트를 통과해 화면을 하나라도 캡처한 뒤라면, 세션이 죽는 것은 **정상적인 종료 사유**다. 실기기 탐험은 완주보다 중단이 흔하다:

- 어떤 명령이든 `ERROR:` (기기 이탈·잠김·세션 만료) → 그 자리에서 **루프만** 끝내고 Step 4 로 간다. 재시도 루프를 돌리지 않는다
- `ERROR: ... left the app for <bundle>` → 그 탭은 앱 밖으로 나갔고 기록되지 않았다. 대상 앱을 다시 포그라운드로 올리고 계속하거나, 예산이 얼마 안 남았으면 종료한다
- `ERROR: tap budget spent` → 정상 종료
- 어느 경우든 브리프 상단에 `> partial capture — <이유>` 를 적고, 커버리지는 `device_flow.py stats` 로 확인해 적는다

**열화(degrade, 계속 진행)** — 기기는 있는데 일부만 막힌 경우:

- 접근성 트리 실패 → 스크린샷 + 사람 주도 캡처로 계속 (Step 3 말미)
- 로그인/페이월 뒤 화면 접근 불가 → 도달한 화면까지로 브리프 작성, 브리프에 `> partial capture — <이유>` 표기
- 특정 화면 캡처 실패 → 나머지로 진행 (부분 성공은 성공)

`scripts/device_capture.sh`(devicectl 스크린샷)와 `scripts/device_idb.sh`(시뮬레이터 전용)는 **탭이 불가능하거나 실기기를 못 잡으므로** 자율 경로의 대안이 아니다. 전자는 사람 주도로 내려갔을 때의 스크린샷 보조, 후자는 대상이 .ipa 로 시뮬레이터에 설치 가능할 때만 쓴다.

## Preconditions

- **필수** — Appium + xcuitest 드라이버, `DEVELOPMENT_TEAM`, iPhone **1대** USB 연결 + 잠금 해제 + Developer Mode + Trust + **UI 자동화 ON**. 로컬 Appium 서버와 iOS 18+ RemoteXPC tunnel은 `device_wda.sh session`이 필요할 때 자동 준비하며, tunnel 전에는 지정된 Xcode 프로젝트가 있으면 먼저 연다. 관리자 인증이 취소되거나 다른 필수 조건이 미충족이면 스킬을 중지한다.
- **권장** — `mcp-appstore` MCP 도구(`mcp__mcp-appstore__*`). 없으면 Step 1 을 건너뛰고 기기 캡처만으로 브리프를 만들되, Hook & Retention 근거가 약해진다고 밝힌다.
