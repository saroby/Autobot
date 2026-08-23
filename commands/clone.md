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

- **입력** — 재현할 앱의 bundle ID 또는 앱 이름. 이름을 주면 `clone_run.sh observe` 가 같은 UDID에서 `--include-all-apps` 로 정확한 bundle ID를 확인한다. 이름이나 현재 포그라운드 상태, 과거 bundle ID만으로 추정하지 않는다.
- **한방 실행** — 기본 경로는 세 명령이고, 모델이 손으로 쓰는 것은 화면 스펙과 **기계 초안의 손질**이다.
  ```bash
  python3 scripts/clone_skill_sync.py check
  scripts/clone_run.sh observe '<앱 이름 또는 bundle id>'   # 게이트 → 전체 탐험 → 측정 → flow 맵 → views.json → SwiftUI 초안
  scripts/clone_run.sh functional                          # 앱이 관측된 전이대로 실제로 이동하는가
  scripts/clone_run.sh polish                              # 화면마다 렌더 → 구조 diff → 대조
  ```
- **순서가 규칙** — 기능이 먼저다. 도달할 수 없는 화면을 픽셀까지 깎는 것은 셈에 들어가는지 모르는 채 쓰는 시간이다. `verify` 는 `functional` → `polish` 를 그 순서로 돌고, 앞이 실패하면 뒤로 넘어가지 않는다.
- **전체 순서** — `clone_skill_sync.py check` → workspace/doctor → 전수 탐험(화면 사이 이동 포함) → **flow 맵** → 병렬 측정·자산 crop → 측정 기반 SwiftUI 초안 + 관찰 전이 router → 기능 워크 → 캐시 렌더·요소별 대조
- **결과물** — `.autobot/clone/flow-map.html`(화면 지도) + `reverse-brief.md`(역기획) + `screens/*.{json,md}`(측정·스펙) + `assets/manifest.json`(연구용 자산 provenance) + `Sources/*.swift`(화면·전이 router) + `compare/*.png`(원본 대조)
- **시작 준비** — `scripts/clone_workspace.sh prepare`로 `.autobot/clone/project/CloneWorkspace.xcodeproj`를 만들고, `CLONE_XCODE_PROJECT`를 지정한 뒤 기기 게이트를 실행한다. Xcode workspace는 CoreDevice 복구와 이후 구현 빌드에 사용하며, 관찰 전에 실행하지 않는다.
- **WDA 서명 격리** — `scripts/device_wda.sh session`은 기본적으로 WDA를 `.autobot/clone/wda`에 복사해 서명 후 bundle 변형 충돌을 격리한다. `CLONE_WDA_REFRESH=1`은 복사본을 갱신하고, 전역 Appium WDA를 직접 수정하지 않는다.

탐험은 **중단돼도 이어서 한다** — 같은 명령을 다시 실행하면 flow 로그에서 재개한다. `session`은 같은 대상의 살아 있는 세션을 재사용하고 필요하면 로컬 Appium을 자동 시작한다. 세션에는 성능 설정(`waitForIdleTimeout=0`·`animationCoolOffTimeout=0`)이 자동 적용된다 — clone의 자체 settle 루프가 안정화를 판정하므로 WDA 대기는 중복이다(`CLONE_WDA_TUNE=0`으로 비활성). iOS 18+ RemoteXPC tunnel이 없으면 `doctor`/`session`이 clone Xcode 프로젝트를 먼저 연 뒤 관리자 인증을 거쳐 자동 시작하고, registry에서 대상 UDID를 확인해야 계속한다. 기존 tunnel은 재사용하며 `CLONE_AUTO_START_TUNNEL=0`으로 자동 시작을 끌 수 있다. 탐험의 기본 경로는 `device_wda.sh explore`다 — 현재 화면의 안전 frontier를 소진하고, 소진되면 이미 관찰한 전이를 되짚어 미탐험 화면으로 **스스로 이동해** 계속한다(탭당·화면당 사람 개입 없음, withheld 제외, step 가드 공유). `device_flow.py next-tap`이 매 반복마다 지금 화면의 fresh 트리에서 탭 하나를 답하므로 낡은 좌표 가드가 경로 홉에도 그대로 적용된다. 개별 진단만 `step`을 쓴다. 탭은 settle XML·도착 PNG·flow를 한 번에 남긴다. `device_flow.py next/stats`는 raw target과 반복 행을 묶은 behavior class 커버리지를 함께 복원하며, 키보드·정적 문구는 제외하고 팔로우/좋아요/게시 같은 상태 변경은 `withheld`로 보류한다. coarse `node`와 포커스·키보드·선택을 포함한 `state`를 분리하므로 같은 화면의 상호작용 상태를 잃지 않는다.

위 명령들이 감싸는 실체는 이렇다 — 반복 후처리는 `clone_postprocess.py --workers 4 --extract-assets`, 화면 초안은 `clone_view_codegen.py`, 관찰 전이 연결은 `clone_flow_codegen.py`, 기능 워크는 `clone_functional.py`, 렌더는 `device_render.sh ... auto ...`, 대조는 `device_compare.py --measure ... --heatmap ...`이며, 화면마다 손으로 반복하지 않고 `clone_run.sh polish`가 한 번에 돈다. 렌더는 **화면마다 컴파일하지 않는다** — Sources 를 한 번 빌드하고 실행 시점에 `CLONE_ROOT_VIEW` 로 루트를 고른다. 요소 누락은 눈보다 먼저 `clone_structural_diff.py <측정.json> <렌더.tree.json>`로 센다 — 누락이 있으면 exit 1로 수렴 루프를 되돌린다. 자세한 옵션·중지 조건은 SSOT 스킬을 따른다.

## `/autobot:copy` 와의 차이

| | `/autobot:copy` | `/autobot:clone` |
|---|---|---|
| 목적 | 다른 앱을 **새로** 만든다 | 같은 화면을 **다시** 만든다 |
| 산출물 | 제품 브리프(기획 입력) | 화면 스펙 + 동작 계약 + SwiftUI 코드 |
| 충실도 | 방향(느낌·팔레트 성격) | 레이아웃 · 룩앤필 · 기능 (측정 기반, 픽셀 일치는 아님) |

둘 다 `scripts/device_wda.sh` 로 기기를 몰고, 같은 탐험 가드(파괴적 라벨 제외·모달 시 후보 0개·낡은 좌표 탭 거부)를 공유한다.

## 에셋 처리 (먼저 알 것)

Appium/WDA만으로 설치된 App Store 앱의 원본 번들 에셋을 보장해서 가져올 수는 없다. 탈옥·샌드박스 우회·서명 무력화는 하지 않는다. clone 산출물은 별도 확인 질문 없이 `research-only`로 생성한다. 사용자 제공 파일·승인된 payload/export·공개 원본 파일·실기기 캡처 crop으로 자산을 확보할 수 있으면 원본 아이콘·이미지·문구를 넣을 수 있다. `.autobot/clone/assets/manifest.json`에 출처·획득 방법·원본 프레임을 기록하고, 자산을 확보하지 못하면 자리표시자를 사용한다.

## CRITICAL RULES

1. **측정하지 않은 값을 쓰지 않는다** — 스크린샷 눈대중으로 색·간격을 정하지 않는다. 픽셀 일치가 목표가 아니어도 측정이 룩앤필에 도달하는 가장 싼 길이다. `scripts/device_measure.py` 가 낸 JSON 에 없는데 필요하면 근사하되 스펙의 "재현 불가 항목"에 근사라고 적는다.
2. **대상 앱에 바인딩되지 않으면 중지** — `device_wda.sh device` → `session <udid> <bundle_id>` 두 게이트를 통과해야 한다. 현재 foreground 앱을 타깃으로 간주하지 않는다. 입력이 필요한 화면은 Appium accessibility ID 기반 `type`을 사용하고, 입력값 자체는 로그에 남기지 않는다.
3. **기능이 픽셀보다 먼저** — `clone_run.sh functional` 이 통과하기 전에는 화면별 픽셀 폴리싱을 하지 않는다. 도달할 수 없는 화면의 색·간격은 아직 값이 정해지지 않은 작업이다.
4. **대조 이미지 없이 완료 선언 금지** — 재현본을 시뮬레이터에서 렌더해 원본과 나란히 붙인 뒤에야 완료다. 대조는 수렴 루프다: 요소 누락·구조 차이를 먼저 없애고, 남은 차이가 스펙에 선언된 재현 불가 항목뿐일 때 끝난다.
5. **파이프라인 상태 위조 금지** — `build-state.json`/`architecture.json` 을 만들지 않는다.
6. **진행을 사람에게 묻지 않는다** — 재현 대상·화면 매핑·추가 탐험은 자율 기본값을 쓴다. 사람을 부르는 경우는 기술 게이트 실패(중지)와 `CLONE_ASK_FOR_DATA=1` 로 켠 데이터 요청뿐이다.

전체 절차는 `autobot-clone-app` 스킬을 로드해 그대로 따른다.
