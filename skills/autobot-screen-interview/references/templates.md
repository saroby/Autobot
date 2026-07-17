# SSOT 문서 템플릿

`autobot-screen-interview` 가 생성하는 문서의 표준 구조. 섹션 이름은 계약이다 — 병합·재개 로직이 헤딩으로 위치를 찾는다. 내용이 없는 섹션은 만들지 않는다 (빈 헤딩 금지).

## docs/screens/<slug>.md — 화면 spec

```markdown
---
screen: <slug>
view: <ScreenName>View.swift
status: interviewing | confirmed | built
updated: <YYYY-MM-DD>
---

# <화면 이름>

> <한 문장 정의 — 이 화면은 누가 언제 무엇을 얻는 곳인가>

## 존재 이유 (R1)
- **도착 맥락**: <어떤 순간·감정·경로로 오나>
- **3초 가치**: <도착 즉시 얻는 것>
- **성공 기준**: <잘 작동하면 유저가 하게 되는 행동>
- **훅**: <비슷한 앱과 다르게 만드는 한 가지>

## 콘텐츠 위계 (R2)
| 요소 | 우선순위 | 데이터 출처 |
|------|---------|------------|
| <최상위 요소> | 1 | 유저 입력 / 저장 / 계산 |

## 인터랙션 (R3)
- **주 CTA**: <액션> → 콜백 `onXxx`
- **보조**: <액션 목록, 각각 콜백 이름>
- **진입**: <어디서 오나> / **이탈**: <어디로 가나>
- **제스처**: <이 화면 특유의 것만>

## 상태 매트릭스 (R4)
| 상태 | 보이는 것 | 유도 행동 |
|------|----------|----------|
| default | | |
| empty | | |

## 룩앤필 (R5)
- **톤**: <키워드 3개>
- **레퍼런스**: <앱·화면>
- **모션**: <절제/표현적> · **다크모드**: <방침>

## 결정 로그
- <날짜> <갈림길>: <선택> — <이유> (기각: <대안>)

## 미결/후속
- [ ] <이 화면 밖으로 새어나간 아이디어·다른 화면 후보>

## 구현 노트
- 뷰: `<경로>` · mock: <위치> · 프리뷰: <상태 목록>
```

status 전이: `interviewing`(R1–R5 진행 중, 라운드마다 갱신) → `confirmed`(R6 승인) → `built`(뷰코드 생성 완료).

## SOUL.md — 제품 정체성

화면 세부사항은 넣지 않는다. 화면 인터뷰에서 **제품 수준** 통찰이 나왔을 때만 갱신.

```markdown
# <앱 이름>의 영혼

> <제품 한 문장 — 누구의 어떤 순간을 어떻게 바꾸나>

## 누구의 어떤 순간
<핵심 유저와 그들이 앱을 여는 순간·감정>

## 앱을 닫을 때 남아야 하는 감정
<성취감 / 안도 / 재미 … — 모든 화면이 공유하는 감정 목표>

## 차별화 한 방
<이 앱을 대체 불가능하게 만드는 것>

## 성격
<톤 키워드와 그것이 UI 에서 뜻하는 것>

## 하지 않을 것
- <의도적으로 배제하는 기능·패턴 — "왜 없어요?"에 대한 선답변>
```

## AGENTS.md — 에이전트 작업 규칙 (정본)

```markdown
# AGENTS

이 프로젝트에서 작업하는 모든 에이전트의 규칙. CLAUDE.md 는 이 파일을 참조한다.

## SSOT 지도
| 문서 | 소유 |
|------|------|
| SOUL.md | 제품 정체성 — 왜 |
| docs/screens/<slug>.md | 화면별 spec — 무엇·어떻게 |
| AGENTS.md | 작업 규칙 — 이 파일 |

## 규칙
1. 화면 코드를 만지기 전에 `docs/screens/<해당 화면>.md` 를 먼저 읽는다.
2. 화면 spec 과 코드가 어긋나면 spec 을 진실로 본다 (spec 이 틀렸으면 spec 부터 고친다).
3. 새 화면은 `/autobot:screen` 인터뷰로 시작한다 — spec 없는 화면 코드 금지.

## 프로젝트 구조
<Views/ 위치, 네이밍, 디자인 토큰 위치 등 스캔 결과>

## 화면 목록
| 화면 | spec | 뷰 | 상태 |
|------|------|-----|------|
| <이름> | docs/screens/<slug>.md | <경로> | interviewing/confirmed/built |
```

## CLAUDE.md — Claude Code 전용

```markdown
@AGENTS.md

# Claude Code 전용
<빌드·프리뷰 커맨드, 권한, Claude Code 에만 해당하는 지침. AGENTS.md 와 중복 금지 — 없으면 이 섹션 생략>
```

## SwiftUI 뷰 스켈레톤

```swift
import SwiftUI

struct HomeFeedView: View {
    enum ScreenState { case content([Workout]), empty, loading, error(String) }

    var state: ScreenState = .content(Workout.samples)
    var onStartWorkout: () -> Void = {}   // R3 콜백 이름 그대로

    var body: some View {
        // 레이아웃만. 네트워크/저장/ViewModel 없음.
    }
}

extension Workout {
    static let samples: [Workout] = [ /* R2 데이터 출처 기반 mock */ ]
}

#Preview("default") { HomeFeedView() }
#Preview("empty") { HomeFeedView(state: .empty) }
#Preview("dark") { HomeFeedView().preferredColorScheme(.dark) }
// R4 매트릭스의 모든 상태 + 다크모드
```
