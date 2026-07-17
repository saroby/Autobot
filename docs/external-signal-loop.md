# External Signal Loop — v1 구현됨

> **상태: 구현됨 (v1, 리뷰 기반).** 진입점 `/autobot:feedback` (`commands/feedback.md`),
> 워크플로우 `skills/autobot-feedback/SKILL.md`, 결정적 로직
> `scripts/external_feedback.py`, 단위 검증 `tests/test_external_feedback.py`.
> crash/retention 등 ASC 인증 메트릭은 v2 로 남아 있다.

## 구현 요약 (v1)

- `/autobot:feedback [bundleId]` — bundleId 미지정 시 `.autobot/architecture.json`
  (fallback: build-state.json) 에서 해석. 빌드 세션 밖 운영자 트리거.
- fetch_reviews → analyze_reviews → LLM 테마 추출 → `external_feedback.py record` 가
  `patterns.external_feedback` `{theme, severity, source_apps, sample_quotes,
  suggested_prevention_rule, frequency}` + `items[]` (`stable_id("external", rule)`,
  `phase: "external"`) 기록 → 기존 effect_score/quarantine 재사용.
- 렌더 소비자: `render-active-learnings.py` 의 `## External Feedback` 섹션
  (write-only 함정 방지). 리뷰 원문 quotes 는 프롬프트에 렌더되지 않는다 —
  테마·심각도·빈도만 렌더하고, quotes 는 운영자 승인 판단용으로만
  learnings.json 에 남으며 글로벌 publish 시 strip 된다 (인젝션 잔여 경로 봉쇄).
- 리뷰 텍스트는 신뢰 불가 입력: 제어/포맷 문자 제거·길이 제한, 리뷰 원문을 그대로
  베낀 prevention rule 은 폐기 (`rule_is_quoted_review`).
- 이벤트: `feedback_fetched` / `external_feedback_recorded` (spec.logEvents 선등록).
  entry-level 필드라 build-log.sh 로는 표현 불가 → `external_feedback.py` 가
  `event_log.validate_log_event` 로 spec 검증 후 직접 append. 대상: build-log.jsonl
  이 있으면 그 파일, 없으면 `.autobot/feedback-log.jsonl` (이벤트당 정확히 한 파일,
  audit-only — gate 는 읽지 않음).
- 글로벌 승격: 후보 제시 → `AskUserQuestion` 운영자 확인 1회 →
  `learning_impact.py publish-global`. 자동 승격 금지 (lessons #24). 같은 테마
  재관측에서 rule 텍스트가 교체되면 `approved` 는 자동 리셋된다 — 운영자가 본
  적 없는 rule 이 승인을 상속해 자동 승격되는 우회를 막는다.
- 심사 verdict 유입: app-review 파이프라인이 남긴 `.autobot/review-verdict.json`
  을 `external_feedback.py record-verdict` 가 읽어 REJECTED + Guideline 번호를
  `source: "app_review"` high-severity 테마로 같은 저장소에 합류시킨다 (상세
  사유는 운영자 반자동 — SKILL §3b). crash/retention 은 여전히 v2.

## 왜 (leverage)

Autobot 의 모든 품질 게이트(visual_judge · peer review · axiom · functional flow ·
critique)는 **내부 자가-judge** 다. 빌드 산출물을 빌드 자신의 기준으로 판정하므로
**Goodhart 천장**에 갇힌다 — "탁월한 앱"의 ground-truth 가 시스템 안에 없다.

두 차례의 외부 품질 보고서 검증과 플러그인 평가가 **일관되게 도달한 결론**: 더 많은
내부 게이트는 천장을 *더 정교하게* 만들 뿐 *뚫지* 못한다. **외부 ground-truth(출시 후
사용자 신호)만이 그 닻이다.** `learnings.json` 은 현재 내부 빌드 산출물에만 닫혀 있고,
유일한 post-deploy 데이터는 `upload_success`(업로드 메커닉, 수신 아님)다. loop-closing
도구는 환경에 **이미 있는데 미배선**이다 (아래).

## 신호 소스 + 인증 (조사 완료)

| 신호 | 도구 | 인증 | appId |
|------|------|------|-------|
| 리뷰 텍스트·평점 | `mcp-appstore` `fetch_reviews`/`analyze_reviews` | **불필요 (public 스크래핑)** | bundle ID 또는 numeric ID |
| 앱 상세·버전 이력 | `mcp-appstore` `get_app_details`/`get_version_history` | 불필요 | bundle ID |
| 노출/전환/리텐션 | `aso-skills:asc-metrics` | **ASC API Key** | 자기 앱 |
| 크래시 | `aso-skills:crash-analytics` | ASC API Key | 자기 앱 |

- **핵심 발견**: 리뷰/평점 회수는 **ASC 인증이 전혀 필요 없다** (도구 스키마가 `appId`+
  `platform` 만 받음). bundle ID 는 이미 `architecture.json` 에 있다.
- ASC API Key(비공개 메트릭용)는 **이미 `/autobot:setup` §3.7 이 받아** `~/.autobot/.env`
  에 저장한다 (deploy 와 공유). 별도 setup 수정 불필요.

## 회수 트리거

출시 후 리뷰는 며칠~몇 주 뒤 쌓이므로 **빌드 흐름과 분리된 별도 명령**:

```
/autobot:feedback <앱 또는 bundle ID>
```

`app-review` 는 Phase G(submit)에서 끝난다. feedback 은 그 *이후* 의 독립 루프다 —
같은 빌드 세션이 아니라, 운영자가 출시 후 임의 시점에 돌린다.

## learnings 저장소 — 핵심 설계 질문 (v1 에서 해소: 둘 다)

v1 결정: 프로젝트-로컬 기록은 자동, 글로벌은 운영자 확인 후 publish. 아래는
원래의 트레이드오프 분석.

- **프로젝트별** (`.autobot/learnings.json`): 그 앱 *재빌드* 시에만 흡수. Autobot 은
  보통 한 번 빌드하고 끝이라 **재빌드가 드물어 leverage 가 낮다.**
- **글로벌** (`~/.autobot/` 또는 `active-learnings`): 여러 앱의 리뷰에서 *공통 패턴*
  (예: "온보딩이 혼란스럽다"가 3개 앱에서 반복) → **모든 미래 빌드의 prevention rule**.
  이게 진짜 leverage. 단 **새 글로벌 학습 저장소 아키텍처가 필요** (현재 learnings 는
  프로젝트별).

**권고**: 둘 다. 프로젝트별엔 그 앱 피드백을, 글로벌엔 cross-app 패턴을 승격. 글로벌
저장소는 기존 `effect_score`/quarantine 메커니즘(`learning_impact.py`)을 재사용.

## 흡수 메커니즘

```
리뷰 회수(mcp-appstore) → 공통 불만 추출(analyze_reviews 또는 LLM 분류)
  → learnings.json patterns 새 카테고리 `external_feedback` (프로젝트)
  → 글로벌 prevention rule 후보 (cross-app)
  → 다음 빌드 Phase 0 learning bootstrap 이 흡수
```

`patterns` 스키마에 `external_feedback` 추가: `{theme, severity, source_apps, sample_quotes,
suggested_prevention_rule}`.

## MVP 범위 (v1)

1. **리뷰 기반만** (인증 불필요 — 즉시 가능). crash/retention(ASC)은 v2.
2. `/autobot:feedback` 명령 → fetch_reviews → analyze_reviews → 공통 테마 추출.
3. 프로젝트 learnings.json `external_feedback` 기록 + 글로벌 prevention rule 후보 제시
   (자동 승격은 사람 검토 1회 — 첫 보고서 검증의 "자동 재작업 금지" 원칙, lessons #24).

## 검증 전략

- **흡수/파싱/변환 로직은 인증 없이 단위 검증 가능** — *임의의 공개 앱* bundle ID 로
  fetch_reviews → 파싱 → learning 변환을 테스트한다 (내 앱이 출시 안 됐어도).
- **end-to-end**("내 앱 출시 → 실 리뷰 → 다음 빌드 개선")는 출시된 앱이 필요 — 이
  환경에선 검증 불가. 그래서 v1 은 흡수 경로만 단위로 닫고, end-to-end 는 실 출시 후.

## 리스크 / 미해결

- **외부 신호도 Goodhart 가능**: 평점 조작·리뷰 편향·소수 vocal 사용자. 자가-judge 보다
  외부적이지만 완벽한 ground-truth 는 아니다. v1: items[] 채널로 `effect_score`/quarantine
  이 그대로 적용된다 — 나쁜 외부 학습도 채점으로 격리된다.
- **글로벌 learnings 아키텍처**: WS3 가 글로벌 저장소(`~/.config/autobot/learnings.json`)
  병합을 멱등화해 해소. external_feedback 리스트는 theme 키로 병합, source_apps 는
  합집합 (cross-app 패턴 감지가 목적이므로).
- **리뷰→learning 변환 신뢰성**: LLM 분류가 노이즈를 prevention rule 로 승격할 위험 →
  v1 에 사람 검토 게이트 1회 구현 (자동 승격 금지). 추가 결정적 방어: 리뷰 인용문을
  그대로 베낀 rule 은 스크립트가 폐기 (프롬프트 인젝션 경로 차단).
- **회수 빈도/비용**: 언제·얼마나 자주 회수? 출시 후 1주/1개월 등 운영자 트리거 (v1 유지).
- **(v2) ASC 인증 메트릭**: crash/retention/전환 — `aso-skills` 도구 + 기존 setup §3.7 키.

## 관련

- 첫인상 시딩·시각 동질성(0.11.0) = per-build 품질 (다른 시계).
- quality-max 모드 = 내부 게이트 엄격화 (같은 천장 안).
- **이 문서 = 천장을 뚫는 유일한 외부 닻.** 우선순위 최상위지만 *느린* 베팅.
