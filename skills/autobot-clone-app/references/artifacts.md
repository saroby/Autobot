## Output Artifacts

| 산출물 | 경로 | 소비자 |
|-------|------|--------|
| 탐험 로그(시각·탭/스와이프 전이·입력 길이·커버리지·재개 상태) | `.autobot/clone/flow.jsonl` | Step 2·2a·2b |
| WDA 세션·기기 프로필·선택적 HTTP 계측 | `.autobot/clone/wda-session.json`, `device-profile.json`, `http-metrics.jsonl` | 재개·동일 기종 렌더·병목 진단 |
| flow 맵 | `.autobot/clone/flow-map.html` | 사람 검토 (Step 2a·2c) |
| 역기획 | `.autobot/clone/reverse-brief.md` | 사람 · `/autobot:mvp` |
| 원본 캡처 + 트리 | `.autobot/clone/raw/*.png`, `*.xml` | Step 3 측정 |
| 측정값 | `.autobot/clone/screens/*.json` | Step 4·5 |
| 측정 증거(요소 표·레이아웃) | `.autobot/clone/screens/*.md` | 사람 리뷰 · 스펙이 링크 (기계 소유, 매번 덮어씀) |
| 화면 스펙 + 동작 계약 | `.autobot/clone/specs/<ViewName>.md` | 사람 리뷰 · `/autobot:mvp` (사람 소유) |
| SwiftUI 재현 | `.autobot/clone/Sources/*.swift` | 빌드 |
| state/view 매핑 + 관찰 전이 라우터 | `.autobot/clone/views.json`, `Sources/ObservedFlow.swift` | 기능 재생 |
| 반복 단위 초안(감지 → 사람 확인) | `.autobot/clone/structure/*.json` | 사람 리뷰 (Step 3a) |
| 사람이 선언한 state 병합 | `.autobot/clone/state-aliases.json` | `load_flow` (로딩 단계로 갈라진 한 화면) |
| 연구용 자산과 출처 | `.autobot/clone/assets/*`, `assets/manifest.json` | 연구용 clone 빌드·감사 |
| 대조 이미지 | `.autobot/clone/compare/*.png` | Step 6 검증 |
| 렌더 접근성 트리 (AXe 설치 시) | `.autobot/clone/compare/*-rendered.tree.json` | Step 6 구조 diff (`clone_structural_diff.py`) |
| 화면별 점수 이력 (통과·실패 모두) | `.autobot/clone/scores.jsonl` | 퇴행 탐지 · 조일 한도의 근거 |
| 화면별 최근 판정 | `.autobot/clone/compare/*.verdict` | `polish --changed` 가 읽는 유일한 근거 |
| 변덕스러운 영역 선언 (사람 소유) | `.autobot/clone/exclusions.json` | 시계·배지·재정렬 피드를 점수에서 제외 |
| 측정·렌더 캐시 | `.autobot/clone/.postprocess-cache.json`, `render-cache/` | 반복 실행 가속 |
| clone Xcode 작업공간 | `.autobot/clone/project/CloneWorkspace.xcodeproj` | Xcode/CoreDevice 준비 및 이후 구현 빌드 |
| 대상 앱 바인딩(bundle ID · 기기가 보고한 이름) | `.autobot/clone/target.json` | Step 6c 표시 이름 · 감사 |
| 실기기 설치 프로젝트 | `.autobot/clone/device-app/` | Step 6c |

기계 진입점은 `scripts/clone_run.sh` 하나다. 기본 완주 경로는 `observe`·`functional`·`polish`이고, `verify`는 뒤의 두 게이트를 순서대로 실행한다. `codegen`은 기기 없는 복구, `install`은 선택적 실기기 설치다.
