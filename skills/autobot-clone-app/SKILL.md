---
name: autobot-clone-app
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

**기술적 한계**: Appium/WebDriverAgent가 제공하는 것은 대상 앱의 화면·접근성 트리이지, 설치된 App Store 앱의 원본 번들 파일을 보장하는 경로가 아니다. 따라서 탈옥·샌드박스 우회·서명 무력화 없이는 **바이너리 에셋(아이콘·이미지·폰트 파일)의 원본 추출을 약속하지 않는다.**

다만 이것이 연구용 clone 산출물에서 원본 시각 자산을 항상 자리표시자로 바꿔야 한다는 뜻은 아니다. 사용자가 연구용 사용을 승인했고, 자산을 **사용자 제공 파일·승인된 앱 payload/export·공개된 원본 파일·실기기 캡처에서 합법적으로 얻은 화면 crop** 중 하나로 확보할 수 있으면, 연구 전용 산출물에는 원본 아이콘·이미지·문구를 넣을 수 있다. crop은 바이너리 추출이 아니라 캡처 기반 재현이며, 품질·투명도·해상도 손실을 스펙에 기록한다. 모든 자산은 출처·획득 방법·원본 프레임을 `assets/manifest.json`에 남긴다.

앱 샌드박스나 암호화·서명 경계를 우회하지 않는다. 자산을 확보하지 못하면 SF Symbols·그라디언트·자리표시자로 근사하고, `research-only` 표시를 유지한다. 이후 외부 공유·App Store 배포로 범위가 바뀌면 연구용 자산을 그대로 승계하지 말고 라이선스·상표·카피 검토를 다시 통과시킨다.

**가능** — 좌표·크기·계층·색·글자 크기·굵기·정렬·네비게이션 구조·인터랙션. 이것만으로도 화면은 대부분 같아 보인다.

### Step 0 — 소유 확인 (건너뛰지 않는다)

첫 질문으로 **대상 앱의 소유 여부와 결과물의 사용 범위(연구 전용인지 배포용인지)** 를 확인하고, 답에 따라 재현 범위를 바꾼다.

| | 본인 앱 (또는 소유 조직의 앱) | 타사 앱 — 연구 전용, 사용자 승인 | 타사 앱 — 외부 공유·배포 |
|---|---|---|
| 레이아웃·간격·색·타이포·네비게이션·인터랙션 | 재현 | 재현 | 재현 |
| 앱 이름·로고·아이콘·화면 이미지 | 그대로 사용 | **접근 가능한 원본 또는 캡처 crop이면 사용 가능**. `research-only`와 출처를 기록 | 원본 승계 금지. 대체 자산 사용 |
| 화면 내 문구·마케팅 카피 | 그대로 사용 | 연구 관찰에 필요하면 그대로 기록·재현 가능. 출처와 연구 전용 범위를 기록 | 그대로 옮기지 않는다. 역할만 유지한 새 문구 사용 |

타사 앱을 재현한 결과물을 App Store 에 내면 **Guideline 4.1 (Copycats) 로 리젝될 수 있다.** 연구용 승인만으로 배포 권한이 생기는 것은 아니다. 산출물 상단과 자산 manifest에 `research-only` 또는 `distribution-safe` 분기를 명시한다.

## Workflow

### Step 0a — 저장소/설치 스킬 계약 확인

저장소에서 플러그인을 개발 중이면 실행 전에 canonical 스킬과 설치된 플러그인의 버전·내용을 확인한다.

```bash
python3 scripts/clone_skill_sync.py check
```

같은 버전이 설치되어 있고 스킬이 참조하는 clone runtime 스크립트의 존재·해시가 모두 같은데 **스킬 문서만** drift한 경우에만, 변경을 검토한 뒤 `sync`를 쓴다. 저장소가 0.13.9이고 설치본이 0.13.8인 것처럼 버전이 다르거나 스크립트가 빠졌으면 동기화하지 않는다. 먼저 일치하는 플러그인 패키지를 설치·reload해야 하며, 새 문서와 옛 스크립트를 섞어 실행하지 않는다.

### Step 0b — clone workspace 준비

소유·사용 범위 확인(Step 0)과 대상 bundle ID 확인이 끝나면, 관찰에 사용할 Xcode workspace를 먼저 만든다. 이 프로젝트는 Xcode/CoreDevice를 깨우기 위한 **clone 전용 작업공간**이며, Threads의 bundle ID를 그대로 쓰지 않는다. 연구용 분기에서 승인된 이름·로고·이미지는 별도 자산으로 넣을 수 있지만, clone 앱의 bundle ID·서명·앱 식별자는 별개로 유지한다.

```bash
scripts/clone_workspace.sh prepare
export CLONE_XCODE_PROJECT=".autobot/clone/project/CloneWorkspace.xcodeproj"
```

`device_wda.sh device`는 연결된 물리 기기가 없을 때 이 프로젝트를 `open -a Xcode`로 열고 최대 30초 동안 `devicectl` 상태를 재조회한다. 이는 CoreDevice 터널을 깨우는 best-effort 복구다. 계속 `paired`/`unavailable`이면 연결된 것으로 간주하지 않고 중지한다 — 그때는 Xcode의 **Window > Devices and Simulators**를 한 번 열거나 USB·잠금 해제·Developer Mode·Trust를 확인한다. 프로젝트를 먼저 빌드하거나 실행하지 않는다. 관찰 전에 foreground 앱을 바꾸면 대상 앱 바인딩 증거가 흐려진다.

### Step 1 — 기기 게이트 + 대상 앱 바인딩 (HARD)

대상 앱을 단순히 현재 포그라운드 앱으로 추정하지 않는다. **같은 UDID에서 bundle ID를 먼저 확인하고 Appium 세션에 `appium:bundleId`로 주입**한다. `devicectl device info apps`는 기본값이 developer 앱만 표시하므로, App Store로 설치된 원본 앱까지 찾으려면 반드시 `--include-all-apps`를 쓴다. 과거에 알려진 bundle ID나 앱 프로세스 경로만으로 추정하지 않는다.

```bash
udid="$(scripts/device_wda.sh device '<기기 이름 또는 UDID>')"
# <앱 이름>과 같은 target UDID를 사용한다. 출력의 Bundle Identifier를 복사한다.
xcrun devicectl device info apps \
  --device "$udid" --include-all-apps --search '<앱 이름>'
bundle_id="<위 출력의 정확한 Bundle Identifier>"
scripts/device_wda.sh doctor "$udid" "$bundle_id"
sid="$(scripts/device_wda.sh session "$udid" "$bundle_id")"
```

`device`를 먼저 실행해야 Xcode/CoreDevice 자동 복구와 기기 profile 생성이 선행된다. 그 다음 `doctor`가 Appium/xcuitest driver, Xcode·`devicectl`, 서명 team, 대상 기기·앱, iOS 18+ RemoteXPC tunnel, 빌드에 필요한 디스크 여유를 한 번에 점검한다. `device`가 성공하면 `.autobot/clone/device-profile.json`에 UDID·기기명·marketing name·product type·OS/build·연결 상태를 남기며 Step 6의 동일 기종 시뮬레이터 선택이 이를 사용한다.

`session`은 로컬 `APPIUM_URL`이 응답하지 않으면 Appium을 자동 시작하고, 같은 UDID·bundle ID·서버의 살아 있는 세션이 있으면 `.autobot/clone/wda-session.json`에서 재사용한다. 자동 시작을 끄려면 `CLONE_AUTO_START_APPIUM=0`, 재사용을 끄려면 `CLONE_SESSION_REUSE=0`을 쓴다. 이 스크립트가 시작한 서버만 `scripts/device_wda.sh stop-server`로 종료할 수 있다. HTTP 병목을 계측할 때만 `CLONE_METRICS=1`을 켜며 원시 요청 시간은 `.autobot/clone/http-metrics.jsonl`에 남는다.

iOS 18+ 물리 기기는 CoreDevice의 `connected` 상태와 별도로 Appium xcuitest RemoteXPC tunnel이 필요하다. `doctor`와 `session`은 `http://127.0.0.1:42314/remotexpc/tunnels`에 대상 UDID가 있는지 먼저 확인한다. 없으면 다음 명령을 **별도 터미널에서 실행하고 계속 켜 둔다**.

```bash
sudo appium driver run xcuitest tunnel-creation -- --udid "$udid"
```

이 단계는 macOS TUN 인터페이스 생성 때문에 sudo가 필요하다. 스킬은 비밀번호를 요청하거나 성공을 위조하지 않고 정확한 명령과 함께 중지한다. custom registry를 쓰면 `CLONE_TUNNEL_REGISTRY_URL`을 지정한다.

예를 들어 Threads는 기기·릴리스에 따라 식별자가 달라질 수 있으므로 `com.instagram.barcelona`를 고정하지 않는다. 이 회차의 `heewook의 iPhone`에서는 `Threads`가 `com.burbn.barcelona`로 확인됐다. `--include-all-apps`를 생략해 앱이 보이지 않거나, 다른 기기의 목록을 보고 미설치로 결론내리면 안 된다. 대상 앱 자체는 Debug 빌드일 필요가 없으며, 기기에 설치되는 WDA runner만 개발자 서명이 필요하다.

실패 시 **중지**한다. 실패 분기와 안내는 `autobot-copy-analyze` SKILL 의 Step 2 표와 동일하다(미연결 / 다중 연결 / UI 자동화 OFF / 서명 누락 / Appium 미기동 / 대상 bundle ID 누락 또는 미설치). `screen`·`tap`·`type`·`swipe`는 매번 Appium의 active-app 정보를 세션 bundle ID와 대조하므로, 다른 앱·SpringBoard·권한 대화상자가 foreground면 중지한다.

`xcodebuild code 65`와 함께 `0xe8008001` 또는 `invalid Info.plist`가 나오면 Threads의 Debug 여부로 해석하지 않는다. 이는 WDA runner의 별도 서명·재서명 산출물 문제다. `CLONE_WDA_DEBUG=1`로 Appium 로그를 남기고, 로그에 나온 `WebDriverAgentRunner-Runner.app`에 `codesign --verify --deep --strict --verbose=4`를 실행해 WDA 서명을 먼저 검증한다. 대상 앱의 bundle ID나 설치 상태를 바꾸지 않는다.

`device_wda.sh session`은 기본적으로 Appium 패키지의 WDA를 `.autobot/clone/wda`에 격리 복사하고(`CLONE_WDA_ISOLATE=1`), 이미 서명된 Runner.app을 다시 변형하는 로컬 post-action을 no-op으로 교체한다. 같은 표시명의 개발 인증서가 키체인에 여러 개 있으면 `codesign --sign "Apple Development"`가 모호해져 위 오류가 날 수 있기 때문이다. 필요하면 `CLONE_WDA_REFRESH=1`로 복사본을 새로 만들고, 기존 전역 Appium WDA를 직접 수정하지 않는다. 레거시 동작을 명시적으로 재현해야 할 때만 `CLONE_WDA_ISOLATE=0`을 사용한다. 이 격리는 WDA runner에만 적용되고, 관찰 대상 앱의 설치·서명·bundle ID에는 적용되지 않는다.

### Step 2 — 전수 탐험 (flow 를 먼저 확보한다)

**화면 하나를 골라 재현하지 않는다.** 앱 전체를 훑어 화면과 그 사이 전이를 먼저 모으고, 그 지도를 본 뒤에 재현할 화면을 고른다. 맥락 없이 복제한 화면은 껍데기다.

```bash
scripts/device_wda.sh screen "$sid" .autobot/clone/raw <NN>-<screen>
scripts/device_wda.sh candidates .autobot/clone/raw/<NN>-<screen>.xml
# 권장: 탭 + settle + 도착 PNG/XML + flow 기록을 한 번에 원자적으로 완료
scripts/device_wda.sh step "$sid" <x> <y> \
  .autobot/clone/raw/<NN>-<screen>.xml .autobot/clone/raw <NN>-<destination>
scripts/device_wda.sh type "$sid" <accessibility-id> <text>  # 입력값은 flow에 기록하지 않음
scripts/device_flow.py next .autobot/clone/flow.jsonl    # 아직 안 가본 곳
```

탐험 규율·STOP 조건은 `autobot-copy-analyze` Step 3 과 **동일하며 같은 코드가 강제한다** — 접근성 트리를 먼저 읽고 semantic text input을 사용하며, 좌표 탭은 후보·현재 화면 서명이 일치할 때만 허용한다. 파괴적 라벨은 후보에서 제외하고, 모달이면 후보 0개로 중지한다. clone 에서 달라지는 건 셋:

**① 전이가 자동으로 기록된다.** `screen`·`step`·`tap`·`swipe`가 `.autobot/clone/flow.jsonl` 에 한 줄씩 남긴다 — 손으로 적는 게 아니다. 기본 경로는 `step`이다. 탭, settle에 사용한 최종 XML 재사용, 도착 스크린샷, 원자적 파일 교체, 전이·화면 이벤트 기록을 한 명령으로 닫아 추가 `/source` 왕복과 캡처 누락을 없앤다. 저수준 `tap`은 디버깅용으로만 두며, `changed=true`인데 별도 `screen`이 없으면 여전히 `incomplete`다. 끝내 바뀌지 않은 동작도 `changed=false`로 기록한다.

**② 화면 정체성은 세 층이다.** `sig`(라벨 집합 해시)는 stale-coordinate 탭 가드, `node`/`nodekey`는 데이터 변화·스크롤을 흡수하는 coarse 구조, `state`/`statekey`는 키보드·포커스·선택·모달을 포함하는 상호작용 상태다. flow와 생성 라우터는 `state`를 우선하고 옛 로그의 `node`로 fallback한다. 같은 coarse node라도 검색 포커스 전후는 다른 상태이므로 기능 복제에서 사라지지 않는다.

**③ 후보 수와 커버리지는 안전성을 포함한다.** 역할·actionable trait가 없는 설명문, `AXKey`/`KeyboardKey`와 키보드 하위 요소는 후보가 아니다. 팔로우·언팔로우·좋아요·리포스트·게시·전송·추천 숨기기·토글 등 계정이나 콘텐츠를 바꾸는 동작은 `withheld`로 분류해 자동 탭하지 않는다. `stats`는 실제 좌표 단위 raw target coverage와 반복 행을 묶은 behavior-class coverage를 둘 다 보여주고, 완료 판정은 안전한 behavior class 기준으로 한다.

**④ 중단은 실패가 아니라 정상 종료다.** 실기기에서는 세션 만료·잠금·로그인 벽 중 하나에 반드시 걸린다. 완주가 예외고 중단이 기본이다. 그래서 **재개가 1급 경로**다 — `device_flow.py next` 가 로그를 읽어 미방문 후보를 복원하므로, 새 세션을 열고 이어서 탐험한다. 처음부터 다시 하지 않는다.

**데이터가 필요한 화면**: 읽기 전용으로는 빈 상태밖에 못 보는 지점이 나온다(항목 0개인 목록의 채워진 레이아웃). 여기서 **한 번 멈춰 사용자에게 "항목 1개만 직접 만들어 주세요"라고 요청**하고 재개한다. 에이전트가 대신 만들지 않는다 — 사용자의 실제 기기이고, 삭제는 파괴적 라벨이라 되돌릴 수도 없다. 사용자가 거절하면 그 화면은 flow 맵에 `데이터 필요` 로 남기고 넘어간다.

**커버리지를 숨기지 않는다.** `device_flow.py stats`가 raw target과 behavior class를 따로 낸다. raw 6/30 또는 class 4/12를 탐험하고 "전수 완료"라고 말하지 않는다. withheld는 안전한 미탐험 작업으로 세지 않는다. 후보가 모두 탭됐더라도 변경된 탭/스와이프의 도착 화면 캡처가 없거나 접근성 트리가 빠졌으면 `incomplete`이며, 재현 완료로 보고하지 않는다.

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
python3 scripts/clone_postprocess.py .autobot/clone --workers 4 \
  --extract-assets \
  --assets-catalog .autobot/clone/project/CloneWorkspace/Assets.xcassets
```

기본 경로는 raw XML/PNG pair를 bounded 병렬로 측정하고, 입력 해시가 같은 화면은 캐시하며, 결정적인 `screens/*.json`·`screens/*.md`를 생성한다. 실패 pair가 하나라도 있으면 요약과 함께 non-zero로 끝난다. 단일 화면을 진단할 때만 기존 `device_measure.py <xml> <png>`를 직접 쓴다.

`--extract-assets`는 측정의 `AXImage` 프레임을 point→pixel scale로 crop하고 SHA-256으로 중복 제거한다. 필요하면 `device_assets.py <measurement.json> --indices 3,7`처럼 비표준 custom-drawn 요소를 명시한다. crop과 선택적 `.imageset`은 `.autobot/clone/assets/manifest.json`에 원본 캡처·프레임·해시·`capture-crop`·`research-only` 품질 한계와 함께 기록한다.

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
- **재현 불가 항목**: 접근 가능한 원본 파일이 없는 바이너리 에셋, 커스텀 폰트, 애니메이션 타이밍 등 측정으로 알 수 없는 것을 명시한다. 연구용 캡처 crop을 썼다면 원본 바이너리가 아니라는 점과 품질 손실을 적는다. 숨기지 않는다. 룩앤필에 필요해서 **근사한 값(모서리 반경 등)은 근사라고 적는다** — 측정값과 섞이면 다음 사람이 구분할 수 없다.
- **자산 출처**: 연구용 원본 자산을 사용한 화면은 `assets/manifest.json`의 파일명·출처 캡처·원본 프레임·획득 방법·`research-only` 범위를 링크한다.

### Step 5 — SwiftUI 재현

`.autobot/clone/Sources/` 에 화면당 한 파일씩 SwiftUI 뷰를 생성한다.

- 측정된 수치를 **그대로** 쓴다 — `.padding(16)` 이 아니라 측정값이 20이면 `.padding(20)`.
- 색은 측정 팔레트를 `Color` 상수로 뽑아 쓴다.
- 화면은 관찰된 액션을 `onAction: (String) -> Void = { _ in }` 하나로 노출한다. flow에 실제로 기록된 화면 전이는 clone이 재생해야 할 UI 동작이므로 상태 라우터를 생성하지만, 네트워크·계정 변경·게시·결제 같은 백엔드/비즈니스 로직은 만들지 않는다. 미탐험·withheld 동작을 추측해 구현하지 않는다.
- 연구용 분기에서 승인된 원본 자산이 있으면 `.xcassets`에 넣고 실제 화면에서 소비한다. 캡처 crop이면 원본 프레임·해상도 손실을 주석으로 남긴다.
- 원본 자산을 확보하지 못했거나 배포용 분기면 `Rectangle().fill(.secondary)` + 크기 고정 자리표시자를 넣고 원본 크기를 남긴다.
- 이름·문구·로고의 사용 여부는 타사 여부만으로 결정하지 않고 Step 0의 연구 전용/배포용 분기를 따른다.

관찰된 전이를 실제 clone 화면에 연결한다:

```bash
python3 scripts/clone_flow_codegen.py manifest \
  .autobot/clone/flow.jsonl .autobot/clone/views.json
# views.json의 state -> Swift View 타입 매핑을 검토·수정한다.
python3 scripts/clone_flow_codegen.py generate \
  .autobot/clone/flow.jsonl .autobot/clone/views.json \
  .autobot/clone/Sources/ObservedFlow.swift
```

생성물은 `ObservableObject` router, 관찰된 전이 표, `send(action:)`, 현재 state에 맞는 root switch를 제공한다. 같은 state/action이 여러 목적지로 관찰됐거나 화면 매핑이 빠지면 추측하지 않고 실패한다. 생성 뷰와 root는 Step 6에서 인자 없이 렌더할 수 있도록 기본값 계약을 유지한다.

### Step 6 — 대조 검증 (재현을 주장하기 전에)

재현했다고 말하려면 **원본과 재현본을 나란히 보여준다.**

1. 생성한 SwiftUI 를 **원본과 같은 논리 해상도의 시뮬레이터**에서 렌더 → 스크린샷.
   ```bash
   scripts/device_render.sh .autobot/clone/Sources <RootView> auto \
                            .autobot/clone/compare/<NN>-rendered.png
   ```
   프로젝트 파일 없이 `swiftc` 로 바로 `.app` 을 만들어 설치·실행·촬영한다. 컴파일이 깨지면
   컴파일러 진단을 그대로 보여주고 중지한다 — 그 상태로 대조하면 이전 실행의 낡은
   스크린샷과 비교하게 된다.
   `auto`는 `.autobot/clone/device-profile.json`의 `marketingName`과 일치하는 시뮬레이터를 고르고, booted 기기와 최신 runtime을 우선한다. 명시적인 이름·UDID도 계속 지원한다. source/root/SDK/deployment target/architecture 해시가 같으면 `.autobot/clone/render-cache/`의 컴파일 결과를 재사용하고, 고정 sleep 대신 두 번 연속 같은 프레임이 나올 때 촬영한다. 레거시 고정 대기는 `CLONE_RENDER_SETTLE=<seconds>`로만 opt-in한다.

   측정값은 원본 기기의 pt 좌표라 크기가 다른 기기에서 렌더하면 전부 어긋난다. matching simulator가 없으면 만든다:
   ```bash
   xcrun simctl create clone-probe com.apple.CoreSimulator.SimDeviceType.iPhone-12-mini <runtime>
   ```
   `device_compare.py` 가 종횡비 불일치를 `WARN` 으로 잡아주지만, 애초에 맞추는 게 맞다.
2. 원본과 나란히 붙인다:
   ```bash
   scripts/device_compare.py .autobot/clone/raw/<NN>.png \
                             .autobot/clone/compare/rendered.png \
                             .autobot/clone/compare/<NN>-compare.png \
                             --measure .autobot/clone/screens/<NN>.json \
                             --heatmap .autobot/clone/compare/<NN>-heatmap.png \
                             --mask-system-chrome
   ```
3. 사용자에게 연다(`open .autobot/clone/compare/`)

`device_compare.py`는 같은 픽셀 크기로 렌더된 경우에 한해 전체 및 측정 요소별 mismatch/평균 오차와 high·medium·low 차이, 결정적 heatmap을 출력한다. `--mask x,y,w,h`와 `--mask-system-chrome`은 애니메이션·시각 자산 같은 advisory 지표만 제외하며, 나란히 붙인 원본 증거는 가리지 않는다. 크기가 다르면 region metric과 heatmap을 건너뛰고 side-by-side만 만든다. 이 지표는 통과 판정의 단독 근거가 아니다. **대조 이미지와 요소 표/동작 계약의 사람 검토를 함께 통과해야 한다.**

4. **누락부터 센다.** 이 작업의 지배적 실패는 색이나 간격이 아니라 **요소가 통째로 빠지는 것**이다 — screenshot-to-code 연구(DCGen, arXiv 2406.16386)가 분류한 실패 1,699건 중 누락 85.3%, 배치 오류 12.7%, 왜곡 2.6%였다. 그러니 대조할 때 눈으로 "비슷하네"부터 하지 말고 **Step 4 요소 표의 행을 하나씩 짚어** 재현본에 있는지 센다. 우리 측정 단계는 크롬을 버리므로(Step 3) 콘텐츠를 같이 버렸을 위험이 특히 크다.

5. **차이는 분류해서 무거운 것부터 고친다.** 발견한 차이를 같은 무게로 다루면 모서리 반경을 다듬는 동안 빠진 요소가 살아남는다. 순서는 고정이다:

   | 우선 | 분류 | 예 |
   |---|---|---|
   | 상 | 요소 누락 · 레이아웃 구조 | 요소가 없다, 스택 방향·섹션 순서가 다르다 |
   | 중 | 간격 · 타이포 · 색 | 패딩/간격 어긋남, 글자 크기·굵기·색 불일치 |
   | 하 | 광택 | 모서리 반경, 그림자, 구분선 두께 |

   상위 분류에 차이가 남아 있는 동안 하위를 다듬지 않는다.

기준은 픽셀 일치가 아니라 **"나란히 놓으면 같은 화면인가"** 다. 수치가 맞아도 눈으로 다르면 재현이 아니고, 몇 pt 어긋나도 같아 보이면 통과다.

대조는 1회 통과/탈락이 아니라 **수렴 루프**다: 차이를 분류하고(위 5) → 스펙의 해당 항목(대개 근사 값)을 고치고 → 재렌더(Step 6-1) → 재대조. **종료 기준** — 상·중 분류의 차이가 0이고, 남은 차이가 전부 스펙의 "재현 불가 항목"에 미리 선언된 것뿐일 때. 그 전에는 통과가 아니라 다음 반복이다. 반복해도 좁혀지지 않는 차이는 스펙의 재현 불가 항목으로 승격하고 이유를 적는다 — 조용히 포기하지 않는다.
같은 방식으로 **동작 계약도 대조한다** — Step 4 표의 각 요소가 재현본에서 같은 화면/상태로 가는가. 여기서 빠진 것이 곧 기능 차이다.
**비교 이미지 없이 "완료"라고 하지 않는다.**

## Output Artifacts

| 산출물 | 경로 | 소비자 |
|-------|------|--------|
| 탐험 로그(시각·탭/스와이프 전이·입력 길이·커버리지·재개 상태) | `.autobot/clone/flow.jsonl` | Step 2·2a·2b |
| WDA 세션·기기 프로필·선택적 HTTP 계측 | `.autobot/clone/wda-session.json`, `device-profile.json`, `http-metrics.jsonl` | 재개·동일 기종 렌더·병목 진단 |
| flow 맵 | `.autobot/clone/flow-map.html` | 사람 검토 (Step 2a·2c) |
| 역기획 | `.autobot/clone/reverse-brief.md` | 사람 · `/autobot:mvp` |
| 원본 캡처 + 트리 | `.autobot/clone/raw/*.png`, `*.xml` | Step 3 측정 |
| 측정값 | `.autobot/clone/screens/*.json` | Step 4·5 |
| 화면 스펙 | `.autobot/clone/screens/*.md` | 사람 리뷰 |
| SwiftUI 재현 | `.autobot/clone/Sources/*.swift` | 빌드 |
| state/view 매핑 + 관찰 전이 라우터 | `.autobot/clone/views.json`, `Sources/ObservedFlow.swift` | 기능 재생 |
| 연구용 자산과 출처 | `.autobot/clone/assets/*`, `assets/manifest.json` | 연구용 clone 빌드·감사 |
| 대조 이미지 | `.autobot/clone/compare/*.png` | Step 6 검증 |
| 측정·렌더 캐시 | `.autobot/clone/.postprocess-cache.json`, `render-cache/` | 반복 실행 가속 |
| clone Xcode 작업공간 | `.autobot/clone/project/CloneWorkspace.xcodeproj` | Xcode/CoreDevice 준비 및 이후 구현 빌드 |

## CRITICAL RULES

1. **측정하지 않은 값을 쓰지 않는다** — 스크린샷을 보고 눈대중으로 색·간격을 정하지 않는다. 목표가 픽셀 동일이 아니라고 해서 이 규율이 느슨해지는 게 아니다: 측정이 룩앤필에 도달하는 가장 싼 길이다. 측정 JSON 에 없는데 재현에 필요하면 **근사하고 근사라고 적는다**(스펙의 "재현 불가 항목").
2. **원본 바이너리 에셋 추출을 약속하지 않는다** — 접근 가능한 승인 파일·payload·화면 crop이 있으면 연구 전용 산출물에 사용할 수 있고, 없으면 자리표시자 + 명시한다. 샌드박스·암호화·서명 경계를 우회하지 않는다.
3. **Step 0 분기를 산출물에 남긴다** — 본인 앱인지, 타사 연구 전용인지, 외부 공유·배포용인지가 이름·로고·문구·자산 처리 방식을 결정한다.
4. **대조 이미지 없이 완료 선언 금지** (Step 6).
5. **파이프라인 상태 위조 금지** — `build-state.json`/`architecture.json` 을 만들지 않는다. 산출물은 `/autobot:mvp`·`/autobot:plan` 의 입력이거나 독립 참고물이다.
6. **flow 를 확보하기 전에 재현하지 않는다** — 화면 하나만 보고 코드를 쓰면 그 화면이 앱에서 어떤 위치인지 모른 채 복제하게 된다. Step 2 → 2a → 2b → 2c 를 거친 뒤 Step 3 으로 간다.
7. **커버리지와 근거를 숨기지 않는다** — 부분 탐험은 부분이라고 말하고(`stats`), 역기획의 해석은 관찰과 분리하고, 동작 계약의 미확인 행은 `미탐험` 으로 표시한다. 변경된 탭/스와이프의 도착 캡처가 없거나 원본 트리가 빠진 경우도 `incomplete`로 남긴다. 셋 다 추측이 명세로 승격되는 걸 막는 같은 규칙이다.
8. **관찰 전에 clone 앱을 실행하지 않는다** — clone workspace는 Xcode/CoreDevice 준비용으로만 열고, 대상 앱의 화면·전이를 수집하기 전에는 빌드·설치·실행하지 않는다.
9. **연구용 자산은 provenance를 남긴다** — `assets/manifest.json` 없이 원본 자산을 생성본에 넣지 않는다. 연구용 승인과 기술적으로 접근 가능한 출처를 혼동하지 않는다.

## Preconditions

- `autobot-copy-analyze` 와 동일: Appium + xcuitest, `DEVELOPMENT_TEAM`, iPhone 1대 연결 + 잠금 해제 + Developer Mode + Trust + **UI 자동화 ON**, 설치된 대상 bundle ID. 로컬 Appium 서버는 `session`이 자동 시작할 수 있지만 iOS 18+ RemoteXPC tunnel, 설치·driver·서명·기기·디스크 조건은 `doctor`에서 통과해야 한다. 미충족 시 중지.
