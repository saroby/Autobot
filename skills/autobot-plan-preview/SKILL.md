---
name: autobot-plan-preview
user-invocable: false
description: "Render and critique the Phase 2.5 plan-preview HTML (/autobot:plan)."
---

# Plan Preview (Phase 2.5)

`/autobot:plan`에서 Phase 1 architecture와 Phase 2 디자인·아이콘을 HTML 한 페이지로 검토한다. Phase 2.5는 `manual: true`이며 mvp 자율 흐름은 자동 skip한다.

## 입출력

입력: `.autobot/architecture.md`(Overview/Features/Screens/Navigation), `.autobot/design-spec.md`(토큰), `.autobot/designs/*.png`, `.autobot/app-icon-1024.png`, `.autobot/build-state.json`(appName/displayName).

출력: `.autobot/designs/preview/index.html`. 외부 CDN 없는 self-contained HTML에 기획 요약, 번호 매긴 스토리보드(진입→탭그룹), 갤러리, 상태/인터랙션, 토큰 swatch, 아이콘, critique를 담는다. 빌더의 화면 목록·flow·갤러리가 같은 **1..N** 번호를 쓰며 카드 ID는 `screen-N`이다.

## 순차 실행

### 1. 빌드

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-preview.sh" --project-dir "$PWD"
```

실패는 stderr FATAL을 Phase 2.5 fail 사유로 기록한다. 성공 HTML의 `<!-- CRITIQUE_PLACEHOLDER -->`가 주입 위치다.

### 2. 멀티모달 critique

사용자 아이디어·architecture·design-spec과 PNG를 함께 비교한다. **기획 축부터** 검토한다:

- 기능 누락(P2 포함), 화면 수·Navigation 적합성, P0 우선순위, 로컬/백엔드 필요 판단.
- **차별점이 말뿐(HIGH)**: Overview/`### Hook & Retention`이 P0 구현체로 이어지지 않음.
- **훅 부재(HIGH)**: P0가 카테고리 CRUD뿐이며 다운로드 이유 없음.
- **재방문 이유 부재(MEDIUM)**: 히스토리·streak·주기 가치 등 retention 없음.
- **첫 실행 권한 다이얼로그**: `firstRunPolicy`/`## First-Run Experience`와 비교해 맥락 없는 권한 요청 점검.

디자인 축:
- **Safe area(HIGH 우선)**: PNG 상단 약 5.5%(47pt) status bar·하단 약 4%(34pt) home indicator에 앱 제목/버튼/CTA/탭바가 겹치는지 실제 픽셀로 판단하고 요소를 명시한다.
- HIG(탭바·44pt 터치 타깃·텍스트·대비), primary CTA/정보 위계, empty/loading/error, 색 토큰 WCAG AA, 컴포넌트 일관성.
- 색 정체성: system blue/gray 그대로인 generic 디자인.
- **레이아웃 동질성/templated(HIGH 우선)**: 동일 List/카드 몰드 또는 4종 Layout Personality 무변형 복제. `### Signature Layout`의 hero·위계·density·화면 간 차별화와 PNG를 대조하고 동일한 화면들과 차별화 방법을 명시한다.

각 항목은 `severity(high/medium/low/positive) · 축(기획/디자인) · 제목 · 화면(N 또는 —) · 영향 · 구체 개선 1줄`. high는 코드 생성 전에 수정, medium은 권장, low는 참고다. 특정 화면은 **스토리보드 번호**, 앱 전반은 `—`로 연결한다.

총 **3–8개**. 문제가 없으면 좋은 결정의 근거를 `positive` 1–2개와 개선 가능한 nuance medium/low 1–2개로 기록한다. 발견 0개여도 positive 1개 이상은 남긴다.

### 3. HTML 주입

마커와 직후 placeholder 문단을 정확히 교체한다. 기존 CSS를 쓰고 배지 색만 inline style로 넣는다(외부 CSS 변경 금지): high `#ff3b30`, medium `#ff9500`, low `#8e8e93`, positive `#34c759`, 텍스트 white.

```html
<ul class="critique-list">
  <li class="critique-item">
    <span class="critique-badge severity-high" style="background:#ff3b30;color:white">HIGH · 디자인</span>
    <strong>{제목}</strong>
    <a class="critique-screen" href="#screen-{N}">→ 화면 {N}</a>
    <p class="muted">영향: {영향}</p>
    <p>개선: {개선}</p>
  </li>
</ul>
```

`N`은 critique 화면 번호와 같아야 한다. 앱 전반(`—`) 항목에는 링크 칩을 생략한다.

### 4. 브라우저·보고

```bash
open "$PWD/.autobot/designs/preview/index.html" 2>/dev/null ||   xdg-open "$PWD/.autobot/designs/preview/index.html" 2>/dev/null ||   echo "INFO: 브라우저 자동 열기 실패. 수동으로 .autobot/designs/preview/index.html 을 여세요."
```

자동 열기 성공 여부와 무관하게 HTML 경로·severity별 개수를 보고한다. 다음 선택을 안내한다: `/autobot:resume`(Phase 3), 같은 디렉토리 `/autobot:plan`(재생성), 새 디렉토리 `/autobot:plan <새 아이디어>`.

### 5. advance

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 2.5   --metadata preview_html_path=.autobot/designs/preview/index.html   --metadata critique_count_high=<N>   --metadata critique_count_medium=<N>   --metadata critique_count_low=<N>
```

Gate `2.5->3`은 HTML 존재만 검사한다. critique 품질은 이 스킬 계약이며 gate가 강제하지 않는다.

## 실패·범위

| 조건 | 동작 |
|---|---|
| architecture 없음 | Phase 2.5 fail, `/autobot:resume 1` |
| design-spec 없음 | Phase 2.5 fail, `/autobot:resume 2` |
| PNG 0개 | WARN, placeholder 갤러리 + spec 기반 critique로 진행 |
| 아이콘 없음 | WARN, 헤더 아이콘 생략 후 진행 |
| 브라우저 열기 실패 | 경로 출력, Phase 2.5 success |

PNG-only이며 Stitch HTML iframe/CDN, 외부 LLM critique 위탁, Approve/Reject watcher는 포함하지 않는다. 사용자는 다음 명령으로 검토 결정을 표현한다.
