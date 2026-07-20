---
name: make
description: "현재 프로젝트에 맞는 Makefile 을 생성/갱신합니다. 포트를 바인딩하는 프로그램은 run 타깃이 이전 포트 점유 프로세스를 먼저 kill 해 재시작이 'address already in use' 로 실패하지 않게 합니다. Autobot 파이프라인과 무관하게 아무 프로젝트에서나 사용 가능한 독립 명령입니다."
argument-hint: "[포트 또는 실행 힌트] (예: 8080, 'uvicorn app.main:app', 생략 시 자동 탐지)"
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

# Autobot Make — 프로젝트 Makefile 생성 (포트 재사용 안전)

> **이 문서는 진입점이다. 실행하지 않는다.**
> 탐지 규칙·타깃 선택·포트-kill 규약의 SSOT 는 **`autobot-make` 스킬**이 소유한다.

- **입력** — 포트 번호 또는 실행 명령 힌트 (생략 시 프로젝트 파일에서 자동 탐지)
- **결과물** — `<project>/Makefile` (생성 또는 기존 파일에 비파괴 병합)
- **핵심** — 서버 프로그램의 `make run` 은 `kill-port` 에 의존해 **이전 포트를 먼저 해제**하고 시작

## 무엇을 만드는가

프로젝트 런타임(Node/Python/Docker/Go 등)과 실행 명령·포트를 탐지해 관용 타깃(`install`/`run`/`stop`/`test`/`clean`)을 만든다. 포트를 쓰는 프로그램이면 재시작 시 "address already in use" 를 없애는 `kill-port` 규약을 넣는다.

## CRITICAL RULES

1. **Makefile 레시피는 TAB 들여쓰기** — 스페이스면 `missing separator`. 스킬의 `references/port-targets.mk` 레시피를 탭 보존해 복사한다.
2. **비파괴 병합** — 기존 Makefile 의 사용자 타깃을 지우지 않는다. 없는 것만 추가, 동명 타깃은 확인 후 교체.
3. **해당하는 타깃만** — 포트 안 쓰는 CLI/라이브러리엔 `kill-port` 생략. 없는 명령을 지어내지 않는다.
4. **추측 금지** — 실행 명령·포트는 파일에서 읽고, 못 찾으면 1개만 확인한다.

전체 절차는 `autobot-make` 스킬을 로드해 그대로 따른다.
