# iOS 앱 복제(clone) 생태계 조사 — 프로세스 · 기술 · 노하우

조사일: 2026-08-28 · 대상: 공개된 스킬/툴/벤치마크/논문 · 목적: `autobot-clone-app` / `autobot-copy-analyze` 에 흡수할 것 찾기

---

## 0. 결론 먼저

**"iOS 실기기에서 앱을 관측해 SwiftUI 로 재현하고 기능까지 검증한다"를 통째로 하는 공개 스킬은 없다.** 생태계는 네 조각으로 흩어져 있고, 각 조각은 웹(HTML/CSS) 도메인에서 훨씬 성숙해 있다. Autobot clone 이 이미 가진 것(실기기 게이트 · 접근성 트리 실측 · 픽셀 색 샘플링 · 기능 먼저/픽셀 나중 게이트 · 재개 가능성)은 **공개 생태계 어디에도 한 몸으로 존재하지 않는다.**

배울 것은 "무엇을 만들까"가 아니라 **"검증을 어떻게 숫자로 만들고, 루프를 어떻게 싸게 돌리는가"** 다. 특히 세 가지:

1. **닫힌 루프의 계약화** — Cloning Bench 의 *screenplay*(action/assert/wait) + 반칙 금지 가드레일
2. **비교의 공학** — 정렬 후 diff, 제외 영역, SSIM/블록매칭 같은 *연속값* 지표 (통과/실패 이분법이 아님)
3. **루프 비용** — 프런티어 에이전트 4종 모두 세션 시간의 **40~50%를 검증에 썼다**. 검증을 빠르게 하는 것이 모델을 바꾸는 것보다 점수를 더 올린다.

---

## 1. 조사 결과 — 생태계 지도

### A. 바이너리/정적 리버싱 (IPA → 구조)

**[incogbyte/iOS-reverse-engineering-claude-skill](https://github.com/incogbyte/iOS-reverse-engineering-claude-skill)** — 이 축의 유일한 성숙 스킬. Unlicense(퍼블릭 도메인).

- 입력: `.ipa` / `.app` / Mach-O / `.dylib` / `.framework`
- 파이프라인: `ipsw class-dump` → Info.plist·entitlements·임베디드 프레임워크·문자열 → API 엔드포인트 탐색(URLSession/Alamofire/Moya/GraphQL/WebSocket) → 호출 흐름 추적(VC→VM→Service→APIClient) → 보안 감사 → 클라우드 크리덴셜 스캔 → r2/rizin/Ghidra headless 디컴파일 → **SDK 지문(+CVE 대조)** → 보호기법 탐지(점수 0~20)
- 구조: `commands/extract-ipa.md` 슬래시 커맨드 + `skills/*/SKILL.md` + `scripts/*.sh` 9개 + `references/*.md` 9개 + Ghidra Java 스크립트 5개

> **클론 관점의 가치**: 화면 재현엔 안 쓰인다. 그러나 *"이 앱은 무슨 SDK 조합으로 만들어졌나 / 백엔드 API 형상이 어떤가"* 는 `copy` 의 제품 브리프 품질을 크게 올린다. 다만 IPA 를 **합법적으로 확보한 경우에만** 성립 — Autobot clone 이 이미 "바이너리 추출을 약속하지 않는다"고 선언한 경계와 정확히 같은 자리다.

### B. 기기 구동/관측 (실행 중인 앱 → 구조)

| 도구 | 성격 | 핵심 |
|---|---|---|
| **[mobile-next/mobile-mcp](https://github.com/mobile-next/mobile-mcp)** | MCP 서버 | *accessibility-first* — 접근성 트리로 구동, 비전 모델·이미지 토큰 안 씀. 스크린샷+좌표는 폴백. iOS/Android × 시뮬/에뮬/실기기 단일 API |
| **[XcodeBuildMCP](https://www.xcodebuildmcp.com/)** (+ `idb_companion`) | MCP 서버 | `describe_ui` / `snapshot_ui` 로 정확한 프레임을 받고 **"스크린샷에서 좌표를 추측하지 말 것"** 을 규칙으로 명시. tap/swipe/long-press/type/screenshot/녹화 |
| **Appium MCP** | MCP 래퍼 | Appium 이 노출하는 전체 UI 그래프를 **구조화된 크롤러**로 쓴다는 관점 |

> Autobot clone 은 이 계층을 이미 `scripts/device_wda.sh` 로 자체 구현했고, 실기기 iOS 18+ RemoteXPC 터널·CoreDevice 복구·세션 재사용 같은 **공개 툴들이 사용자에게 떠넘기는 부분까지** 흡수해 있다. 여기서 배울 건 도구가 아니라 **규칙 문구** 하나다: *"좌표는 추측하지 않는다"* 를 스킬 계약의 1급 문장으로 둘 것.

### C. 디자인 시스템 추출 (화면 → 토큰)

- **[skillui](https://github.com/amaancoderx/skillui)** — URL/로컬 디렉터리/깃 레포에서 디자인 시스템 추출. **AI·API 키 없음, 순수 정적 분석.** 모드: URL(Playwright 로 computed style) · dir(css/scss/tsx 스캔, Tailwind config, CSS 변수) · repo · **ultra(스크롤 스크린샷 + 애니메이션 라이브러리 탐지)**. 출력은 `SKILL.md` + `CLAUDE.md` + 레퍼런스 문서 + JSON 토큰 + 폰트 + `.skill` ZIP — **에이전트가 자동으로 읽는 형태로 패키징**하는 것이 핵심 아이디어.
- **[arvindrk/extract-design-system](https://github.com/arvindrk/extract-design-system)** — 스킬 + CLI. 색/타이포/간격/반경/그림자 → W3C 호환 `tokens.json` + `tokens.css`. **스코프를 스스로 좁힌다**: "public 사이트만, 단일 페이지, 스타터 토큰이지 컴포넌트 라이브러리 아님, **픽셀 완벽 재현용이 아니라 초기화용**". 보안 항목에 *"대상 사이트는 신뢰할 수 없는 제3자 입력"* 을 명시.
- **[Codia AI](https://codia.ai/blog/figma-to-swiftui)** — 상용. 스크린샷/이미지 → Figma 편집 가능 레이어 → SwiftUI. iOS 도메인에서 유일하게 상용화된 "이미지→네이티브 코드" 경로. 포지셔닝은 *"first pass, 리뷰하고 리팩터해서 상태에 연결하라"*.

> **배울 점 1**: 산출물을 *에이전트가 읽는 포맷*으로 패키징한다(skillui). Autobot 은 `.autobot/clone/` 에 증거를 남기지만, 그것을 **다음 세션이 자동으로 집어드는 스킬 형태로** 접어주면 재개 비용이 더 내려간다.
> **배울 점 2**: 한계를 문서 상단에 스스로 못박는 습관(extract-design-system). Autobot clone 이 이미 하고 있는 것 — 계속 유지할 근거.

### D. 클론 루프와 검증 (재현물 ↔ 원본)

이 축이 **가장 배울 게 많다.**

**[Cloning Bench (Vibrant Labs, 2026-03)](https://vibrantlabs.com/research/cloning-bench)** — 프런티어 에이전트 4종에게 Slack 을 클론시키고 6시간 무인 세션을 측정한 벤치마크. 아래 §2 에서 상세히 다룬다.

**[ui-cloner 스킬](https://lobehub.com/skills/kensledev-dotfiles-ui-clone)** — "역공학 조립 라인": *대상을 찍는다 → 현재 상태를 찍는다 → diff → 정밀 스펙 추출 → 빌드 계획*. 두 모드로 갈린다:

```
dev_url 이 주어졌나?
├─ YES → COMPARISON MODE : 양쪽 캡처 → 시각 diff → 갭 분석 → 계획
└─ NO  → GREENFIELD MODE : 대상만 캡처 → 전체 스펙 추출 → 처음부터 계획
```

산출물이 **spec 과 plan 으로 분리**돼 있고, plan 의 각 태스크는 "생성/수정할 정확한 파일 + 정확한 클래스값(모호한 '큰 글씨' 금지) + 브레이크포인트별 반응형 + 스크린샷이 못 잡는 인터랙티브 상태 + 의존성 순서 + **커밋 하나 크기**"를 요구하는 체크리스트를 통과해야 저장된다.

**[visual-pixel-perfect 스킬](https://lobehub.com/skills/nguyenthienthanh-aura-frog-visual-pixel-perfect)** — `IMPLEMENT → RENDER → SNAPSHOT → COMPARE → FIX` 를 **통과하거나 max attempts 까지** 반복. baseline/current/diff 3단 스냅샷 관리, pngjs+pixelmatch, CI 아티팩트로 diff 이미지 배출.

**[auto-image-diff](https://github.com/AdamManuel-dev/auto-image-diff)** — 이 축에서 기술적으로 가장 배울 게 많은 도구. **픽셀 diff 이전에 컴퓨터 비전으로 두 이미지를 정렬**한다.
- `align -m feature|phase|subimage` — 특징점/위상상관/부분이미지 정렬
- `-e exclusions.json` — 무시할 영역 정의 (동적 콘텐츠·상태바·시간)
- `--smart-diff` — 차이를 **content / style / layout / size / structural** 로 분류
- `--suggest-css` — 스타일·레이아웃 차이에 대한 수정 제안 생성
- `refine --auto --exclude-types content,style` — 점진적 정제

**[Design2Code](https://arxiv.org/pdf/2403.03163) / [Web2Code](https://arxiv.org/pdf/2406.20098) 계열 벤치마크** — 지표 설계의 표준.
- 고수준: **CLIP 임베딩 코사인 유사도** (텍스트 영역 마스킹 → 레이아웃/구조에 집중)
- 저수준: OCR 로 텍스트 블록+바운딩박스 추출 → **Jonker-Volgenant 알고리즘으로 최적 매칭** → 블록 재현율 · 텍스트 일치 · 공간 정렬 · **색 유사도**를 각각 점수화

### E. 탐험(exploration) 연구

- **[AppAgent](https://github.com/TencentQQGYLab/AppAgent)** — 탐험 단계에서 **앱 레벨 지식 베이스**를 쌓고 배포 단계에서 재사용. "탐험 결과를 문서로 남겨 다음 실행이 싸진다"는 구조.
- **GPTDroid / LLMDroid / AutoDroid / LLM-Explorer** — GUI 테스트를 Q&A 로 재구성해 액티비티 커버리지 +32%. **UTG(UI Transition Graph)** 를 구조화된 앱 메모리로 구축. LLM-Explorer 는 *탐험 비용 절감* 자체를 문제로 놓는다.
- **[OmniParser V2 (Microsoft)](https://microsoft.github.io/OmniParser/)** — **순수 비전으로 스크린샷을 구조화된 요소 목록으로 파싱**. 6.7만 장 UI 스크린샷으로 파인튜닝한 아이콘 검출 모델 + 기능 설명 모델, Set-of-Marks 오버레이. V2 는 작은 요소 정확도↑, 지연 60%↓.

> **직결되는 발견**: Autobot clone/copy 가 겪는 **role-blind 화면 문제**(커스텀 렌더러 앱이 전부 `XCUIElementTypeOther` 로 나와 후보 0개 — 실측 zeta 3.47.0 홈: 요소 144개, 라벨 60개, 후보 0개)는 **OmniParser 류 비전 검출기가 정확히 겨냥하는 문제**다. 현재의 라벨-리프 티어는 "라벨이 있는" 컨트롤만 건진다. 라벨조차 없는 아이콘 버튼은 여전히 사각지대이고, 그건 비전으로만 메워진다.

---

## 2. Cloning Bench — 프로세스 노하우의 본체

### 2.1 방법론

1. **사람이 실제 세션을 녹화**한다. 중요한 순간마다 마커 키를 누른다.
2. 녹화 파이프라인이 캡처하는 것: 전체 영상 · 마커마다 **고정 해상도 스크린샷** · 각 assertion 시점의 **전체 HTML + 스타일 + 접근성 정보** · 이미지/아이콘/폰트.
3. 녹화에서 **screenplay** 를 생성 — action / assert / wait 의 구조화된 시퀀스:
   ```json
   { "type": "action", "description": "헤더의 'Invite teammates' 버튼에 호버" },
   { "type": "assert",  "description": "툴팁/호버 상태가 보인다",
     "screenshot": "screenshots/1/screenshot.png" }
   ```
   Slack 세션 1개 = **43 스텝 / 33 시각 assertion**.
4. `site-test` 하네스가 클론을 이 시나리오대로 몰고 다니며 스크린샷을 찍고 **픽셀 diff 를 붉게 표시해 돌려준다.** 에이전트가 읽고 고치고 다시 돌린다.
5. 스펙은 모호하지 않고(*"이 픽셀에 맞춰라"*), 피드백은 정밀하며, 루프는 예산이 허용하는 만큼 돈다.

### 2.2 가드레일 — 반칙 금지를 계약에 쓴다

`AGENTS.md` 에 **하드 제약 2개**를 프롬프트로 박아둔다:

1. **스크린샷 임베딩 금지** — 참조 스크린샷을 `<img>` / CSS background / base64 data URI 로 깔지 못한다.
2. **DOM 통째 주입 금지** — `dom.html` 을 `dangerouslySetInnerHTML` 로 렌더링하지 못한다.

반면 **허용·권장**: 매니페스트를 통한 개별 자산(아이콘·로고·폰트) 추출, DOM 스냅샷/접근성 트리/computed style 을 **디자인 스펙으로 참조**하는 것.

> 이 구분이 정확히 Autobot clone 의 `assets/manifest.json` + `research-only` 정책과 같은 사고다. 조사 시점에 Autobot 에는 "스크린샷을 그대로 `Image` 로 깔아 화면을 위조하지 않는다"는 명문 규정이 없었다 — 픽셀 게이트를 숫자로 세우는 순간 이 반칙이 최단 경로가 되기 때문에, **규칙 11 과 `--max-asset-coverage` 게이트로 지표 강화와 같은 커밋에 넣었다**(§4).

### 2.3 결과 (6시간 무인 세션)

| | Claude (Opus 4.6) | Gemini (3 Pro) | GLM 5 | Codex (GPT-5.3) |
|---|---|---|---|---|
| 최종 평균 SSIM | 0.757 | **0.871** | 0.723 | 0.583 |
| SSIM 개선폭 | +0.142 | **+0.254** | +0.060 | **−0.010** |
| 테스트 실행 횟수 | 14 | 41 | 91 | 46 |
| 테스트 성공률 | 71% | 71% | 25% | 43% |
| JSX / CSS 라인 | 925 / 1,657 | 2,194 / 467(+4.8MB 실제 CSS) | 677 / 998 | 483 / 782 |
| 추출 자산 | 34 | 62 | 20 | 19 |
| **인터랙티브 기능** | **Full** | **None** | **Full** | **Full** |

### 2.4 여기서 나오는 다섯 개의 교훈

**① 충실도 ↔ 인터랙티비티는 부분적으로 경쟁한다.**
Gemini 는 앱을 쓴 게 아니라 **컴파일러를 썼다** — Cheerio 로 `dom.html` 을 파싱해 JSX 로 기계 번역하는 Node 파이프라인 10개 + 원본 프로덕션 CSS 4.8MB 를 그대로 복사. 같은 클래스명을 쓰니 스타일이 자동으로 붙었다. 정적 SSIM 0.90~0.91 로 압도적이었지만 **인터랙션은 0**. 채널 전환도, 메시지 전송도, 리액션도 없다.
→ **순수 시각 유사도 하나로 게이트를 세우면 "안 움직이는 예쁜 껍데기"가 최적해가 된다.** Autobot clone 이 `functional` 을 `polish` 앞에 두고 실패 시 진행을 막는 설계는 **이 함정을 구조적으로 피한 것**이며, 벤치마크가 사후에 "인터랙션을 별도 차원으로 점수화해야 한다"고 반성한 바로 그 지점이다. 이 순서는 지켜야 한다.

**② 수확 체감은 보편적이다.**

| 에이전트 | 0–1h | 1–2h | 2–6h |
|---|---|---|---|
| Claude | +0.023/h | +0.007/h | +0.027/h\* |
| Gemini | +0.175/h | +0.058/h | ~0/h |
| GLM | +0.060/h | ~0/h | ~0/h |
| Codex | ~0/h | ~0/h | ~0/h |

\*Claude 의 후반 상승은 **폰트 로딩 같은 고레버리지 시스템 변경** — 모든 assertion 에 동시에 작용하는 한 방.
→ 초반에 레이아웃 구조·주요 CSS·폰트가 잡히고 나면, 남는 격차는 **패딩·마진·반경·자간·아이콘 렌더링의 롱테일 수십 개**다. **네 에이전트 중 누구도 이 롱테일을 체계적으로 닫는 전략을 보여주지 못했다.**
→ 시사점: 화면별로 값을 깎지 말고, **간격/반경/자간을 토큰으로 승격해 시스템 단위로 한 번에 움직이는** 경로를 만들어야 한다. 고레버리지 축(폰트 · 타이포 스케일 · 간격 스케일 · 안전영역)을 먼저 훑는 체크리스트가 롱테일 노가다보다 싸다.

**③ 검증이 숨은 병목이다.**
`site-test` 1회 = 13~22분(43 스텝). 세션 시간의 **48% / 42% / 51% / 50%** 를 검증이 먹었다 — 6시간 세션에서 실제 개발 시간은 **3시간**뿐.
→ 벤치마크의 처방: **변경된 assertion 만 부분 실행** · **스크린샷 병렬 캡처**.
→ Autobot 대응: `polish` 가 매번 전 화면을 렌더/diff 한다면 같은 세금을 낸다. **화면 단위 부분 검증 + 마지막 실행 이후 변경된 뷰만** 이 가장 큰 단일 개선일 가능성이 높다.

**④ 다단계로 도달하는 화면이 최악이다 — 삭제 확인 모달 문제.**

| 에이전트 | 삭제 모달 SSIM | 그 외 평균 |
|---|---|---|
| Claude | 0.550 | 0.770 |
| Codex | 0.532 | 0.590 |
| GLM | ~0.69 | ~0.72 |
| Gemini | N/A (도달 못함) | 0.871 |

모달은 구조적으로 어렵고(백드롭 · 정밀 센터링 · 고유 버튼 스타일 · 앱 크롬과 다른 레이아웃), **여러 단계를 거쳐야 나오므로 테스트에서 자주 안 보인다 → 반복 개선 기회 자체가 적다.**
→ Autobot 대응: **도달 깊이를 diff 예산의 가중치로 쓴다.** 깊은 화면은 캡처 횟수가 적으니 우선순위를 낮출 게 아니라 **더 자주 렌더**해야 한다. 파괴적 라벨이 withheld 되는 정책 탓에 삭제 계열 모달은 원본 캡처조차 없을 수 있으므로, 그런 화면은 "미도달"로 명시적으로 표기하는 편이 근사 재현보다 정직하다.

**⑤ 회귀 복구 능력이 곧 장기 세션 성능이다.**
Claude 는 2시간 지점에서 CSS 변경 하나로 메시지 영역 레이아웃이 깨져 평균 SSIM 이 0.462 로 급락했으나, **20분 안에 원인을 특정하고 되돌려** 다음 테스트에서 회복했다. 벤치마크가 꼽은 Claude 의 최대 강점 — "뭔가 깨지면 위에 변경을 더 쌓는 대신 회귀를 진단해 겨냥한다."
반면 컨텍스트 압력이 대가였다: 180K 윈도, **67회 압축(약 5분마다)**, 2,096 툴 호출 중 **626회가 Read** — 상당수가 컨텍스트 축출로 인한 같은 파일 재독. **세션 API 호출의 거의 절반이 작업이 아니라 컨텍스트 관리에 쓰였다.** Tasks 시스템이 압축 경계를 넘는 지속 메모리 역할을 했다.
→ Autobot 대응: (a) assertion 별 점수를 **시계열로 파일에 남겨** 하락을 자동 검출, (b) 참조 증거(`views.json`·측정치)를 **재독이 아니라 요약된 스펙 파일 한 장**으로 접어 컨텍스트 재독 비용을 낮춘다.

---

## 3. 법적/윤리 노하우

- 클론 자체는 **IPR(상표·저작권·특허)을 침해하지 않는 한 합법**. 위험은 "닮음"이 아니라 **무엇을 그대로 가져왔는가**에서 온다.
- **표준 UI 패턴(햄버거 메뉴, 스와이프, 탭바)은 보호받지 않는다.** 표현 선택지가 제한된 기능은 merger doctrine 으로 보호에서 빠진다.
- 위험한 축은 **trade dress / "look and feel"** — 전체적 외관의 식별력. 웹/앱 소유자들이 저작권 대신(또는 더해) 이 법리에 기대는 흐름.
- 실무 규칙: **독점 코드·디자인·UI 요소·브랜딩·상표를 쓰지 말고**, 자체 인터페이스를 만들고 추가 가치를 얹는다.
- 2026 년 맥락: 생성 모델로 **수 시간 만에 수천 개의 시각적 유사 앱을 자동 리스킨**하는 것이 가능해지면서, 플랫폼·권리자 양쪽의 감시가 강해졌다.

> Autobot 의 현재 문서(“이름/에셋/상표는 복제하지 않는다”, `research-only` 기본값, 외부 공유·배포로 범위가 바뀌면 라이선스·상표·카피 검토를 다시 통과)는 **이 판례 지형과 정확히 정렬돼 있다.** 특히 `/autobot:copy` 브리프에서 대상 앱 이름을 식별자로 넣지 않고 "reference app" 으로만 지칭하는 규칙은 공개 도구 어디에도 없는 수준의 보수성이다. 유지할 것.

---

## 4. Autobot 에 적용한 것 / 남은 것

> 2026-08-28 적용 완료: 아래 P0 3건 + P1 2건. 코드는 `scripts/device_compare.py`, `scripts/clone_run.sh`, 계약은 `skills/autobot-clone-app/SKILL.md`, 테스트는 `tests/test_device_compare.py`, `tests/test_clone_run.py`.

### P0 — 검증을 숫자로 만든다 ✅ 적용됨
1. ✅ **`polish` 게이트를 연속값 지표로 승격.** 현재의 "구조 diff + 사람이 보는 대조 이미지"에 **SSIM(또는 CLIP 유사도) + 블록 매칭 점수**를 추가하고 화면별 점수를 `.autobot/clone/scores.jsonl` 에 시계열로 적재. 블록 매칭은 Design2Code 방식(OCR 블록 추출 → Jonker-Volgenant 최적 매칭 → 텍스트/위치/색 각각 점수)이 그대로 이식된다 — 이미 접근성 트리에서 텍스트와 프레임을 갖고 있으므로 **OCR 없이** 더 정확하게 계산할 수 있다.
2. ✅ **정렬 후 diff + 제외 영역.** 상태바·시각·동적 콘텐츠(피드 항목, 배지 숫자)를 `exclusions.json` 으로 빼고, 비교 전 phase correlation 정렬을 넣는다. 이거 없이 픽셀 diff 를 켜면 노이즈가 신호를 덮는다.
3. ✅ **반칙 금지 규정 명문화** — clone 스킬 계약에 "참조 스크린샷을 `Image` 로 깔아 화면을 위조하지 않는다 / 캡처 crop 은 자산 슬롯에만 쓰고 레이아웃 대체물로 쓰지 않는다". 게이트를 숫자로 만드는 커밋과 **같이** 들어가야 한다.

### P1 — 루프를 싸게 만든다
4. ✅ **부분 검증.** `polish` 를 전 화면 고정이 아니라 *마지막 통과 이후 변경된 뷰 + 점수 하락 이력이 있는 뷰*로 좁힌다. 벤치마크 기준 세션의 40~50% 를 되찾는 자리다.
5. ✅ **회귀 감지(기록 층).** `scores.jsonl` 에서 화면별 하락을 자동 검출하고, 하락 시 "직전 통과 커밋"을 제시. Claude 가 벤치마크에서 이겼던 유일한 축이 이거다.
6. ⬜ **`functional` 을 screenplay 로 형식화.** 지금의 "관측된 전이를 탭해 도달 확인"을 `action` / `assert` / `wait` 스키마의 JSON 으로 떨어뜨리면, 재개·부분 실행·회귀 지목이 전부 같은 파일 하나 위에서 된다.

**적용 결과 요약**

| 항목 | 무엇이 생겼나 |
|---|---|
| 연속값 지표 | `mismatch` / `mae` 옆에 **SSIM**(8x8 luma 창 평균, 마스크에 닿은 창은 통째 제외)과 **region score**(측정 요소 프레임 중 low 비율). 블록 매칭은 측정이 요소↔프레임을 이미 짝지어 두었으므로 OCR 없이 구성적으로 성립 |
| 정렬 후 diff | `--align`(polish 기본 6px, `CLONE_ALIGN_PX`). ±N 정수 평행이동 전수 탐색 후 미세 격자 재확인. 실측: 3,2px 밀린 재현본의 mismatch 5.34% → 0.00%, SSIM 0.848 → 1.000. 찾은 offset 은 로그에 남는 **발견**(0이 아니면 inset 값이 체계적으로 틀림) |
| 제외 영역 | `.autobot/clone/exclusions.json` (`reason` 필수 관행, 로그가 이유를 되읽음). 파일을 못 읽으면 조용히 넘어가지 않고 WARN |
| 점수 시계열 | `.autobot/clone/scores.jsonl` — 통과·실패 **양쪽** 기록 |
| 반칙 금지 | crop 이 화면의 60%(`--max-asset-coverage`)를 넘게 덮으면 게이트 실패 (규칙 11). 게이트 미무장 시엔 WARN |
| 부분 검증 | `polish --changed` — `compare/<stem>.verdict` 가 `pass` 이고 뷰 소스·측정 JSON 이 그 뒤로 안 움직인 화면만 건너뜀. **판단이 안 서면 건너뛰지 않음** |

두 가지를 일부러 하지 않았다:

- **SSIM 한도를 게이트로 걸지 않았다.** 분포가 쌓이기 전에 임계값을 지어내면 그건 측정이 아니라 추측이다. 게이트는 여전히 `mismatch` 하나에만 걸려 있고, SSIM 은 지금은 읽는 숫자다 — `scores.jsonl` 이 회차를 쌓으면 그때 조인다.
- **`functional` → `polish` 순서를 건드리지 않았다.** 지표를 도입하면 시각 점수만으로 게이트를 세우고 싶어지는데, Cloning Bench 에서 그 유혹의 끝이 SSIM 0.91 / 인터랙션 0 인 Gemini 였다. 순서가 그 함정을 막는 구조다.

### P2 — 사각지대를 메운다
7. ⬜ **role-blind 폴백에 비전 검출기.** OmniParser V2 급 아이콘 검출을 라벨-리프 티어 **다음** 티어로 둔다. 라벨조차 없는 아이콘 버튼은 현재 원리적으로 후보에 오르지 못한다. 후보 출처를 `source=vision` 으로 표기해 신뢰도 서열(role > label > vision)을 유지.
8. ⬜ **롱테일 전용 경로.** 화면별 미세 조정 대신 **간격/반경/자간/타이포 스케일을 토큰으로 승격**하고, "폰트·타이포 스케일·간격 스케일·안전영역" 고레버리지 4종을 먼저 훑는 체크리스트를 `polish` 앞에 둔다.
9. ⬜ **깊은 화면 가중치.** 도달 깊이가 큰 화면(모달·다단계 시트)은 캡처·렌더 빈도를 **높인다**. withheld 정책으로 원본을 못 얻은 화면은 근사하지 말고 "미도달"로 명시.

### P3 — 선택적 확장
10. ⬜ **정적 분석 브리지(연구용).** 사용자가 **합법적으로 확보한** IPA 가 있을 때만, incogbyte 스킬 계열의 SDK 지문/API 엔드포인트 결과를 `/autobot:copy` 브리프의 "기술 스택 추정" 섹션에 주입. 기본 비활성 + 출처 확인 게이트 필수. 클론 경로에는 연결하지 않는다.
11. ⬜ **증거를 다음 세션용 스킬로 패키징(skillui 방식).** `.autobot/clone/` 산출물에서 토큰·컴포넌트 스펙을 뽑아 에이전트가 자동으로 읽는 형태(`SKILL.md` 스타일 요약 한 장)로 접으면, 컨텍스트 재독 비용이 내려간다.

---

## 5. 한 줄 요약

공개 생태계에 **"iOS 앱을 실기기에서 재현하는 스킬"은 없다.** 있는 것은 (a) IPA 정적 리버싱, (b) 기기 구동 MCP, (c) 웹 디자인 토큰 추출, (d) 웹 클론 루프/검증. Autobot clone 이 (b)+(d)를 iOS 네이티브로 합친 자리에 이미 서 있으므로, 남은 일은 **(d)의 계량화·비용절감 노하우를 이식하는 것** — 연속값 지표, 정렬 후 diff, 부분 검증, 회귀 시계열, 반칙 금지 계약. 그리고 **"기능 먼저, 픽셀 그다음"이라는 현재 게이트 순서는 벤치마크가 사후에 후회한 바로 그 설계**이므로, 지표를 도입하면서도 이 순서는 건드리지 않는다.

---

## 출처

- [incogbyte/iOS-reverse-engineering-claude-skill](https://github.com/incogbyte/iOS-reverse-engineering-claude-skill)
- [mobile-next/mobile-mcp](https://github.com/mobile-next/mobile-mcp)
- [XcodeBuildMCP](https://www.xcodebuildmcp.com/) · [XcodeBuild MCP: UI Automation is here!](https://www.async-let.com/posts/xcodebuild-ui-automation/)
- [skillui](https://github.com/amaancoderx/skillui) · [skillui.vercel.app](https://skillui.vercel.app/)
- [arvindrk/extract-design-system](https://github.com/arvindrk/extract-design-system)
- [Codia AI — Figma to SwiftUI](https://codia.ai/blog/figma-to-swiftui)
- [Cloning Bench: Evaluating AI Agents on Visual Website Cloning](https://vibrantlabs.com/research/cloning-bench)
- [ui-cloner 스킬](https://lobehub.com/skills/kensledev-dotfiles-ui-clone) · [visual-pixel-perfect 스킬](https://lobehub.com/skills/nguyenthienthanh-aura-frog-visual-pixel-perfect)
- [AdamManuel-dev/auto-image-diff](https://github.com/AdamManuel-dev/auto-image-diff)
- [Design2Code (arXiv 2403.03163)](https://arxiv.org/pdf/2403.03163) · [Web2Code (arXiv 2406.20098)](https://arxiv.org/pdf/2406.20098)
- [AppAgent](https://github.com/TencentQQGYLab/AppAgent) · [LLMDroid](https://dl.acm.org/doi/pdf/10.1145/3715763) · [LLM-Explorer (arXiv 2505.10593)](https://arxiv.org/pdf/2505.10593)
- [OmniParser (Microsoft Research)](https://microsoft.github.io/OmniParser/) · [OmniParser V2](https://www.microsoft.com/en-us/research/articles/omniparser-v2-turning-any-llm-into-a-computer-use-agent/)
- [Copyright for Mobile Apps vs. Clones (BrandR)](https://brandr.legal/en/how-copyright-registration-for-a-mobile-app-helps-block-clones/) · [Clone App Development: Process, Advantages and Legal Risks](https://xperti.io/clone-app-development-process/) · [Harvard Berkman — look and feel / trade dress](https://cyber.harvard.edu/property/protection/resources/byerly.html)
