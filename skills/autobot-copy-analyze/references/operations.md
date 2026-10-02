## 이 스킬이 쓰지 않는 명령, 그리고 노브

드라이버에는 이 워크플로가 부르지 않는 명령이 더 있다. **왜 안 쓰는지**를 알아야 잘못 손이 가지 않는다.

| 명령 | 무엇인가 | 이 스킬에서 |
|------|---------|------------|
| `device_wda.sh explore` | 눈 없이 프론티어를 기계적으로 소진하는 루프 | **쓰지 않는다.** 스크린샷을 못 읽으므로 `source=label` 후보를 거부한다 — 커스텀 렌더러 앱에서는 한 발도 못 뗀다. 이 스킬의 루프는 LLM 이 판단하는 `capture → candidates → 판단 → tap` 이다 |
| `device_wda.sh step` | 탭 + 도착 화면 증거를 한 번에 남긴다 | `tap` 후 `screen` 과 같다. 어느 쪽이든 무방하되, 쓴다면 `CLONE_STATE_DIR=` 접두사를 똑같이 붙인다 |
| `device_wda.sh back` | leading nav 슬롯만 누른다 | **쓴다.** 상세 화면에서 나오는 유일한 길이다 (Step 3 참조) |
| `device_wda.sh stop-server` | 이 스크립트가 띄운 Appium 서버를 종료 | Step 6 마무리에서 쓴다. `quit` 은 세션만 닫는다 |
| `device_flow.py audit` | 탐험이 남긴 변경을 사후 감사 | 브리프 작성 전에 한 번 돌려 무엇을 건드렸는지 확인하면 좋다 |

| 환경변수 | 기본 | 무엇을 바꾸나 |
|---------|------|-------------|
| `CLONE_TAP_BUDGET` | 25 | **누적** 탭 상한. `tap` 이 이 수를 넘으면 거부한다 — 실행 단위가 아니라 로그 전체 기준이다 |
| `CLONE_TAP_UNVOUCHED` | (없음) | `1` 이면 기계적 루프가 `source=label` 후보도 탭한다. **이 스킬에서는 켜지 않는다** — 눈으로 확인하는 책임을 없애는 스위치다 |
| `CLONE_PROBE_SWITCHES` | (없음) | `1` 이면 스위치를 켜봤다 되돌린다. 사용자 계정 설정을 건드리므로 **켜지 않는다** |
| `CLONE_STATE_DIR` | `.autobot/clone` | 탐험 로그·`broken-<해시>` 센티넬·기기 프로필·세션 기술자·Appium 서버 상태가 모두 여기 모인다. **이 스킬은 모든 호출에서 `.autobot/copy-analysis` 로 바꿔** clone 과 예산·커버리지를 섞지 않는다 (Step 2) |
| `CLONE_FLOW_LOG` | `$CLONE_STATE_DIR/flow.jsonl` | 로그만 따로 옮긴다. **쓰지 않는다** — 센티넬은 `CLONE_STATE_DIR` 에 남으므로 로그만 옮기면 상태가 두 폴더로 갈린다. 격리는 `CLONE_STATE_DIR` 하나로 한다 |
| `CLONE_SCREEN_SETTLE_TRIES` | 12 | `screen` 이 화면이 멈출 때까지 트리를 다시 읽는 횟수. 느린 네트워크 화면에서 올린다 |
| `CLONE_SCREEN_SETTLE` | 1 | `0` 이면 settle 대기 없이 즉시 캡처한다. **끄지 않는다** — 로딩 중 화면을 "빈 화면"으로 기록하게 된다 |

## Output Artifacts

| 산출물 | 경로 | 소비자 |
|-------|------|--------|
| 제품 브리프 | `.autobot/copy-analysis/brief.md` | 사용자 → `/autobot:plan`·`/autobot:mvp` (architect) |
| **화면 흐름도** | `.autobot/copy-analysis/flow-map.html` | 사용자 — 무엇을 눌러 어디로 갔는지, 무엇이 미탐인지 |
| 탐험 로그 | `.autobot/copy-analysis/flow.jsonl` | `device_flow.py` (흐름도·커버리지·재개). `CLONE_STATE_DIR` 로 clone 의 로그와 분리했다 |
| 접근성 트리 | `.autobot/copy-analysis/device/*.xml` | Step 4 구조 분석 (1급 소스) |
| 실기기 캡처 | `.autobot/copy-analysis/device/*.png` | 시각 보완 + 흐름도 카드 |
| 스토어 스크린샷 | `.autobot/copy-analysis/store/*.png` | 구조 분석 |
| 리뷰 인사이트 | `.autobot/copy-analysis/reviews.md` | 브리프 Hook & Retention 근거 |
