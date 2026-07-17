# /autobot:screen — 화면 하나 집중 인터뷰 스킬 신설 — 2026-07-17

목표: 앱 화면 하나를 인터뷰로 깊게 기획하고, SSOT 문서(AGENTS.md + CLAUDE.md + SOUL.md + docs/) + 로직 제외 SwiftUI 뷰코드까지 산출하는 독립 스킬.

## 수용 조건
- [ ] `/autobot:screen <화면>` 진입점 + `autobot-screen-interview` 스킬 (기존 command/skill 컨벤션 준수)
- [ ] 인터뷰: 혼합 방식(AskUserQuestion 갈림길 + 오픈 질문), 라운드별 스냅샷 → docs/screens/<slug>.md 에 즉시 기록 (중단 재개 가능)
- [ ] SSOT 병합 규칙: 신규 생성 + 기존 문서 비파괴 병합, CLAUDE.md 는 AGENTS.md 참조 (중복 금지)
- [ ] SwiftUI 뷰: presentation-only 정의 명확 (mock 주입, 콜백 파라미터, 상태별 #Preview), 빌드 검증은 advisory
- [ ] Autobot 프로젝트(.autobot/)면 컨텍스트 활용, 아니어도 동작 (독립)
- [ ] README 트리 + CHANGELOG [Unreleased] 반영
- [ ] Workflow 리뷰 패널 (컨벤션·인터뷰 설계·정합성) → confirmed 지적 반영

## 체크리스트
- [x] 리포 컨벤션 조사 (commands/meta.md, skills/autobot-ux-design, plan.md)
- [x] 사용자 결정 확보: 산출물=SSOT+뷰코드, 방식=혼합, 통합=독립
- [x] commands/screen.md 작성
- [x] skills/autobot-screen-interview/SKILL.md 작성
- [x] skills/autobot-screen-interview/references/templates.md 작성 (SSOT 4종 템플릿)
- [x] README + CHANGELOG 갱신
- [x] Workflow 리뷰 → 반영 → Results 기록

## Results (2026-07-17)
- 신규: commands/screen.md, skills/autobot-screen-interview/{SKILL.md, references/templates.md}. 갱신: README(트리 + 독립 명령 소단락 + 누락 명령 3종 보충), CHANGELOG [Unreleased].
- Workflow 리뷰(3렌즈 20에이전트, finding별 적대적 반증): raw 17 → confirmed 15(중복 2 포함, 실질 12) / 기각 2. 전부 반영 —
  주요: allowed-tools Skill 누락(high), status 3분기 재개(confirmed/built 미정의, high), R2 헤딩 계약 불일치(high), R6 하류 전파(high), built 전이 누락(medium), 미결정 에스컬레이션(medium), refreshing/stale 상태 축(medium).
- 검증: 새 파일 frontmatter YAML 파싱 OK, scripts/verify_spec_docs.py All checks passed. (문서 전용 diff — 런타임 테스트 해당 없음)

## Working Notes
- SSOT 역할 분담: SOUL.md=제품 정체성(왜), AGENTS.md=에이전트 작업 규칙 정본, CLAUDE.md=@AGENTS.md 참조+Claude 전용, docs/screens/<slug>.md=화면 spec(인터뷰 주 산출물, 라운드마다 갱신).
- 로직 제외 = 네트워크/저장/ViewModel 금지, 액션은 `var onX: () -> Void = {}` 콜백 노출, 상태는 이니셜라이저 주입.
- 기획 깊이 철칙 (memory): 화면 나열 금지 — R1 에서 훅·3초 가치·성공 기준 필수 도출.
- 게이트 철학 (memory): 빌드 검증 실패는 advisory 보고, hard fail 금지.
