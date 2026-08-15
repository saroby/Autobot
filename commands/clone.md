---
name: clone
description: "연결된 iPhone 에서 대상 앱의 화면을 측정해(좌표·크기·실제 픽셀 색·텍스트 스타일) 레이아웃·룩앤필·동작이 같은 화면 스펙과 SwiftUI 재현 코드를 `.autobot/clone/` 에 생성합니다. 시작할 때 clone 전용 Xcode workspace를 만들고 연결이 없으면 Xcode를 열어 CoreDevice를 제한 시간 동안 재시도합니다. 픽셀 단위 일치가 아니라 '나란히 놓으면 같은 화면'이 기준이며, 원본과 붙인 대조 이미지로 검증합니다. 끝내 실기기 연결이 없으면 중지합니다. 기획 재구성이 목적이면 `/autobot:copy` 를 쓰세요."
argument-hint: "<bundle id 또는 앱 이름> (bundle ID가 불명확하면 target UDID에서 --include-all-apps로 확인)"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Skill
  - AskUserQuestion
---

# Autobot Clone — 화면을 있는 그대로 재현

> **이 문서는 진입점이다. 실행하지 않는다.**
> 측정 방식·재현 범위·법적 경계·산출물 계약의 SSOT 는 **`autobot-clone-app` 스킬**이 소유한다.

- **입력** — 재현할 앱의 bundle ID. 모르면 먼저 같은 UDID에 `xcrun devicectl device info apps --include-all-apps --search '<앱 이름>'`을 실행해 확인한다. 이름이나 현재 포그라운드 상태, 과거 bundle ID만으로 추정하지 않는다.
- **순서** — `clone_skill_sync.py check` → workspace/doctor → 전수 탐험 → **flow 맵** → 병렬 측정·자산 crop → 역기획 → 재현 대상 선택 → SwiftUI + 관찰 전이 router → 캐시 렌더·요소별 대조
- **결과물** — `.autobot/clone/flow-map.html`(화면 지도) + `reverse-brief.md`(역기획) + `screens/*.{json,md}`(측정·스펙) + `assets/manifest.json`(연구용 자산 provenance) + `Sources/*.swift`(화면·전이 router) + `compare/*.png`(원본 대조)
- **시작 준비** — `scripts/clone_workspace.sh prepare`로 `.autobot/clone/project/CloneWorkspace.xcodeproj`를 만들고, `CLONE_XCODE_PROJECT`를 지정한 뒤 기기 게이트를 실행한다. Xcode workspace는 CoreDevice 복구와 이후 구현 빌드에 사용하며, 관찰 전에 실행하지 않는다.
- **WDA 서명 격리** — `scripts/device_wda.sh session`은 기본적으로 WDA를 `.autobot/clone/wda`에 복사해 서명 후 bundle 변형 충돌을 격리한다. `CLONE_WDA_REFRESH=1`은 복사본을 갱신하고, 전역 Appium WDA를 직접 수정하지 않는다.

탐험은 **중단돼도 이어서 한다** — `session`은 같은 대상의 살아 있는 세션을 재사용하고 필요하면 로컬 Appium을 자동 시작한다. iOS 18+는 별도 RemoteXPC tunnel이 필요하며, sudo가 필요한 tunnel을 플러그인이 몰래 띄우지 않고 `doctor`가 공식 명령을 제시한다. 탭은 `device_wda.sh step`으로 settle XML·도착 PNG·flow를 한 번에 남긴다. `device_flow.py next/stats`는 raw target과 반복 행을 묶은 behavior class 커버리지를 함께 복원하며, 키보드·정적 문구는 제외하고 팔로우/좋아요/게시 같은 상태 변경은 `withheld`로 보류한다. coarse `node`와 포커스·키보드·선택을 포함한 `state`를 분리하므로 같은 화면의 상호작용 상태를 잃지 않는다.

반복 후처리는 `clone_postprocess.py --workers 4 --extract-assets`, 관찰 전이 연결은 `clone_flow_codegen.py`, 렌더는 `device_render.sh ... auto ...`, 대조는 `device_compare.py --measure ... --heatmap ...`를 기본 경로로 사용한다. 자세한 옵션·중지 조건은 SSOT 스킬을 따른다.

## `/autobot:copy` 와의 차이

| | `/autobot:copy` | `/autobot:clone` |
|---|---|---|
| 목적 | 다른 앱을 **새로** 만든다 | 같은 화면을 **다시** 만든다 |
| 산출물 | 제품 브리프(기획 입력) | 화면 스펙 + 동작 계약 + SwiftUI 코드 |
| 충실도 | 방향(느낌·팔레트 성격) | 레이아웃 · 룩앤필 · 기능 (측정 기반, 픽셀 일치는 아님) |

둘 다 `scripts/device_wda.sh` 로 기기를 몰고, 같은 탐험 가드(파괴적 라벨 제외·모달 시 후보 0개·낡은 좌표 탭 거부)를 공유한다.

## 에셋 처리 (먼저 알 것)

Appium/WDA만으로 설치된 App Store 앱의 원본 번들 에셋을 보장해서 가져올 수는 없다. 탈옥·샌드박스 우회·서명 무력화는 하지 않는다. 다만 사용자가 **연구 전용 사용을 승인**했고 사용자 제공 파일·승인된 payload/export·공개 원본 파일·실기기 캡처 crop으로 자산을 확보할 수 있으면, 연구용 clone에는 원본 아이콘·이미지·문구를 넣을 수 있다. `.autobot/clone/assets/manifest.json`에 출처·획득 방법·원본 프레임을 기록하고 `research-only`를 표시한다. 자산을 확보하지 못하거나 외부 공유·배포용이면 자리표시자/대체 자산을 사용한다.

## CRITICAL RULES

1. **Step 0 소유·사용 범위 확인** — 본인 앱이면 이름·아이콘·문구를 그대로 쓴다. 타사 앱의 **연구 전용**이면 사용자 승인과 자산 출처 manifest를 전제로 접근 가능한 원본 또는 캡처 crop을 사용할 수 있다. 외부 공유·배포용이면 타사 이름·로고·아이콘·문구·원본 자산을 승계하지 않고 대체한다. 타사 재현물을 App Store에 내면 Guideline 4.1(Copycats) 리스크가 있으므로 배포 전에 별도 검토한다.
2. **측정하지 않은 값을 쓰지 않는다** — 스크린샷 눈대중으로 색·간격을 정하지 않는다. 픽셀 일치가 목표가 아니어도 측정이 룩앤필에 도달하는 가장 싼 길이다. `scripts/device_measure.py` 가 낸 JSON 에 없는데 필요하면 근사하되 스펙의 "재현 불가 항목"에 근사라고 적는다.
3. **대상 앱에 바인딩되지 않으면 중지** — `device_wda.sh device` → `session <udid> <bundle_id>` 두 게이트를 통과해야 한다. 현재 foreground 앱을 타깃으로 간주하지 않는다. 입력이 필요한 화면은 Appium accessibility ID 기반 `type`을 사용하고, 입력값 자체는 로그에 남기지 않는다.
4. **대조 이미지 없이 완료 선언 금지** — 재현본을 시뮬레이터에서 렌더해 원본과 나란히 붙인 뒤에야 완료다. 대조는 수렴 루프다: 요소 누락·구조 차이를 먼저 없애고, 남은 차이가 스펙에 선언된 재현 불가 항목뿐일 때 끝난다.
5. **파이프라인 상태 위조 금지** — `build-state.json`/`architecture.json` 을 만들지 않는다.

전체 절차는 `autobot-clone-app` 스킬을 로드해 그대로 따른다.
