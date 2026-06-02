# External Signal Loop — 설계 스파이크 (미구현)

> **상태: 설계만. 코드 없음.** 출시된 앱 + (일부) ASC 인증이 있는 환경에서 구현한다.
> 이 문서는 "왜 이게 최고 leverage 인가"와 "어떻게 만들 것인가"를 명문화해 다음
> 구현자가 0 부터 다시 설계하지 않게 한다.

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

## learnings 저장소 — 핵심 설계 질문 (미해결)

이게 이 기능의 진짜 난점이다. 단순 구현이 아니라 아키텍처 선택이다.

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
  외부적이지만 완벽한 ground-truth 는 아니다. `effect_score` 처럼 신호→개선의 실제 효과를
  추적해 나쁜 학습을 quarantine.
- **글로벌 learnings 아키텍처**: 현재 프로젝트별 → 글로벌 저장소 신설이 v1 의 가장 큰 작업.
- **리뷰→learning 변환 신뢰성**: LLM 분류가 노이즈를 prevention rule 로 승격할 위험 →
  사람 검토 게이트 1회 필수 (자동 승격 금지).
- **회수 빈도/비용**: 언제·얼마나 자주 회수? 출시 후 1주/1개월 등 운영자 트리거.

## 관련

- 첫인상 시딩·시각 동질성(0.11.0) = per-build 품질 (다른 시계).
- quality-max 모드 = 내부 게이트 엄격화 (같은 천장 안).
- **이 문서 = 천장을 뚫는 유일한 외부 닻.** 우선순위 최상위지만 *느린* 베팅.
