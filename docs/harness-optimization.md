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

## 2026-10-04 추가 스킬 최적화

앱 아이콘을 제외한 25개 스킬을 검토해 22개를 축약했다. 이미 간결한 app-review·clone-app·integration-build 라우터는 유지했다. 중복 프롬프트, 일반 도구 설명, 반복 명령·예시와 스크립트 내부 구현 설명을 제거했다. 기존 reference로 본문을 옮기거나 새 reference를 만들지 않았다.

| 측정 대상 | 이전 | 이후 | 감소 |
|-----------|-----:|-----:|-----:|
| `SKILL.md` 25개 파일, 줄 수 | 3,649 | 1,560 | 57.2% |
| 같은 파일의 UTF-8 바이트 수 | 208,872 B | 105,158 B | 49.7% |

Frontmatter·자동 생성 Phase 표·입출력 경로·스키마·승인 경계·sandbox·실기기 증거·출하 preflight·원래 lock token 해제 계약을 유지했다. 인증 방식·환경 변수 우선순위·CLI 옵션·결과 enum·실제 수정 대상 경로의 오래된 설명은 현재 소스와 일치시켰다.

측정은 파일 분량이며 토큰·비용·latency나 실제 모델 완료율 측정은 아니다. 연결된 상세 reference는 현재 단계에 필요할 때 읽는다.

최종 검증: `bash tests/run_tests.sh` 1회, 1,595 tests OK; `verify_spec_docs.py`, `spec_bundle.py check`, 전체 스킬 YAML/공통 스키마·reference·자동 생성 블록 보존 검사와 `git diff --check` 통과. 실제 모델 실행 품질 비교나 배포 검증은 하지 않았다.
