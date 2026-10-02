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
