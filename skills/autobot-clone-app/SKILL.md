---
name: autobot-clone-app
user-invocable: false
description: Use when reproducing an existing iOS app's screens so they look and behave the same — same layout, spacing, colors, typography, navigation and per-screen behavior — as a buildable SwiftUI project. Not a pixel-diff exercise — the bar is "side by side it reads as the same screen, and the same taps do the same things". Drives a connected iPhone via Appium/WebDriverAgent (`scripts/device_wda.sh`), measures every element's exact frame from the accessibility tree, samples real colors from the screenshot pixels, and emits per-screen specs plus SwiftUI code under `.autobot/clone/`. Requires a connected device — aborts without one. Unlike `autobot-copy-analyze` (which extracts *direction* for an original app), this reproduces the screens themselves. Triggers on "이 앱 그대로 복제해줘", "화면 똑같이 만들어줘", "앱 클론", "/autobot:clone".
---

# Autobot Clone — 화면을 있는 그대로 재현

대상 앱의 화면을 **같아 보이고 같이 움직이게** 재현한다. `autobot-copy-analyze`(`/autobot:copy`)가 "왜 이 앱이 다시 열리는가"를 뽑아 *새 원본 앱*의 기획을 만든다면, 이 스킬은 **화면 그 자체**를 SwiftUI 로 재현한다.

| | `/autobot:copy` | `/autobot:clone` (이 스킬) |
|---|---|---|
| 산출물 | 제품 브리프(기획 입력) | 화면 스펙 + 동작 계약 + SwiftUI 코드 |
| 충실도 | 방향(personality·팔레트 느낌) | **레이아웃 · 룩앤필 · 기능** |
| 목적 | 다른 앱을 새로 만든다 | 같은 화면을 다시 만든다 |
| 공유 | 둘 다 `scripts/device_wda.sh` 로 기기를 몬다 | |

**픽셀 단위 동일이 목표가 아니다.** 나란히 놓고 "같은 화면이다" 싶으면 되고, 같은 조작에 같은 반응을 하면 된다. 그렇다고 눈대중으로 쓰라는 뜻은 아니다 — 좌표·색·글자 크기를 **측정해서** 쓰는 게 그 룩앤필에 도달하는 가장 싼 길이다(눈대중은 카드 간격 16pt 를 20pt 로, FAB 의 파란 fill 을 회색으로 만든다. 둘 다 실측 사고다). 측정으로 알 수 없는 값(모서리 반경, 그라디언트 방향)은 **근사하고 스펙에 근사임을 표시**한다.

## 무엇이 가능하고 무엇이 불가능한가 (먼저 읽을 것)

**불가능 — 정책이 아니라 기술적 사실**: 기기에서 대상 앱의 **바이너리 에셋(아이콘·이미지·폰트 파일)을 추출할 수 없다.** 앱 샌드박스는 탈옥 없이 열리지 않는다. 그러므로 이 스킬의 재현은 전부 **스크린샷 픽셀 + 접근성 트리**에서 나온다. "에셋을 그대로 가져온다"고 약속하지 않는다 — 이미지는 자리표시자(placeholder)로 두고 사용자가 채우거나, SF Symbols·그라디언트로 근사한다.

**가능** — 좌표·크기·계층·색·글자 크기·굵기·정렬·네비게이션 구조·인터랙션. 이것만으로도 화면은 대부분 같아 보인다.

### Step 0 — 소유 확인 (건너뛰지 않는다)

첫 질문으로 **대상 앱이 사용자 본인 것인지** 확인하고, 답에 따라 재현 범위를 바꾼다.

| | 본인 앱 (또는 소유 조직의 앱) | 타사 앱 |
|---|---|---|
| 레이아웃·간격·색·타이포·네비게이션·인터랙션 | 재현 | 재현 |
| 앱 이름·로고·아이콘 | 그대로 사용 | **사용 금지** — 자리표시자로 두고 사용자가 정한다 |
| 화면 내 문구·마케팅 카피 | 그대로 사용 | **그대로 옮기지 않는다** — 같은 역할의 자리표시자 문구로 |

타사 앱을 재현한 결과물을 App Store 에 내면 **Guideline 4.1 (Copycats) 로 리젝된다.** 이건 경고가 아니라 결과에 대한 사실이고, 작업을 막지는 않는다 — 학습·프로토타입·자사 앱 리빌드는 정상 용도다. 산출물 상단에 어느 분기로 만들었는지 한 줄 남긴다.

## Workflow

### Step 1 — 기기 게이트 + 세션 (HARD)

```bash
udid="$(scripts/device_wda.sh device)"
sid="$(scripts/device_wda.sh session "$udid")"
```

실패 시 **중지**한다. 실패 분기와 안내는 `autobot-copy-analyze` SKILL 의 Step 2 표와 동일하다(미연결 / 다중 연결 / UI 자동화 OFF / 서명 누락 / Appium 미기동).

### Step 2 — 전수 탐험 (flow 를 먼저 확보한다)

**화면 하나를 골라 재현하지 않는다.** 앱 전체를 훑어 화면과 그 사이 전이를 먼저 모으고, 그 지도를 본 뒤에 재현할 화면을 고른다. 맥락 없이 복제한 화면은 껍데기다.

```bash
scripts/device_wda.sh screen "$sid" .autobot/clone/raw <NN>-<screen>
scripts/device_wda.sh candidates .autobot/clone/raw/<NN>-<screen>.xml
scripts/device_wda.sh tap "$sid" <x> <y> .autobot/clone/raw/<NN>-<screen>.xml
scripts/device_flow.py next .autobot/clone/flow.jsonl    # 아직 안 가본 곳
```

탐험 규율·STOP 조건은 `autobot-copy-analyze` Step 3 과 **동일하며 같은 코드가 강제한다** — 파괴적 라벨은 후보에서 제외, 모달이면 후보 0개, 낡은 좌표 탭은 거부. clone 에서 달라지는 건 셋:

**① 전이가 자동으로 기록된다.** `screen` 과 `tap` 이 `.autobot/clone/flow.jsonl` 에 한 줄씩 남긴다 — 손으로 적는 게 아니다. `tap` 은 탭 직후가 아니라 **화면이 실제로 바뀔 때까지 기다렸다가** 도착 화면을 적는다(안 기다리면 전환 애니메이션 중이라 출발 화면이 도착지로 기록된다). 끝내 안 바뀌면 `changed=false` 로 남는다 — "이 버튼은 아무 데도 안 간다"도 flow 데이터다.

**② 화면 정체성은 `sig` 가 아니라 `nodekey` 다.** `sig`(라벨 집합 해시)는 탭 가드용이라 데이터가 바뀌면 같이 바뀐다 — 그걸로 노드를 세면 목록을 스크롤할 때마다 새 화면이 생겨 탐험이 끝나지 않는다. `nodekey`(구조 해시: role 개수 버킷 + 네비바 제목)는 같은 화면의 데이터 변화와 스크롤을 흡수하되, **빈 상태와 채워진 상태는 다른 노드로 둔다** — 그 둘은 재현해야 할 서로 다른 레이아웃이다.

**③ 중단은 실패가 아니라 정상 종료다.** 실기기에서는 세션 만료·잠금·로그인 벽 중 하나에 반드시 걸린다. 완주가 예외고 중단이 기본이다. 그래서 **재개가 1급 경로**다 — `device_flow.py next` 가 로그를 읽어 미방문 후보를 복원하므로, 새 세션을 열고 이어서 탐험한다. 처음부터 다시 하지 않는다.

**데이터가 필요한 화면**: 읽기 전용으로는 빈 상태밖에 못 보는 지점이 나온다(항목 0개인 목록의 채워진 레이아웃). 여기서 **한 번 멈춰 사용자에게 "항목 1개만 직접 만들어 주세요"라고 요청**하고 재개한다. 에이전트가 대신 만들지 않는다 — 사용자의 실제 기기이고, 삭제는 파괴적 라벨이라 되돌릴 수도 없다. 사용자가 거절하면 그 화면은 flow 맵에 `데이터 필요` 로 남기고 넘어간다.

**커버리지를 숨기지 않는다.** `device_flow.py stats` 가 "후보 N개 중 M개 탐험"을 낸다. 6/30 을 탐험하고 "전수 완료"라고 말하지 않는다.

### Step 2a — flow 맵 (사람이 보는 지점)

```bash
scripts/device_flow.py map .autobot/clone/flow.jsonl .autobot/clone/flow-map.html
open .autobot/clone/flow-map.html
```

화면 썸네일을 진입 화면으로부터의 깊이별로 놓고, 어떤 탭이 어디로 가는지와 **미탐험 후보**를 함께 보여준다. 사용자에게 열어 보여주고, 더 탐험할지 여기서 정한다.

### Step 2b — 역기획 (관찰과 해석을 섞지 않는다)

`.autobot/clone/reverse-brief.md` 에 **두 섹션으로** 쓴다. 섞으면 다음 사람이 사실과 내 추측을 구분할 수 없고, 그 문서가 `/autobot:mvp` 입력이 되면 추측이 명세가 된다.

- `## 관찰` — flow 로그와 측정에서 **그대로 나온 것만**. 진입 화면, 루트에서 한 탭 거리에 있는 것, 몇 탭을 들어가야 나오는 것, 어느 화면이 어디로 이어지는지, 화면별 요소 수·강조 색.
- `## 해석` — 왜 이렇게 만들었나. 항목마다 **어느 관찰에서 나왔는지 표시한다**. 근거 없는 문장은 쓰지 않는다.

읽는 범위는 **flow 그래프와 측정된 화면까지**다. App Store 리뷰·평점은 `copy` 의 입력이다 — 끌어오면 두 스킬 경계가 무너진다.

### Step 2c — 재현 대상 선택

화면 30개를 전부 SwiftUI 로 재현하지 않는다. flow 맵을 사용자와 함께 보고 **재현할 화면을 고른다**(보통 진입 화면 + 핵심 흐름 3~5개). 고르지 않은 화면은 스펙(Step 4)만 남기고 코드를 만들지 않는다 — flow 맵에 이미 있으므로 나중에 언제든 이어서 만들 수 있다.

### Step 3 — 측정 (이 스킬의 핵심)

각 화면의 `.xml` 과 `.png` 에서 재현에 필요한 수치를 뽑는다.

```bash
scripts/device_measure.py .autobot/clone/raw/<NN>-<screen>.xml \
                          .autobot/clone/raw/<NN>-<screen>.png \
                        > .autobot/clone/screens/<NN>-<screen>.json
```

뽑는 것:

- **기하** — 각 요소의 x·y·width·height(pt), 부모 대비 상대 위치, 형제 간 간격. 여기서 **패딩·스택 간격**이 그대로 나온다.
- **색** — 모서리에서 `background`, 컨트롤 내부 격자의 최빈값에서 `fill`, 텍스트는 배경과 대비가 가장 큰 픽셀에서 `foreground`. 세 개가 다 필요하다: FAB 의 파란 fill 은 모서리(뒤 캡슐)에도 중심(흰 글리프)에도 없다. 팔레트는 빈도순 집계.
- **타이포** — 텍스트 요소의 높이와 폭에서 대략적인 폰트 크기·굵기를 역산하고, iOS 표준 텍스트 스타일(`.body`/`.headline`/`.largeTitle`…)에 매핑한다. 정확한 폰트 파일은 알 수 없으므로 **시스템 폰트 기준**으로 맞춘다.
- **구조** — 접근성 트리의 부모-자식에서 스택 방향(`vstack`/`hstack`/`zstack`)과 형제 간 간격을 계산해 `layout` 으로 낸다. 축은 형제가 **겹치지 않는** 쪽이다(양수 간격 합이 아니라 겹침이 신호 — 6pt 겹친 두 줄은 zstack 이 아니라 vstack 이다). 버리는 것 셋: 라벨 없는 전체화면 래퍼(자식은 살아남은 조상에 재부착), 스크롤 막대 같은 크롬(**자식까지 함께** — 그 자식은 스크롤 막대 부품이지 콘텐츠가 아니다), WDA 가 창을 둘로 보고해 생기는 완전 중복 요소. 셋 다 안 버리면 카드 4장이 16pt 간격인 화면이 "spacing 147" 로 나온다(실측).
  카드 자신의 배경은 부모를 꽉 채워 모든 형제와 겹치므로 간격 계산에서 뺀다 — 안 그러면 한 줄의 간격이 `-343` 으로 잡힌다.

측정값은 JSON 으로 남긴다. 이후 단계는 이 JSON 만 보고 코드를 쓴다 — 스크린샷을 눈으로 보고 "대충 이 정도"로 쓰지 않는다.

### Step 4 — 화면 스펙

화면당 `.autobot/clone/screens/<NN>-<screen>.md` 를 쓴다. 최소 포함:

- 스크린샷 임베드 + 측정 JSON 링크
- **요소 표**: 역할 · 텍스트 · 프레임(x,y,w,h) · 색 · 텍스트 스타일
- **레이아웃 트리**: 어떤 스택에 무엇이 어떤 간격으로 들어가는지
- **동작 계약**: 이 화면이 *무엇을 하는가*. 요소별로 — 탭하면 어느 화면(sig)으로 가는지, 무엇이 바뀌는지, 어떤 상태(빈/채워짐/로딩/에러)에서 무엇이 보이는지. **기능 동일성은 여기서 나온다** — 이 표가 곧 `/autobot:mvp` 가 읽는 기능 명세이므로, 화면이 하는 일을 빠뜨리면 재현본은 껍데기가 된다.
  **모든 행은 근거 열을 갖는다.** 실제로 탭해 본 전이만 실측이고(`sig A → sig B`), 라벨을 보고 짐작한 것은 `미탐험` 으로 표시한다. 짐작을 실측처럼 적으면 `/autobot:mvp` 가 그걸 명세로 믿고 구현한다 — 이 레포가 같은 실패(존재하지 않는 능력을 문서가 전제)를 이미 세 번 겪었다. `미탐험` 행은 명세가 아니라 미확인 가설이다.
- **재현 불가 항목**: 바이너리 에셋, 커스텀 폰트, 애니메이션 타이밍 등 측정으로 알 수 없는 것을 명시한다. 숨기지 않는다. 룩앤필에 필요해서 **근사한 값(모서리 반경 등)은 근사라고 적는다** — 측정값과 섞이면 다음 사람이 구분할 수 없다.

### Step 5 — SwiftUI 재현

`.autobot/clone/Sources/` 에 화면당 한 파일씩 SwiftUI 뷰를 생성한다.

- 측정된 수치를 **그대로** 쓴다 — `.padding(16)` 이 아니라 측정값이 20이면 `.padding(20)`.
- 색은 측정 팔레트를 `Color` 상수로 뽑아 쓴다.
- 로직은 만들지 않는다(동작 계약은 Step 4 의 스펙이 갖고, 그걸 읽어 기능을 구현하는 건 `/autobot:mvp` 다 — clone 이 두 번째 앱 빌더가 되면 안 된다) — 액션은 `var onTap: () -> Void = {}` 콜백으로 노출하고 상태는 이니셜라이저로 주입한다(`autobot-screen-interview` 와 같은 규약). **모든 프로퍼티에 기본값을 준다** — Step 6 의 렌더러가 `<RootView>()` 로 띄우므로 필수 인자가 하나라도 있으면 대조 이미지를 못 만든다.
- 이미지 자리에는 `Rectangle().fill(.secondary)` + 크기 고정 자리표시자를 넣고 주석으로 원본 크기를 남긴다.
- 타사 앱 분기면 이름·문구를 자리표시자로 둔다(Step 0).

### Step 6 — 대조 검증 (재현을 주장하기 전에)

재현했다고 말하려면 **원본과 재현본을 나란히 보여준다.**

1. 생성한 SwiftUI 를 **원본과 같은 논리 해상도의 시뮬레이터**에서 렌더 → 스크린샷.
   ```bash
   scripts/device_render.sh .autobot/clone/Sources <RootView> <simulator> \
                            .autobot/clone/compare/<NN>-rendered.png
   ```
   프로젝트 파일 없이 `swiftc` 로 바로 `.app` 을 만들어 설치·실행·촬영한다. 컴파일이 깨지면
   컴파일러 진단을 그대로 보여주고 중지한다 — 그 상태로 대조하면 이전 실행의 낡은
   스크린샷과 비교하게 된다.
   측정값은 원본 기기의 pt 좌표라 크기가 다른 기기에서 렌더하면 전부 어긋난다. 없으면 만든다:
   ```bash
   xcrun simctl create clone-probe com.apple.CoreSimulator.SimDeviceType.iPhone-12-mini <runtime>
   ```
   `device_compare.py` 가 종횡비 불일치를 `WARN` 으로 잡아주지만, 애초에 맞추는 게 맞다.
2. 원본과 나란히 붙인다:
   ```bash
   scripts/device_compare.py .autobot/clone/raw/<NN>.png \
                             .autobot/clone/compare/rendered.png \
                             .autobot/clone/compare/<NN>-compare.png
   ```
3. 사용자에게 연다(`open .autobot/clone/compare/`)

3. **누락부터 센다.** 이 작업의 지배적 실패는 색이나 간격이 아니라 **요소가 통째로 빠지는 것**이다 — screenshot-to-code 연구(DCGen, arXiv 2406.16386)가 분류한 실패 1,699건 중 누락 85.3%, 배치 오류 12.7%, 왜곡 2.6%였다. 그러니 대조할 때 눈으로 "비슷하네"부터 하지 말고 **Step 4 요소 표의 행을 하나씩 짚어** 재현본에 있는지 센다. 우리 측정 단계는 크롬을 버리므로(Step 3) 콘텐츠를 같이 버렸을 위험이 특히 크다.

기준은 픽셀 일치가 아니라 **"나란히 놓으면 같은 화면인가"** 다. 수치가 맞아도 눈으로 다르면 재현이 아니고, 몇 pt 어긋나도 같아 보이면 통과다. 다른 곳은 스펙의 근사 항목을 고쳐 좁힌다.
같은 방식으로 **동작 계약도 대조한다** — Step 4 표의 각 요소가 재현본에서 같은 화면/상태로 가는가. 여기서 빠진 것이 곧 기능 차이다.
**비교 이미지 없이 "완료"라고 하지 않는다.**

## Output Artifacts

| 산출물 | 경로 | 소비자 |
|-------|------|--------|
| 탐험 로그(전이·커버리지·재개 상태) | `.autobot/clone/flow.jsonl` | Step 2·2a·2b |
| flow 맵 | `.autobot/clone/flow-map.html` | 사람 검토 (Step 2a·2c) |
| 역기획 | `.autobot/clone/reverse-brief.md` | 사람 · `/autobot:mvp` |
| 원본 캡처 + 트리 | `.autobot/clone/raw/*.png`, `*.xml` | Step 3 측정 |
| 측정값 | `.autobot/clone/screens/*.json` | Step 4·5 |
| 화면 스펙 | `.autobot/clone/screens/*.md` | 사람 리뷰 |
| SwiftUI 재현 | `.autobot/clone/Sources/*.swift` | 빌드 |
| 대조 이미지 | `.autobot/clone/compare/*.png` | Step 6 검증 |

## CRITICAL RULES

1. **측정하지 않은 값을 쓰지 않는다** — 스크린샷을 보고 눈대중으로 색·간격을 정하지 않는다. 목표가 픽셀 동일이 아니라고 해서 이 규율이 느슨해지는 게 아니다: 측정이 룩앤필에 도달하는 가장 싼 길이다. 측정 JSON 에 없는데 재현에 필요하면 **근사하고 근사라고 적는다**(스펙의 "재현 불가 항목").
2. **에셋 추출을 약속하지 않는다** — 불가능하다. 자리표시자 + 명시.
3. **Step 0 분기를 산출물에 남긴다** — 본인 앱인지 타사 앱인지가 이름·로고·문구 처리 방식을 결정한다.
4. **대조 이미지 없이 완료 선언 금지** (Step 6).
5. **파이프라인 상태 위조 금지** — `build-state.json`/`architecture.json` 을 만들지 않는다. 산출물은 `/autobot:mvp`·`/autobot:plan` 의 입력이거나 독립 참고물이다.
6. **flow 를 확보하기 전에 재현하지 않는다** — 화면 하나만 보고 코드를 쓰면 그 화면이 앱에서 어떤 위치인지 모른 채 복제하게 된다. Step 2 → 2a → 2b → 2c 를 거친 뒤 Step 3 으로 간다.
7. **커버리지와 근거를 숨기지 않는다** — 부분 탐험은 부분이라고 말하고(`stats`), 역기획의 해석은 관찰과 분리하고, 동작 계약의 미확인 행은 `미탐험` 으로 표시한다. 셋 다 추측이 명세로 승격되는 걸 막는 같은 규칙이다.

## Preconditions

- `autobot-copy-analyze` 와 동일: Appium + xcuitest, 기동 중인 서버, `DEVELOPMENT_TEAM`, iPhone 1대 연결 + 잠금 해제 + Developer Mode + Trust + **UI 자동화 ON**. 미충족 시 중지.
