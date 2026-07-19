---
name: ssot
description: "제품 전체를 인터뷰로 끌어내 정수가 되는 결정을 ssot/ 폴더에 체계적 마크다운으로 남기고, 그 폴더를 별도 git repository(submodule)로 승격해 언제든 코드를 재빌드할 수 있는 청사진으로 관리합니다. SOUL.md·AGENTS.md·CLAUDE.md 도 함께 생성·병합합니다. 어떤 프로젝트에서나 쓰는 독립 명령입니다."
argument-hint: "<제품 한 줄 설명> (예: '지하철 30초 동안 오늘 할 일 하나만 보여주는 앱'). 생략 시 인터뷰 첫 질문으로 시작"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Skill
  - AskUserQuestion
  - WebSearch
---

# Autobot SSOT — 제품 인터뷰 → 청사진(ssot/) + git submodule

> **이 문서는 진입점이다. 실행하지 않는다.**
> 인터뷰 절차·SSOT 병합·submodule 배선의 SSOT 는 **`autobot-ssot` 스킬**이 소유한다.

- **입력** — 제품 한 줄 설명 (생략 시 인터뷰 첫 질문으로 확정)
- **결과물** — `ssot/*.md` (제품 청사진, 주 산출물) + `SOUL.md`/`AGENTS.md`/`CLAUDE.md` 생성·병합 + `ssot/` 를 **git submodule(별도 repo)** 로 승격 (git 없으면 init 먼저)

`/autobot:screen` 이 화면 하나를 깊게 판다면, 이 명령은 **제품 전체**를 판다. 둘은 상보적이다: `ssot/` = 제품 청사진(재빌드마다 재사용), `docs/screens/` = 화면별 spec.

## 왜 이 명령이 있는가

제품의 정수(왜 존재·차별화·기능 경계·도메인·원칙)가 대화와 코드에만 흩어져 있으면, 코드를 다시 만들 때 같은 제품이 나오지 않는다. 이 명령이 잡으려는 실패 모드:

1. **청사진 증발** — 제품 수준 결정이 세션과 함께 사라짐 → `ssot/` 가 라운드마다 즉시 기록.
2. **재사용 불가** — 청사진이 프로젝트에 묶여 재빌드에 못 씀 → 별도 repo(submodule)로 승격해 어디서나 `git submodule add` 로 재사용.

## CRITICAL RULES

1. **정수만 담는다** — 화면 픽셀·구현 디테일은 `ssot/` 밖(코드·`docs/screens/`)에. 기준: "코드를 잃어도 이걸로 같은 제품을 다시 만들 수 있는가".
2. **진입 상태 먼저 판정** — 신규(A) / 중단된 일반 폴더(B) / 이미 submodule(C=UPDATE). C 에서 `gh repo create`·`submodule add` 재실행 금지.
3. **라운드마다 기록** — 중간 결과는 대화가 아니라 `ssot/*.md` 에. 끊겨도 그 폴더에서 재개.
4. **GitHub repo 생성은 실행 전 확인** — 외부로 나가는 동작. 푸시 성공을 검증하기 전엔 원본을 옮기거나 지우지 않는다.
5. **기존 SSOT 비파괴** — 이번 인터뷰에서 드러난 것만 병합. 충돌은 사용자에게 확인.

## 실행 흐름

`autobot-ssot` 스킬을 로드하고 그 절차를 따른다:

1. **Step 0** — 컨텍스트 스캔 + 진입 상태(A/B/C) 판정
2. **R1–R5 인터뷰** — 존재 이유 → 기능 세트 → 도메인 → 원칙 → 성격 (혼합: 갈림길 AskUserQuestion, 열린 질문 대화)
3. **R6 확정** — 청사진 스냅샷 승인
4. **배선** — SSOT 병합 + `ssot/` 를 git submodule 로 승격 (`references/submodule-setup.md`) + 최종 보고
