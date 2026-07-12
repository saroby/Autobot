# Design & HIG — iOS 26+ Distilled

> **출처**: axiom-design + axiom-apple-docs (MIT, WWDC 2025+) 의 핵심 규칙을 Autobot 자족(self-contained) 형태로 증류한 문서. 외부 axiom 플러그인이 없어도 동일하게 작동한다.
>
> **사용자**: `architect` 에이전트(필수), `ui-builder`/`ux-designer`(참조). Phase 1·2 산출물의 Look & Feel 계약이 이 규칙과 충돌하면 안 된다.
>
> **갱신 정책**: 다음 WWDC 또는 iOS 메이저 릴리스 후 한 번씩 갱신. 본 파일이 SSOT.

---

## 0. 절대 규칙 (위반 시 빌드 가치 0)

1. **iOS 26+ 한정 타깃이면 Liquid Glass · @Observable · NavigationStack 을 기본값으로 가정한다.** iOS 17/18 패턴(Material blur, ObservableObject, NavigationView)은 *마이그레이션 대상*이지 새 코드의 출발점이 아니다.
2. **색상은 의미(semantic)부터 — 절대 hex 직접 사용 금지.** `Color.primary`, `.secondary`, `.accentColor`, `.background`, `.tint`. 커스텀 색이 필요하면 Asset Catalog + Dark Mode 변형까지 동반.
3. **SF Symbols 우선. 커스텀 아이콘은 SF Symbols로 표현 불가능할 때만.** 이 한 줄로 디자인 일관성·접근성·다크모드·Dynamic Type이 자동으로 따라온다.
4. **모든 텍스트는 Dynamic Type 텍스트 스타일로.** `.font(.body)`, `.font(.headline)`, `.font(.title2)`. 고정 포인트(`.font(.system(size: 14))`) 사용 시 *반드시* 사유를 주석으로 남길 것.
5. **시트(.sheet, fullScreenCover)는 Cancel/Done 또는 .cancellationAction/.confirmationAction 없이 금지.** dismiss trap 은 HIG 위반이고 App Store 거절 사유 가능.

---

## 1. Liquid Glass — iOS 26+ 머티리얼 시스템

### Regular vs Clear 의 결정 트리

```
표면 위에 텍스트/컨트롤이 올라가는가?
├─ 예: Regular  (가독성 + 콘텐츠 분리)
│   예: Toolbar, TabView, NavigationBar, Card 위 버튼
└─ 아니오: Clear (장식적 깊이감)
    예: 미디어 위 오버레이, 비-인터랙티브 챙(brim)
```

기본은 **Regular**. Clear 는 의도적으로만 선택.

### 적용 API

```swift
.glassEffect()                 // iOS 26+, Regular
.glassEffect(.clear)           // Clear 변형
.glassEffect(in: .rect(cornerRadius: 16))  // shape 명시
.glassEffect(.regular.tint(.accentColor))  // primary action 강조 (tint: 파라미터는 없다)
```

`@available(iOS 26, *)` 가드 없이 사용. 타깃이 iOS 26+ 이면 OK. 더 낮은 타깃이라면 `if #available(iOS 26, *) { … } else { .ultraThinMaterial }` 패턴.

### 흔한 실수 (감지 패턴)

- **Glass on Glass nesting**: `.glassEffect()` 가 또 다른 `.glassEffect()` 안에 들어가면 시각 노이즈. 한 컴포넌트는 한 glass 레이어만.
- **Primary action tinting 누락**: 강조 버튼은 `.glassEffect(.regular.tint(.accentColor))`. 누락 시 시각 위계 손실.
- **TabRole 누락**: 검색 탭은 `.tabRole(.search)` 로 마킹해야 iOS 26 검색 전용 표면을 받는다.
- **UIBlurEffect/.regularMaterial 잔존**: pre-iOS 26 코드의 흔적. iOS 26+ 타깃에서는 Liquid Glass 로 교체.

---

## 2. HIG 빠른 결정

### 배경 색 결정 트리

```
미디어/사진 중심 화면인가?
├─ 예: Color(.systemBackground) 또는 .background 없이 미디어가 풀블리드
└─ 아니오:
    └─ 일반 콘텐츠 → Color(.systemGroupedBackground) (List, Form 기본)
        └─ 명시적 흰/검 배경 → Color(.systemBackground)
```

### 타이포그래피 위계

| 역할 | 텍스트 스타일 | 비고 |
|---|---|---|
| 화면 제목 | `.largeTitle` | `.navigationBarTitleDisplayMode(.large)` 와 짝 |
| 섹션 헤더 | `.title2` 또는 `.headline` | List 섹션은 `.headline` 권장 |
| 본문 | `.body` | Dynamic Type 기본값 |
| 보조 정보 | `.subheadline` + `.foregroundStyle(.secondary)` | |
| 캡션 / 메타 | `.caption` + `.secondary` | |

### SF Symbols 렌더링 모드

```
단순 아이콘?
├─ Monochrome (기본) — 상태 변화 없을 때
├─ Hierarchical — 한 색 기반 농담 표현 (활성/비활성 동시 표시)
├─ Palette — 멀티 컬러 명시 (브랜드 색 매핑)
└─ Multicolor — 시스템 정의 컬러 (예: heart.fill 빨강)
```

```swift
Image(systemName: "heart.fill")
    .symbolRenderingMode(.hierarchical)
    .foregroundStyle(.pink)
```

심볼 이펙트는 인터랙션 피드백에만 (`.symbolEffect(.bounce, value: …)`). 장식적 남발 금지.

---

## 3. App Composition — @main, Auth, Root 분기

### 최소 골격 (iOS 26+, SwiftUI life-cycle)

```swift
@main
struct MyApp: App {
    @State private var appState = AppState()  // @Observable 클래스

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(appState)
        }
    }
}

@Observable
final class AppState {
    var auth: AuthState = .unknown   // .unknown / .signedOut / .signedIn(User)
}

struct RootView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        switch appState.auth {
        case .unknown:    LaunchView()
        case .signedOut:  SignInView()
        case .signedIn:   MainTabView()
        }
    }
}
```

### 절대 하지 말 것

- `if isSignedIn { … } else { … }` 를 *최상위가 아닌* 곳에서 — 인증 분기는 root 단 1곳.
- `@StateObject` / `ObservableObject` — iOS 17+ 부터는 `@Observable` + `@State` 가 표준.
- `AppDelegate` 를 *상태 저장소*로 — 상태는 `@Observable` 클래스 또는 SwiftData/UserDefaults 에.
- onAppear 에서 무거운 초기화 — `.task` 사용 또는 `init()` 에서 *동기 가능한 것만*.

---

## 4. 아이콘·이미지 정책

- **App Icon**: iOS 26 에서 Dark / Tinted / Clear 변형 추가 가능. 최소 Light 1종, 권장 Light + Dark 2종.
- **이미지 자산**: Asset Catalog 에 Universal + Dark Appearance. Display P3 색공간 사용.
- **시스템 아이콘이 있으면 SF Symbols** — 매번 자문할 것. 90% 케이스에서 SF Symbols 로 해결된다.

---

## 5. Anti-Rationalization 표 (생성 시 즉시 STOP)

| 생각 | 현실 |
|---|---|
| "iOS 17 패턴이지만 작동하잖아" | iOS 26+ 타깃이면 ObservableObject 는 *부채*. 첫 빌드부터 @Observable 로. |
| "Liquid Glass 는 멋이고 필요할 때만 쓰자" | iOS 26+ 시스템 컨테이너(toolbar, tab, nav)는 *자동으로* glass. 의식 안 하면 일관성 깨짐. |
| "색은 일단 hex 로 빨리 박고 나중에 의미화" | "나중에" 는 안 온다. 첫 줄부터 의미색. |
| "고정 폰트 크기가 디자인이 더 잘 맞는다" | Dynamic Type 위반은 접근성 거절 사유. `.body` + `.minimumScaleFactor` 로 해결. |
| "Cancel 버튼은 사용자가 알 거다" | Sheet 의 dismiss trap 은 HIG 위반. `.cancellationAction` 자동 배치 사용. |
| "SF Symbols 에 없으니 PNG 로" | 90% 케이스에서 SF Symbols 에 *있다*. 찾아본 다음 결정. |

---

## 6. 빠른 자가 체크 (architect 가 Design Direction 작성 후)

- [ ] 모든 색은 의미명(semantic) 또는 Asset Catalog 참조
- [ ] 모든 텍스트는 Dynamic Type 스타일
- [ ] 모든 아이콘 후보가 SF Symbols 우선 검토됨
- [ ] iOS 26+ 타깃이면 Liquid Glass 적용 표면 명시 (toolbar / tab / card 등)
- [ ] App 루트의 인증 분기가 단 1곳
- [ ] 모든 시트/풀스크린 커버에 명시적 dismiss 경로
- [ ] 다크모드 변형이 모든 색·이미지에 존재

체크리스트 1개라도 빠지면 Gate 1→2 통과 불가.
