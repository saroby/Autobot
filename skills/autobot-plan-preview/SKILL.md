---
name: autobot-plan-preview
user-invocable: false
description: Use during Autobot Phase 2.5 (or when the user invokes "/autobot:plan") to assemble the static plan-preview HTML, inject a multi-modal critique of the generated mockups, and open the result in the browser for user review before code generation begins.
---

# Plan Preview (Phase 2.5)

Phase 2.5 스킬: Phase 1 (architect) 과 Phase 2 (ux-designer + app-icon) 의 산출물을 **HTML 한 페이지**로 합쳐 사용자가 코드 생성 전에 기획·디자인을 검토할 수 있게 한다. 호출 흐름은 항상 `/autobot:plan` 이 트리거하며, mvp 자율 흐름은 Phase 2.5 를 자동 skip (spec `manual: true`).

목적: **잘못된 기획/디자인 위에 Phase 3–5 가 5분 만에 코드를 만들고 나서야 발견되는 비용 0 으로 떨어뜨리기.** mvp 빌드는 검증된 architecture/design 위에서만 시작해야 한다.

## Inputs (필수)

| 파일 | 생성자 | 본 스킬에서의 용도 |
|------|--------|------------------|
| `.autobot/architecture.md` | architect | concept summary (Overview / Features / Screens / Navigation), critique 컨텍스트 |
| `.autobot/design-spec.md` | ux-designer | color/typography 토큰, critique 컨텍스트 |
| `.autobot/designs/*.png` | ux-designer | 갤러리 PNG + critique 의 시각 분석 대상 |
| `.autobot/app-icon-1024.png` | autobot-app-icon | 아이콘 미리보기 |
| `.autobot/build-state.json` | Phase 0 | appName / displayName |

## Output

| 파일 | 내용 |
|------|------|
| `.autobot/designs/preview/index.html` | self-contained 1 페이지 HTML (외부 CDN 없음). 기획 요약 + **번호 매긴 화면-흐름 스토리보드**(진입→탭그룹 순서, ①②③) + 화면 갤러리(각 카드 `id="screen-N"`) + 상태/인터랙션 + 토큰 swatch + 아이콘 + **critique 패널** |

> 빌더(`build_preview.py`)가 화면을 스토리보드 순서로 정렬해 **1..N 번호**를 부여한다 (화면 목록·flow 노드·갤러리 카드가 같은 번호). critique 의 각 항목은 이 번호로 해당 화면 카드(`#screen-N`)에 딥링크된다.

## Execution

스킬은 다음 4 단계를 **순서대로** 수행한다. 각 단계는 다음 단계의 입력을 만들므로 병렬화하지 않는다.

### Step 1 — 정적 HTML 빌드

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-preview.sh" --project-dir "$PWD"
```

성공 시 `.autobot/designs/preview/index.html` 가 생성되며, `<!-- CRITIQUE_PLACEHOLDER -->` 마커가 critique 자리에 남아 있다. 실패 시 stderr 의 FATAL 메시지를 그대로 Phase 2.5 fail 사유로 기록한다.

### Step 2 — 멀티모달 critique 작성

`designs/*.png` 들과 architecture.md / design-spec.md 를 함께 보고 **기획 · 디자인 두 축의 critique** 를 작성한다. 시각 critique 만으로는 architect 의 컨셉 오해를 잡지 못하므로 기획 축이 1순위다.

**critique 축 1 — 기획 (architecture / spec 정합성)**

architecture.md 의 Overview, Features, Screens, Navigation 을 사용자 아이디어와 비교해 다음을 찾는다:

- 아이디어에 있었지만 빠진 기능 (P2 누락 포함 — capability_coverage 가 강조)
- 화면 수가 너무 많거나 (cognitive overload) 너무 적은 (기능 불충분)
- Navigation 구조가 화면 수에 비해 부적절 (TabView 가 1탭 / NavigationStack 무한 push 등)
- Feature 우선순위가 아이디어와 어긋남 (P0 가 핵심이 아님)
- API/백엔드 필요 여부 판단이 틀림 (로컬 가능한데 backend_required=true 등)
- **차별점이 말뿐 (HIGH)** — Overview / `### Hook & Retention` 의 차별점이 P0 기능 목록에 구현체로 존재하지 않음
- **훅 부재 (HIGH)** — P0 전부가 카테고리 기본 CRUD (목록+상세+추가/삭제) 뿐이고 다운로드 이유가 되는 기능이 없음
- **재방문 이유 부재 (MEDIUM)** — 히스토리 축적·streak·주기적 가치 등 리텐션 메커니즘이 기능 셋에 없음
- **첫 실행 흐름** — 권한 다이얼로그가 맥락 없이 첫 실행 즉시 뜨는 설계인가 (`firstRunPolicy` / `## First-Run Experience` 와 대조)

**critique 축 2 — 디자인 (시각 / HIG)**

design-spec.md 의 토큰과 Screen-by-Screen Layout 결정을 보고 다음을 찾는다:

- **네이티브 우선 위반 (HIGH 우선)** — 시스템 컴포넌트(`List`/`Form`/`.searchable()` 등)로 충분한 UX 를 정당화 없이 커스텀 뷰로 설계했는지. 커스텀 결정에 "시스템 컴포넌트로 안 되는 이유" 한 줄이 없으면 HIGH 로 보고.
- iOS HIG 위반 소지 (탭 바 구조, 터치 타깃 < 44pt 가 될 레이아웃, 텍스트 크기, contrast)
- 정보 계층 약함 (primary CTA 불명확, 제목/본문/메타 구분 약함)
- empty / loading / error state 누락
- 색 토큰의 접근성 (Primary on background 가 WCAG AA 미달)
- 일관성 결여 (같은 컴포넌트가 화면별로 다른 결정, 화면 전체가 같은 템플릿으로 동질화)
- 디자인이 generic — system blue + system gray 그대로 → 앱 정체성 0 (색 정체성)
- **레이아웃 동질성 / templated (HIGH 우선)** — 모든 화면이 같은 컨테이너(동일 `List`/카드 피드)로 보여 "다른 앱과 구별 안 됨"인지, 4종 Layout Personality 골격을 변형 없이 베꼈는지. architecture.md 의 `### Signature Layout`(hero element·정보 위계·density·화면 간 차별화)이 실제 화면 PNG 에 구현됐는지 대조한다 — primary 화면과 2순위 화면이 시각적으로 구별되지 않으면(둘 다 같은 몰드) HIGH 로 보고하고 어느 화면들이 동일한지 + 어떻게 차별화할지 명시. (위 "generic"이 *색* 정체성이라면 이 항목은 *레이아웃/구성* 정체성. 둘은 별개 축.)

각 항목은 다음 구조로:

```
<severity> <축> <제목>
화면: <N 또는 —>
영향: <왜 문제인가>
개선: <구체 액션 1줄>
```

- severity: `high` (코드 생성 진입 전 반드시 수정), `medium` (수정 권장), `low` (참고)
- 축: `기획` 또는 `디자인`
- **화면**: 그 항목이 가리키는 화면의 **스토리보드 번호** (preview 의 갤러리 카드·화면 목록·flow 노드에 ①②③ 로 표시된 그 숫자). 특정 화면 1개를 지목하는 디자인/HIG 항목은 그 번호를, 앱 전반에 걸친 기획 항목(예: 누락 기능, 화면 수 과다)은 `—` 를 쓴다. **이 번호로 critique 가 해당 화면 카드(`#screen-N`)에 딥링크된다** — 사용자가 "어느 화면의 어디"를 눈대중하지 않게 하는 핵심.
- 총 항목 수: **3–8 개 범위**. 너무 많으면 사용자가 무시. 너무 적으면 게이트 가치 없음

발견할 게 없으면 정직하게 비워두지 말고 `<positive>` 항목 1–2 개 (왜 좋은 결정인지) + medium/low 1–2 개 (개선 가능한 nuance) 를 적는다.

### Step 3 — HTML 에 critique 주입

`<!-- CRITIQUE_PLACEHOLDER -->` 와 그 직후 placeholder 문단을 critique HTML 로 교체한다.

critique HTML 형식 (특정 화면을 지목하면 `→ 화면 N` 딥링크 칩을 넣고, 앱 전반 항목이면 칩을 생략):

```html
<ul class="critique-list">
  <li class="critique-item">
    <span class="critique-badge severity-high">HIGH · 디자인</span>
    <strong>{제목}</strong>
    <a class="critique-screen" href="#screen-{N}">→ 화면 {N}</a>
    <p class="muted">영향: {영향}</p>
    <p>개선: {개선}</p>
  </li>
  <li class="critique-item">
    <span class="critique-badge severity-medium">MEDIUM · 기획</span>
    <strong>{앱 전반 항목 제목}</strong>
    <p class="muted">영향: {영향}</p>
    <p>개선: {개선}</p>
  </li>
  ...
</ul>
```

`href="#screen-{N}"` 의 `N` 은 위 critique 항목의 `화면:` 번호와 동일해야 한다 (`.critique-screen` 클래스 스타일은 빌더가 이미 주입). `화면: —` 인 항목은 `<a class="critique-screen">` 줄을 넣지 않는다.

배지 색 (스킬이 작성하는 HTML 안에 inline style 으로 포함, 외부 CSS 변경 금지):

| severity | 배경 | 텍스트 |
|----------|------|--------|
| high | `#ff3b30` | white |
| medium | `#ff9500` | white |
| low | `#8e8e93` | white |
| positive | `#34c759` | white |

주입은 Edit 도구로 정확히 두 문자열 (placeholder marker + 그 다음 문단) 을 replace 한다.

### Step 4 — 브라우저 자동 열기

```bash
open "$PWD/.autobot/designs/preview/index.html" 2>/dev/null || \
  xdg-open "$PWD/.autobot/designs/preview/index.html" 2>/dev/null || \
  echo "INFO: 브라우저 자동 열기 실패. 수동으로 .autobot/designs/preview/index.html 을 여세요."
```

성공/실패 무관하게 다음 메시지를 화면에 출력:

```
✅ Plan Preview 생성 완료
  파일: .autobot/designs/preview/index.html
  critique: <high N> · <medium N> · <low N> · <positive N>

검토 후 다음 중 하나:
  /autobot:resume         — 마음에 들면 Phase 3 (코드 생성) 진입
  /autobot:plan           — 같은 디렉토리에서 디자인 재생성
  (이 디렉토리 폐기)      — 새 디렉토리에서 /autobot:plan <새 아이디어>
```

### Step 5 — Phase 2.5 advance

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 2.5 \
  --metadata preview_html_path=.autobot/designs/preview/index.html \
  --metadata critique_count_high=<N> \
  --metadata critique_count_medium=<N> \
  --metadata critique_count_low=<N>
```

Gate `2.5->3` 은 preview HTML 존재만 검사하므로 critique 가 부실해도 pass 한다. critique 의 품질 강제는 **이 스킬의 contract** — gate 가 아니다. 발견 항목이 0개여도 positive 1개 이상은 반드시 남긴다.

## Failure Modes

| 증상 | 원인 | 동작 |
|------|------|------|
| `architecture.md` 없음 | Phase 1 미완 | Phase 2.5 fail — `/autobot:resume 1` 안내 |
| `design-spec.md` 없음 | Phase 2 미완 | Phase 2.5 fail — `/autobot:resume 2` 안내 |
| `designs/*.png` 0 개 | 정상 (Phase 2 는 design-spec 직접 저작, 목업 없음) | 갤러리는 placeholder, critique 는 design-spec.md 기반으로 작성 후 진행 |
| `app-icon-1024.png` 없음 | Phase 2 fallback | WARN, 헤더 아이콘만 생략하고 진행 |
| `open` / `xdg-open` 둘 다 실패 | 헤드리스 환경 | 경로만 출력 후 진행 (Phase 2.5 는 success) |

## Non-goals (v1 에서 의도적으로 뺀 것)

- **critique 의 외부 LLM 위탁** — 현재 self (Claude) 가 멀티모달로 직접 분석. codex 위탁은 cost / 신뢰성 비교 후 v2.
- **"Approve / Reject" 버튼 + watcher** — HTML 검토 결과를 자동 captures 하지 않는다. 사용자가 다음 명령 (`/autobot:resume` 또는 `/autobot:plan`) 으로 결정을 표현한다.

## Why this skill exists

mvp 자율 흐름의 약점은 architect / ux-designer 의 **첫 패스** 결과가 사람 검토 없이 Phase 3–5 의 코드로 곧장 변환되는 것이다. 잘못된 architecture 위에서 5분간 코드가 생성된 뒤 발견하면 모두 폐기. preview HTML 은 사람이 평가 가능한 가장 빠른 surface — iOS 빌드 + 시뮬레이터 + Xcode Run 의 사람 개입 없이도, 비기술 stakeholder 까지도, 화면 단위로 평가할 수 있다.

이 스킬이 잡으려는 두 실패 모드:
1. **컨셉 오해** — architect 가 사용자 아이디어를 잘못 해석 (시각 critique 만으로는 못 잡음 → 기획 축 critique 필수)
2. **시각 / HIG 실패** — ux-designer 가 generic / 접근성 미달 / iOS 답지 않은 디자인 결정을 내림 (시각 critique 가 잡음)
