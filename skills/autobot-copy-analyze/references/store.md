### Step 1 — 대상 확정 + App Store 메타 수집

`mcp-appstore` 도구로 먼저 공개 정보를 확보한다 (사용자가 기기를 준비하는 동안 병렬로 진행 가능하지만, Step 2 게이트를 통과하지 못하면 이 결과물만으로 브리프를 만들지 않는다):

1. `search_app` 로 앱 검색 → 대상 확정 (사용자에게 후보 확인)
2. `get_app_details` — 이름·카테고리·설명·subtitle·평점·스크린샷 URL
3. `fetch_reviews` + `analyze_reviews` — 유저가 사랑하는 것/불만 → **훅·리텐션 근거**
   - ⚠️ **조용한 실패를 반드시 확인한다.** 이 도구는 리뷰가 없어도 에러가 아니라 **빈 분석 객체**(`totalReviewsAnalyzed: 0`)를 돌려준다. 실측: 리뷰 30,562개인 앱이 us·kr 모두 0건으로 왔다(1st-party 앱은 RSS 리뷰 미노출).
   - `totalReviewsAnalyzed == 0` 이면 → 다른 country 로 1회 재시도 → 그래도 0이면 **리뷰 근거는 없는 것으로 확정**하고, 브리프 상단에 `> review-signal unavailable` 을 적는다. Hook & Retention 은 **기기 트리에서 관찰한 리텐션 장치**(연속 기록·통계·알림·위젯 등)와 스토어 설명으로 도출한다. 없는 근거를 있는 것처럼 쓰지 않는다.
4. `get_similar_apps` — Market Context 표의 근거 앱들
   - ⚠️ **카테고리 기반이라 자주 무관하다.** 실측: 일기 앱에 MyFitnessPal·Fitbod·요가 앱이 반환됐다(App Store 카테고리가 '건강 및 피트니스'라서).
   - 반환된 앱의 설명을 대상 앱의 **핵심 기능 명사**(예: 일기·기록·회고)와 대조해 무관한 것을 버린다. 3개 미만 남으면 `search_app` 으로 그 명사를 직접 검색해 경쟁군을 만들고, Market Context 표에 **근거를 어떻게 얻었는지** 한 줄로 밝힌다.
5. `analyze_top_keywords` / `get_keyword_scores` — 카테고리 table-stakes 신호

App Store 스크린샷 URL 은 `WebFetch`/curl 로 `.autobot/copy-analysis/store/` 에 저장한다.

**리뷰 인사이트를 파일로 남긴다** — `.autobot/copy-analysis/reviews.md`. 브리프의 Hook & Retention 은 여기서 근거를 끌어오고, 사람이 검토할 때도 원문 인용이 필요하다. 최소 구성:

- 수집 방법과 표본 수 (country·정렬·페이지), 평점 분포
- **평점 신뢰도 경고** — 이 카테고리는 "5점 줘야 눈에 띈다"며 불만을 5★로 다는 관행이 있다. 실측되면 명시한다
- 불만 — 빈도순, 각 항목에 유저 원문 인용
- 사랑받는 것 — hook 근거
- 재구현이 가져갈 차별점 표 (관찰된 문제 → 원본 앱이 취할 입장)
