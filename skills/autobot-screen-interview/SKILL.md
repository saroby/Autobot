---
name: autobot-screen-interview
user-invocable: false
description: Use when the user invokes "/autobot:screen" to deep-dive on a single app screen through a structured interview, producing SSOT documents (SOUL.md, AGENTS.md, CLAUDE.md, docs/screens/) and presentation-only SwiftUI view code. Also use when resuming a half-finished screen (docs/screens/*.md with status "interviewing" or "confirmed") or when the user asks to design one screen in depth before any code generation.
---

# Screen Interview — 화면 하나를 깊게

화면 하나를 인터뷰로 기획하고, 결정을 SSOT 문서로 남기고, presentation-only SwiftUI 뷰까지 만든다. 독립 스킬 — Autobot 파이프라인 프로젝트가 아니어도 동작한다.

## 산출물 계약

| 산출물 | 경로 | 역할 | 기존 파일이 있으면 |
|--------|------|------|--------------------|
| 화면 spec | `docs/screens/<slug>.md` | **인터뷰의 주 산출물.** 라운드마다 갱신 | 이어서 재개 (status 참조) |
| SOUL.md | 프로젝트 루트 | 제품 정체성 — 왜 존재, 누구의 어떤 순간, 감정 목표, 하지 않을 것 | 비파괴 병합 |
| AGENTS.md | 프로젝트 루트 | 에이전트 작업 규칙의 **정본** — 구조, 컨벤션, SSOT 지도 | 비파괴 병합 |
| CLAUDE.md | 프로젝트 루트 | `@AGENTS.md` 참조 + Claude Code 전용 지침만 (내용 중복 금지) | 참조 줄만 보장 |
| SwiftUI 뷰 | 기존 Views 패턴 위치 (없으면 `Views/<ScreenName>View.swift`) | presentation-only, 상태별 `#Preview` | diff 요약 확인 후 교체 |

슬러그는 kebab-case 영문 (예: 홈 피드 → `home-feed`, 뷰는 `HomeFeedView.swift`). 문서 템플릿은 `references/templates.md` 참조.

## 인터뷰 철칙

1. **스캔 먼저, 질문은 나중** — 코드·문서·`.autobot/` 에서 알 수 있는 것은 묻지 않는다. 이미 결정된 것은 "이렇게 이해했는데 맞나요" 확인만.
2. **한 라운드 = 한 주제.** 라운드가 끝나면 결정 요약(스냅샷)을 보여주고 정정 기회를 준 뒤 `docs/screens/<slug>.md` 에 즉시 기록한다.
3. **갈림길은 AskUserQuestion** (선택지 2–4개 + 추천 표시), **열린 질문은 대화로.** 한 호출에 질문 최대 4개, 한 라운드에 호출 1–2회를 넘기지 않는다 — 심문이 아니라 인터뷰다.
4. **모호한 답은 시나리오로 한 번 되묻는다** — "유저가 지하철에서 30초 있을 때 이 화면을 열면 무엇을 얻고 닫나요?" 처럼 구체 상황으로. 그래도 결정이 안 나오면 추천안을 **잠정 채택**해 spec 결정에 `(잠정)` 을 표시하고 "미결/후속" 에 재검토 항목으로 등록한 뒤 진행한다. 같은 질문을 두 번 이상 되묻지 않는다.
5. **화면 나열 금지 (기획 깊이)** — R1 에서 훅·3초 가치·성공 기준을 반드시 도출한다. "무엇이 보이나" 전에 "왜 존재하나".
6. **스코프 = 화면 하나** — 다른 화면·기능 아이디어는 spec 의 "미결/후속" 에 적고 돌아온다.
7. **답을 유도하지 않는다** — 선택지에는 실제로 다른 결과를 낳는 대안만 넣는다. 들러리 선택지 금지.

## Step 0: 컨텍스트 스캔 + 대상 확정

질문 전에 조용히 수행:

```bash
# 프로젝트 유형과 기존 산출물 파악
ls *.xcodeproj Package.swift 2>/dev/null          # Xcode/SPM 여부
ls SOUL.md AGENTS.md CLAUDE.md 2>/dev/null        # 기존 SSOT
ls docs/screens/*.md 2>/dev/null                  # 기존 화면 spec (재개 후보 포함)
ls .autobot/architecture.md .autobot/design-spec.md 2>/dev/null  # Autobot 컨텍스트
```

- 기존 SwiftUI 코드가 있으면 Views 디렉토리 패턴·네이밍·디자인 토큰(색/폰트 자산) 을 파악한다.
- `.autobot/architecture.md` 가 있으면 앱 컨셉·화면 목록·Design Direction 을 읽어 이미 답이 있는 질문을 지운다.
- 인자가 주어져도 기존 `docs/screens/*.md` 의 slug·H1 과 대조해 같은 화면으로 보이는 후보가 있으면 AskUserQuestion 으로 (기존 spec 이어서 vs 새 화면) 을 먼저 확정한다 — 같은 화면의 중복 spec 을 만들지 않는다.
- 기존 spec 을 이어가는 경우 status 로 재개 지점을 정한다:
  - `interviewing` → 기록된 마지막 라운드 다음부터 이어간다.
  - `confirmed` → 인터뷰 전체 생략, "SSOT 생성·병합" 부터 재개한다 (병합은 비파괴 규칙이라 재실행 안전).
  - `built` → 완료된 화면. 무엇을 바꾸고 싶은지 확인한 뒤 해당 라운드만 재오픈한다 (R6 의 수정 규칙 재사용).
- 인자가 없거나 모호하면 첫 AskUserQuestion 으로 대상 화면부터 확정한다 (기존 화면 목록이 있으면 그걸 선택지로).

스캔 결과를 2–4줄로 요약해 보여주고 인터뷰를 시작한다. 이 시점에 `docs/screens/<slug>.md` 를 status `interviewing` 으로 생성한다.

## 인터뷰 라운드

라운드는 표준 5개. 화면이 단순하거나 컨텍스트가 이미 답을 주면 라운드를 축소·확인형으로 바꾼다 — 형식이 아니라 결정의 완성이 목적이다.

### R1 — 존재 이유 (오픈 대화 중심)

핵심 질문 (대화로, 한 번에 2–3개까지만):
- 유저는 **어떤 순간·맥락**에서 이 화면에 도착하나? (하루 중 언제, 어떤 감정으로, 무엇을 하다가)
- 도착 후 **3초 안에** 무엇을 얻어야 하나?
- 이 화면이 잘 작동하면 유저는 **무엇을 하게** 되나? (성공 기준 — 행동으로)
- 비슷한 앱의 같은 화면과 **다르게 만들 한 가지(훅)** 는 무엇인가?

산출: 화면의 한 문장 정의 + 도착 맥락 + 3초 가치 + 성공 기준 + 훅. 스냅샷 확인 후 기록.

### R2 — 콘텐츠 위계 (혼합)

- 화면에 보여야 할 정보 요소를 함께 도출한다 (대화). R1 의 3초 가치에서 시작해 자연스럽게 나오는 것 위주 — 요소를 먼저 나열시키지 않는다.
- **최상위 요소 1개** (가장 크고 먼저 보이는 것) 는 AskUserQuestion 갈림길로 확정한다.
- 각 요소의 데이터가 어디서 오는지(유저 입력/저장된 것/계산된 것)를 표로 정리 — 뷰코드의 mock 설계 입력이 된다.

산출: 요소 표 (요소 · 우선순위 · 데이터 출처) + 최상위 요소.

### R3 — 인터랙션 (AskUserQuestion 중심)

- **주 액션(CTA) 1개** — 이 화면에서 유저가 가장 자주 할 일. 갈림길로 확정.
- 보조 액션들, 진입 경로(어디서 오나 — 탭바·타 화면·알림·위젯·딥링크)와 이탈 경로(어디로 가나), 제스처(스와이프·길게 누르기 등 이 화면 특유의 것만).

산출: 주 CTA + 보조 액션 목록 + 진입/이탈 + 제스처. 각 액션은 뷰의 콜백 파라미터 이름까지 정한다 (`onStartWorkout` 등).

### R4 — 상태 매트릭스 (AskUserQuestion 중심)

default 외 상태를 화면 유형에 맞게 **제안하고** 고르게 한다 (빈 목록에서 시작하지 않는다):
- 공통 후보: empty (첫 사용 — 무엇으로 채우도록 유도하나), loading, error. 보는 중 데이터가 갱신될 수 있는 화면(피드·목록·대시보드류)이면 refreshing(갱신 중)·stale(낡은 데이터 + 마지막 갱신 표시)도 공통 후보로 제안한다.
- 화면 특유 후보를 스킬이 추론해 제안: 권한 거부(카메라·위치 등), 오프라인, 알림·딥링크 진입 시 특정 항목 포커스(R3 진입 경로에서 나왔다면), 항목 1개 vs 1,000개, 텍스트 초장문, 무료/유료 분기 등

각 채택 상태마다: 유저에게 보이는 것 + 다음 행동 유도 한 줄.

산출: 상태 매트릭스 (상태 · 보이는 것 · 유도 행동). 채택된 상태는 전부 `#Preview` 대상이 된다.

### R5 — 룩앤필 (혼합)

- 톤 키워드 3개 (예: 차분한/밀도있는/장난기). 기존 SOUL.md 나 design-spec 이 있으면 확인만.
- 레퍼런스 앱·화면 (있으면; 필요시 WebSearch 로 함께 찾기).
- 모션 성격 (절제 vs 표현적), 다크모드 우선순위.

산출: 톤 + 레퍼런스 + 모션 + 다크모드 방침.

### R6 — 확정

`docs/screens/<slug>.md` 전체를 최종 스냅샷으로 보여주고 승인받는다. 수정 요청은 해당 라운드 결정을 고치되, 상류 결정(R1 훅·R2 최상위 요소)이 바뀌면 의존 하류(R3 주 CTA·콜백 이름, R4 상태 매트릭스)를 함께 점검해 갱신하거나 유지 이유를 결정 로그에 남긴 뒤 전체 스냅샷을 다시 확인받는다. 승인되면 status 를 `confirmed` 로 바꾸고 산출물 생성으로 진행한다.

## SSOT 생성·병합

순서: `docs/screens/<slug>.md` (이미 완성) → SOUL.md → AGENTS.md → CLAUDE.md. 템플릿과 섹션 구조는 `references/templates.md`.

**병합 규칙 (기존 파일이 있을 때):**
- 기존 섹션·문장을 임의로 삭제·재작성하지 않는다. 이번 인터뷰에서 **드러난 것만** 해당 섹션에 추가한다.
- SOUL.md: R1/R5 에서 제품 수준 통찰이 나왔을 때만 갱신 (화면 세부사항은 넣지 않는다 — 그건 spec 소유).
- AGENTS.md: "화면 작업 전 `docs/screens/<slug>.md` 를 먼저 읽는다" 규칙과 SSOT 지도가 없으면 추가. 이번 화면을 화면 목록에 등록.
- CLAUDE.md: 첫 줄 `@AGENTS.md` 참조가 없으면 추가. AGENTS.md 와 내용 중복 금지 — Claude Code 전용 지침(권한, 빌드 커맨드 등)만 거주.
- 기존 내용과 이번 결정이 **충돌**하면 덮어쓰지 말고 사용자에게 어느 쪽이 맞는지 확인한다.

## SwiftUI 뷰 생성 — presentation-only 계약

**허용:**
- 레이아웃·스타일·타이포·색 (기존 디자인 토큰/자산이 있으면 그것 사용)
- 화면 상태는 이니셜라이저 주입: 상태 enum 또는 옵셔널 모델 파라미터 → 프리뷰에서 상태별 렌더
- mock 데이터: 뷰 파일 내 `extension <Model> { static let sample… }` 또는 `#Preview` 인라인
- 액션은 콜백 파라미터: `var onStartWorkout: () -> Void = {}` — R3 에서 정한 이름 그대로
- 순수 시각 상태의 로컬 `@State` (선택된 탭, 펼침/접힘)

**금지:**
- 네트워크·저장 (URLSession, SwiftData, UserDefaults …)
- ViewModel·`@Observable` 비즈니스 로직, 타이머·백그라운드 작업
- 실 내비게이션 목적지 연결 (진입/이탈은 콜백으로만 표현)

**필수:**
- R4 상태 매트릭스의 **모든 상태**에 `#Preview` 하나씩 + 다크모드 프리뷰 1개
- 접근성: 의미 있는 라벨, Dynamic Type 에 깨지지 않는 레이아웃
- 파일 위치는 기존 프로젝트 패턴을 따른다. 신규 프로젝트면 `Views/<ScreenName>View.swift`. 뷰가 커지면 같은 파일 내 서브뷰로 분리 (파일 수 최소).
- 동일 경로에 파일이 이미 있으면 덮어쓰기 전에 diff 요약을 보여주고 확인받는다.

타깃 OS 는 프로젝트의 deployment target 을 따른다 (신규면 iOS 26+, Autobot 기본).

## 검증 (advisory)

```bash
# Xcode 프로젝트면 (스킴 자동 감지)
xcodebuild -project *.xcodeproj -scheme <scheme> -destination 'generic/platform=iOS Simulator' build 2>&1 | tail -5
# SPM 이면
swift build 2>&1 | tail -5
```

- 성공 → "컴파일 확인됨" 보고.
- 실패 → **산출물은 그대로 두고** 원인을 분류해 보고: 이번 뷰 코드 문제면 즉시 수정 후 재시도 (최대 2회), 기존 프로젝트의 무관한 문제면 그 사실만 명시.
- 빌드 수단이 없으면 (스캐폴드 없는 신규) "Xcode 에서 프리뷰로 확인" 안내.

뷰 생성·검증 후 `docs/screens/<slug>.md` frontmatter 를 `status: built`, `updated: <오늘 날짜>` 로 갱신하고 `## 구현 노트`(뷰 경로·mock 위치·프리뷰 상태 목록)를 채우며, AGENTS.md 화면 목록의 상태 열도 함께 갱신한다. 검증(advisory) 컴파일이 실패해도 뷰 파일이 생성됐으면 `built` 다.

## 최종 보고

- 화면 한 문장 정의 + 훅
- 생성·변경 파일 목록 (SSOT 4종 상태: 생성/병합/유지)
- 뷰 파일 경로 + 프리뷰 상태 목록 + 컴파일 확인 결과
- "미결/후속" 에 쌓인 항목 (다음 `/autobot:screen` 후보)

## 중단·재개

어느 단계에서 끊겨도 `docs/screens/<slug>.md` 가 진실이다. 다음 호출 때 Step 0 이 status 를 보고 이어갈 지점을 정한다 (`interviewing`/`confirmed`/`built` 3분기는 Step 0 참조). 별도 상태 파일을 만들지 않는다.
