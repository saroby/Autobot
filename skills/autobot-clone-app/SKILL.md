---
name: autobot-clone-app
description: Use when reproducing an existing iOS app's screens so they look and behave the same — same layout, spacing, colors, typography, navigation and per-screen behavior — as a buildable SwiftUI project. Not a pixel-diff exercise — the bar is "side by side it reads as the same screen, and the same taps do the same things". Drives a connected iPhone via Appium/WebDriverAgent (`scripts/device_wda.sh`), measures every element's exact frame from the accessibility tree, samples real colors from the screenshot pixels, and emits measurement evidence plus SwiftUI code under `.autobot/clone/`; optional human-authored screen specs are an `/autobot:mvp` handoff. Requires a connected device — aborts without one. Unlike `autobot-copy-analyze` (which extracts *direction* for an original app), this reproduces the screens themselves. Triggers on "이 앱 그대로 복제해줘", "화면 똑같이 만들어줘", "앱 클론", "/autobot:clone".
---

# Autobot Clone — 화면을 있는 그대로 재현

대상 앱의 화면을 **같아 보이고 같이 움직이게** 재현한다. `autobot-copy-analyze`(`/autobot:copy`)가 "왜 이 앱이 다시 열리는가"를 뽑아 *새 원본 앱*의 기획을 만든다면, 이 스킬은 **화면 그 자체**를 SwiftUI 로 재현한다.

| | `/autobot:copy` | `/autobot:clone` (이 스킬) |
|---|---|---|
| 산출물 | 제품 브리프(기획 입력) | 측정 증거 + SwiftUI 코드 (선택: mvp용 화면 스펙·동작 계약) |
| 충실도 | 방향(personality·팔레트 느낌) | **레이아웃 · 룩앤필 · 기능** |
| 목적 | 다른 앱을 새로 만든다 | 같은 화면을 다시 만든다 |
| 공유 | 둘 다 `scripts/device_wda.sh` 로 기기를 몬다 | |

**픽셀 단위 동일이 목표가 아니다.** 나란히 놓고 "같은 화면이다" 싶으면 되고, 같은 조작에 같은 반응을 하면 된다. 그렇다고 눈대중으로 쓰라는 뜻은 아니다 — 좌표·색·글자 크기를 **측정해서** 쓰는 게 그 룩앤필에 도달하는 가장 싼 길이다(눈대중은 카드 간격 16pt 를 20pt 로, FAB 의 파란 fill 을 회색으로 만든다. 둘 다 실측 사고다). 측정으로 알 수 없는 값(모서리 반경, 그라디언트 방향)은 **근사하고 스펙에 근사임을 표시**한다.

## 무엇이 가능하고 무엇이 불가능한가 (먼저 읽을 것)

**기술적 한계**: Appium/WebDriverAgent가 제공하는 것은 대상 앱의 화면·접근성 트리이지, 설치된 App Store 앱의 원본 번들 파일을 보장하는 경로가 아니다. 따라서 탈옥·샌드박스 우회·서명 무력화 없이는 **바이너리 에셋(아이콘·이미지·폰트 파일)의 원본 추출을 약속하지 않는다.**

clone 산출물은 별도 확인 질문 없이 기본적으로 `research-only`로 생성한다. 자산을 **사용자 제공 파일·승인된 앱 payload/export·공개된 원본 파일·실기기 캡처에서 합법적으로 얻은 화면 crop** 중 하나로 확보할 수 있으면, 원본 아이콘·이미지·문구를 넣을 수 있다. crop은 바이너리 추출이 아니라 캡처 기반 재현이며, 품질·투명도·해상도 손실을 스펙에 기록한다. 모든 자산은 출처·획득 방법·원본 프레임을 `assets/manifest.json`에 남긴다.

앱 샌드박스나 암호화·서명 경계를 우회하지 않는다. 자산을 확보하지 못하면 SF Symbols·그라디언트·자리표시자로 근사하고, `research-only` 표시를 유지한다. 이후 외부 공유·App Store 배포로 범위가 바뀌면 연구용 자산을 그대로 승계하지 말고 라이선스·상표·카피 검토를 다시 통과시킨다.

**가능** — 좌표·크기·계층·색·글자 크기·굵기·정렬·네비게이션 구조·인터랙션. 이것만으로도 화면은 대부분 같아 보인다.

## Workflow

**기본 완주 경로는 세 명령이다:** `observe` → `functional` → `polish`. `codegen`은 기기 없는 복구 경로이고 `install`은 검증 뒤 실기기에 올리는 선택 단계다. 스크립트가 소유할 수 없는 것은 선택적인 mvp 화면 스펙과 기계 생성본의 손질이다.

```bash
python3 scripts/clone_skill_sync.py check                 # Step 1-0 (레포에서 개발 중일 때만)
scripts/clone_run.sh observe '<앱 이름 또는 bundle id>'    # Step 1–3, + Step 5 기계 초안
scripts/clone_run.sh functional                           # Step 6a — 앱이 동작하는가
scripts/clone_run.sh polish                               # Step 6b — 화면이 같아 보이는가
#   scripts/clone_run.sh verify 는 위 둘을 이 순서로 돈다.
scripts/clone_run.sh codegen                              # 기기 없이 생성만 다시 (Step 5)
scripts/clone_run.sh install [RootView]                   # Step 6c — 실기기에 설치 (이름은 원본과 동일)
```

`observe` 는 workspace 준비 → 기기 게이트 → bundle ID 확인 → doctor → session → **앱 전체 탐험**(화면 사이 이동 포함) → 측정·자산 crop → flow 맵 → router manifest → **화면마다 측정 기반 SwiftUI 초안**을 **질문 없이** 수행한다.

**생성은 기기가 필요 없고, 그래서 따로 돌릴 수 있다.** `observe` 의 마지막 단계(`views.json` → `ObservedFlow.swift` → 화면 뷰)에서 ambiguous transition 은 이제 생성을 죽이지 않는다 — 그 엣지만 WARN 과 함께 빠지고 나머지는 전부 생성된다. WARN 이 가리키는 두 state 가 실은 한 화면이면 `state-aliases.json` 으로 병합을 선언하고 `clone_run.sh codegen` 을 돌린다 — 라이브 앱을 다시 탐험할 필요 없이 **기기가 전혀 관여하지 않는 작업**만 다시 하는 것이며, 탐험 증거는 그대로 둔다. 그 밖의 로그 모순으로 생성이 실패했을 때도 같은 경로다: 로그(또는 `views.json`)를 고치고 `codegen`.

**순서가 규칙이다: 기능 먼저, 픽셀은 그 다음.** 도달할 수 없는 화면을 픽셀까지 깎는 것은 그 값이 셈에 들어가는지 모르는 채로 쓰는 시간이다. `functional` 은 한 번 빌드해 재현본을 실제로 띄우고, 관측된 전이를 **앱 안에서 탭해** 목적 화면에 도착하는지 본다 — 전이가 끊겼거나 도달 불가 화면이 있으면 non-zero. `polish` 는 그 다음에야 화면마다 렌더 → 구조 diff → 대조를 돌린다. `verify` 는 `functional` 이 실패하면 `polish` 로 넘어가지 않는다.

**둘 다 재개가 기본이다.** 실기기 실행은 완주보다 중단이 흔하다(세션 만료·잠금·로그인 벽). 중단되면 거기까지의 증거를 남기고 non-zero 로 끝나며, **같은 명령을 다시 실행하면 flow 로그에서 이어서** 한다. 처음부터 다시 하지 않는다.

**진행 중에 사용자에게 묻지 않는다.** 아래의 모든 선택에는 자율 기본값이 있다(재현 대상=증거가 있는 전 화면, 화면 매핑=자동 생성, 데이터 필요 화면=표시하고 계속). 사람이 보는 지점은 `flow-map.html` 과 `compare/` 이며, 둘 다 실행을 막지 않는다.

아래 Step 들은 그 두 명령이 각각 무엇을 보장하는지와, 개별 진단에 쓰는 하위 명령을 정의한다.

**산출물은 두 종류다 — 섞지 않는다.**
- **clone 완주 경로** (Step 1 → 2 → 3 → 5 → 6a → 6b): `observe`·`functional`·`polish` 가 만들고 검증하는 것. 이것만으로 "같아 보이고 같이 움직이는" 재현본이 나온다.
- **`/autobot:mvp` 인수인계 문서** (Step 2b 역기획 · Step 4 화면 스펙): 사람이 쓰고, 완주 경로의 어느 게이트도 읽지 않는다. 클론이 아니라 *다음 기획*의 입력이다. 없어도 클론은 완주되고, 있으면 mvp 가 추측 대신 실측을 받는다.

### Step 1 — 기기 게이트 + 대상 앱 바인딩 (HARD)

한 단계지만 순서가 있다: 스킬 계약 → workspace → 기기 확정 → 터널 → bundle ID → doctor → session. `observe` 가 이 순서로 돌고, 어느 항목이든 실패하면 **중지**한다. 1-0 ~ 1-2 는 복제 논리가 아니라 Appium/CoreDevice 를 iOS 18+ 에서 세우기 위한 준비이며, 이 게이트 밖에서는 의미가 없다.

#### 1-0 저장소/설치 스킬 계약 확인

저장소에서 플러그인을 개발 중이면 실행 전에 canonical 스킬과 설치된 플러그인의 버전·내용을 확인한다.

```bash
python3 scripts/clone_skill_sync.py check
```

같은 버전이 설치되어 있고 스킬이 참조하는 clone runtime 스크립트의 존재·해시가 모두 같은데 **스킬 문서만** drift한 경우에만, 변경을 검토한 뒤 `sync`를 쓴다. 저장소와 설치본의 버전이 다르거나 스크립트가 빠졌으면 동기화하지 않는다. 먼저 일치하는 플러그인 패키지를 설치·reload해야 하며, 새 문서와 옛 스크립트를 섞어 실행하지 않는다.

#### 1-1 clone workspace 준비

기기 확정보다 **먼저** 관찰에 사용할 Xcode workspace를 만든다 — 다음 항목의 `device` 가 CoreDevice 복구에 이 프로젝트를 연다. 이 프로젝트는 Xcode/CoreDevice를 깨우기 위한 **clone 전용 작업공간**이며, Threads의 bundle ID를 그대로 쓰지 않는다. clone 앱의 **표시 이름은 원본과 같게**(Step 6c), bundle ID·서명·앱 식별자는 별개로 유지한다.

```bash
scripts/clone_workspace.sh prepare
export CLONE_XCODE_PROJECT=".autobot/clone/project/CloneWorkspace.xcodeproj"
```

`device_wda.sh device`는 연결된 물리 기기가 없을 때 이 프로젝트를 `open -a Xcode`로 열고 최대 30초 동안 `devicectl` 상태를 재조회한다. 이는 CoreDevice 터널을 깨우는 best-effort 복구다. 계속 `paired`/`unavailable`이면 연결된 것으로 간주하지 않고 중지한다 — 그때는 Xcode의 **Window > Devices and Simulators**를 한 번 열거나 USB·잠금 해제·Developer Mode·Trust를 확인한다. 프로젝트를 먼저 빌드하거나 실행하지 않는다. 관찰 전에 foreground 앱을 바꾸면 대상 앱 바인딩 증거가 흐려진다.

#### 1-2 터널 인증은 시작 시점에 묻는다

iOS 18+ 실기기는 RemoteXPC 터널이 필요하고 그 TUN 인터페이스 생성에는 root 가 든다. `clone_run.sh observe` 는 기기를 확정한 **직후** 터널을 세운다 — 터미널이면 `sudo -v`, 아니면 macOS 관리자 대화상자로 그 자리에서 묻는다.

그 전에는 같은 대화상자가 몇 분 뒤 `doctor` 안에서 떴다. 사용자가 보고 있지 않을 때 조용히 떴다가 시간 초과로 죽는 자리였다 — **묻는 시점이 게이트의 일부다.**

```bash
scripts/device_wda.sh tunnel-status <udid>   # 0 준비됨/불필요, 1 세워야 함, 2 판단 불가
scripts/device_wda.sh tunnel-start  <udid>   # 세운다 (필요하면 인증을 요청)
```

`tunnel-status` 는 프로필이 **다른 기기**를 가리키면 통과가 아니라 exit 2 로 거부한다. "판단 불가"를 "불필요"로 흘리면 iOS 26 기기가 조용히 통과한다(실측 2026-08-23). `CLONE_REQUIRE_SUDO=0` 으로 이 단계를 건너뛴다.

#### 1-3 기기 확정 · bundle ID 바인딩 · doctor · session

대상 앱을 단순히 현재 포그라운드 앱으로 추정하지 않는다. **같은 UDID에서 bundle ID를 먼저 확인하고 Appium 세션에 `appium:bundleId`로 주입**한다. `devicectl device info apps`는 기본값이 developer 앱만 표시하므로, App Store로 설치된 원본 앱까지 찾으려면 반드시 `--include-all-apps`를 쓴다. 과거에 알려진 bundle ID나 앱 프로세스 경로만으로 추정하지 않는다.

```bash
udid="$(scripts/device_wda.sh device '<기기 이름 또는 UDID>')"
# 선택자는 하드웨어 UDID(00008101-…) · 기기 이름 조각 · CoreDevice Identifier
# (`devicectl list devices` 의 Identifier 열, 74859CB7-… 모양) 셋 다 받는다.
# 연결된 기기가 있는데 선택자가 아무것도 못 고르면 "no connected iPhone" 이 아니라
# "matches none" 으로 실패하고 연결된 기기 목록을 보여준다 — Xcode 복구를 열지 않는다.
# <앱 이름>과 같은 target UDID를 사용한다. 출력의 Bundle Identifier를 복사한다.
xcrun devicectl device info apps \
  --device "$udid" --include-all-apps --search '<앱 이름>'
bundle_id="<위 출력의 정확한 Bundle Identifier>"
scripts/device_wda.sh doctor "$udid" "$bundle_id"
sid="$(scripts/device_wda.sh session "$udid" "$bundle_id")"
```

`device`를 먼저 실행해야 Xcode/CoreDevice 자동 복구와 기기 profile 생성이 선행된다. 그 다음 `doctor`가 Appium/xcuitest driver, Xcode·`devicectl`, 서명 team, 대상 기기·앱, iOS 18+ RemoteXPC tunnel, 빌드에 필요한 디스크 여유를 한 번에 점검한다. `device`가 성공하면 `.autobot/clone/device-profile.json`에 UDID·기기명·marketing name·product type·OS/build·연결 상태를 남기며 Step 6의 동일 기종 시뮬레이터 선택이 이를 사용한다.

`session`은 로컬 `APPIUM_URL`이 응답하지 않으면 Appium을 자동 시작하고, 같은 UDID·bundle ID·서버의 살아 있는 세션이 있으면 `.autobot/clone/wda-session.json`에서 재사용한다. 자동 시작 서버는 각 skill 명령의 shell이 끝난 뒤에도 유지되도록 현재 사용자의 launchd job이 소유하며, PID와 label을 `.autobot/clone/`에 기록한다. 자동 시작을 끄려면 `CLONE_AUTO_START_APPIUM=0`, 재사용을 끄려면 `CLONE_SESSION_REUSE=0`을 쓴다. 새 세션과 재사용 세션 모두에 성능 설정을 적용한다 — `waitForIdleTimeout=0`·`animationCoolOffTimeout=0` (clone 은 자체 settle 루프로 안정화를 판정하므로 WDA 의 idle/애니메이션 대기는 이중 대기다). 대상 앱이 idle 대기 없이 오동작하면 `CLONE_WDA_IDLE_TIMEOUT`/`CLONE_WDA_ANIM_COOLOFF`(초)로 되돌리고, 트리가 너무 커서 `/source` 가 타임아웃할 때만 `CLONE_WDA_SNAPSHOT_MAX_DEPTH` 를 쓴다(기본은 미전송 — 얕은 스냅샷은 측정이 의존하는 깊은 트리를 잘라낸다). `CLONE_WDA_TUNE=0` 으로 전체 비활성화한다. 설정 적용 실패는 경고만 남기고 세션을 막지 않는다. 이 스크립트가 시작한 서버만 `scripts/device_wda.sh stop-server`로 종료할 수 있고, 이때 launchd job과 두 상태 파일을 함께 제거한다. HTTP 병목을 계측할 때만 `CLONE_METRICS=1`을 켜며 원시 요청 시간은 `.autobot/clone/http-metrics.jsonl`에 남는다.

iOS 18+ 물리 기기는 CoreDevice의 `connected` 상태와 별도로 Appium xcuitest RemoteXPC tunnel이 필요하다. `doctor`와 `session`은 `http://127.0.0.1:42314/remotexpc/tunnels`에 **대상 UDID**가 있는지 먼저 확인한다. 이미 있으면 그대로 재사용하며 Xcode나 tunnel 프로세스를 다시 띄우지 않는다.

없으면 `doctor`가 다른 기기·서명·설치·디스크 검사를 모두 통과한 뒤 자동 준비한다. 순서는 `clone workspace 준비 → Xcode에서 프로젝트 열기(백그라운드, 빌드·실행 안 함) → RemoteXPC tunnel 시작 → registry에서 대상 UDID 확인 → WDA session`이다. Xcode 프로젝트 자체는 tunnel 명령의 입력이 아니지만, CoreDevice 연결과 개발자 서비스를 안정화하는 선행 복구 단계이므로 tunnel보다 먼저 연다.

macOS TUN 인터페이스 생성에는 관리자 권한이 필요하다. 캐시된 `sudo` 권한이 있으면 비대화식으로 시작하고, 없으면 macOS 표준 관리자 인증 창을 한 번 띄운다. 인증이 취소되거나 CI처럼 GUI를 쓸 수 없으면 기다리며 멈추지 않고 `sudo -v` 후 같은 스킬 명령을 다시 실행하라고 안내한다. 자동 시작을 끄려면 `CLONE_AUTO_START_TUNNEL=0`, GUI 인증을 끄려면 `CLONE_TUNNEL_GUI_AUTH=0`을 쓴다. custom local registry는 `CLONE_TUNNEL_REGISTRY_URL`로 지정한다. 시작 후 대상 UDID가 실제 registry에 나타나지 않으면 성공으로 간주하지 않으며 로그는 `.autobot/clone/remotexpc-tunnel.log`에 남는다.

예를 들어 Threads는 기기·릴리스에 따라 식별자가 달라질 수 있으므로 `com.instagram.barcelona`를 고정하지 않는다. 이 회차의 `heewook의 iPhone`에서는 `Threads`가 `com.burbn.barcelona`로 확인됐다. `--include-all-apps`를 생략해 앱이 보이지 않거나, 다른 기기의 목록을 보고 미설치로 결론내리면 안 된다. 대상 앱 자체는 Debug 빌드일 필요가 없으며, 기기에 설치되는 WDA runner만 개발자 서명이 필요하다.

실패 시 **중지**한다. 실패 분기와 안내는 `autobot-copy-analyze` SKILL 의 Step 2 표와 동일하다(미연결 / 다중 연결 / UI 자동화 OFF / 서명 누락 / Appium 미기동 / 대상 bundle ID 누락 또는 미설치). `screen`·`tap`·`type`·`swipe`는 매번 Appium의 active-app 정보를 세션 bundle ID와 대조하므로, 다른 앱·SpringBoard·권한 대화상자가 foreground면 중지한다.

`xcodebuild code 65`와 함께 `0xe8008001` 또는 `invalid Info.plist`가 나오면 Threads의 Debug 여부로 해석하지 않는다. 이는 WDA runner의 별도 서명·재서명 산출물 문제다. `CLONE_WDA_DEBUG=1`로 Appium 로그를 남기고, 로그에 나온 `WebDriverAgentRunner-Runner.app`에 `codesign --verify --deep --strict --verbose=4`를 실행해 WDA 서명을 먼저 검증한다. 대상 앱의 bundle ID나 설치 상태를 바꾸지 않는다.

`device_wda.sh session`은 기본적으로 Appium 패키지의 WDA를 `.autobot/clone/wda`에 격리 복사하고(`CLONE_WDA_ISOLATE=1`), 이미 서명된 Runner.app을 다시 변형하는 로컬 post-action을 no-op으로 교체한다. 같은 표시명의 개발 인증서가 키체인에 여러 개 있으면 `codesign --sign "Apple Development"`가 모호해져 위 오류가 날 수 있기 때문이다. 필요하면 `CLONE_WDA_REFRESH=1`로 복사본을 새로 만들고, 기존 전역 Appium WDA를 직접 수정하지 않는다. 레거시 동작을 명시적으로 재현해야 할 때만 `CLONE_WDA_ISOLATE=0`을 사용한다. 이 격리는 WDA runner에만 적용되고, 관찰 대상 앱의 설치·서명·bundle ID에는 적용되지 않는다.

### Step 2 — 전수 탐험 (flow 를 먼저 확보한다)

**화면 하나를 골라 재현하지 않는다.** 앱 전체를 훑어 화면과 그 사이 전이를 먼저 모으고, 그 지도를 본 뒤에 재현할 화면을 고른다. 맥락 없이 복제한 화면은 껍데기다.

`clone_run.sh observe` 가 이 단계를 끝까지 돌린다. 아래는 그 안에서 도는 명령과, 개별 진단에 쓰는 하위 명령이다.

```bash
# 기본 경로: 현재 화면의 안전 frontier를 소진하고, 소진되면 **이미 관찰한 전이를 되짚어
# 아직 소진되지 않은 화면으로 스스로 이동해** 계속한다 — 탭마다도, 화면마다도 사람이
# 개입하지 않는다. 모든 탭은 step과 같은 가드(후보 출처·fresh sig·foreground)를 거치며
# withheld 는 절대 탭하지 않는다. 스위치(AXSwitch)는 기본 withheld 다.
# 대상 앱에서 왕복 변경이 허용됨을 확인한 경우에만 CLONE_PROBE_SWITCHES=1 로 켠다.
# probe 는 탭 → 바뀐 화면 캡처 → 같은 자리 재탭(via=revert) 뒤 원래 state 복구를 검증한다.
# 전역 소진·max steps·경로 한도·가드 발동에서 멈춘다.
scripts/device_wda.sh explore "$sid" .autobot/clone/raw 200
scripts/device_flow.py next .autobot/clone/flow.jsonl     # 남은 미탐험(사람이 읽는 요약)
scripts/device_flow.py next-tap .autobot/clone/flow.jsonl <현재.xml>   # 지금 할 탭 하나
# 수동 경로는 진단·이동용:
scripts/device_wda.sh screen "$sid" .autobot/clone/raw <NN>-<screen>
scripts/device_wda.sh candidates .autobot/clone/raw/<NN>-<screen>.xml
scripts/device_wda.sh step "$sid" <x> <y> \
  .autobot/clone/raw/<NN>-<screen>.xml .autobot/clone/raw <NN>-<destination>
scripts/device_wda.sh type "$sid" <accessibility-id> <text>  # 입력값은 flow에 기록하지 않음
```

탐험 규율·STOP 조건은 `autobot-copy-analyze` Step 3 과 **동일하며 같은 코드가 강제한다** — 접근성 트리를 먼저 읽고 semantic text input을 사용하며, 좌표 탭은 후보·현재 화면 서명이 일치할 때만 허용한다. 파괴적 라벨은 후보에서 제외하고, 모달이면 후보 0개로 중지한다. clone 에서 달라지는 건 셋:

**⓪ 화면 사이 이동도 자동이다.** `next-tap` 이 한 번에 탭 하나를 답한다 — 이 화면에 미탐험 후보가 있으면 그것, 없으면 **미탐험 화면까지의 최단 관찰 경로의 첫 홉**이다. 이 캡처가 소진됐다는 것과 탐험이 끝났다는 것은 다른 주장이므로(같은 화면의 다른 스크롤 위치에만 있는 후보), 전자는 "이 캡처에 남은 탭 없음"으로, 후자만 "frontier empty"로 말한다. 경로 홉은 정의상 이미 탭해 본 전이이므로 `todo` 가 제외하는 대상이고, 그래서 별도 질의가 필요하다. 좌표는 항상 **지금 화면의 fresh 트리**에서 다시 읽으므로 낡은 좌표 가드가 그대로 적용된다. 도착이 예상과 다르면 다음 반복이 현재 상태에서 다시 계획한다. 경로 홉만 연속 `CLONE_EXPLORE_MAX_ROUTE`(기본 12)회면 ping-pong 으로 보고 멈춘다. **경로 홉도 `max_steps` 를 소비한다** — 앱 전체를 도는 값(기본 경로는 200)을 준다.

**⓪-3 실행은 자신이 무엇을 눌렀는지 감사한다.** `observe` 는 끝에 `device_flow.py audit` 로 **실제로 탭한 것**을 지금의 가드로 다시 판정하고, 상태 변경 대상이 하나라도 있으면 non-zero 로 끝난다. 가드의 구멍은 열려 있는 동안 보이지 않는다 — 탭이 그냥 성공하기 때문이다. 실측 2026-08-22: 두 번의 실행이 사용자의 실제 Threads 계정으로 남의 게시물에 좋아요·공유를 눌렀고, 로그를 손으로 감사하고 나서야 드러났다. 원인은 `STATE_CHANGING` 패턴이 라벨 **끝**에 앵커돼 있는데 실제 라벨은 `좋아요. 226명이 이 게시물을 좋아합니다.` 처럼 **액션 이름 + 설명문**이었던 것. 감사가 실패하면 탐험을 재개하기 전에 가드를 고치고, **사용자에게 계정에서 무엇이 바뀌었는지 알린다.**

**⓪-4 화면을 떠난 것은 도착한 것이 아니다.** 탭 뒤의 settle 은 statekey 가 처음 달라진 순간이 아니라 **새 state 가 유지될 때까지** 기다린다. 탭한 화면 위의 스피너도, 목적 화면의 첫 렌더도 이미 다른 state 이므로, 먼저 끊으면 존재한 적 없는 화면이 목적지 증거가 되고 Step 3 가 그것을 측정한다(실측 2026-08-23: 28개 중 2개). 그런 유령은 로그에서 **단일 캡처 + 나가는 전이 0** 으로 보인다. 한도 안에 안정되지 않으면 탭 자체는 `evidence=unstable`로 남기되 도착 화면을 durable로 저장하지 않고 non-zero로 중단한다. `CLONE_TAP_SETTLE_TRIES`/`CLONE_TAP_SETTLE_QUIET` 로 한도를 조정한다.

**⓪-2 목록은 스크롤해서 끝까지 본다.** 이 캡처에 탭할 것이 없다는 것은 앱을 다 봤다는 뜻이 아니다 — 목록은 다른 스크롤 위치에만 있는 타깃을 갖는다. 탭할 후보가 하나도 없을 때만(=원래 멈췄을 자리에서만) 스크롤 후 재캡처하고 다시 고른다. `frontier` 는 한 state 의 모든 캡처의 후보를 합치므로 새 캡처의 후보가 곧바로 탐험 대상이 된다. 화면당 `CLONE_EXPLORE_MAX_SCROLL`(기본 6)회, 그리고 **화면이 실제로 움직이지 않으면 그 자리가 끝**이다(무한 피드가 실행을 독점하지 못한다). 스크롤 시도는 움직이지 않았어도 `swipe`+`screen` 으로 기록한다 — "봤는데 더 없었다"도 결과다. 이것 없이는 피드 앱 탐험이 첫 화면분에서 끝난다: Threads 실측(2026-08-22)에서 타깃 235개 중 34개, 나머지는 **애초에 어떤 캡처에도 없었다**.

**⓪-1 화면이 움직이는 것은 정상이다.** 캡처와 탭 사이에 화면이 바뀌면 그 탭만 버리고 재캡처해서 다시 고른다(연속 `CLONE_EXPLORE_MAX_STALE`, 기본 5회까지). 탭은 아직 일어나지 않았으므로 재시도가 실기기를 두 번 누르지 않는다 — 탭 **이후** 실패는 여전히 치명적이다. 화면 정체성은 `statekey` 로 판정한다. 라벨 집합(`sig`)으로 판정하면 라이브 앱에서 탐험이 통째로 죽는다: Threads 실측(2026-08-22)에서 좋아요 수가 226 → 227 로 오르는 것만으로 후보 43개가 전부 거절돼 0 step 으로 끝났다.

**① 전이가 자동으로 기록된다.** `explore`·`screen`·`step`·`tap`·`swipe`가 `.autobot/clone/flow.jsonl` 에 한 줄씩 남긴다 — 손으로 적는 게 아니다. 기본 경로는 `explore`(내부적으로 `step` 반복)이고, 개별 탭은 `step`이다. 탭, settle에 사용한 최종 XML 재사용, 도착 스크린샷, 원자적 파일 교체, 전이·화면 이벤트 기록을 한 명령으로 닫아 추가 `/source` 왕복과 캡처 누락을 없앤다. 저수준 `tap`은 디버깅용으로만 두며, `changed=true`인데 별도 `screen`이 없으면 여전히 `incomplete`다. 끝내 바뀌지 않은 동작도 `changed=false`로 기록한다.

**② 화면 정체성은 세 층이다.** `sig`(라벨 집합 해시)는 stale-coordinate 탭 가드, `node`/`nodekey`는 데이터 변화·스크롤을 흡수하는 coarse 구조, `state`/`statekey`는 키보드·포커스·선택·모달을 포함하는 상호작용 상태다. flow와 생성 라우터는 `state`를 우선하고 옛 로그의 `node`로 fallback한다. 같은 coarse node라도 검색 포커스 전후는 다른 상태이므로 기능 복제에서 사라지지 않는다.

**③ 후보 수와 커버리지는 안전성을 포함한다.** 역할·actionable trait가 없는 설명문, `AXKey`/`KeyboardKey`와 키보드 하위 요소는 후보가 아니다. 팔로우·언팔로우·좋아요·리포스트·게시·전송·추천 숨기기 등 계정이나 콘텐츠를 바꾸는 동작은 `withheld`로 분류해 자동 탭하지 않는다. 스위치(`AXSwitch`)도 로컬 설정과 계정 설정을 구분할 수 없어 기본 withheld 다. 왕복 변경이 허용된 대상에서만 `CLONE_PROBE_SWITCHES=1`로 `reversible` probe를 켠다(아래 ⑤). 라벨이 서버 동작으로 분류되면 역할이 스위치여도 probe하지 않는다. `stats`는 실제 좌표 단위 raw target coverage와 반복 행을 묶은 behavior-class coverage를 둘 다 보여주고, 완료 판정은 안전한 behavior class 기준으로 한다.

**④ 중단은 실패가 아니라 정상 종료다.** 실기기에서는 세션 만료·잠금·로그인 벽 중 하나에 반드시 걸린다. 완주가 예외고 중단이 기본이다. 그래서 **재개가 1급 경로**다 — `device_flow.py next` 가 로그를 읽어 미방문 후보를 복원하므로, 새 세션을 열고 이어서 탐험한다. 처음부터 다시 하지 않는다.

**데이터가 필요한 화면**: 읽기 전용으로는 빈 상태밖에 못 보는 지점이 나온다(항목 0개인 목록의 채워진 레이아웃). **기본값은 멈추지 않는다** — 그 화면을 flow 맵과 스펙에 `데이터 필요` 로 남기고 계속한다. 에이전트가 데이터를 대신 만들지 않는다: 사용자의 실제 기기이고, 삭제는 파괴적 라벨이라 되돌릴 수도 없다. 채워진 레이아웃까지 재현해야 할 때만 `CLONE_ASK_FOR_DATA=1` 로 한 번 멈춰 "항목 1개만 직접 만들어 주세요"를 요청하고 재개한다.

**커버리지를 숨기지 않는다.** `device_flow.py stats`가 raw target과 behavior class를 따로 낸다. raw 6/30 또는 class 4/12를 탐험하고 "전수 완료"라고 말하지 않는다. withheld는 안전한 미탐험 작업으로 세지 않는다. 후보가 모두 탭됐더라도 변경된 탭/스와이프의 도착 화면 캡처가 없거나 접근성 트리가 빠졌으면 `incomplete`이며, 재현 완료로 보고하지 않는다.

**탐험이 끝나는 조건은 "이 화면에 할 게 없다"가 아니다.** `explore` 는 한 화면이 마르면 ① 텍스트 필드에 probe 를 한 번 입력해 보고(검색 결과 화면은 키보드 너머에만 있다) ② 스크롤해 보고 ③ 관측된 경로로 미탐험 화면에 가고 ④ 그 길도 없으면 **앱을 재시작**해 초기 화면에서 이어간다. 종료는 전역 frontier 소진·max steps·재시작 한도(`CLONE_EXPLORE_MAX_RESTART`, 기본 8)뿐이다. 관측되지 않은 버튼은 재현본에서 아무 일도 하지 않으므로, 커버리지가 곧 재현본의 기능이다.

**⑤ 스위치는 명시적으로 켠 경우에만 probe 하고 복구를 증명한다.** 스위치를 withheld 로 두면 재현본의 토글 동작은 미관측으로 남지만, 트리는 로컬 토글과 계정 설정을 구분하지 못한다(Threads 의 `비공개 프로필` 은 Switch 다). 그래서 기본은 계정 쓰기 0을 지키는 withheld다. 대상 앱에서 왕복 변경이 허용됨을 확인한 경우에만 `CLONE_PROBE_SWITCHES=1`을 설정한다. 이때 `explore`는 스위치를 탭해 바뀐 화면을 캡처하고 같은 좌표·같은 behavior를 즉시 재탭한 뒤 **도착 state가 시작 state와 같은지 검증한다.** 복구 실패·다른 컨트롤·다른 state이면 라벨과 좌표를 ERROR로 알리고 non-zero로 중단한다. 성공한 경우에만 `base → flipped`와 `flipped → base`(`via=revert`)가 남는다. 세그먼트·슬라이더는 기존 navigation 후보이고 텍스트 입력은 ①의 probe가 맡는다.

**관측하지 않는 것도 있다 — 의도적으로.** 좋아요·팔로우·게시·공유 같은 상태 변경(`withheld`)은 절대 탭하지 않는다. 그 버튼들은 재현본에서도 죽어 있고, 그게 맞다. `device_flow.py stats` 가 몇 개인지 센다.

### Step 2a — flow 맵 (사람이 보는 지점)

```bash
scripts/device_flow.py map .autobot/clone/flow.jsonl .autobot/clone/flow-map.html
open .autobot/clone/flow-map.html
```

화면 썸네일을 진입 화면으로부터의 깊이별로 놓고, 어떤 탭이 어디로 가는지와 **미탐험 후보**를 함께 보여준다. `observe` 가 매번 다시 생성하며, **이 지점에서 멈추지 않는다** — 사람이 보는 창이지 게이트가 아니다. 더 탐험할 곳이 남았으면 `observe` 를 다시 실행하는 것이 답이고, 지도를 보고 결정할 필요가 없다.

### Step 2b — 역기획 (mvp 인수인계 · 완주 경로 밖)

관찰과 해석을 섞지 않는다.

`.autobot/clone/reverse-brief.md` 에 **두 섹션으로** 쓴다. 섞으면 다음 사람이 사실과 내 추측을 구분할 수 없고, 그 문서가 `/autobot:mvp` 입력이 되면 추측이 명세가 된다.

- `## 관찰` — flow 로그와 측정에서 **그대로 나온 것만**. 진입 화면, 루트에서 한 탭 거리에 있는 것, 몇 탭을 들어가야 나오는 것, 어느 화면이 어디로 이어지는지, 화면별 요소 수·강조 색.
- `## 해석` — 왜 이렇게 만들었나. 항목마다 **어느 관찰에서 나왔는지 표시한다**. 근거 없는 문장은 쓰지 않는다.

읽는 범위는 **flow 그래프와 측정된 화면까지**다. App Store 리뷰·평점은 `copy` 의 입력이다 — 끌어오면 두 스킬 경계가 무너진다.

### Step 2c — 재현 대상

**기본값: 내구 증거(트리 + 스크린샷 + 측정 JSON)가 있는 모든 화면을 재현한다.** 고르는 데 사람을 부르지 않는다 — 증거가 있으면 재현하고, 없으면 스펙만 남긴다. `views.json` 이 그 목록이고, `clone_run.sh verify` 가 정확히 그 목록을 검증한다.

`views.json` 은 **관찰된 모든 state 를 덮어야 한다** — `clone_flow_codegen.py generate` 는 매핑이 빠진 state 에서 추측하지 않고 실패한다. 그리고 `device_render.sh` 는 `Sources/` 를 한 덩어리로 컴파일하므로, **아직 쓰지 않은 뷰가 하나만 있어도 모든 화면의 렌더가 실패한다**. 그래서 `verify` 는 렌더 전에 정의가 없는 타입을 먼저 이름으로 알린다 — 같은 컴파일 오류 24개를 읽게 두지 않는다.

범위를 좁혀야 하면 항목을 **지우지 말고**(지우면 라우터 생성이 실패한다) 그 화면의 뷰를 원본 크기 자리표시자로 두고, 스펙의 "재현 불가 항목"에 이유를 적는다.

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
- **미커버 영역** — 스크린샷에서 배경이 아닌데 측정된 어떤 요소의 프레임에도 덮이지 않는 영역을 `uncoveredRegions` 로 낸다(시스템 크롬 상·하단 밴드는 제외). 지배적 실패인 **요소 누락**(Step 6-4)과 크롬 필터가 콘텐츠까지 버린 사고를 측정 단계에서 잡는 장치다. WARN 이 나오면 스크린샷과 대조해 원인을 확인한 뒤 스펙을 쓴다 — 무시하고 넘어가면 누락이 재현본까지 전파된다. 모달 화면은 예외적으로 이 경고가 정상이다: iOS 가 시트 뒤를 접근성 트리에서 감추므로 배경 전체가 미커버로 잡히고, 그 영역의 crop 은 글자를 글리프 조각으로 자른다. 그래서 `clone_view_codegen.py` 는 어떤 측정 요소도 겹치지 않는 32pt 이하 미커버 crop 을 뷰에 싣지 않는다(빈 영역이 조각보다 낫다 — 조각은 레이아웃 버그로 읽힌다. 실측 2026-08-23).
- **구조** — 접근성 트리의 부모-자식에서 스택 방향(`vstack`/`hstack`/`zstack`)과 형제 간 간격을 계산해 `layout` 으로 낸다. 축은 형제가 **겹치지 않는** 쪽이다(양수 간격 합이 아니라 겹침이 신호 — 6pt 겹친 두 줄은 zstack 이 아니라 vstack 이다). 버리는 것 셋: 라벨 없는 전체화면 래퍼(자식은 살아남은 조상에 재부착), 스크롤 막대 같은 크롬(**자식까지 함께** — 그 자식은 스크롤 막대 부품이지 콘텐츠가 아니다), WDA 가 창을 둘로 보고해 생기는 완전 중복 요소. 셋 다 안 버리면 카드 4장이 16pt 간격인 화면이 "spacing 147" 로 나온다(실측).
  카드 자신의 배경은 부모를 꽉 채워 모든 형제와 겹치므로 간격 계산에서 뺀다 — 안 그러면 한 줄의 간격이 `-343` 으로 잡힌다.

측정값은 JSON 으로 남긴다. 이후 단계는 이 JSON 만 보고 코드를 쓴다 — 스크린샷을 눈으로 보고 "대충 이 정도"로 쓰지 않는다.

### Step 3a — 반복 단위 (측정이 표현하지 못하는 층)

측정은 요소의 평면 목록이다. 피드의 카드 30장은 그 안에서 **독립된 30개 뭉치**이고, `clone_view_codegen.py` 는 그것을 충실하게 30개의 절대좌표 블록으로 재생한다. 그 산출물은 요소 누락 검사도 대조도 통과하지만 사람이 손댈 수 있는 코드가 아니다 — 유일하게 말하지 않는 것이 **"이건 카드 하나가 서른 번"** 이기 때문이다.

이 층은 측정할 수 없지만 **유도할 수는 있다**: 같은 모양의 형제가 한 축을 따라 일정한 간격으로 놓여 있으면 반복이다. `codegen` 이 화면마다 초안을 쓴다.

```bash
python3 scripts/clone_structure.py .autobot/clone   # codegen 이 이미 실행함
```

- **모양만 비교하고 내용은 절대 비교하지 않는다.** 실제 피드에서 항상 다른 유일한 것이 항목별 텍스트라, 라벨이나 폭이 같기를 요구하면 아무것도 찾지 못한다. 그래서 텍스트 요소는 높이만 본다(폭은 내용이지 모양이 아니다).
- **모양만으로는 패턴이 아니다.** 같은 모양이 불규칙한 간격으로 흩어져 있으면 그냥 블록 셋이다. 없는 `ForEach` 를 만드는 것은 자신 있게 읽히는 **구조적 거짓말**이라 없는 것보다 나쁘다. 그래서 규칙적인 pitch(허용 오차 2pt 또는 2%)와 연속 3개 이상을 함께 요구한다.
- **소유권 경계는 생성 뷰와 같다.** `generated_by_clone_structure` 키가 있으면 기계 초안이고 매 실행 덮어쓴다. 키를 지우면 그 파일은 사람 것이고 이후 어떤 실행도 건드리지 않는다. 이게 없으면 확인 단계가 무의미하다 — 다음 `observe` 가 사람의 수정을 지운다.
- `component` 는 **제안된 이름**이다. 바꾸는 것이 정상이다.

**확인된 그룹은 코드가 된다.** `clone_view_codegen.py` 가 이 파일을 읽어, 반복 단위를 **컴포넌트 하나 + `ForEach`** 로 내보낸다. 요소의 좌표는 항목 원점 기준 상대값이 되고 원점은 별도 배열로 나가므로, 화면은 픽셀 단위로 동일하면서 코드는 "카드 하나가 N번"이라고 말한다. **컴포넌트를 한 번 고치면 모든 인스턴스가 따라온다** — 그것이 이 층이 존재하는 이유 전부다.

지키는 것 둘:
- **요소를 하나도 잃지 않는다.** 재구조화가 요소를 떨어뜨리면 가독성 문제를 지배적 재현 실패(요소 누락)와 맞바꾸는 것이라 어떤 값에도 나쁜 거래다. 이동 중 요소 id 는 보존되고, 테스트가 총량을 고정한다.
- **구조 파일이 없으면 출력은 한 글자도 바뀌지 않는다.** 추출은 증거에 대한 opt-in 이지 생성기의 추측이 아니다. 스크롤 경계를 걸치는 그룹, 이미 다른 그룹이 가져간 요소, id 가 다 있지 않은 그룹은 재구조화하지 않고 평면으로 남긴다.

### Step 4 — 화면 스펙 (mvp 인수인계 · 완주 경로 밖)

화면당 스펙을 쓴다. **쓰는 곳은 `.autobot/clone/specs/<ViewName>.md` 다** — `screens/<NN>-<screen>.md` 는 `clone_postprocess.py` 가 소유하는 *측정 증거*이고 실행할 때마다 결정적으로 덮어쓰므로, 거기 쓴 동작 계약은 다음 `observe` 에서 사라진다(생성 뷰의 `// Generated by` 같은 소유권 표시가 그 파일에는 없다). 스펙은 증거를 **링크**하고 복사하지 않는다 — 요소 표·프레임·색의 SSOT 는 측정 JSON 하나다.

최소 포함:

- 스크린샷 임베드 + 측정 JSON 링크
- **요소 표**: 역할 · 텍스트 · 프레임(x,y,w,h) · 색 · 텍스트 스타일
- **레이아웃 트리**: 어떤 스택에 무엇이 어떤 간격으로 들어가는지
- **동작 계약**: 이 화면이 *무엇을 하는가*. 요소별로 — 탭하면 어느 화면(sig)으로 가는지, 무엇이 바뀌는지, 어떤 상태(빈/채워짐/로딩/에러)에서 무엇이 보이는지. **기능 동일성은 여기서 나온다** — 이 표가 곧 `/autobot:mvp` 가 읽는 기능 명세이므로, 화면이 하는 일을 빠뜨리면 재현본은 껍데기가 된다.
  **모든 행은 근거 열을 갖는다.** 실제로 탭해 본 전이만 실측이고(`sig A → sig B`), 라벨을 보고 짐작한 것은 `미탐험` 으로 표시한다. `CLONE_PROBE_SWITCHES=1`로 복구까지 검증한 스위치만 양방향 실측이다(`base → flipped`, `flipped → base`). 기본 경로의 스위치 행은 `미탐험`이다. 짐작을 실측처럼 적으면 `/autobot:mvp` 가 그걸 명세로 믿고 구현한다 — 이 레포가 같은 실패(존재하지 않는 능력을 문서가 전제)를 이미 세 번 겪었다. `미탐험` 행은 명세가 아니라 미확인 가설이다.
- **재현 불가 항목**: 접근 가능한 원본 파일이 없는 바이너리 에셋, 커스텀 폰트, 애니메이션 타이밍 등 측정으로 알 수 없는 것을 명시한다. 연구용 캡처 crop을 썼다면 원본 바이너리가 아니라는 점과 품질 손실을 적는다. 숨기지 않는다. 룩앤필에 필요해서 **근사한 값(모서리 반경 등)은 근사라고 적는다** — 측정값과 섞이면 다음 사람이 구분할 수 없다.
- **자산 출처**: 연구용 원본 자산을 사용한 화면은 `assets/manifest.json`의 파일명·출처 캡처·원본 프레임·획득 방법·`research-only` 범위를 링크한다.

### Step 5 — SwiftUI 재현

**초안은 기계가 쓴다.** `observe` 가 끝나면 `scripts/clone_view_codegen.py` 가 측정 JSON 하나당 뷰 하나를 이미 생성해 뒀다 — 측정된 프레임 그대로, 측정된 색·글자 크기 그대로, 접근성 라벨 그대로. 빈 자리표시자에서 시작하면 `verify` 가 모든 화면에 대해 같은 말("전부 누락")만 하고 어느 화면이 가까운지 알 수 없다. 지배적 실패인 **요소 누락**(DCGen 85.3%)은 측정으로 기계적으로 닫을 수 있는 유일한 실패다.

```bash
python3 scripts/clone_view_codegen.py .autobot/clone   # observe 가 이미 실행함
```

생성물은 **측정 재생**이다 — 요소를 측정 프레임에 그대로, 스크롤 컨테이너의 자손은 `ScrollView` 안에, 크롬은 밖에 고정, 루트 캔버스는 기기 크기에 aspect-fit. 사람이 할 일은 처음부터 쓰는 것이 아니라 여기서부터 의미 있는 구조로 옮기는 것이다. 파일 첫 줄의 `// Generated by clone_view_codegen.py` 를 지우면 그 화면은 손질본으로 간주되어 **다시 생성되지 않는다** — 이것이 소유권 경계다.

손질할 때 지키는 것:

- 측정된 수치를 **그대로** 쓴다 — `.padding(16)` 이 아니라 측정값이 20이면 `.padding(20)`.
- 색은 측정 팔레트를 `Color` 상수로 뽑아 쓴다.
- 화면은 관찰된 액션을 `onAction: (String) -> Void = { _ in }` 하나로 노출한다. flow에 실제로 기록된 화면 전이는 clone이 재생해야 할 UI 동작이므로 상태 라우터를 생성하지만, 네트워크·계정 변경·게시·결제 같은 백엔드/비즈니스 로직은 만들지 않는다. 미탐험·withheld 동작을 추측해 구현하지 않는다.
- 출처를 기록한 원본 자산이 있으면 `.xcassets`에 넣고 실제 화면에서 소비한다. 캡처 crop이면 원본 프레임·해상도 손실을 주석으로 남긴다.
- 원본 자산을 확보하지 못하면 `Rectangle().fill(.secondary)` + 크기 고정 자리표시자를 넣고 원본 크기를 남긴다.
- 이름·문구·로고도 확보 경로와 출처를 기록하고 `research-only` 범위에서 사용한다.

관찰된 전이를 실제 clone 화면에 연결한다:

`observe` 가 `views.json`(state → Swift 뷰 타입)을 이미 생성해 뒀다 — **검토를 기다리지 않고 그대로 쓴다.** 타입 이름이 마음에 들지 않을 때만 고치고, 항목은 지우지 않는다(Step 2c). 추측이 필요한 경우(같은 state/action 이 여러 목적지로 관찰됨, 매핑 누락)는 `generate` 가 실패로 알리므로, 사람 검토를 선행 조건으로 둘 이유가 없다.

```bash
# observe 가 이미 실행한 것 (파일이 없을 때만):
python3 scripts/clone_flow_codegen.py manifest \
  .autobot/clone/flow.jsonl .autobot/clone/views.json
python3 scripts/clone_flow_codegen.py generate \
  .autobot/clone/flow.jsonl .autobot/clone/views.json \
  .autobot/clone/Sources/ObservedFlow.swift
```

생성물은 `ObservableObject` router, 관찰된 전이 표, `send(action:)`, 현재 state에 맞는 root switch, 그리고 **히스토리 스택**을 제공한다.

**관측 한 번이 여러 화면을 살린다 — 단, 구조가 허락할 때만.** 탭바처럼 **도착 화면에도 그대로 남아 있는** 컨트롤은 한 화면에서 관측한 전이를 같은 컨트롤(라벨+역할+8pt 프레임 격자)이 있는 다른 화면에도 적용한다(`inferred`). 뒤로가기·닫기는 도착 화면에 없으므로 추론되지 않는다 — 라벨 사전이 아니라 구조로 거른다. 추론은 앱에서 본 적 없는 전이이므로 라우터에 표시되고 게이트가 따로 센다.

**뒤로가기는 고정 목적지가 없다.** 한 액션의 목적지가 여럿 관찰됐을 때, 그 전부가 **이 화면에 도달했던 출발지**라면 모순이 아니라 pop 이다 — 앱이 스택을 갖고 있으므로 라우터도 갖는다. 목적지 중 하나라도 와 본 적 없는 곳이면 **여전히 추측하지 않고 실패한다.** 화면 매핑이 빠져도 실패한다.

**한 화면이 두 state 로 갈라지는 경우는 사람이 선언한다.** 라이브 앱은 같은 화면을 로딩 중에 한 번, 다 뜬 뒤에 또 한 번 캡처한다 — 요소 수가 달라 state 키가 갈라지고, 하나뿐인 액션이 목적지 둘을 가진 것처럼 보인다(실측 2026-08-23: Threads 프로필 `auto-0050`/`auto-0052`). 로그만으로는 둘이 같은 화면인지 알 수 없으므로 추측하지 않는다. 두 캡처를 사람이 읽고 같은 화면임을 확인했으면 `.autobot/clone/state-aliases.json` 에 선언한다:

```json
{"version": 1,
 "aliases": {"<갈라진 state>": {"canonical": "<대표 state>", "why": "두 캡처를 비교한 근거"}}}
```

`load_flow` 가 이 파일을 읽어 모든 소비자(전이 추출·캡처 선택·탭 좌표·기능 워크)에 같은 이름을 준다. **`flow.jsonl` 은 증거이므로 절대 고쳐 쓰지 않는다.** 한 홉만 허용하며(체인·자기 참조는 실패), `why` 없이 선언하는 것은 추측을 명세로 올리는 것과 같다. 생성 뷰와 root는 Step 6에서 인자 없이 렌더할 수 있도록 기본값 계약을 유지한다.

### Step 6a — 기능 게이트 (픽셀보다 먼저)

```bash
scripts/clone_run.sh functional
```

한 번 빌드하고, 재현본을 시뮬레이터에 띄우고, `ObservedFlow` 의 전이를 **앱 안에서 실제로 탭한다**. 탭은 요소 프레임을 읽어 **드라이버의 좌표 드리프트를 보정한 좌표**로 한다 — 12/13 mini 시뮬레이터는 렌더 버퍼를 패널로 다운샘플해 AXe 의 탭이 y 에 비례해 아래로 밀린다(실기기 손가락엔 없는 문제)
(`scripts/clone_functional.py <clone-root> <simulator-udid>` — 한 화면만 진단할 때 직접 쓴다). 도착한 화면은 각 뷰가 내보내는 `clone-state:<statekey>` 라벨로 읽는다. 결과는 두 숫자다 — 배선된 전이 수, 도달 가능한 화면 수. 전이에 구멍이 있으면 non-zero 이고, 그 화면의 픽셀 작업은 **아직 할 때가 아니다**.

**이 게이트가 증명하는 것과 아닌 것.** 라우터 표·뷰의 탭 타깃·워크가 검사하는 엣지 목록은 모두 `clone_flow_codegen.observed_transitions` 한 곳에서 나온다. 그래서 이것은 **재현본의 내비게이션 배선이 관측 로그와 일치하는지**를 앱 안에서 실측하는 것이지, 대상 앱과 동작이 같은지를 재는 것이 아니다. 그래도 값이 있다 — 기계적으로 깨지는 것들(중복 라벨로 드라이버가 탭 거부, 터치가 닿지 않는 3pt·18pt 타깃, 히트 테스트를 가로채는 레이어)은 정확히 여기서만 드러난다.

관측된 전이의 라벨이 그 화면의 캡처에 없으면 기록된 탭 좌표에 타깃을 **합성**한다. 이건 캡처가 담고 있던 요소보다 약한 증거이므로, 생성기와 워크가 **몇 개인지 세어 말한다**(`N of them on a target synthesised at a recorded tap point`). 그 수가 크면 재현 대상 캡처가 실행이 탐험한 화면과 어긋나 있다는 신호다.

### Step 6b — 대조 검증 (재현을 주장하기 전에)

재현했다고 말하려면 **원본과 재현본을 나란히 보여준다.**

```bash
scripts/clone_run.sh polish              # 뷰가 있는 화면 전부
scripts/clone_run.sh polish auto-0001    # 한 화면만 (측정 stem 또는 뷰 이름)
```

**시각 점수는 게이트다 — 조언이 아니다.** `polish` 는 `--max-mismatch`(기본 `0.30`, `CLONE_MAX_MISMATCH` 로 조정)로 대조를 돌리고, 마스킹 후 mismatch 가 그 값을 넘으면 그 화면은 **실패**한다. 2026-08-24 이전에는 이 점수가 `advisory` 라 출력만 되고 버려졌고, 그래서 원본과 닮지 않은 화면도 `polish` 가 통과시켰다 — 수렴 루프가 시작조차 하지 않았다. 기본값 `0.30` 은 **총체적 실패의 하한이지 유사도 목표가 아니다**: 시스템 크롬과 캡처 crop 을 이미 제외하고 픽셀당 24/765 허용치가 안티에일리어싱을 흡수한 뒤에도 남은 픽셀의 3분의 1이 다르다면 그것은 잡음이 아니라 콘텐츠가 없거나 엉뚱한 자리에 있는 것이다. 실제 회차의 분포가 쌓이기 전이라 일부러 느슨하게 뒀다 — **조이는 것은 측정한 뒤에 하고, 조일 때 그 측정을 남긴다.**
마스킹으로 비교할 픽셀이 하나도 남지 않은 화면도 **실패**다. 아무것도 비교하지 않은 것은 통과가 아니라 미검증이고, 그것을 통과로 세는 것이 이 스킬이 금지하는 커버리지 은폐다(규칙 6).

**점수를 두 겹으로 읽는다.** 캡처 crop 은 대조 대상인 바로 그 원본에서 잘렸으므로 그 영역의 mismatch 는 구조적으로 0 이다. `polish` 는 crop 을 제외하고 재며(`--mask-assets`), 로그가 제외 면적을 먼저 말한다 — 그 비율이 크면 점수는 "재현이 좋다"가 아니라 "crop 을 제자리에 놓았다"에 가깝다.

**반복 비용을 아는 것도 절차의 일부다.** 한 번 고치고 다시 재는 데 드는 것은 빌드 한 번 + 화면당 렌더·대조다.
- `polish <화면>` — 한 화면만. 고치는 중에는 이걸 쓴다.
- `CLONE_COMPARE_WORKERS`(기본 4) — 대조는 시뮬레이터가 필요 없어 병렬로 돈다.
- `CLONE_RENDER_CACHE_KEEP`(기본 12) — 캐시 항목마다 캡처 crop 이 실리므로 상한이 있다. 디스크가 차면 이 레포는 그것을 SwiftUI 컴파일 오류로 읽은 전례가 있다.
- 생성 뷰는 요소를 **JSON 문자열**로 싣는다. Swift 배열 리터럴로 두면 타입 체크만 몇 분이다.

**지표가 정체되면 대조 이미지를 연다.** 이 스킬의 기준은 "나란히 놓으면 같은 화면"이고 그 판정은 사람 눈이 한다. 실제로 이 회차에서 아이콘이 통째로 빠진 것은 숫자가 아니라 이미지로 드러났다 — 아이콘은 접근성 트리에 그림이 아니라 설명으로만 있어 측정으로 재현할 수 없고, 캡처 crop 이 유일한 경로다.

`polish` 는 렌더 루프에 들어가기 **전에** 시뮬레이터를 한 번 확정한다 — 시뮬레이터는 실행의 속성이지 화면의 속성이 아니므로, 없으면 화면 수만큼 반복되는 렌더 실패가 아니라 한 번의 환경 실패로 끝난다. `auto` 는 시뮬레이터 **이름이 아니라 기기 종류**(`deviceTypeIdentifier`)로 고르므로 `simctl create clone-probe ...` 처럼 임의로 이름 붙인 것도 선택된다. 여러 개 중 하나를 고정하려면 `CLONE_RENDER_SIMULATOR=<udid|name>` 를 쓴다(`scripts/device_render.sh resolve-simulator` 가 `auto` 의 선택 결과만 출력한다).

`views.json` 의 화면마다 렌더 → 구조 diff → 대조를 한 번에 돌리고, 요소 누락·렌더 실패·**시각 mismatch 초과**가 하나라도 있으면 **non-zero** 로 끝난다. `<NN>` 을 손으로 갈아 끼우며 화면마다 세 명령을 반복하지 않는다 — 그렇게 하면 어느 화면을 빠뜨렸는지 아무도 모른다. 아래 1–3은 `verify` 가 화면마다 실행하는 내용이며, **한 화면만 진단할 때** 직접 쓴다.

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

4. **누락부터 센다.** 이 작업의 지배적 실패는 색이나 간격이 아니라 **요소가 통째로 빠지는 것**이다 — screenshot-to-code 연구(DCGen, arXiv 2406.16386)가 분류한 실패 1,699건 중 누락 85.3%, 배치 오류 12.7%, 왜곡 2.6%였다. 세기는 기계가 먼저 한다: AXe 가 설치돼 있으면 `device_render.sh` 가 렌더된 접근성 트리를 `<out>.tree.json` 으로 남기므로,
   ```bash
   python3 scripts/clone_structural_diff.py .autobot/clone/screens/<NN>.json \
           .autobot/clone/compare/<NN>-rendered.tree.json
   ```
   가 스펙 요소마다 렌더 대응물을 라벨→프레임 순으로 찾고, **누락이 하나라도 있으면 exit 1** 로 수렴 루프를 되돌린다(위치 이탈은 WARN, 픽셀 유사도는 여전히 `device_compare` 몫). 이 diff 는 라벨→프레임 매칭이라 **좌표만 맞으면 잘린 글리프 조각도 present 로 센다** — "누락 0" 은 대조 이미지를 연 뒤에만 재현의 증거다(실측 2026-08-23: 글자 조각이 흩어진 화면이 all-present 로 통과했다). 트리 덤프가 없거나 그 후에도, **Step 4 요소 표의 행을 하나씩 짚어** 재현본에 있는지 사람이 다시 센다. 우리 측정 단계는 크롬을 버리므로(Step 3) 콘텐츠를 같이 버렸을 위험이 특히 크다 — Step 3 의 `uncoveredRegions` 경고가 남아 있는 화면이면 더더욱.

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

### Step 6c — 실기기 설치: 이름은 원본, 식별자는 clone 의 것

```bash
scripts/clone_run.sh install [RootView]     # 기본 RootView = ObservedFlowRootView
```

시뮬레이터에만 있는 클론은 손에 쥘 수 있는 앱의 클론이 아니다. `install` 은 생성 뷰를 `clone_device_project.py` 가 만든 최소 프로젝트로 묶어 서명·설치한다. **스펙은 둘이다:**

- **홈 화면 이름 = 원본 앱 이름.** `observe` 가 후보 bundle ID를 기존 `target.json`과 대조하고, doctor와 WDA session이 그 대상에 바인딩된 뒤 기기가 보고한 이름을 원자적으로 기록한다(`{"bundleId","name","resolvedBy","query"}`). 기존 root가 다른 bundle ID에 묶여 있으면 별도 `CLONE_ROOT`를 요구한다. `install`은 그 `name`을 `CFBundleDisplayName`으로 넣는다. 사용자가 입력한 검색어가 아니라 **기기가 보고한 이름**이다. `CLONE_APP_DISPLAY_NAME`으로 덮어쓴다. `target.json`이 없으면(옛 observe 로그) WARN과 함께 `CloneApp`으로 설치하고 멈추지 않는다.
- **bundle ID · 타깃 · 바이너리는 clone 의 것**(`com.axi.clone.<rootview>`, `CloneApp`). 원본과 같은 기기에 나란히 설치되어야 대조가 되고, 원본의 식별자를 쓰면 원본을 덮어쓴다. 이름이 같고 식별자가 다른 앱 둘이 홈 화면에 보이는 것이 의도된 상태다.

시뮬레이터 프리뷰(`device_render.sh` 의 `ClonePreview`)는 대조 스크린샷용 하네스라 이름을 바꾸지 않는다.

## Output Artifacts

| 산출물 | 경로 | 소비자 |
|-------|------|--------|
| 탐험 로그(시각·탭/스와이프 전이·입력 길이·커버리지·재개 상태) | `.autobot/clone/flow.jsonl` | Step 2·2a·2b |
| WDA 세션·기기 프로필·선택적 HTTP 계측 | `.autobot/clone/wda-session.json`, `device-profile.json`, `http-metrics.jsonl` | 재개·동일 기종 렌더·병목 진단 |
| flow 맵 | `.autobot/clone/flow-map.html` | 사람 검토 (Step 2a·2c) |
| 역기획 | `.autobot/clone/reverse-brief.md` | 사람 · `/autobot:mvp` |
| 원본 캡처 + 트리 | `.autobot/clone/raw/*.png`, `*.xml` | Step 3 측정 |
| 측정값 | `.autobot/clone/screens/*.json` | Step 4·5 |
| 측정 증거(요소 표·레이아웃) | `.autobot/clone/screens/*.md` | 사람 리뷰 · 스펙이 링크 (기계 소유, 매번 덮어씀) |
| 화면 스펙 + 동작 계약 | `.autobot/clone/specs/<ViewName>.md` | 사람 리뷰 · `/autobot:mvp` (사람 소유) |
| SwiftUI 재현 | `.autobot/clone/Sources/*.swift` | 빌드 |
| state/view 매핑 + 관찰 전이 라우터 | `.autobot/clone/views.json`, `Sources/ObservedFlow.swift` | 기능 재생 |
| 반복 단위 초안(감지 → 사람 확인) | `.autobot/clone/structure/*.json` | 사람 리뷰 (Step 3a) |
| 사람이 선언한 state 병합 | `.autobot/clone/state-aliases.json` | `load_flow` (로딩 단계로 갈라진 한 화면) |
| 연구용 자산과 출처 | `.autobot/clone/assets/*`, `assets/manifest.json` | 연구용 clone 빌드·감사 |
| 대조 이미지 | `.autobot/clone/compare/*.png` | Step 6 검증 |
| 렌더 접근성 트리 (AXe 설치 시) | `.autobot/clone/compare/*-rendered.tree.json` | Step 6 구조 diff (`clone_structural_diff.py`) |
| 측정·렌더 캐시 | `.autobot/clone/.postprocess-cache.json`, `render-cache/` | 반복 실행 가속 |
| clone Xcode 작업공간 | `.autobot/clone/project/CloneWorkspace.xcodeproj` | Xcode/CoreDevice 준비 및 이후 구현 빌드 |
| 대상 앱 바인딩(bundle ID · 기기가 보고한 이름) | `.autobot/clone/target.json` | Step 6c 표시 이름 · 감사 |
| 실기기 설치 프로젝트 | `.autobot/clone/device-app/` | Step 6c |

기계 진입점은 `scripts/clone_run.sh` 하나다. 기본 완주 경로는 `observe`·`functional`·`polish`이고, `verify`는 뒤의 두 게이트를 순서대로 실행한다. `codegen`은 기기 없는 복구, `install`은 선택적 실기기 설치다.

## CRITICAL RULES

1. **측정하지 않은 값을 쓰지 않는다** — 스크린샷을 보고 눈대중으로 색·간격을 정하지 않는다. 목표가 픽셀 동일이 아니라고 해서 이 규율이 느슨해지는 게 아니다: 측정이 룩앤필에 도달하는 가장 싼 길이다. 측정 JSON 에 없는데 재현에 필요하면 **근사하고 근사라고 적는다**(스펙의 "재현 불가 항목").
2. **원본 바이너리 에셋 추출을 약속하지 않는다** — 접근 가능한 승인 파일·payload·화면 crop이 있으면 연구 전용 산출물에 사용할 수 있고, 없으면 자리표시자 + 명시한다. 샌드박스·암호화·서명 경계를 우회하지 않는다.
3. **대조 이미지 없이 완료 선언 금지, 그리고 대조가 통과해야 한다** (Step 6) — 이미지를 만든 것은 완료가 아니다. `polish` 가 `--max-mismatch` 를 넘긴 화면은 실패이고, 실패한 화면을 두고 재현했다고 말하지 않는다. 한도를 올려서 통과시키는 것은 **이유를 적었을 때만** 허용한다.
4. **파이프라인 상태 위조 금지** — `build-state.json`/`architecture.json` 을 만들지 않는다. 산출물은 `/autobot:mvp`·`/autobot:plan` 의 입력이거나 독립 참고물이다.
5. **flow 를 확보하기 전에 재현하지 않는다** — 화면 하나만 보고 코드를 쓰면 그 화면이 앱에서 어떤 위치인지 모른 채 복제하게 된다. 기본 완주 경로는 Step 2 → 2a → 2c 뒤 Step 3 으로 간다. Step 2b 역기획은 `/autobot:mvp` 인수인계가 필요할 때 작성하는 선택 산출물이다.
6. **커버리지와 근거를 숨기지 않는다** — 부분 탐험은 부분이라고 말하고(`stats`), 역기획의 해석은 관찰과 분리하고, 동작 계약의 미확인 행은 `미탐험` 으로 표시한다. 변경된 탭/스와이프의 도착 캡처가 없거나 원본 트리가 빠진 경우도 `incomplete`로 남긴다. 셋 다 추측이 명세로 승격되는 걸 막는 같은 규칙이다.
7. **관찰 전에 clone 앱을 실행하지 않는다** — clone workspace는 Xcode/CoreDevice 준비용으로만 열고, 대상 앱의 화면·전이를 수집하기 전에는 빌드·설치·실행하지 않는다.
8. **연구용 자산은 provenance를 남긴다** — `assets/manifest.json` 없이 원본 자산을 생성본에 넣지 않는다. 연구용 기본값과 기술적으로 접근 가능한 출처를 혼동하지 않는다.
9. **진행을 사람에게 묻지 않는다** — 재현 대상·화면 매핑·추가 탐험 여부는 모두 자율 기본값이 있다(Step 2a·2c·5). 사람을 부르는 경우는 둘뿐이다: 기술 게이트 실패(중지), 그리고 `CLONE_ASK_FOR_DATA=1` 로 명시적으로 켠 데이터 요청. 중간에 묻는 것은 자율성만 깨는 게 아니라 실기기 세션이 만료될 시간을 벌어 준다.

## Preconditions

- `autobot-copy-analyze` 와 동일: Appium + xcuitest, `DEVELOPMENT_TEAM`, iPhone 1대 연결 + 잠금 해제 + Developer Mode + Trust + **UI 자동화 ON**, 설치된 대상 bundle ID. 로컬 Appium 서버와 iOS 18+ RemoteXPC tunnel은 `doctor`/`session`이 필요할 때 자동 준비한다. 설치·driver·서명·기기·디스크 조건 또는 관리자 인증이 충족되지 않으면 중지한다.
