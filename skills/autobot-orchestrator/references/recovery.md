## Error Recovery

| 실패 유형 | 대응 | 한도 |
|----------|------|------|
| 에이전트 산출물 누락 | 같은 에이전트 재실행 | spec `phases.<N>.maxRetry` |
| 컴파일 에러 | Phase 5 build-fix loop | spec `policies.buildFixLoop.maxAttempts` |
| 동일 에러 시그니처 반복 | Circuit breaker | spec `policies.circuitBreaker.errorSignatureRepeat` |
| Phase 5 가 Phase 4 산출물 손상 | `snapshot-contracts.sh restore-phase --phase 4` | 2회 실패 시 자동 |
| 외부 시스템 (ASC, fastlane) 실패 | fallback 경로 또는 사용자 안내 | 1 |

복구 기준점은 git 이 아니라 build artifact snapshot — 설계상 git 상태에 의존하지 않는다.
