## Step 8: Opposite-Runtime Peer Review (필수 시도, soft-skip)

빌드와 Axiom critical audit 이 통과했으면 `autobot-peer-review-bridge` 스킬을 실행한다. 현재 실행 위치가 Codex면 Claude에게, Claude면 Codex에게 Phase 5 산출물을 리뷰시킨다.

```bash
Read $CLAUDE_PLUGIN_ROOT/skills/autobot-peer-review-bridge/SKILL.md
```

기록 규칙:

- `phases.5.metadata.peerReview.verdict == "PASS"` → Gate 5→6 진행.
- peer 도구 부재/호출 실패 → `verdict="skipped"` 와 `skipReason` 기록 후 진행.
- `verdict == "FAIL"` → `blockingFindings` 를 Step 3 Build-Fix Loop 의 다음 에러 배치로 처리한다.
- 누락/실패/비감사 가능 결과는 hard fail 이 아니라 Gate 5→6 의 DEGRADED evidence 로 남긴다. 로컬 MVP 완료는 계속 진행하고, 출하 경로가 non-passed Gate 5→6 을 거부한다.
