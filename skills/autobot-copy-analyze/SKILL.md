---
name: autobot-copy-analyze
user-invocable: false
description: "Analyze an installed iOS app on a connected iPhone into an original product brief (/autobot:copy)."
---

# Autobot Copy Analyze

연결된 iPhone의 설치 앱을 분석해 독창적인 구현의 입력인 `.autobot/copy-analysis/brief.md`를 만든다. 접근성 트리가 주 근거이고 스크린샷·App Store 자료는 보조다. 클론 코드나 게시 앱을 생성하는 작업은 아니다.

## 기기·탐색 경계

- Appium + xcuitest, `DEVELOPMENT_TEAM`, USB iPhone **1대**, 잠금 해제, Developer Mode, Trust, **UI 자동화 ON**이 필수다. `device_wda.sh session`이 로컬 서버와 iOS 18+ RemoteXPC tunnel을 준비하고, 지정된 Xcode 프로젝트는 tunnel 전에 연다. 필수 조건 미충족이나 관리자 인증 취소는 중지한다.
- `mcp-appstore` 도구는 권장이다. 없으면 Store 단계를 건너뛰고 기기 증거로 진행하며 Hook & Retention 근거가 약함을 밝힌다.
- 사용자는 대상 앱을 포그라운드로 열고 기기를 잠금 해제한다. 에이전트가 `capture → candidates → tap/swipe`로 탐색하며 STOP 경계에서만 사용자에게 넘긴다.
- **모든 탭 전에 스크린샷을 읽는다.** `device_wda.sh candidates <tree.xml>`이 제공한 좌표만 사용한다. 목록 밖 탭·좌표 추측은 금지(`back` 명령 예외는 Explore reference).
- 후보의 파괴/상태변경 분류는 **거부 목록**이다. 한국어·영어의 알려진 라벨만 막으므로 다른 표현·언어·아이콘과 마커 없는 광고는 통과할 수 있다. 광고·프로모션은 후보에 있어도 누르지 않고, 대상 계정·결제 수단이 붙은 기기에 무인 실행하지 않는다. 누적 탭 상한 25는 안전을 보장하지 않는다.
- 광고 `virtual_root` 하위와 `광고`/`Ad`/`Sponsored`/`AdChoices` 배지의 배너 조상은 후보에서 제외된다. 마커·배지가 없는 광고는 시각 판단으로 거른다.

### 역할 없는 후보

`candidates`는 역할 후보와 **자기 라벨을 소유한 최말단 요소** 후보를 병합한다. 라벨을 합친 조상 컨테이너와 화면 크기 배경 리프는 제외한다. 후보별 `candidate-meta source=role|label`을 확인한다; `WARN: role-blind screen`은 역할 후보가 전혀 없는 화면에만 나오므로 혼합 화면의 라벨 후보도 따로 점검한다.

`source=label`은 역할 보증이 없다. 매 탭 전 스크린샷으로 화면 종류·라벨과 좌표 일치·탐색 목적을 확인한다. 의미 불명 라벨, 좌표 불일치, 광고는 건너뛴다. 로그인·회원가입·페이월·구독·결제·연령확인 화면은 후보가 있어도 **STOP**하고 사용자에게 넘긴다. 라벨 없는 컨트롤은 검사되지 않는다. 파괴/상태변경 라벨 거부는 이 티어에도 적용된다.

누를 후보가 없으면 스와이프하거나 종료한다. `explore` 자동화는 `source=label`을 거부하므로 화면을 읽는 에이전트 루프를 대신할 수 없다.

## 단계별 reference

현재 단계만 읽는다. 프로젝트 경로는 프로젝트 루트, runtime은 `$CLAUDE_PLUGIN_ROOT/scripts/` 기준이다.

| 단계 | Reference |
|---|---|
| 최초 설치·서명 | [Setup](references/setup.md) |
| 1 대상·App Store 근거 | [Store](references/store.md) |
| 2 실기기·세션 게이트 | [Device](references/device.md) |
| 3 안전 탐색·부분 캡처 | [Explore](references/explore.md) |
| 4 관찰 화면 구조 | [Analyze](references/analyze.md) |
| 5 출처·미지원 공백을 포함한 브리프 | [Brief](references/brief.md) |
| 6 검토·plan/mvp 인계 | [Handoff](references/handoff.md) |
| 진단·설정·산출물 | [Operations](references/operations.md) |

## 중지·열화

| 상태 | 처리 |
|---|---|
| 기기 경로가 한 번도 성립하지 않음(미연결/복수 기기/자동화·서명 미비/Step 2 전 세션 종료) | 브리프 없이 abort |
| 게이트 통과 후 한 화면 이상 캡처한 뒤 `ERROR:`(잠김·세션 만료 등) | 루프만 즉시 종료, 재시도 루프 없이 Analyze→Brief |
| `ERROR: … left the app for <bundle>` | 해당 탭은 미기록. 대상 앱을 다시 포그라운드로 올려 계속하거나 남은 예산에 따라 종료 |
| `ERROR: tap budget spent` | 정상 탐색 종료→Analyze |
| 접근성 트리 실패 | 스크린샷 + 사람 주도 캡처로 계속(Explore 말미) |
| 로그인/페이월 뒤 접근 불가·특정 캡처 실패 | 도달한 증거로 브리프 작성 |

부분 브리프 상단에 `> partial capture — <이유>`를 쓰고 `device_flow.py stats`의 커버리지를 보고한다. 세션이 죽어도 확보한 증거를 버리지 않는다.

`device_capture.sh`는 사람 주도 devicectl 스크린샷 보조, `device_idb.sh`는 시뮬레이터 설치 가능한 .ipa에만 해당한다. 둘 다 실기기 자율 탐색의 대안이 아니다.
