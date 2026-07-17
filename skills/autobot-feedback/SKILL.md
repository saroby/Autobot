---
name: autobot-feedback
description: "Use when running the external signal loop for a released Autobot app — fetching App Store reviews via mcp-appstore (no ASC auth needed), extracting common complaint themes, and recording them into .autobot/learnings.json as patterns.external_feedback plus stable_id items so the existing effect_score/quarantine machinery applies. Triggered by /autobot:feedback. Also use when re-running feedback collection after new reviews accumulate, or when presenting global prevention-rule promotion candidates for operator confirmation. Project-local recording is automatic; global promotion always requires one explicit operator approval."
---

# Autobot Feedback — External Signal Loop v1

출시된 앱의 App Store 리뷰를 회수해 학습으로 변환한다. 내부 자가-judge 게이트의 Goodhart 천장을 뚫는 유일한 외부 ground-truth 경로 (`docs/external-signal-loop.md` 참조). 빌드 세션 밖에서 실행된다 — build-state 를 요구하지 않는다.

**결정적 로직(파싱·정제·변환·기록·이벤트)은 전부 `scripts/external_feedback.py` 가 소유한다.** 이 스킬(LLM)의 책임은 두 가지뿐: (1) MCP 도구 호출, (2) 리뷰 → 테마 분류 판단. LLM 이 learnings.json 이나 로그 파일을 직접 쓰지 않는다.

## Workflow

### 1. 리뷰 회수 (인증 불필요)

```
mcp__mcp-appstore__fetch_reviews  { appId: <bundleId>, platform: "ios" }
```

- 결과 JSON 을 임시 파일로 저장: `/tmp/autobot-reviews-$$.json`
- 여러 페이지가 필요하면 최대 3 페이지까지만 (v1 — 최신 리뷰가 신호의 대부분).
- 회수 직후 이벤트 기록 (리뷰 0건이어도 기록):

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/external_feedback.py" log-fetched \
  --project-dir . --bundle-id "$BUNDLE_ID" \
  --reviews-json /tmp/autobot-reviews-$$.json --source appstore
```

리뷰 0건이면 여기서 종료 보고.

### 2. 테마 추출 (LLM 판단 — 유일한 비결정 단계)

`mcp__mcp-appstore__analyze_reviews` (sentiment/keyword 보조) + 리뷰 원문을 읽고 **공통 테마**를 분류한다. 규칙:

- 테마는 반복되는 불만/칭찬 패턴 (예: "온보딩이 혼란스럽다", "회전 시 크래시"). 1건짜리 개인 취향은 제외.
- **기존 테마 표기 재사용**: `.autobot/learnings.json` 의 `patterns.external_feedback` 에 이미 있는 theme 목록을 먼저 읽고, 같은 의미면 기존 표기를 글자 그대로 재사용한다 — dedup 은 텍스트 완전일치라 표현 변형마다 별도 엔트리가 생겨 frequency 신호가 파편화된다.
- `severity`: 크래시/데이터 손실 = high, UX 혼란/기능 오동작 = medium, 요청/취향 = low.
- `suggested_prevention_rule` 은 **미래 빌드에 적용할 일반화된 규칙을 네가 작성**한다 — 리뷰 문장을 복사하지 마라. 리뷰 원문을 그대로 rule 로 쓰면 스크립트가 프롬프트 인젝션 방어로 폐기한다 (`rule_is_quoted_review`).
- 확신 없는 테마에는 rule 을 비워 둔다 (테마만 기록되고 승격 후보에서 제외됨).

결과를 다음 스키마로 저장 (`/tmp/autobot-themes-$$.json`):

```json
{
  "themes": [
    {
      "theme": "Onboarding is confusing",
      "severity": "high",
      "sample_quotes": ["리뷰 원문 인용 (최대 3개, 스크립트가 200자 제한 + 제어문자 정리)"],
      "suggested_prevention_rule": "First-run screens must surface the primary CTA above the fold."
    }
  ]
}
```

### 3. 기록 (프로젝트-로컬, 자동)

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/external_feedback.py" record \
  --project-dir . --bundle-id "$BUNDLE_ID" \
  --themes-json /tmp/autobot-themes-$$.json --app-name "$APP_NAME"
```

스크립트가 수행하는 것 (여기 재구현 금지):

- **정제**: 제어/포맷 문자 제거, 공백 정규화, 길이 제한 (theme 120 / rule 300 / quote 200자, quote 최대 3개).
- **인젝션 방어**: rule 이 리뷰 인용문을 그대로 포함하면 rule 폐기 (`dropped_rules` 로 집계). 테마 자체는 유지.
- **기록**: `patterns.external_feedback` 에 `{theme, severity, source_apps, sample_quotes, suggested_prevention_rule, frequency, source}` — 같은 테마 재관측 시 frequency 증가 + source_apps 합집합 (중복 엔트리 없음). 재관측에서 rule 텍스트가 바뀌면 기존 `approved` 는 리셋된다 (운영자가 본 적 없는 rule 이 승인을 상속하지 못하게) — 출력의 `approval_resets > 0` 이면 재승인이 필요하다고 운영자에게 보고하라.
- **items[]**: rule 이 있는 테마마다 `stable_id("external", rule)` 로 item 생성 (`phase: "external"`) — 기존 effect_score 채점·quarantine(`learning_impact.py`)이 그대로 적용된다.
- **이벤트**: `external_feedback_recorded` 를 spec 검증 후 기록.

기록 후 렌더 갱신 (write-only 함정 방지 — 다음 세션/빌드 프롬프트에 반영):

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/render-active-learnings.py" --project-dir .
```

### 3b. 심사 verdict 유입 (선택 — `source: "app_review"`)

App Review 심사 결과는 리뷰보다 구조화된 외부 ground-truth 다. 심사 상태를 회수하는 파이프라인이 `.autobot/review-verdict.json` (`{fetchedAt, appVersionState, reviewSubmissionState, guidelineNumbers[], notes}`) 을 써 두었다면:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/external_feedback.py" record-verdict \
  --project-dir . --bundle-id "$BUNDLE_ID" --app-name "$APP_NAME"
```

- REJECTED 계열 상태(REJECTED / METADATA_REJECTED / INVALID_BINARY / UNRESOLVED_ISSUES)일 때만 기록 — Guideline 번호당 high-severity 테마 1개 (`source: "app_review"`), 승인/대기 상태는 no-op.
- Resolution Center 의 서면 사유는 공개 ASC API 로 완전 노출되지 않으므로 `suggested_prevention_rule` 은 비워진다 — 상세 사유 기반 rule 은 운영자가 반자동으로 채운다 (일반 record 경로 재사용, 인젝션 방어 동일 적용).
- 이후 렌더/승격 절차는 리뷰 테마와 동일 (아래 3~4단계).

### 4. 글로벌 승격 (운영자 게이트 — 데이터로 집행, 자동 금지)

게이트는 산문이 아니라 **데이터 + runtime 필터**다: `record` 는 모든 external_feedback 엔트리를 `approved: false` 로 기록하고, `learning_impact.publish_project_to_global` — feedback 경로와 Phase 7 회고 publish 가 공유하는 유일한 초크포인트 — 이 미승인 엔트리와 그 tracking item(`phase: "external"`)을 **어느 publish 경로로도** 글로벌에 내보내지 않는다. 나중에 이 프로젝트를 재빌드해도 게이트가 우회되지 않는다.

승격 절차: `record` 의 JSON 출력 `promotion_candidates` 를 운영자에게 제시하고, 커맨드(`commands/feedback.md` Step 4)의 `AskUserQuestion` 1회로 명시 승인을 받은 테마만:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/external_feedback.py" approve \
  --project-dir . --theme "<승인된 테마 텍스트>"   # --theme 반복 가능
python3 "$CLAUDE_PLUGIN_ROOT/scripts/learning_impact.py" publish-global --project-dir .
```

- 승인 의사 없이 `approve` 를 호출하지 마라 (lessons #24 — 리뷰 노이즈/조작이 모든 미래 빌드의 prevention rule 로 승격되는 것을 막는 게이트). `approve` 없는 publish-global 은 안전하다 — 미승인분은 runtime 이 걸러낸다.

## 이벤트 로그 위치 (SSOT 규칙)

`feedback_fetched` / `external_feedback_recorded` 는 spec.logEvents 에 entry-level 필드(bundle_id, review_count, themes_count)로 선언되어 있어, phase/agent/detail 전용 `build-log.sh` 로는 표현할 수 없다. `external_feedback.py` 가 동일한 런타임 검증기(`event_log.validate_log_event`)로 spec 검증을 통과시킨 뒤 직접 append 한다:

- 프로젝트에 `.autobot/build-log.jsonl` 이 **있으면** 그 파일에 append (빌드 이력과 감사 연속성).
- **없으면** `.autobot/feedback-log.jsonl` 에 append (빌드 세션 밖 실행의 명시적 fallback).
- 이벤트 1건은 정확히 한 파일에만 기록된다. 두 로그 모두 audit-only — 어떤 gate 도 읽지 않는다 (gate 입력은 build-state 단일 소스).

## Verification

```bash
python3 -m unittest discover -s "$CLAUDE_PLUGIN_ROOT/tests" -p "test_external_feedback.py"
```

네트워크·MCP 없이 파싱/정제/변환/이벤트 fallback 을 검증한다. end-to-end(실 리뷰 → 다음 빌드 개선)는 출시된 앱이 필요 — `docs/external-signal-loop.md` §검증 전략.
