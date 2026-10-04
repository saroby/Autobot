---
name: autobot-screen-interview
user-invocable: false
description: "Interview or resume one screen’s specification and presentation-only SwiftUI (/autobot:screen)."
---

# Screen Interview

화면 하나를 인터뷰로 기획하고 SSOT와 presentation-only SwiftUI를 만든다. Autobot 파이프라인 밖에서도 사용할 수 있다.

## 산출물·재개

| 산출물 | 경로·기존 처리 |
|---|---|
| 인터뷰 정본 | `docs/screens/<slug>.md`, 라운드마다 갱신·status로 재개 |
| 제품 정체성 | 루트 `SOUL.md`, 비파괴 병합 |
| 작업 규칙·SSOT 지도 | 루트 `AGENTS.md`, 비파괴 병합·화면 목록 등록 |
| 상태별 `#Preview` 뷰 | 기존 Views 패턴, 없으면 `Views/<ScreenName>View.swift`; 기존 파일 교체는 diff 요약 확인 후 |
| 프리뷰 최소 프로젝트 | 없을 때만 `<App>.xcodeproj` + `project.yml` + `App/<App>App.swift` 생성 |

슬러그는 영문 kebab-case(`home-feed` → `HomeFeedView.swift`). [references/templates.md](references/templates.md)를 사용한다. **CLAUDE.md는 생성·수정·병합하지 않는다.** 별도 상태 파일 없이 화면 spec을 정본으로 삼는다.

질문 전에 Xcode/SPM 구조, 기존 SOUL/AGENTS, `docs/screens/*.md`, SwiftUI Views 패턴·토큰, `.autobot/architecture.md`/`design-spec.md`를 읽는다. 인자가 있어도 기존 slug·H1과 같은 화면 후보가 있으면 기존 재개 vs 신규를 먼저 확정한다. 대상이 없거나 모호하면 기존 화면을 선택지로 AskUserQuestion한다.

| spec status | 재개 지점 |
|---|---|
| `interviewing` | 마지막 기록 라운드 다음 |
| `confirmed` | 인터뷰 생략, SSOT 생성·병합 |
| `built` | 바꿀 내용 확인 후 해당 라운드만 재오픈 |

스캔·대상을 2–4줄로 알리고 신규 spec은 `status: interviewing`으로 생성한다.

## 인터뷰

- 코드·문서가 답을 주면 재질문 없이 확인형으로 축소한다.
- 한 라운드 한 주제. 스냅샷을 보여 정정 기회를 준 뒤 **즉시 기존 섹션에 추가**하며 결정 로그·미결 헤딩을 중복 생성하지 않는다.
- 갈림길은 AskUserQuestion(실제로 다른 대안 2–4개 + 추천), 열린 질문은 대화. 한 호출 최대 4질문, 라운드당 호출 1–2회; R1 대화는 한 번에 2–3개 이하.
- 모호하면 구체 시나리오로 한 번만 되묻는다. 그래도 미결이면 추천안을 `(잠정)`으로 채택하고 미결/후속에 재검토를 기록한다.
- 다른 화면·기능 아이디어는 미결/후속으로 보낸다. 요소 나열보다 존재 이유·훅·3초 가치·성공 행동을 먼저 정한다.

| 라운드 | 결정·기록 |
|---|---|
| R1 존재 이유 | 한 문장 정의, 도착 순간·맥락, 3초 가치, 행동으로 측정하는 성공 기준, 차별화 훅 |
| R2 콘텐츠 위계 | 요소·우선순위·데이터 출처(입력/저장/계산) 표, 최상위 요소 1개를 갈림길로 확정 |
| R3 인터랙션 | 주 CTA 1개, 보조 액션, 진입/이탈, 화면 특유 제스처; 액션별 콜백 이름까지 확정 |
| R4 상태 | default 외 empty/loading/error를 제안. 갱신 화면은 refreshing/stale, 도메인에 맞게 권한·오프라인·딥링크 포커스·데이터량/장문·유료 분기도 제안. 채택 상태마다 보이는 것 + 다음 행동 |
| R5 룩앤필 | 톤 3개, 레퍼런스, 모션, 다크모드 방침(기존 SOUL/design-spec은 확인만) |
| R6 확정 | 전체 spec 스냅샷 승인 → `confirmed` |

수정으로 R1 훅/R2 최상위 요소가 바뀌면 R3 CTA·콜백과 R4 상태를 함께 갱신하거나 유지 이유를 결정 로그에 남긴 뒤 전체를 다시 확인받는다.

## SSOT 병합

완성 spec → SOUL → AGENTS 순서로 [templates](references/templates.md)를 적용한다. 기존 문장·섹션은 보존하고 이번 인터뷰 결정만 추가한다. 충돌은 사용자에게 확인한다.

- SOUL은 R1/R5의 제품 수준 통찰만 증류한다(화면 세부는 spec 소유).
- AGENTS에는 화면 작업 전 spec 읽기 규칙·SSOT 지도(없을 때)와 화면 목록을 추가한다.

## SwiftUI 계약

- 기존 디자인 토큰·파일 위치·deployment target을 따른다(신규 iOS 26+). 큰 뷰는 같은 파일 내 서브뷰로 나눈다.
- 화면 상태는 initializer의 enum/옵셔널 모델로 주입하고 mock은 모델 `sample` extension 또는 `#Preview` 인라인에 둔다. 액션은 R3 이름의 콜백(`var onStartWorkout: () -> Void = {}`)만 연결한다.
- 로컬 `@State`는 선택 탭·펼침 같은 순수 시각 상태만 허용한다.
- **네트워크·저장(URLSession/SwiftData/UserDefaults), ViewModel/`@Observable` 비즈니스 로직, 타이머·백그라운드 작업, 실 내비게이션 목적지 연결은 금지**다.
- R4 채택 상태마다 `#Preview` 하나 + 다크모드 하나. 의미 있는 접근성 라벨과 Dynamic Type 대응을 포함한다.
- 동일 경로 뷰 교체 전 diff 요약 확인을 받는다.

## 프리뷰·검증

결과는 **살아있는 Xcode `#Preview` 캔버스**로 표시한다. PNG 스냅샷이나 확인 안내만으로 끝내지 않는다.

1. Xcode 프로젝트가 없으면 xcodegen 최소 스캐폴드: 앱 타깃 1개, iOS 26.0, `sources: [App, Views]`, bundle ID는 `~/.autobot/config.json` 조직 값 또는 임시. App의 `WindowGroup`은 이번 화면(별도 루트가 있으면 루트)을 배치한다. `xcodegen generate`; 미설치면 `brew install xcodegen` 안내 후 advisory로 진행한다.
2. 기존 프로젝트는 뷰의 타깃 포함 확인. xcodegen이면 재생성, Xcode 16 synchronized-folder면 자동 포함; 수동 pbxproj 편집 금지.
3. advisory 컴파일을 확인한다:

```bash
xcodebuild -project <App>.xcodeproj -scheme <scheme> -destination 'generic/platform=iOS Simulator' build
# SPM 프로젝트
swift build
# 빌드 수단 없는 신규 뷰
xcrun swiftc -typecheck -sdk "$(xcrun --sdk iphonesimulator --show-sdk-path)" -target arm64-apple-ios<SDK버전>-simulator <뷰파일>
```

이번 뷰 문제는 수정·재시도 최대 2회. 무관한 기존 문제는 원인을 보고하고 산출물을 보존한다. 검증 실패는 hard fail이 아니다.

4. `xed <프로젝트> && xed <뷰파일>`로 뷰에 포커스하고 캔버스(⌥⌘↩)를 연다.
5. 뷰가 생성됐으면 컴파일 실패여도 spec을 `status: built`, `updated: <오늘>`로 갱신한다. `## 구현 노트`에 뷰 경로·mock 위치·프리뷰 상태를 적고 AGENTS 화면 상태도 갱신한다.

최종 보고는 캔버스에 프리뷰가 열린 상태에서 확인할 `#Preview` 이름으로 시작한다. 화면 정의·훅, 파일 목록(생성/병합/유지), 뷰·상태·컴파일 결과, 미결/후속을 보고한다. 실제 열기/컴파일을 확인하지 못하면 그 한계를 명시한다.
