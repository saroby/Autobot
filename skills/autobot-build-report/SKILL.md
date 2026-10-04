---
name: autobot-build-report
user-invocable: false
description: "Write the Phase 7 build report or inspect a completed Autobot run."
---

# Build Report Generator

Phase 7에서 이번 빌드의 **Autobot 플러그인 문제와 수정 제안**을 `.autobot/build-report.md`에 기록한다. 누적 기계 학습은 `autobot-retrospective`의 `learnings.json`이 맡는다.

## 입력과 출력

`.autobot/build-state.json`, `.autobot/build-log.jsonl`, Phase 5의 기존 xcodebuild 결과, 프로젝트 산출물, 로그에 없는 세션 관측을 수집한다. 에이전트 실패·수동 개입·컴파일/Gate 실패·fallback·병목을 포함한다. **Phase 7에서 xcodebuild를 다시 실행하지 않는다.**

[report-template.md](references/report-template.md)를 채운다. 각 문제에 증상, 실제 에러, 원인, 영향, **플러그인 내 수정 대상 경로**, 실행 가능한 수정 제안을 쓴다. 성공 패턴과 재현에 필요한 환경도 기록한다.

| 분류 | 수정 대상 |
|------|----------|
| `agent-prompt` | `agents/*.md` |
| `orchestrator-logic` | `skills/autobot-orchestrator/` |
| `gate-validation` | `skills/autobot-orchestrator/references/phase-gates.md` |
| `tooling` | `scripts/` |
| `template` | `skills/autobot-ios-scaffold/references/project-templates.md` |
| `style-guide` | `references/ios-ux-style.md` |
| `fallback-missing`, `ux-friction` | 해당 스킬·에이전트·Phase 로직 |

심각도 순서: `critical`(빌드 중단/데이터 손실) → `major`(수동 개입 필요) → `minor`(완료했으나 불편) → `info`(개선 기회).

중단된 빌드도 보고한다. 완료 Phase의 실제 결과, 실패 Phase의 에러·재시도, 미실행 Phase의 "미실행" 상태를 구분한다. Circuit Breaker가 발동했다면 전체 재시도 이력을 포함한다.

생성 후 보고서 경로, 심각도별 문제 수, 성공 패턴 수, 수정 제안 수를 간결하게 보고한다.
