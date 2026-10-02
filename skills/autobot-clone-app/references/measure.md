### Step 3 — 측정 (이 스킬의 핵심)

각 화면의 `.xml` 과 `.png` 에서 재현에 필요한 수치를 뽑는다.

```bash
python3 scripts/clone_postprocess.py .autobot/clone --workers 4 \
  --extract-assets \
  --assets-catalog .autobot/clone/project/CloneWorkspace/Assets.xcassets
```

기본 경로는 raw XML/PNG pair를 bounded 병렬로 측정하고, 입력 해시가 같은 화면은 캐시하며, 결정적인 `screens/*.json`·`screens/*.md`를 생성한다. 실패 pair가 하나라도 있으면 요약과 함께 non-zero로 끝난다. 단일 화면을 진단할 때만 기존 `device_measure.py <xml> <png>`를 직접 쓴다.

`--extract-assets`는 측정의 `AXImage` 프레임을 point→pixel scale로 crop하고 SHA-256으로 중복 제거한다. 필요하면 `device_assets.py <measurement.json> --indices 3,7`처럼 비표준 custom-drawn 요소를 명시한다. crop과 선택적 `.imageset`은 `.autobot/clone/assets/manifest.json`에 원본 캡처·프레임·해시·`capture-crop`·`research-only` 품질 한계와 함께 기록한다.

뽑는 것:

- **기하** — 각 요소의 x·y·width·height(pt), 부모 대비 상대 위치, 형제 간 간격. 여기서 **패딩·스택 간격**이 그대로 나온다.
- **색** — 모서리에서 `background`, 컨트롤 내부 격자의 최빈값에서 `fill`, 텍스트는 배경과 대비가 가장 큰 픽셀에서 `foreground`. 세 개가 다 필요하다: FAB 의 파란 fill 은 모서리(뒤 캡슐)에도 중심(흰 글리프)에도 없다. 팔레트는 빈도순 집계.
- **타이포** — 텍스트 요소의 높이와 폭에서 대략적인 폰트 크기·굵기를 역산하고, iOS 표준 텍스트 스타일(`.body`/`.headline`/`.largeTitle`…)에 매핑한다. 정확한 폰트 파일은 알 수 없으므로 **시스템 폰트 기준**으로 맞춘다.
- **미커버 영역** — 스크린샷에서 배경이 아닌데 측정된 어떤 요소의 프레임에도 덮이지 않는 영역을 `uncoveredRegions` 로 낸다(시스템 크롬 상·하단 밴드는 제외). 지배적 실패인 **요소 누락**(Step 6-4)과 크롬 필터가 콘텐츠까지 버린 사고를 측정 단계에서 잡는 장치다. WARN 이 나오면 스크린샷과 대조해 원인을 확인한 뒤 스펙을 쓴다 — 무시하고 넘어가면 누락이 재현본까지 전파된다. 모달 화면은 예외적으로 이 경고가 정상이다: iOS 가 시트 뒤를 접근성 트리에서 감추므로 배경 전체가 미커버로 잡히고, 그 영역의 crop 은 글자를 글리프 조각으로 자른다. 그래서 `clone_view_codegen.py` 는 어떤 측정 요소도 겹치지 않는 32pt 이하 미커버 crop 을 뷰에 싣지 않는다(빈 영역이 조각보다 낫다 — 조각은 레이아웃 버그로 읽힌다. 실측 2026-08-23).
- **구조** — 접근성 트리의 부모-자식에서 스택 방향(`vstack`/`hstack`/`zstack`)과 형제 간 간격을 계산해 `layout` 으로 낸다. 축은 형제가 **겹치지 않는** 쪽이다(양수 간격 합이 아니라 겹침이 신호 — 6pt 겹친 두 줄은 zstack 이 아니라 vstack 이다). 버리는 것 셋: 라벨 없는 전체화면 래퍼(자식은 살아남은 조상에 재부착), 스크롤 막대 같은 크롬(**자식까지 함께** — 그 자식은 스크롤 막대 부품이지 콘텐츠가 아니다), WDA 가 창을 둘로 보고해 생기는 완전 중복 요소. 셋 다 안 버리면 카드 4장이 16pt 간격인 화면이 "spacing 147" 로 나온다(실측).
  카드 자신의 배경은 부모를 꽉 채워 모든 형제와 겹치므로 간격 계산에서 뺀다 — 안 그러면 한 줄의 간격이 `-343` 으로 잡힌다.

측정값은 JSON 으로 남긴다. 이후 단계는 이 JSON 만 보고 코드를 쓴다 — 스크린샷을 눈으로 보고 "대충 이 정도"로 쓰지 않는다.
