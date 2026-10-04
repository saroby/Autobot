---
name: autobot-ios-scaffold
user-invocable: false
description: "Create or repair the Autobot Phase 3 Xcode project, targets, and schemes."
---

# iOS Project Scaffolding

Phase 3에서 `create-xcode-project.sh`로 프로젝트·App/Test target·scheme·로컬 Design System package를 생성한다. 스크립트가 XcodeGen을 우선 사용하고, 미설치 시 `generate-pbxproj.py`로 fallback한다. XcodeGen 템플릿은 [project-templates.md](references/project-templates.md).

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-ios-scaffold/scripts/create-xcode-project.sh" \
  --name "$APP_NAME" \
  --bundle-id "$BUNDLE_ID" \
  --project-dir "." \
  --deployment-target "$DEPLOY_TARGET" \
  --design-system-module "$DESIGN_SYSTEM_MODULE"
```

- Bundle ID·deployment target은 `autobot-setup`에서 해석하고, 모듈 이름은 `architecture.json.designSystemModule`을 사용한다.
- `--project-dir .`는 Phase 0에서 만든 현재 루트에 생성한다. 생략하면 `<AppName>/` 루트를 새로 만든다.
- `backend_required == true`이면 `--backend`를 추가한다.
- 스크립트 직후 orchestrator가 `design-system` 에이전트를 dispatch해 `Packages/<DesignSystemModule>/`의 Tokens/Components를 채운다. 두 단계 완료 후 Gate 3→4의 `design_system_package_exists` / `design_system_tokens_exist`를 통과해야 한다.

## 산출물 계약

- `.xcodeproj`, App/Test target, shared scheme, Debug/Release 설정. pbxproj fallback은 `PBXFileSystemSynchronizedRootGroup`과 `objectVersion = 77`을 사용하므로 새 파일 개별 등록은 필요 없다.
- Swift 6.0, 기본 iOS 26.0, strict concurrency `complete`, user script sandbox `YES`, `CODE_SIGN_ENTITLEMENTS=<AppName>/<AppName>.entitlements`.
- `GENERATE_INFOPLIST_FILE=YES`; display name, 빈 `UILaunchScreen`, portrait/landscape 지원과 권한을 `INFOPLIST_KEY_*`로 주입한다. `INFOPLIST_KEY_ITSAppUsesNonExemptEncryption=NO`는 항상 포함한다 ([CONVENTIONS.md](../../CONVENTIONS.md)의 iOS project content contract).
- `.gitignore`, `PrivacyInfo.xcprivacy`(기본 FileTimestamp + architect 지정 카테고리), 빈 entitlements(Phase 5에서 capabilities 채움), AppIcon(1024×1024), AccentColor.
- `Packages/<DesignSystemModule>/Package.swift`와 Tokens stub 4개; scaffold stub은 Phase 3의 design-system이 실제 토큰·컴포넌트로 교체한다.
- `--backend`는 root `.gitignore`에 `backend/.env`를 미리 추가하고 xcconfig 참조와 `INFOPLIST_KEY_API_BASE_URL=$(API_BASE_URL)`을 설정한다. `Debug.xcconfig`: `API_BASE_URL = http:/$()/localhost:8080`; `Release.xcconfig`: `API_BASE_URL = https:/$()/$(PRODUCTION_HOST)`.

## 복구

pbxproj fallback에는 Python 3.8+가 필요하다. XcodeGen 실패는 생성된 `project.yml`을 확인하고 fallback으로 재시도한다. pbxproj 열기 실패는 Xcode 버전·`objectVersion`·ASCII AppName을 확인한다. entitlements 누락은 유효한 빈 plist를 복구한 뒤 gate를 재실행한다. 빈 AppIcon 경고로 최종 아이콘 검증을 생략하지 않는다.
