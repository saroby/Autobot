## 보고 / 회고

Phase 7 은 두 산출물을 순서대로 생성:

1. **`build-report.md`** — `autobot-build-report` 스킬 사용. 플러그인 수준 문제를 구조화.
2. **`learnings.json`** — `autobot-retrospective` 스킬 사용. 누적 학습 + `effect_score` 갱신.

Phase 7 직후 `run-summary.json` / `run-summary.md` 가 모든 run (성공/실패) 에 대해 생성된다 — phase duration, gate 결과, build attempts, runtime smoke 결과, visual contract 점수, applied learnings, **capability coverage** (미지원 카테고리·P2 stub·backend pending·검증 prereq 설치 안내·검증 깊이 caveat — `scripts/capability_coverage.py`) 포함. 완료 보고는 coverage 의 격차를 침묵하지 않고 화면에 표면화한다.

## Additional Resources

| Reference | 내용 |
|-----------|------|
| `references/phase-gates.md` | Phase 별 검증 항목, 통과 조건, 실패 시 동작 |
| `references/learning-bootstrap.md` | 학습 로드 프로토콜 SSOT |
| `references/architecture-template.md` | architecture.md 템플릿 |
| `references/planning-patterns.md` | 아이디어 분석, 기능 추출, 복잡도 추정 |
| `references/agent-dispatch.md` | 병렬 에이전트 프롬프트, 전체 fileOwnership 매트릭스 |
| `references/troubleshooting.md` | 증상별 진단 + 해결법 |
| `autobot-integration-build` 스킬 | Phase 5 Build-Fix Loop, Wiring 패턴, 에러 카탈로그 |
