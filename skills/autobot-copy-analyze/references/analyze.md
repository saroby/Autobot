### Step 4 — 구조 분석

수집한 **접근성 트리(`.xml`)를 1급 소스로, 스크린샷을 보완으로** 읽어 분석:

- **Screens**: 각 화면의 목적·Tab·주요 UI 요소 (a11y 트리의 type/label 로 정확히). architecture.md `## Screens` 표 형식
- **Navigation**: TabView / NavigationStack / Split — 트리의 탭바·네비바 요소로 판별
- **Features**: P0/P1 + role(`table-stakes`/`hook`/`retention`/`insight`). 리뷰에서 사랑받는 기능 = hook 후보, 불만 = 개선 차별점
- **Design Direction**: personality, color palette(스크린샷에서 추출한 *방향* — 정확한 hex 복제 아님), typography 느낌, layout personality, signature layout
- **Hook & Retention**: 리뷰·기능에서 도출. 제네릭 금지 — 이 앱만 식별되는 구체 문장
