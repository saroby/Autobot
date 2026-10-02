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
