### Step 6c — 실기기 설치: 이름은 원본, 식별자는 clone 의 것

```bash
scripts/clone_run.sh install [RootView]     # 기본 RootView = ObservedFlowRootView
```

시뮬레이터에만 있는 클론은 손에 쥘 수 있는 앱의 클론이 아니다. `install` 은 생성 뷰를 `clone_device_project.py` 가 만든 최소 프로젝트로 묶어 서명·설치한다. **스펙은 둘이다:**

- **홈 화면 이름 = 원본 앱 이름.** `observe` 가 후보 bundle ID를 기존 `target.json`과 대조하고, doctor와 WDA session이 그 대상에 바인딩된 뒤 기기가 보고한 이름을 원자적으로 기록한다(`{"bundleId","name","resolvedBy","query"}`). 기존 root가 다른 bundle ID에 묶여 있으면 별도 `CLONE_ROOT`를 요구한다. `install`은 그 `name`을 `CFBundleDisplayName`으로 넣는다. 사용자가 입력한 검색어가 아니라 **기기가 보고한 이름**이다. `CLONE_APP_DISPLAY_NAME`으로 덮어쓴다. `target.json`이 없으면(옛 observe 로그) WARN과 함께 `CloneApp`으로 설치하고 멈추지 않는다.
- **bundle ID · 타깃 · 바이너리는 clone 의 것**(`com.axi.clone.<rootview>`, `CloneApp`). 원본과 같은 기기에 나란히 설치되어야 대조가 되고, 원본의 식별자를 쓰면 원본을 덮어쓴다. 이름이 같고 식별자가 다른 앱 둘이 홈 화면에 보이는 것이 의도된 상태다.

시뮬레이터 프리뷰(`device_render.sh` 의 `ClonePreview`)는 대조 스크린샷용 하네스라 이름을 바꾸지 않는다.
