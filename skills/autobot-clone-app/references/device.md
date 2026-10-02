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
