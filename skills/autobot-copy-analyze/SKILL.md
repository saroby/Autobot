---
name: autobot-copy-analyze
user-invocable: false
description: Use when analyzing an existing iOS app on a physically connected iPhone to reconstruct a build-ready product brief for an original re-implementation. Autonomously explores the target app via Appium/WebDriverAgent (accessibility tree → tap/swipe → screenshot, destructive controls withheld), complements it with App Store metadata/reviews via the mcp-appstore MCP, and synthesizes `.autobot/copy-analysis/brief.md` mapped to the architect's architecture.md sections so `/autobot:plan` or `/autobot:mvp` can build an original app from it. Requires a connected device — aborts without one. Triggers on "이 앱 분석해서 비슷하게 만들어줘", "실기기 앱 분석", "앱 복제 분석", "/autobot:copy".
---

# Autobot Clone-Analyze — 실기기/스토어에서 제품 브리프 재구성

기존 앱을 **실기기(Appium/WebDriverAgent) + App Store 메타데이터**로 분석해, Autobot 파이프라인이 **원본(original) 앱을 새로 빌드**할 수 있는 제품 브리프를 만든다. 산출물은 architect 에이전트의 `architecture.md` 섹션 구조에 1:1 대응하는 `.autobot/copy-analysis/brief.md` 이며, 사용자가 `/autobot:plan` 또는 `/autobot:mvp` 에 넘기면 진짜 architect 가 gate-valid 산출물을 만든다.

**실기기가 없으면 이 스킬은 시작하지 않는다.** 탐험은 에이전트가 주도한다 (Step 2 게이트 참조).

## 재구성의 핵심 자산: 접근성 트리

WebDriverAgent 의 `GET /source` 는 포그라운드 앱의 **접근성 트리를 XML 로 덤프**한다 — 각 요소의 type(`XCUIElementTypeButton`/`…StaticText`/…), label/name, 정확한 x·y·width·height, enabled, **visible**. 스크린샷 비전보다 훨씬 정확한 구조 소스다(요소 타입·계층·레이블이 텍스트로 나옴). **이 트리가 화면 재구성의 1급 입력**이고, 스크린샷은 시각적 보완, App Store 메타는 backbone 이다.

트리 해석은 드라이버와 분리돼 있다 — `scripts/device_a11y.py` 가 WDA XML 과 idb JSON 을 자동 판별해 같은 형태로 정규화하고, 탭 후보·파괴적 필터·화면 서명을 **한 곳에서** 계산한다.

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

## 데이터 소스

| 소스 | 획득 방법 | 필수? |
|------|----------|-------|
| 실기기 화면 + 구조 | `scripts/device_wda.sh screen` → WDA `GET /screenshot` + `GET /source` | **필수** — 없으면 중지 |
| 공개 메타데이터 | `mcp-appstore` MCP — 설명·스크린샷·리뷰·유사앱·키워드 | 보완(backbone). 기기의 대체재는 아님 |
| 사용자 제공 스크린샷 | 사용자가 캡처해 전달 | 접근성 차단·잠긴 화면 보완용 |

## Setup (Appium + WebDriverAgent, 최초 1회)

> **왜 idb 가 아닌가** — fb-idb 의 UI 명령은 **시뮬레이터 전용**이다. 실기기에서 `ui describe-all` 은 `Target doesn't conform to FBAccessibilityCommands protocol`, `ui tap` 은 `...FBSimulatorLifecycleCommands protocol` 로 거부되고 `idb screenshot` 도 iOS 26 기기에서 실패한다(companion 을 새로 붙여도 동일). 실기기를 실제로 조작하는 유일한 경로가 WebDriverAgent(XCUITest)다. `device_idb.sh` 는 시뮬레이터 전용으로 남아 있다.

```bash
npm i -g appium && appium driver install xcuitest
export DEVELOPMENT_TEAM=<10자리 팀 ID>   # WDA 서명용 (없으면 session 이 거부)
```

`session` 이 필요할 때 로컬 Appium 서버와 iOS 18+ RemoteXPC 터널을 **자동으로 띄운다** — 직접 실행할 필요는 없다. 이미 돌고 있는 서버를 쓰려면 `APPIUM_URL` 로 가리킨다.

기기 쪽 준비 — **셋 다 필수**:

1. **개발자 모드** — 설정 > 개인정보 보호 및 보안 > 개발자 모드 ON
2. **이 Mac 신뢰** — USB 연결 후 "이 컴퓨터를 신뢰하시겠습니까?" 승인
3. **UI 자동화** — 설정 > 개발자 > **UI 자동화(Enable UI Automation) ON**. 이게 꺼져 있으면 WDA 가 설치·실행까지 성공하고도 `Timed out while enabling automation mode` 로 죽는다(xcodebuild code 65 로 보임).

첫 세션은 WDA 를 빌드·서명·설치하느라 수 분 걸린다. 이후 세션은 재부착이라 빠르다. 자동 잠금은 꺼두는 편이 안전하다(설정 > 디스플레이 및 밝기 > 자동 잠금 > 안 함).

## Workflow

### Step 1 — 대상 확정 + App Store 메타 수집

`mcp-appstore` 도구로 먼저 공개 정보를 확보한다 (사용자가 기기를 준비하는 동안 병렬로 진행 가능하지만, Step 2 게이트를 통과하지 못하면 이 결과물만으로 브리프를 만들지 않는다):

1. `search_app` 로 앱 검색 → 대상 확정 (사용자에게 후보 확인)
2. `get_app_details` — 이름·카테고리·설명·subtitle·평점·스크린샷 URL
3. `fetch_reviews` + `analyze_reviews` — 유저가 사랑하는 것/불만 → **훅·리텐션 근거**
   - ⚠️ **조용한 실패를 반드시 확인한다.** 이 도구는 리뷰가 없어도 에러가 아니라 **빈 분석 객체**(`totalReviewsAnalyzed: 0`)를 돌려준다. 실측: 리뷰 30,562개인 앱이 us·kr 모두 0건으로 왔다(1st-party 앱은 RSS 리뷰 미노출).
   - `totalReviewsAnalyzed == 0` 이면 → 다른 country 로 1회 재시도 → 그래도 0이면 **리뷰 근거는 없는 것으로 확정**하고, 브리프 상단에 `> review-signal unavailable` 을 적는다. Hook & Retention 은 **기기 트리에서 관찰한 리텐션 장치**(연속 기록·통계·알림·위젯 등)와 스토어 설명으로 도출한다. 없는 근거를 있는 것처럼 쓰지 않는다.
4. `get_similar_apps` — Market Context 표의 근거 앱들
   - ⚠️ **카테고리 기반이라 자주 무관하다.** 실측: 일기 앱에 MyFitnessPal·Fitbod·요가 앱이 반환됐다(App Store 카테고리가 '건강 및 피트니스'라서).
   - 반환된 앱의 설명을 대상 앱의 **핵심 기능 명사**(예: 일기·기록·회고)와 대조해 무관한 것을 버린다. 3개 미만 남으면 `search_app` 으로 그 명사를 직접 검색해 경쟁군을 만들고, Market Context 표에 **근거를 어떻게 얻었는지** 한 줄로 밝힌다.
5. `analyze_top_keywords` / `get_keyword_scores` — 카테고리 table-stakes 신호

App Store 스크린샷 URL 은 `WebFetch`/curl 로 `.autobot/copy-analysis/store/` 에 저장한다.

**리뷰 인사이트를 파일로 남긴다** — `.autobot/copy-analysis/reviews.md`. 브리프의 Hook & Retention 은 여기서 근거를 끌어오고, 사람이 검토할 때도 원문 인용이 필요하다. 최소 구성:

- 수집 방법과 표본 수 (country·정렬·페이지), 평점 분포
- **평점 신뢰도 경고** — 이 카테고리는 "5점 줘야 눈에 띈다"며 불만을 5★로 다는 관행이 있다. 실측되면 명시한다
- 불만 — 빈도순, 각 항목에 유저 원문 인용
- 사랑받는 것 — hook 근거
- 재구현이 가져갈 차별점 표 (관찰된 문제 → 원본 앱이 취할 입장)

### Step 2 — 기기 게이트 + 세션 (HARD — 통과 못 하면 여기서 종료)

```bash
# stdout = udid 한 줄, 진단은 stderr — 그래서 명령 치환으로 그대로 받는다
udid="$(CLONE_STATE_DIR=.autobot/copy-analysis scripts/device_wda.sh device)"

# bundle ID 는 추측하지 않는다 — 같은 UDID 에서 확인한다.
# --include-all-apps 를 빼면 developer 앱만 나와 App Store 로 설치된 대상 앱이
# "미설치" 로 보인다. 포그라운드 앱이나 과거에 알던 ID 로 대신하지 않는다.
xcrun devicectl device info apps --device "$udid" --include-all-apps --search '<앱 이름>'
bundle_id="<위 출력의 정확한 Bundle Identifier>"

CLONE_STATE_DIR=.autobot/copy-analysis \
  scripts/device_wda.sh doctor "$udid" "$bundle_id"    # Appium·서명·기기·앱·tunnel 일괄 점검
# stdout = session id 한 줄
sid="$(CLONE_STATE_DIR=.autobot/copy-analysis scripts/device_wda.sh session "$udid" "$bundle_id")"
```

**`CLONE_STATE_DIR=.autobot/copy-analysis` 를 모든 `device_wda.sh` 호출에 붙인다.** 드라이버의 기본 상태 폴더는 `.autobot/clone/` 이고, 그건 `/autobot:clone` 의 작업 공간이다 — 탐험 로그(`flow.jsonl`)·기기 프로필·세션 기술자·Appium 서버 상태가 전부 거기 모인다. 기본값을 그대로 쓰면 두 스킬이 **한 로그를 공유하고, 그러면 누적 탭 예산도 공유한다** — 직전 clone 이 20탭을 썼으면 이 실행은 5탭에서 `tap budget spent` 를 만난다. 한 변수를 옮기면 로그·`broken-<해시>` 센티넬·세션 상태가 **함께** 따라오므로, 정리도 이 폴더 안에서 끝난다.

**`export` 로 대신하지 않는다.** 각 명령은 자기 셸에서 실행되고 셸 상태는 명령 간에 남지 않는다. 한 줄에서 빠뜨리면 그 명령만 `.autobot/clone/` 을 보고, 그 순간 예산·커버리지가 두 파일로 갈린다 — **접두사가 없어도 명령은 성공하므로 이 실수는 조용하다.** 로그를 읽는 `device_flow.py` 는 경로를 인자로 받으므로 접두사가 필요 없다.

`doctor` 는 선택이 아니라 **진단을 앞당기는 단계**다 — 서명·드라이버·tunnel 문제를 `session` 이 수 분을 쓴 뒤가 아니라 지금 알려준다.

`device` → (bundle ID 확인) → `session` 이 연속된 하드 게이트다. 하나라도 실패하면 **스킬을 중지한다.** 스토어 메타만으로 대신 진행하지 않는다.

| 실패 | 의미 | 안내 |
|------|------|------|
| `ERROR: no connected iPhone` | 전송 계층 없음(`paired` 는 신뢰 기록일 뿐 연결이 아님) | USB 재연결 + 잠금 해제 + 신뢰. **Xcode 에는 보이는데 여기서 안 보이면** Xcode > Window > Devices and Simulators 를 한 번 열어 CoreDevice 터널을 되살린다 |
| `ERROR: N connected devices match` | 대상 모호 | 사용자에게 물어보고 `device <udid\|name>` 로 재실행 |
| `Timed out while enabling automation mode` | UI 자동화 토글 꺼짐 | 설정 > 개발자 > UI 자동화 ON 후 재시도 |
| `xcodebuild failed with code 65` | WDA 서명·빌드 실패 | `DEVELOPMENT_TEAM` 확인, 기기 잠금 해제 상태로 재시도 |
| `Appium unreachable` | 서버 미기동 | `appium server --port 4723` |

세션이 열렸다는 것은 **그 시점에** 기기가 잠금 해제된 채 조작 가능하고 Appium 세션이 대상 bundle ID에 묶였다는 뜻이다 — idb 시절의 "첫 캡처" 2차 게이트를 대체한다. 다만 이후에도 계속 그렇다는 보장은 아니다: 루프 도중 어떤 명령이든 `ERROR:` 를 내면(기기 이탈·잠김·세션 만료·다른 앱 전환) 그 자리에서 중단한다(Step 3 STOP 표).

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

### Step 4 — 구조 분석

수집한 **접근성 트리(`.xml`)를 1급 소스로, 스크린샷을 보완으로** 읽어 분석:

- **Screens**: 각 화면의 목적·Tab·주요 UI 요소 (a11y 트리의 type/label 로 정확히). architecture.md `## Screens` 표 형식
- **Navigation**: TabView / NavigationStack / Split — 트리의 탭바·네비바 요소로 판별
- **Features**: P0/P1 + role(`table-stakes`/`hook`/`retention`/`insight`). 리뷰에서 사랑받는 기능 = hook 후보, 불만 = 개선 차별점
- **Design Direction**: personality, color palette(스크린샷에서 추출한 *방향* — 정확한 hex 복제 아님), typography 느낌, layout personality, signature layout
- **Hook & Retention**: 리뷰·기능에서 도출. 제네릭 금지 — 이 앱만 식별되는 구체 문장

### Step 5 — 브리프 합성

`.autobot/copy-analysis/brief.md` 를 architect 의 `architecture.md` 섹션 순서로 작성한다 (참조: `skills/autobot-orchestrator/references/architecture-template.md`). 최소 포함 섹션:

- `## Overview` (원본 재구현 대상의 *가치*, 이름/상표 제외)
- `## Market Context` (유사앱 근거 표)
- `## Features` (P0/P1 + role)
- `### Hook & Retention` (구체·비제네릭)
- `## Screens`
- `## Navigation Structure`
- `## Design Direction` (color/typography/layout/**signature layout**)

브리프는 architect 의 *입력*이지 최종 산출이 아니다 — gate 계약(build-state, feature-spec, Models/*.swift)을 위조하지 않는다. architect 가 이 브리프를 받아 정식 파이프라인으로 완성한다.

### Step 6 — 검토 + 핸드오프

1. **화면 흐름도를 만든다.** 탐험 로그가 이미 모든 전이를 갖고 있다 — 쓰지 않으면 버리는 것이다.
   ```bash
   scripts/device_flow.py map .autobot/copy-analysis/flow.jsonl .autobot/copy-analysis/flow-map.html
   scripts/device_flow.py stats .autobot/copy-analysis/flow.jsonl     # 커버리지 한 줄
   ```
   이미지 경로는 출력 파일 기준 상대경로라, **산출물 폴더 안에 직접 생성해야** `device/00-home.png` 로 붙어 폴더째 옮겨도 안 깨진다.

   맵이 보여주는 것: 화면 카드마다 스크린샷이 붙고, **어디를 눌렀는지가 그 스크린샷 위에 점으로 찍히며** 거기서 목적지 화면으로 선이 나간다. 미탐 후보도 같은 방식으로 **눌리지 않은 그 자리에** 점선 점으로 찍힌다 — 빈틈이 몇 개인지가 아니라 **어디인지**가 보인다.

2. **기기 쪽을 정리한다.** `quit` 은 WDA 세션만 닫는다 — `session` 이 자동으로 띄운 Appium 서버는 launchd 가 소유해 셸이 끝난 뒤에도 계속 돈다. 둘 다 내린다:
   ```bash
   CLONE_STATE_DIR=.autobot/copy-analysis scripts/device_wda.sh quit "$sid"
   CLONE_STATE_DIR=.autobot/copy-analysis scripts/device_wda.sh stop-server
   ```
   `stop-server` 는 **이 상태 폴더가 기록한 서버만** 내린다 — 남이 띄운 서버는 거부하므로 `/autobot:clone` 의 서버를 실수로 죽이지 않는다. `INFO: no Appium server managed by device_wda.sh` 는 정상이다: 이미 돌던 서버를 빌려 썼다는 뜻이고, 그건 우리가 내릴 것이 아니다.
3. 수집 이미지·트리·브리프·흐름도를 사용자가 보게 연다 (`open .autobot/copy-analysis/`).
4. 다음 안내:
   ```
   브리프 준비 완료 → 원본 앱을 빌드하려면:
     /autobot:plan  (기획·디자인 검토 후 진행)  또는
     /autobot:mvp   (질문 없이 바로 빌드)
   에 .autobot/copy-analysis/brief.md 내용을 아이디어로 넘기세요.
   ```

## 이 스킬이 쓰지 않는 명령, 그리고 노브

드라이버에는 이 워크플로가 부르지 않는 명령이 더 있다. **왜 안 쓰는지**를 알아야 잘못 손이 가지 않는다.

| 명령 | 무엇인가 | 이 스킬에서 |
|------|---------|------------|
| `device_wda.sh explore` | 눈 없이 프론티어를 기계적으로 소진하는 루프 | **쓰지 않는다.** 스크린샷을 못 읽으므로 `source=label` 후보를 거부한다 — 커스텀 렌더러 앱에서는 한 발도 못 뗀다. 이 스킬의 루프는 LLM 이 판단하는 `capture → candidates → 판단 → tap` 이다 |
| `device_wda.sh step` | 탭 + 도착 화면 증거를 한 번에 남긴다 | `tap` 후 `screen` 과 같다. 어느 쪽이든 무방하되, 쓴다면 `CLONE_STATE_DIR=` 접두사를 똑같이 붙인다 |
| `device_wda.sh back` | leading nav 슬롯만 누른다 | **쓴다.** 상세 화면에서 나오는 유일한 길이다 (Step 3 참조) |
| `device_wda.sh stop-server` | 이 스크립트가 띄운 Appium 서버를 종료 | Step 6 마무리에서 쓴다. `quit` 은 세션만 닫는다 |
| `device_flow.py audit` | 탐험이 남긴 변경을 사후 감사 | 브리프 작성 전에 한 번 돌려 무엇을 건드렸는지 확인하면 좋다 |

| 환경변수 | 기본 | 무엇을 바꾸나 |
|---------|------|-------------|
| `CLONE_TAP_BUDGET` | 25 | **누적** 탭 상한. `tap` 이 이 수를 넘으면 거부한다 — 실행 단위가 아니라 로그 전체 기준이다 |
| `CLONE_TAP_UNVOUCHED` | (없음) | `1` 이면 기계적 루프가 `source=label` 후보도 탭한다. **이 스킬에서는 켜지 않는다** — 눈으로 확인하는 책임을 없애는 스위치다 |
| `CLONE_PROBE_SWITCHES` | (없음) | `1` 이면 스위치를 켜봤다 되돌린다. 사용자 계정 설정을 건드리므로 **켜지 않는다** |
| `CLONE_STATE_DIR` | `.autobot/clone` | 탐험 로그·`broken-<해시>` 센티넬·기기 프로필·세션 기술자·Appium 서버 상태가 모두 여기 모인다. **이 스킬은 모든 호출에서 `.autobot/copy-analysis` 로 바꿔** clone 과 예산·커버리지를 섞지 않는다 (Step 2) |
| `CLONE_FLOW_LOG` | `$CLONE_STATE_DIR/flow.jsonl` | 로그만 따로 옮긴다. **쓰지 않는다** — 센티넬은 `CLONE_STATE_DIR` 에 남으므로 로그만 옮기면 상태가 두 폴더로 갈린다. 격리는 `CLONE_STATE_DIR` 하나로 한다 |
| `CLONE_SCREEN_SETTLE_TRIES` | 12 | `screen` 이 화면이 멈출 때까지 트리를 다시 읽는 횟수. 느린 네트워크 화면에서 올린다 |
| `CLONE_SCREEN_SETTLE` | 1 | `0` 이면 settle 대기 없이 즉시 캡처한다. **끄지 않는다** — 로딩 중 화면을 "빈 화면"으로 기록하게 된다 |

## Output Artifacts

| 산출물 | 경로 | 소비자 |
|-------|------|--------|
| 제품 브리프 | `.autobot/copy-analysis/brief.md` | 사용자 → `/autobot:plan`·`/autobot:mvp` (architect) |
| **화면 흐름도** | `.autobot/copy-analysis/flow-map.html` | 사용자 — 무엇을 눌러 어디로 갔는지, 무엇이 미탐인지 |
| 탐험 로그 | `.autobot/copy-analysis/flow.jsonl` | `device_flow.py` (흐름도·커버리지·재개). `CLONE_STATE_DIR` 로 clone 의 로그와 분리했다 |
| 접근성 트리 | `.autobot/copy-analysis/device/*.xml` | Step 4 구조 분석 (1급 소스) |
| 실기기 캡처 | `.autobot/copy-analysis/device/*.png` | 시각 보완 + 흐름도 카드 |
| 스토어 스크린샷 | `.autobot/copy-analysis/store/*.png` | 구조 분석 |
| 리뷰 인사이트 | `.autobot/copy-analysis/reviews.md` | 브리프 Hook & Retention 근거 |

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
