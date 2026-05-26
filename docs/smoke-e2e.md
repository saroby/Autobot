# Smoke E2E

`tests/run_tests.sh` 회귀 슈트는 stdlib unittest 만 사용하기 때문에 Xcode/simulator 실제 동작을 검증할 수 없다. Smoke E2E 는 그 공백을 메운다.

## 검증 범위

| # | 단계 | 도구 | 통과 조건 |
|---|------|------|----------|
| 1 | scaffold | `skills/autobot-ios-scaffold/scripts/create-xcode-project.sh` | `.xcodeproj` 생성 |
| 2 | env snapshot | `scripts/env_snapshot.py capture` | 스냅샷 파일 생성 |
| 3 | build | `xcodebuild build` (Debug, iphonesimulator) | `.app` 산출물 존재 |
| 4 | boot + install + launch | `xcrun simctl` | PID 반환 + 생존 확인 |
| 5 | cleanup | `simctl terminate/uninstall` + workdir 삭제 | 0 leftover |

## 로컬 실행

```bash
bash scripts/smoke-e2e.sh                 # 기본 — 전체 파이프라인
bash scripts/smoke-e2e.sh --no-launch     # 빌드까지만 (시뮬레이터 부팅 비용 회피)
bash scripts/smoke-e2e.sh --keep          # workdir 보존 (디버그)
bash scripts/smoke-e2e.sh --workdir DIR   # 임시 dir 지정
```

소요: 빌드 ~60s + 시뮬레이터 부팅 ~30s + launch 검증 ~10s. 첫 부팅이면 +수 분.

## CI

`.github/workflows/smoke-e2e.yml` 가 nightly 09:00 UTC (18:00 KST) 와 `workflow_dispatch` 로 실행. macos-15 runner + Xcode 26 사용. 실패 시 `/tmp/autobot-smoke-*/` 로그를 artifact 로 업로드 (7일 보존).

## 종료 코드

| 코드 | 의미 |
|------|------|
| 0 | 성공 |
| 1 | 환경 부족 (Xcode/simulator/SDK 26+) |
| 2 | scaffold 실패 |
| 3 | build 실패 |
| 4 | simulator/install/launch 실패 |
| 5 | env_snapshot 실패 |

## 미커버 영역

이 smoke 는 의도적으로 **Autobot 의 LLM 의존 단계는 검증하지 않는다**:

- Phase 1 architect — LLM 산출 architecture.md
- Phase 2 ux-designer — Stitch MCP 호출
- Phase 4 ui-builder / data-engineer — 코드 생성
- Phase 6 deployer — TestFlight 업로드 (ASC 자격 필요)

이들은 결정론적이지 않거나 외부 서비스/자격증명을 요구하므로 CI 의 범위를 벗어난다. 회귀 보호가 필요한 결정론적 부분(스캐폴드 → 빌드 → simulator 부팅) 만 smoke 가 책임진다.

## 후속 후보

1. **xclog 캡처 통합** — launch 후 30s `xclog launch` 로 `print()` / `Logger` 출력 캡처해 `[smoke]` 로그 1줄 발견 시 PASS.
2. **build_succeeded 메타데이터 검증** — `xcodebuild_runner.py scaffold_build` 결과가 `phases.5.metadata.build_succeeded` 를 정확히 기록하는지 smoke 가 직접 확인.
3. **결정론적 LLM mock** — Foundation Models stub 으로 Phase 1/4 까지 확장.
