# 하네스 경량화

OpenAI의 [최신 모델 지침](https://developers.openai.com/api/docs/guides/latest-model)과
[스킬·프롬프트 정리 지침](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)에
맞춰 기본 컨텍스트를 줄였다. 긴 절차는 현재 단계의 reference로 읽고, 공통 지시와 출력 계약은 진입 문서에 유지한다.

- 스킬 26개와 에이전트 8개의 설명은 선택 조건과 작업 범위만 담는다.
- integration-build, app-review, clone-app, copy-analyze, orchestrator는 단계별 reference를 사용한다. 전체 reference를 미리 읽지 않는다.
- UI/data/backend 코드 예제는 선택적으로 읽는다. 실제 Models·ServiceProtocols·feature-spec과 파일 소유권이 우선한다.
- context-pack은 모든 기존 입력 경로와 출력 계약을 전달하고, 경로 정렬용 공백·파일 해시·크기 표시는 생략한다. 8 KiB는 경고 기준이며 초과해도 내용을 자르지 않는다.
- clone 문서 동기화는 연결된 reference도 검사·복사하고, 그 문서의 runtime 스크립트가 설치본과 일치하는지 먼저 확인한다.
- 필수 검증이 통과하면 관련 변경이나 실패가 생길 때만 해당 검사를 반복한다. Gate·재시도 정책·샌드박스·배포 승인 경계는 기존 실행 계약을 따른다.
- Codex 에이전트는 호스트 모델을 상속한다. Claude 전용 tier routing도 유지한다. 이 변경은 모델이나 reasoning effort를 강제로 바꾸지 않는다.

## 로컬 측정

2026-10-02 수정 전후 UTF-8 바이트 수다. 토큰 수·실제 모델 latency·정확도 측정이 아니다.

| 표면 | 이전 | 이후 | 감소 |
|------|-----:|-----:|-----:|
| 주요 스킬 5개 진입 본문 | 209,175 B | 약 33,200 B | 약 84% |
| UI/data/backend 에이전트 진입 본문 | 40,680 B | 28,646 B | 29.6% |
| 설명 34개 | 14,498 B | 2,903 B | 80.0% |
| Phase 4 context-pack, 입력 26개 fixture | 3,131 B | 1,602 B | 48.8% |

필요한 reference를 읽으면 그 내용은 컨텍스트에 추가된다. 표는 첫 로딩 본문 감소를 나타내며, 전체 작업 토큰 감소율을 보장하지 않는다.

검증은 로컬 회귀 테스트, reference 링크와 설치 동기화, 출력 계약 보존, spec/docs 일치에 한정한다.
실제 모델 품질·비용·시간은 동일 모델/effort에서 새 앱 빌드, 중단 재개, 컴파일 실패 복구,
clone 관찰·검증, 심사 controller 재개를 비교해야 한다. 완료율, 필수 증거, 토큰, 시간, 비용을 함께 보고
기존 결과보다 나빠지는 작업에만 필요한 지침을 추가한다.
