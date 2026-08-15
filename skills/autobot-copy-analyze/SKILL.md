---
name: autobot-copy-analyze
user-invocable: false
description: Use when analyzing an existing iOS app on a physically connected iPhone to reconstruct a build-ready product brief for an original re-implementation. Autonomously explores the target app via Appium/WebDriverAgent (accessibility tree → tap/swipe → screenshot, destructive controls withheld), complements it with App Store metadata/reviews via the mcp-appstore MCP, and synthesizes `.autobot/copy-analysis/brief.md` mapped to the architect's architecture.md sections so `/autobot:plan` or `/autobot:mvp` can build an original app from it. Requires a connected device — aborts without one. Triggers on "이 앱 분석해서 비슷하게 만들어줘", "실기기 앱 분석", "앱 복제 분석", "/autobot:copy".
---

# Autobot Clone-Analyze — 실기기/스토어에서 제품 브리프 재구성

기존 앱을 **실기기(Appium/WebDriverAgent) + App Store 메타데이터**로 분석해, Autobot 파이프라인이 **원본(original) 앱을 새로 빌드**할 수 있는 제품 브리프를 만든다. 산출물은 architect 에이전트의 `architecture.md` 섹션 구조에 1:1 대응하는 `.autobot/copy-analysis/brief.md` 이며, 사용자가 `/autobot:plan` 또는 `/autobot:mvp` 에 넘기면 진짜 architect 가 gate-valid 산출물을 만든다.

**실기기가 없으면 이 스킬은 시작하지 않는다.** 탐험은 에이전트가 주도한다 (Step 2 게이트 참조).

## 무엇을 하고 무엇을 하지 않는가 (법적/윤리 경계)

이 스킬은 **기능·구조·디자인 방향을 이해해 새로 만들기 위한 경쟁 분석**이다. 정상 범주:

- ✅ 화면 구성·네비게이션·기능 목록·정보 위계·색/타이포 *방향* 재구성
- ✅ App Store 설명·리뷰에서 유저가 원하는 것/불만 추출 → 차별화 훅 도출

선 밖 — **하지 않는다**:

- ❌ 대상 앱의 **이름·로고·상표·스크린샷·아이콘·문구를 그대로 복사**. 브리프에는 대상 앱 이름을 식별자로 넣지 않는다("reference app" 으로만 지칭).
- ❌ 소스/에셋 추출·바이너리 복호화·비공개 API 트래픽 가로채기.
- ❌ 픽셀 단위 클론. 재구성은 *방향*이지 *복제물*이 아니다.

브리프 상단에 이 경계를 한 줄로 명시한다: `> 원본 재구현용 분석 — 대상 앱의 이름/에셋/상표는 복제하지 않는다.`

## 재구성의 핵심 자산: 접근성 트리

WebDriverAgent 의 `GET /source` 는 포그라운드 앱의 **접근성 트리를 XML 로 덤프**한다 — 각 요소의 type(`XCUIElementTypeButton`/`…StaticText`/…), label/name, 정확한 x·y·width·height, enabled, **visible**. 스크린샷 비전보다 훨씬 정확한 구조 소스다(요소 타입·계층·레이블이 텍스트로 나옴). **이 트리가 화면 재구성의 1급 입력**이고, 스크린샷은 시각적 보완, App Store 메타는 backbone 이다.

트리 해석은 드라이버와 분리돼 있다 — `scripts/device_a11y.py` 가 WDA XML 과 idb JSON 을 자동 판별해 같은 형태로 정규화하고, 탭 후보·파괴적 필터·화면 서명을 **한 곳에서** 계산한다.

## 누가 조작하나 — 에이전트 주도가 기본

에이전트가 `capture → candidates → tap/swipe` 루프를 스스로 돌려 앱을 탐험한다. 사용자는 대상 앱을 포그라운드로 열어두고 기기를 잠금 해제해두는 것까지만 한다.

블라인드 탐색의 위험(로그인·결제·삭제)은 **탭 후보를 만드는 지점에서** 막는다: `device_wda.sh candidates <tree.xml>` 가 접근성 트리를 읽어 탭 가능한 요소만 `INFO: tap <x> <y>` 로 내보내고, 파괴적 라벨(삭제·구매·구독·로그아웃·탈퇴·결제 / delete·purchase·subscribe·sign out…)은 `WARN: withheld` 로 **후보에서 제외**한다. 에이전트는 이 목록 밖을 탭하지 않는다 — 좌표를 직접 지어내지 말 것.

사람에게 넘기는 순간(아래 STOP 조건)에만 "이 화면을 열어주세요"를 요청한다.

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
appium server --port 4723 &          # 다른 포트면 APPIUM_URL 로 지정
export DEVELOPMENT_TEAM=<10자리 팀 ID>   # WDA 서명용 (없으면 session 이 거부)
```

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

### Step 2 — 기기 게이트 + 세션 (HARD — 통과 못 하면 여기서 종료)

```bash
udid="$(scripts/device_wda.sh device)"    # stdout = udid 한 줄, 진단은 stderr
bundle_id="<target app bundle id>"        # 설치된 대상 앱과 먼저 대조한다
sid="$(scripts/device_wda.sh session "$udid" "$bundle_id")"   # stdout = session id 한 줄
```

두 개가 연속된 하드 게이트다. 하나라도 실패하면 **스킬을 중지한다.** 스토어 메타만으로 대신 진행하지 않는다.

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
# (a) 현재 화면 덤프 — 스크린샷 + 접근성 트리 + 화면 서명
scripts/device_wda.sh screen "$sid" .autobot/copy-analysis/device <NN>-<screen>
#   → <NN>-<screen>.png, <NN>-<screen>.xml, INFO: sig <hash>
# (b) 안전한 탭 후보만 추출
scripts/device_wda.sh candidates .autobot/copy-analysis/device/<NN>-<screen>.xml
# (c) 후보 중 하나로 이동 — 좌표가 나온 트리를 반드시 함께 넘긴다.
#     tap 이 (1) 그 트리의 후보인지 (2) 지금 화면이 아직 그 트리인지 검사하고,
#     아니면 거부한다. 목록 밖 좌표·낡은 좌표는 애초에 실행되지 않는다.
scripts/device_wda.sh tap "$sid" <x> <y> .autobot/copy-analysis/device/<NN>-<screen>.xml
scripts/device_wda.sh swipe "$sid" <x1> <y1> <x2> <y2>   # 스크롤·뒤로가기(좌측 엣지 → 우측)
# (d) 끝나면
scripts/device_wda.sh quit "$sid"
```

**탐색 순서** — 탭바 항목을 먼저 한 바퀴(앱의 최상위 구조), 그다음 각 탭의 첫 리스트 항목(상세 화면), 생성/추가(+) 버튼, 마지막에 설정. 각 화면 이름은 `<NN>-<tab>-<purpose>` 로 짓는다.

**사용자 데이터를 만들지 않는다** — 대상은 사용자의 실제 앱이다. 항목 생성·전송·공유처럼 데이터를 남기는 동작은 화면 구조 확인이 끝나면 저장하지 말고 빠져나온다. 파괴적 라벨은 애초에 후보에서 빠진다.

**STOP 조건 — 하나라도 걸리면 루프를 끝내고 사용자에게 넘긴다:**

| 조건 | 신호 | 행동 |
|------|------|------|
| 탭 예산 소진 | 누적 탭 25회 | 정상 종료 → Step 4 |
| 새 화면 고갈 | 직전 3회 연속 `sig` 가 이미 본 값 | 정상 종료 → Step 4 |
| 시스템/파괴 다이얼로그 | `WARN: alert/sheet on screen` (후보 0개로 강제) | **즉시 중단**, 사용자에게 처리 요청 |
| 기기 이탈·잠김 | 어떤 명령이든 `ERROR:` | **즉시 중단**, 재시도 루프 금지 |
| 예상과 다른 화면 | `ERROR: screen changed since <tree>` | 낡은 좌표로 이어 치지 말고 **다시 `screen` 부터**. 앱 밖으로 나갔으면 사용자에게 복귀 요청 |
| 로그인·페이월 도달 | 화면에 로그인/구독 입력 요소 | 중단하고 사용자에게 통과 요청 후 재개 |
| 후보 0개 | `OK: 0 tappable` | 스와이프 1회 시도, 그래도 0이면 종료 |

`sig` 는 화면 서명(접근성 라벨 집합 해시)이다. `screen` 이 자동으로 출력하며(`scripts/device_wda.sh sig <tree.xml>` 로 재계산도 가능), 본 값을 집합으로 들고 다니며 중복 화면은 다시 캡처하지 않는다. 모달을 만나면 `candidates` 가 후보를 **0개로 강제**하므로 "허용/Allow" 같은 시스템 버튼을 실수로 탭할 수 없다. 반대로 평범한 `취소`/`Cancel`(시트 닫기)은 탈출 경로라 후보에 남는다 — 후보에 있으면 눌러서 빠져나온다.

접근성 트리를 못 받으면(`WARN: ... 접근성 트리 실패`) 스크린샷만 남는다. **이때만 사람 주도로 내려간다**: 사용자에게 핵심 화면을 순서대로 열어달라 요청하고 `scripts/device_wda.sh screen`(트리 없이 PNG 만 남는다) 또는 세션이 죽었으면 `scripts/device_capture.sh shot <udid> <out.png>`(devicectl, 트리 없음) 을 반복한다. 트리가 실패한 상태에서 같은 명령이 저절로 낫기를 기대하고 재시도하지 않는다.

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

1. 수집 이미지·트리·브리프를 사용자가 보게 연다 (`open .autobot/copy-analysis/`).
2. 다음 안내:
   ```
   브리프 준비 완료 → 원본 앱을 빌드하려면:
     /autobot:plan  (기획·디자인 검토 후 진행)  또는
     /autobot:mvp   (질문 없이 바로 빌드)
   에 .autobot/copy-analysis/brief.md 내용을 아이디어로 넘기세요.
   ```

## Output Artifacts

| 산출물 | 경로 | 소비자 |
|-------|------|--------|
| 제품 브리프 | `.autobot/copy-analysis/brief.md` | 사용자 → `/autobot:plan`·`/autobot:mvp` (architect) |
| 접근성 트리 | `.autobot/copy-analysis/device/*.xml` | Step 4 구조 분석 (1급 소스) |
| 실기기 캡처 | `.autobot/copy-analysis/device/*.png` | 시각 보완 |
| 스토어 스크린샷 | `.autobot/copy-analysis/store/*.png` | 구조 분석 |
| 리뷰 인사이트 | `.autobot/copy-analysis/reviews.md` | 브리프 Hook & Retention 근거 |

## 중지 vs 열화 (무엇이 스킬을 끝내나)

**중지(abort)** — 기기 경로가 성립하지 않는 경우. 브리프를 만들지 않고 끝낸다:

- 실기기 미연결 / 여러 대 연결 / Appium·서명·UI 자동화 미비 → Step 2 게이트
- 세션 중 기기가 빠지거나 잠겨 명령이 `ERROR:` 를 내는 경우

**열화(degrade, 계속 진행)** — 기기는 있는데 일부만 막힌 경우:

- 접근성 트리 실패 → 스크린샷 + 사람 주도 캡처로 계속 (Step 3 말미)
- 로그인/페이월 뒤 화면 접근 불가 → 도달한 화면까지로 브리프 작성, 브리프에 `> partial capture — <이유>` 표기
- 특정 화면 캡처 실패 → 나머지로 진행 (부분 성공은 성공)

`scripts/device_capture.sh`(devicectl 스크린샷)와 `scripts/device_idb.sh`(시뮬레이터 전용)는 **탭이 불가능하거나 실기기를 못 잡으므로** 자율 경로의 대안이 아니다. 전자는 사람 주도로 내려갔을 때의 스크린샷 보조, 후자는 대상이 .ipa 로 시뮬레이터에 설치 가능할 때만 쓴다.

## Preconditions

- **필수** — Appium + xcuitest 드라이버, 기동 중인 Appium 서버, `DEVELOPMENT_TEAM`, iPhone **1대** USB 연결 + 잠금 해제 + Developer Mode + Trust + **UI 자동화 ON**. 미충족 시 스킬 중지.
- **권장** — `mcp-appstore` MCP 도구(`mcp__mcp-appstore__*`). 없으면 Step 1 을 건너뛰고 기기 캡처만으로 브리프를 만들되, Hook & Retention 근거가 약해진다고 밝힌다.
