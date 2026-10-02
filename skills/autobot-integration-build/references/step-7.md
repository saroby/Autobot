## Step 7: Axiom Critical Audit (선택, soft-skip)

빌드가 통과하고 Step 6의 grep 체크가 끝났으면, `autobot-axiom-bridge` 스킬의 **Mode 1 (Gate-5 Critical Audit)** 을 실행한다. Axiom 플러그인이 설치되어 있을 때만 동작하며, 미설치 환경에서는 한 줄 로그만 남기고 즉시 통과한다.

```bash
Read $CLAUDE_PLUGIN_ROOT/skills/autobot-axiom-bridge/SKILL.md
```

목적:
- Swift 6 data race / SwiftData 스키마 실수 / 메모리 누수 / SwiftUI 구조 위반처럼 **빌드는 통과하지만 런타임에서 깨지는 4개 클래스**를 한 번에 잡는다.
- 발견된 critical 항목은 Step 3 (Build-Fix Loop) 의 다음 배치로 처리해 수정 → 재빌드 → critical 항목만 재감사 사이클을 돌린다.
- `phases.5.metadata.axiom_critical_audit` 에 결과를 기록 (`ran`, `auditors`, `critical_count`, `findings_path`).

호출 규칙은 bridge 스킬에 SSOT 로 정리되어 있다. 이 스킬에서는 다음만 기억한다:

- Axiom 부재 → soft skip, Gate 5→6 통과에 영향 없음.
- critical 0건 → Gate 5→6 진행.
- critical > 0 → Step 3 로 돌아가 fix_hint 를 따라 수정한다. 한계 도달 시에도 로컬 MVP 완료는 막지 않고 Gate 5→6 에 DEGRADED evidence 로 남긴다.
