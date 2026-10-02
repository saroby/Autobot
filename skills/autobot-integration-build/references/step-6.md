## Step 6: Code Quality Check

빌드 성공 후 코드 품질을 확인한다:

| 항목 | 검증 방법 |
|------|----------|
| Force unwrap 없음 | `grep -rn '!' <AppName>/Views/ <AppName>/ViewModels/ <AppName>/Services/ \| grep -v '//' \| grep '![^=]'` |
| @MainActor on ViewModels | `grep -L '@MainActor' <AppName>/ViewModels/*.swift` |
| 모든 파일에 적절한 import | 빌드 성공으로 검증됨 |
| Swift 6 concurrency 위반 없음 | 빌드 경고 메시지 확인 |
