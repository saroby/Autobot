## Step 0: 프로젝트 파일 동기화

Phase 4에서 생성된 새 `.swift` 파일을 Xcode 프로젝트에 등록한다.

```bash
# xcodegen이 있으면
if command -v xcodegen &>/dev/null && [ -f project.yml ]; then
  xcodegen generate
# 없으면 pbxproj 재생성
elif [ -f "$CLAUDE_PLUGIN_ROOT/skills/autobot-ios-scaffold/scripts/generate-pbxproj.py" ]; then
  python3 "$CLAUDE_PLUGIN_ROOT/skills/autobot-ios-scaffold/scripts/generate-pbxproj.py" \
    --name "<AppName>" --bundle-id "<BundleID>" --sources-dir "<AppName>"
fi
```

> **Folder Reference 방식이면 이 단계를 건너뛸 수 있다.** `PBXFileSystemSynchronizedRootGroup`은 파일시스템과 자동 동기화되므로 재생성이 불필요하다. 빌드 시 "파일을 찾을 수 없다" 에러가 나면 그때 재생성한다.
