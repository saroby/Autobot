---
name: autobot-ssot
user-invocable: false
description: Use when the user invokes "/autobot:ssot" to interview the whole product (vision, users, features, domain, principles) and crystallize the decisions into a reusable blueprint — SOUL.md/AGENTS.md/CLAUDE.md at the root plus an `ssot/` folder of systematic markdown managed as a git submodule (its own repository), so the product can be rebuilt from the blueprint later. Also use when resuming a half-finished blueprint (ssot/ present with status "interviewing"/"confirmed") or updating an already-wired ssot submodule.
---

# SSOT — 제품의 정수를 청사진으로

제품 전체를 인터뷰로 끌어내고, 정수가 되는 결정들을 `ssot/` 폴더에 체계적인 마크다운으로 남긴 뒤, 그 폴더를 **독립 git repository(=submodule)** 로 관리한다. 이 청사진 하나로 언제든 코드를 처음부터 다시 만들 수 있게 하는 게 목적이다. 독립 스킬 — Autobot 파이프라인이 아니어도, 어떤 프로젝트에서나 동작한다.

`/autobot:screen` 이 화면 하나를 깊게 판다면, 이 스킬은 **제품 전체를 얕지 않게** 판다. 둘은 상보적이다: `ssot/` = 제품 청사진(재빌드마다 재사용), `docs/screens/` = 화면별 spec.

## 산출물 계약

| 산출물 | 경로 | 역할 | 기존이 있으면 |
|--------|------|------|--------------|
| 제품 청사진 | `ssot/*.md` | **주 산출물.** 라운드마다 갱신, 재빌드의 정본 | 이어서 재개 (status 참조) |
| SOUL.md | 프로젝트 루트 | 제품 정체성 요약 — `ssot/product.md` 를 가리키는 증류본 | 비파괴 병합 |
| AGENTS.md | 프로젝트 루트 | 에이전트 작업 규칙 정본 — SSOT 지도에 `ssot/` 등록 | 비파괴 병합 |
| CLAUDE.md | 프로젝트 루트 | `@AGENTS.md` 참조 + Claude Code 전용 지침만 | 참조 줄만 보장 |
| git submodule | `.gitmodules` + `ssot` gitlink | `ssot/` 를 별도 repo 로 승격 | UPDATE 모드로 재개 |

`ssot/` 파일 세트는 **상한**이지 고정 스캐폴드가 아니다 (템플릿은 `references/templates.md`). 내용이 나온 것만 만든다 — 빈 파일·빈 헤딩 금지.

- `ssot/README.md` — 청사진 인덱스 + status frontmatter + "이 청사진으로 재빌드하는 법"
- `ssot/product.md` — 왜 존재 (문제 · 대상 유저와 그 순간 · 차별화 · 성공 지표)
- `ssot/principles.md` — 제품 원칙 · 하지 않을 것 · 제약
- `ssot/features.md` — 기능 세트 (MVP / 이후, 우선순위)
- `ssot/domain.md` — 도메인 모델 · 핵심 엔티티 · 용어집
- `ssot/design.md` — 디자인 언어 · 톤 · 플랫폼
- `ssot/decisions.md` — 결정 로그 (경량 ADR)

## 인터뷰 철칙 (screen 스킬과 공유)

1. **스캔 먼저, 질문은 나중** — 코드·문서·`ssot/`·`.autobot/` 에서 알 수 있는 것은 묻지 않는다. 이미 결정된 것은 "이렇게 이해했는데 맞나요" 확인만.
2. **한 라운드 = 한 주제.** 라운드가 끝나면 결정 요약(스냅샷)을 보여주고 정정 기회를 준 뒤 해당 `ssot/*.md` 에 즉시 기록한다. 기록은 항상 **기존 섹션에 항목 추가** — 같은 헤딩을 두 번 만들지 않는다.
3. **갈림길은 AskUserQuestion** (선택지 2–4개 + 추천 표시), **열린 질문은 대화로.** 한 호출에 질문 최대 4개, 한 라운드에 호출 1–2회.
4. **모호한 답은 시나리오로 한 번 되묻는다** — 구체 상황으로. 그래도 안 나오면 추천안을 **잠정 채택**해 `(잠정)` 표시 + `decisions.md` 에 재검토 항목 등록 후 진행. 같은 질문 두 번 금지.
5. **제품 나열 금지 (기획 깊이)** — R1 에서 문제·차별화·성공 지표를 반드시 도출한다. "무엇을 만드나" 전에 "왜 존재하나".
6. **스코프 = 제품의 정수** — 화면 픽셀·구현 디테일은 여기 담지 않는다 (그건 `docs/screens/` · 코드 소유). 청사진은 "코드를 잃어도 이걸로 같은 제품을 다시 만들 수 있는가" 기준으로 담는다.
7. **답을 유도하지 않는다** — 선택지에는 실제로 다른 결과를 낳는 대안만.

## Step 0: 컨텍스트 스캔 + 진입 상태 판정

질문 전에 조용히 수행. **먼저 submodule 상태를 판정한다** — 이게 전체 흐름을 가른다.

```bash
git rev-parse --is-inside-work-tree 2>/dev/null   # git 여부
git submodule status ssot 2>/dev/null             # 이미 submodule?
grep -q 'path = ssot' .gitmodules 2>/dev/null && echo SUBMODULE
test -f ssot/.git && echo SUBMODULE_FILE          # ssot/.git 이 파일이면 submodule
ls ssot/README.md SOUL.md AGENTS.md CLAUDE.md 2>/dev/null
ls .autobot/architecture.md 2>/dev/null           # Autobot 컨텍스트(있으면 답을 미리 채움)
```

**3가지 진입 상태 (반드시 먼저 분기):**

- **상태 A — `ssot/` 없음**: 신규. 인터뷰 → 청사진 생성 → 끝에서 submodule 배선.
- **상태 B — `ssot/` 가 일반 디렉토리** (submodule 아님, 인터뷰 중단): `ssot/README.md` frontmatter status 로 재개.
  - `interviewing` → 마지막 라운드 다음부터 이어간다.
  - `confirmed` → 인터뷰 생략, "청사진 확정 + submodule 배선" 부터.
- **상태 C — `ssot/` 가 이미 submodule** (`.gitmodules` 에 등록 / `ssot/.git` 이 파일): **UPDATE 모드**. `gh repo create`·`submodule add` 를 **절대 다시 하지 않는다**. 무엇을 바꿀지 확인 → 해당 라운드만 재오픈 → **submodule 안에서** 편집·커밋·푸시 → 부모 gitlink 갱신 (`references/submodule-setup.md` UPDATE 절차).

스캔 결과와 판정한 진입 상태를 2–4줄로 요약해 보여주고 시작한다. 상태 A/B 에서 `ssot/README.md` 를 status `interviewing` 으로 만든 시점부터 인터뷰 산출물이 파일에 쌓인다.

기존 코드/`.autobot/architecture.md` 가 있으면 앱 컨셉·기능·유저를 읽어 이미 답이 있는 질문을 지운다 — 그런 프로젝트에서는 인터뷰가 대부분 "확인형"이 된다.

## 인터뷰 라운드

표준 6개. 컨텍스트가 이미 답을 주면 라운드를 축소·확인형으로 바꾼다 — 형식이 아니라 청사진의 완성이 목적이다.

### R1 — 존재 이유 (오픈 대화 중심) → `ssot/product.md`
- 이 제품은 **누구의 어떤 문제**를 푸나? 그 사람은 지금 그 문제를 어떻게 견디고 있나?
- 대체재 대비 **다르게 만드는 한 가지(차별화)** 는?
- 제품이 성공했다는 걸 무엇으로 아나? (**성공 지표** — 숫자 또는 관찰 가능한 행동)

산출: 제품 한 문장 정의 + 문제 + 대상 유저·순간 + 차별화 + 성공 지표.

### R2 — 기능 세트 (혼합) → `ssot/features.md`
- 차별화를 성립시키는 **핵심 기능**을 대화로 도출 (R1 에서 자연히 나오는 것 위주).
- **MVP 경계**는 AskUserQuestion 으로 확정 — 첫 버전에 반드시 있어야 할 것 vs 이후. 유저를 끌어들이는 훅이 MVP 안에 있는지 점검한다.
- 각 기능에 우선순위 (P0/P1/P2) 표시.

산출: 기능 표 (기능 · 우선순위 · 왜 필요) + MVP 경계선.

### R3 — 도메인 모델 (혼합) → `ssot/domain.md`
- 제품이 다루는 **핵심 개념(엔티티)** 과 그 관계를 함께 도출한다. 재빌드 시 데이터 모델의 씨앗이 된다.
- 헷갈리기 쉬운 **용어**는 한 줄 정의로 용어집에 고정 (에이전트마다 다르게 부르는 것 방지).

산출: 엔티티 목록 (엔티티 · 핵심 속성 · 관계) + 용어집.

### R4 — 원칙과 하지 않을 것 (AskUserQuestion 중심) → `ssot/principles.md`
- 이 제품이 절대 타협하지 않는 **원칙 2–4개** (예: "0-설정으로 3초 안에 가치", "광고 없음").
- **하지 않을 것** — 의도적으로 배제하는 기능·패턴 ("왜 없어요?"에 대한 선답변).
- 재빌드가 지켜야 할 **제약** (플랫폼, 규제, 성능·프라이버시 바).

산출: 원칙 목록 + 안 할 것 + 제약.

### R5 — 성격과 디자인 (혼합) → `ssot/design.md`
- 톤 키워드 3개 + 그것이 UI 에서 뜻하는 것.
- 플랫폼·폼팩터, 레퍼런스 제품 (있으면; 필요시 WebSearch).
- 모션 성격, 다크모드 방침 등 재빌드가 알아야 할 디자인 방침.

산출: 톤 + 플랫폼 + 레퍼런스 + 디자인 방침.

### R6 — 확정
`ssot/` 전체(+ `README.md` 의 재빌드 안내)를 최종 스냅샷으로 보여주고 승인받는다. 수정 요청은 해당 라운드 결정을 고치되, 상류 결정(R1 차별화·R2 MVP 경계)이 바뀌면 의존 하류(기능·도메인)를 함께 점검해 갱신하거나 유지 이유를 `decisions.md` 에 남긴다. 승인되면 `README.md` status 를 `confirmed` 로 바꾸고 SSOT 병합 + submodule 배선으로 진행한다.

## SSOT 병합 (SOUL/AGENTS/CLAUDE)

순서: `ssot/*.md` (완성) → SOUL.md → AGENTS.md → CLAUDE.md. 템플릿은 `references/templates.md`.

**병합 규칙 (기존 파일이 있을 때):**
- 기존 섹션·문장을 임의 삭제·재작성하지 않는다. 이번 인터뷰에서 **드러난 것만** 추가한다.
- SOUL.md: `ssot/product.md`·`ssot/principles.md` 의 **증류본**. 세부는 `ssot/` 에 두고 SOUL 은 요약 + "정본은 ssot/" 포인터.
- AGENTS.md: SSOT 지도에 두 소유를 **명시**한다 — `ssot/` = 제품 청사진(재빌드마다 재사용), `docs/screens/` = 화면별 spec. `/autobot:screen` 과 헤딩을 다투지 않게 한다.
- CLAUDE.md: 첫 줄 `@AGENTS.md` 참조 없으면 추가. AGENTS.md 와 중복 금지.
- 충돌하면 덮어쓰지 말고 사용자에게 어느 쪽이 맞는지 확인.

## git submodule 배선 (핵심 — 실패 지점 집중)

전체 절차·정확한 커맨드·실패 처리는 **`references/submodule-setup.md`** 소유. 요지만:

- **git 없으면** 부모에서 `git init` 먼저 (사용자가 명시 요청한 동작).
- **원격 위치는 AskUserQuestion 으로 확정** — GitHub repo 생성(추천, 프로젝트 간 재사용 가능) / 로컬 bare repo / 지금은 건너뛰기. **GitHub repo 생성은 외부로 나가는 동작이라 실행 전 확인**을 받는다.
- 레시피: `ssot/` 내용 완성 → `ssot` 안에서 `git init`·commit → 원격 생성·**푸시 성공 검증** → 부모에서 `mv ssot ssot.tmp && git submodule add <url> ssot && rm -rf ssot.tmp`. **푸시 성공을 확인하기 전에는 `mv`·`rm` 하지 않는다** (부분 푸시 시 재-clone 이 불완전 → 원본 유실).
- **멱등성**: repo 이름 충돌(`gh repo create` 실패)은 이 플러그인의 register-app 패턴대로 already_exists → 기존 원격 재사용(조용한 성공, 에러 아님). 상태 C(이미 submodule)면 배선을 건너뛰고 UPDATE 절차로.
- 부모의 `.gitmodules` + gitlink 커밋은 배선의 일부로 **권장**한다 (staged 상태로 방치하면 취약). 커밋 여부·내용을 최종 보고에 명시.

repo 이름은 프로젝트에서 유도한다 (기존 `origin` 또는 디렉토리명 → `<project>-ssot`). 배선 완료 후 `ssot/README.md` status 를 `blueprinted` 로 갱신한다.

## 최종 보고

- 진입 상태 (A 신규 / B 재개 / C 업데이트) 와 무엇을 했는지
- 제품 한 문장 정의 + 차별화
- 생성·변경 파일: `ssot/*.md` 목록 + SSOT 4종 상태(생성/병합/유지)
- submodule 상태: 원격 URL, 부모 커밋 여부, `git submodule status ssot` 결과
- `decisions.md` 에 쌓인 미결/재검토 항목
- 재빌드 안내 한 줄: "다른 프로젝트에서 `git submodule add <url> ssot` 로 이 청사진을 재사용할 수 있다."

## 중단·재개

어느 단계에서 끊겨도 `ssot/` 가 진실이다. 다음 호출 때 Step 0 이 진입 상태(A/B/C)와 `README.md` status 로 이어갈 지점을 정한다. 별도 상태 파일을 만들지 않는다.
