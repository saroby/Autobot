## Step 3: Build-Fix Loop

이 스킬의 핵심. 빌드를 실행하고, 실패하면 에러를 진단하여 수정하는 루프.

첫 빌드 전에 복구 가능한 attempt 0 체크포인트를 저장한다.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" build-checkpoint save --attempt 0
```

### 빌드 명령

```bash
# 사용 가능한 시뮬레이터를 동적으로 탐색
SIM_DEST=$(xcrun simctl list devices available -j | python3 -c "
import json, sys
data = json.load(sys.stdin)
for runtime, devices in data['devices'].items():
    if 'iOS' in runtime:
        for d in devices:
            if 'iPhone' in d['name'] and d['isAvailable']:
                print(f\"platform=iOS Simulator,id={d['udid']}\")
                sys.exit(0)
print('generic/platform=iOS Simulator')
")
xcodebuild -project *.xcodeproj -scheme <scheme> \
  -destination "$SIM_DEST" \
  build 2>&1 | tee /tmp/xcb-attempt-${ATTEMPT}.log | tail -50
```

### Error Signature 기록 (필수, 매 attempt 후)

빌드가 실패한 직후 stderr 를 `error_signature.py` 로 정규화해 누적한다. 같은 시그니처가 spec `policies.circuitBreaker.errorSignatureRepeat.maxRepeats` (기본 2) 만큼 반복되면 breaker 가 트립되어 더 이상 동일 에러를 고치지 않는다 — 시간 낭비 방지.

```bash
SIGNATURE_RESULT=$(python3 "$CLAUDE_PLUGIN_ROOT/scripts/error_signature.py" \
  record --phase 5 --stderr-file /tmp/xcb-attempt-${ATTEMPT}.log)
echo "$SIGNATURE_RESULT"  # {"tripped":true|false,"occurrences":N,"hash":"..."}

# 매 attempt 를 이벤트로도 남긴다 (run-summary 가 사용)
HASH=$(echo "$SIGNATURE_RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['hash'])")
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" build-checkpoint save \
  --attempt "$ATTEMPT" --error-signature "$HASH"
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" \
  --phase 5 --event build_fix_attempt \
  --detail "{\"attempt\":${ATTEMPT},\"signature\":\"${HASH}\",\"category\":\"<A|B|C|D|E>\"}"

# breaker 가 트립되면 반복 signature 이전의 가장 최근 체크포인트로 복원
if echo "$SIGNATURE_RESULT" | grep -q '"tripped":true'; then
  bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" build-checkpoint restore \
    --exclude-signature "$HASH"
  bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event build_fix_loop_exhausted \
    --detail "{\"attempts\":${ATTEMPT},\"lastSignature\":\"${HASH}\",\"abortStrategy\":\"snapshot_restore_then_handoff\"}"
  exit 1
fi
```

### 에러 진단 의사결정 트리

빌드 실패 시 에러 메시지를 **먼저 분류**한 다음 수정한다. 분류 없이 하나씩 고치면 제한된 시도 예산을 소모하기 쉽다.

```
빌드 에러 발생
├── 에러가 10개 이상인가?
│   ├── Yes → 대부분 같은 근본 원인일 가능성 높음
│   │   ├── 모두 "Cannot find type" → import 누락 (1곳 수정으로 연쇄 해결)
│   │   ├── 모두 같은 파일 → 그 파일의 구조적 문제 (시그니처 불일치)
│   │   └── 파일이 다양 → Phase 4 재생성 고려 (코드 품질이 전체적으로 낮음)
│   └── No → 개별 에러 분류 후 수정
│
├── 에러 분류:
│   ├── [A] Import/Module 에러 → references/build-error-catalog.md "Import 에러" 참조
│   ├── [B] Type/Signature 에러 → references/build-error-catalog.md "타입 에러" 참조
│   ├── [C] Concurrency 에러 → references/build-error-catalog.md "동시성 에러" 참조
│   ├── [D] SwiftData 에러 → references/build-error-catalog.md "SwiftData 에러" 참조
│   └── [E] 프로젝트 설정 에러 → references/build-error-catalog.md "프로젝트 에러" 참조
│
└── 수정 전략:
    ├── 같은 카테고리 에러가 3개 이상 → 근본 원인 1개를 찾아 수정 (연쇄 해결 기대)
    ├── 다른 카테고리 에러가 혼재 → 우선순위: [E] → [A] → [D] → [B] → [C]
    │   (프로젝트 설정 → import → SwiftData → 타입 → 동시성 순서)
    └── 같은 에러 시그니처 반복 → circuit breaker 정책에 따라 snapshot 복원 후 중단·인계
```

**에러 카테고리별 상세 패턴과 수정법은 `references/build-error-catalog.md` 참조.**

### 반복 전략

각 빌드 시도마다 이벤트 로그에 기록한다. detail의 `succeeded` 필드는 필수 (true/false):

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event build_attempt \
  --detail "{\"attempt\":${N},\"errors\":${ERROR_COUNT},\"succeeded\":false}"

# 수정 후
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event build_fix \
  --detail "{\"category\":\"import\",\"files\":[\"Views/HomeView.swift\"]}"
```

빌드가 성공하는 순간 다음 두 가지를 **모두** 기록한다 (Gate 5→6의 truth source는 metadata, build-log는 audit only):

```bash
# 감사 로그
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event build_attempt \
  --detail "{\"attempt\":${N},\"errors\":0,\"succeeded\":true}"

# Gate가 읽는 truth source — 최종 advance-phase 호출에 포함 필수
# visualJudge 는 Step 9 가 스크린샷을 얻었을 때만 포함한다 (없으면 Gate 가 benign-skip).
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 5 \
  --metadata build_succeeded=true \
  --metadata 'peerReview={"host":"codex","peer":"claude","verdict":"skipped","skipReason":"peer_cli_unavailable"}' \
  --metadata 'visualJudge={"verdict":"pass","highCount":0,"summary":"design tokens applied"}'
```

> `metadata.build_succeeded=true`와 `metadata.peerReview`가 최종 `advance-phase` 호출에 포함되지 않으면 Gate 5→6는 실패한다. `visualJudge`(Step 9)는 스크린샷을 얻은 경우 함께 전달한다 — 없으면 `visual_judge` 체크가 green-skip 한다.
> `advance-phase`는 metadata를 gate 평가 전에 반영한 뒤 통과 시 `completed`까지 한 번에 기록한다.

매 attempt마다 전체 에러를 다시 분류하고 가장 상위의 근본 원인만 최소 패치한다. 반복 횟수에 따라 파일 삭제나 전체 재작성을 자동 선택하지 않는다. 동일 signature 반복과 최종 소진 시의 rollback/handoff는 spec의 circuit-breaker와 snapshot 정책이 결정한다.

### 수정 범위 판단

```
에러를 고칠 때 어디를 수정할 것인가?

에러가 Models/*.swift 파일에서 보고되었는가?
├── Yes → Models/는 절대 수정 금지 (architect의 타입 계약)
│   ├── "Cannot find type" → 연쇄 에러다. 사용 코드의 import부터 수정
│   ├── "does not conform to Identifiable/Hashable" → 함정 에러. 사용 코드에서 해결
│   │   (상세: build-error-catalog.md "함정 에러" 섹션 참조)
│   └── 타입 불일치 → Models/가 "정답". 사용 코드를 Models/에 맞춰 수정
└── No → 에러가 있는 파일을 직접 수정

수정 후 다른 파일에 연쇄 에러가 예상되는가?
├── Yes → 연관 파일도 함께 수정 (한 번의 빌드로 확인)
└── No → 단일 파일 수정 후 빌드
```
