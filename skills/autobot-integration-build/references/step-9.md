## Step 9: Visual Fidelity Judge (멀티모달, soft → DEGRADED-only)

빌드와 peer review 가 통과했으면, **빌드된 앱의 실제 화면이 디자인 의도를 충실히 구현했는지** 멀티모달로 판정한다. deltaE 색-매치(`check_visual_contract`)는 informational-only 라 디자인을 무시한 빌드(예: 디자인은 커스텀 coral 인데 system-blue 로 렌더)도 통과시킨다 — 이 step 이 그 격차를 메운다. Phase 2.5 plan-preview 가 *목업*을 비평하는 것과 달리, 여기선 *빌드 산출물*을 디자인 의도와 **비교**한다.

### 9a. 런타임 스크린샷 확보

```bash
JUDGE_SHOT=$(python3 "$CLAUDE_PLUGIN_ROOT/scripts/sim_runtime.py" \
  --project-dir "$PWD" --app-name "<AppName>" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('screenshotPath') or '')")
```

- 스크린샷을 못 얻으면 (`simctl`/시뮬레이터/빌드 부재) `JUDGE_SHOT` 가 빈 값 → **이 step 을 건너뛴다** (verdict 미기록). 이때 Gate 의 `visual_judge` 는 스크린샷도 없으므로 benign-skip(green); runtime_smoke 가 별도로 degraded 처리한다.
- **반대로 스크린샷을 얻었으면 verdict 를 반드시 기록해야 한다.** 스크린샷이 디스크에 있는데 `visualJudge` verdict 가 없으면 Gate 의 `visual_judge` 가 **DEGRADED** 처리한다 (anti-laundering — 검증 가능했는데 안 한 빌드를 VERIFIED 로 세탁 금지, `functional_flows_pass`/`peer_review_acceptable` 와 동일 원칙). 즉 sim 이 있는 환경에서 9b–9c 를 건너뛰면 배지가 DEGRADED 로 떨어진다.

### 9b. 충실도 판정 (Read 로 이미지 직접 분석)

`JUDGE_SHOT` 가 있으면 다음을 Read 해 **비교**한다. **1순위 oracle 은 사용자의 원문 아이디어** — design-spec 은 오케스트레이터가 *직접 작성한* 산출물이라, 그것만 채점하면 spec 에 박힌 결함(예: "꽉 채운다" 면서 letterbox 처방)까지 "spec 과 일치"로 합격시키는 자기-인증 루프가 된다. 그래서:
- **`build-state.json` 의 `idea` (사용자 verbatim)** — 무엇을 만들어 달라 했는가. **최우선.**
- 스크린샷 PNG (`JUDGE_SHOT`) — 빌드된 앱의 실제 렌더
- `.autobot/design-spec.md` + `.autobot/design-spec.json` — 색/타이포/간격 토큰 (보조 의도)
- `.autobot/designs/*.png` — Stitch 목업 (있으면)

먼저 **사용자 원문을 원자적 절(clause)로 분해**하고(예: "윈앰프 UI 그대로" / "기존 .wsz 스킨 사용" / "탭없이" / "화면을 꽉 채우는"), 각 절을 스크린샷에서 **met / unmet** 으로 판정해 `summary` 와 `violations` 에 그대로 적는다. 명시적 사용자 절이 unmet 이면 그것은 design-spec 일치 여부와 무관하게 **HIGH severity violation** 이다 (사용자가 요구한 것을 안 했으므로).

판정 기준 — **빌드가 사용자 요구/디자인을 명백히 버렸는가**를 본다 (보수적: 확신 없으면 pass, 단 *명시적 사용자 절* 위반은 보수성 예외 — 확실하면 fail):

- `verdict="fail"` (HIGH severity) — 디자인은 뚜렷한 정체성(커스텀 팔레트/레이아웃)을 지정했는데 빌드는 **generic system default**(system blue + system gray)로 렌더 / design-spec 의 primary 토큰이 화면에 전혀 안 보임 / 설계된 P0 화면이 **blank·부재**. 반드시 **구체 증거** 인용: 관측 색 vs design 토큰 hex, 부재 화면명.
- `verdict="fail"` (HIGH severity, **templated — 화면 간 동일 몰드**) — 빌드된 화면이 `.autobot/designs/*.png` 목업과 architecture.md 의 **Signature Layout** 계약이 지정한 구분되는 구조 대신, 어느 앱에나 붙일 수 있는 **동일한 generic 몰드**(무표정한 리스트/카드 틀의 복제)로 렌더된 경우. 목업·Signature Layout 과 **대조**해 구체 증거(어떤 화면이 계약의 어떤 구조를 버렸는지)를 인용한다. `/mvp` 자율 경로에서 template smell 을 기계 기록하는 유일한 지점이므로 반드시 이 축을 점검하라 — 게이트 처리는 기존과 동일하게 **DEGRADED-only** (hard fail 금지).
- `verdict="pass"` — 빌드가 디자인 토큰/레이아웃을 충실히 반영. 소프트 드리프트(미세 간격·계층·radius 차이)는 fail 아님 (medium/low 로 summary 에만 기록).

> **보수적 판정 원칙**: 이 게이트의 fail 은 *출하를 막는다* (아래 DEGRADED-only 참조). vision judge 는 비결정적·미보정(ground-truth ~10 빌드)이므로, **애매하면 pass**. fail 은 "디자인을 명백히 버렸다"는 증거가 있을 때만.

### 9c. verdict 기록 (최종 advance-phase 에 포함)

verdict 를 `.autobot/artifacts/visual-judge.json` 에 쓰고, 감사 이벤트를 남긴 뒤, **최종 advance-phase 의 `--metadata visualJudge` 로 전달**한다 (Step 7/8 의 axiom/peerReview 와 동일 패턴):

```bash
mkdir -p .autobot/artifacts
# buildId 를 포함시켜 이 아티팩트를 현재 빌드에 묶는다 — 이전 빌드의 pass 아티팩트
# 재사용을 게이트가 차단(DEGRADED)한다.
BUILD_ID=$(python3 -c "import json;print(json.load(open('.autobot/build-state.json')).get('buildId',''))")
cat > .autobot/artifacts/visual-judge.json <<JSON
{"verdict":"pass","buildId":"$BUILD_ID","highCount":0,"summary":"primary coral #FF6B6B 적용 확인, 탭바·계층 의도대로","violations":[]}
JSON

bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event visual_judge_verdict \
  --detail "{\"verdict\":\"pass\",\"highCount\":0,\"summary\":\"...\"}"
```

> verdict JSON 스키마: `{"verdict":"pass"|"fail", "buildId":"<현재 build-state.json 의 buildId>", "highCount":<int>, "summary":"<1줄>", "violations":[{"severity":"high|medium|low","axis":"디자인","title":"...","evidence":"...","fix":"..."}]}`. `buildId` 가 없거나 state 의 buildId 와 다르면 `check_visual_judge` 가 **DEGRADED** (stale/unscoped 아티팩트 세탁 금지).

### 9d. Gate 매핑 (DEGRADED-only — 빌드를 멈추지 않는다)

`check_visual_judge` 가 `phases.5.metadata.visualJudge` 를 읽어:

| verdict | 스크린샷 | `allowVisualDrift` | 결과 |
|---|---|---|---|
| `pass` (아티팩트 `buildId` == state) | — | — | green |
| `pass` (아티팩트 `buildId` 부재/불일치) | — | false | **DEGRADED** (stale/unscoped 아티팩트) |
| `fail` | — | false (기본) | **DEGRADED** (hard-fail 아님) → 배지 DEGRADED → 출하 차단 |
| 없음/garbled | 있음 | false | **DEGRADED** (anti-laundering — 검증 가능했는데 verdict 없음) |
| 없음/garbled | 없음 | false | benign-skip (green) — sim 부재로 검증 불가 |
| 임의 | — | true | green — `--allow-visual-drift` 가 visual gating 전체 면제 |

**왜 hard-fail 이 아닌가**: Gate 5→6 은 `soft=false` 라 hard-fail 시 Phase 5 가 `failed` + retryCount++ 되어 글로벌 circuit breaker 를 태우고 자율 빌드를 멈춘다. 비결정적 judge 의 false-positive 가 "질문 없이 끝까지"를 깨선 안 된다. 대신 DEGRADED 가 *출하*를 막는다 — `functionalVerification` 을 DEGRADED 로 떨어뜨려 `/autobot:testflight`·`/autobot:app-review` 가 거부한다 (anti-laundering). 운영자는 `/autobot:resume 5 --allow-visual-drift` 로 수용 가능.

### 9e. 결정적 화면-충실도 루프 (occupancy — visual_judge 와 달리 차단함)

visual_judge 는 비결정적이라 DEGRADED-only 다. 하지만 사용자가 화면을 **꽉 채우라**(full-screen / edge-to-edge / 그대로) 요구했는데 UI 가 화면의 일부만 차지하는 것은 **결정적으로 측정 가능한 결함**이라 차단해도 된다. 최종 advance-phase **전에** 직접 실행한다:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/visual_contract.py" --project-dir "$PWD" \
  --screenshot "$JUDGE_SHOT" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['status']); print(d.get('reason','')); print(d.get('occupancy'))"
```

- `status == "failed"` 이고 reason 이 **screen-fill requirement unmet** 이면: 이것은 컴파일 에러와 동급의 결함이다. **Step 3 (Build-Fix Loop) 로 라우팅**해 레이아웃을 고친다 — 고정 크기 윈도우를 화면 폭/높이에 맞춰 채우도록 스케일(floor 정수배 대신 fit-to-screen 분수 스케일), 그리고/또는 sub-window(플레이리스트/EQ)를 기본 스택해 세로를 채운다. 고친 뒤 **재빌드 → 재스크린샷(9a) → 재측정**. `policies.qualityRefineLoop.maxAttempts`(기본 2) 까지 반복.
- `maxAttempts` 소진 후에도 unmet 이면 그대로 advance 한다 — Gate 5→6 의 `visual_contract` 가 hard-fail 하여 Phase 5 가 `failed` 가 되고, 배지가 **UNVERIFIED** 로 정직하게 떨어진다(도구 부재 DEGRADED 로 위장되지 않음). 자율성은 maxAttempts cap 으로 유지된다.
- `status == "passed"` (또는 fill 요구가 없는 앱 → occupancy informational) 이면 그대로 진행.

> 이 루프가 "게이트로는 품질을 못 만든다"는 한계를 메운다: occupancy 게이트는 *이빨*이고, 이 루프가 **렌더 → 사용자 원문 기준 측정 → 안 되면 고치고 재렌더**의 *반복*을 강제한다. visual_judge(9b) 의 사용자-절 위반도 동일하게 Step 3 로 라우팅해 N 회 고친다.
