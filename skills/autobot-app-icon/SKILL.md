---
name: autobot-app-icon
user-invocable: false
description: Use during Autobot Phase 2/3 when generating a production app icon with codex-util:imagegen or applying the generated 1024x1024 PNG into an iOS AppIcon asset catalog.
---

# App Icon Generation

Generate a project-specific iOS app icon before scaffold validation, then apply it to `Assets.xcassets/AppIcon.appiconset`.

## Inputs

- `.autobot/architecture.md`
- `.autobot/design-spec.md`
- App identifier name and display name from `.autobot/build-state.json`

## Phase 2: Generate Source Icon

Use the `codex-util:imagegen` skill as the primary path. If the runtime exposes the same capability as `imagegen`, use that equivalent skill.

Prompt requirements:

- 1024x1024 square iOS app icon
- No text, letters, watermark, badge, or UI screenshot
- No transparency; use a fully opaque background
- Match the app domain, design direction, palette, and visual personality from `architecture.md` and `design-spec.md`
- Keep the silhouette simple enough to remain recognizable at small sizes
- Avoid Apple logos, SF Symbols copied verbatim, and third-party brand marks

Save the selected PNG as:

```text
.autobot/app-icon-1024.png
```

On success, the orchestrator records Phase 2 metadata in the final Phase 2 completion command:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 2 \
  --metadata app_icon_status=generated \
  --metadata app_icon_path=.autobot/app-icon-1024.png
```

### Pillow Fallback (imagegen 부재/실패 시)

`imagegen` 스킬이 노출되지 않거나 1회 재시도 후에도 생성에 실패하면, **빈 placeholder 대신 Pillow 로 합성한 아이콘**을 자동 생성한다. 시각적으로 식별 가능한 색상 + 이니셜 아이콘이 항상 우선이다.

```bash
# imagegen 실패 후 또는 imagegen 자체가 부재할 때
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-icon/scripts/pillow-fallback.sh" \
  --name "<AppName>" \
  --out ".autobot/app-icon-1024.png"

# architect 가 brand color 를 정의한 경우 명시 전달 (선택)
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-icon/scripts/pillow-fallback.sh" \
  --name "<AppName>" \
  --out ".autobot/app-icon-1024.png" \
  --color "#3366FF"
```

특징:
- 1024×1024 단일 PNG, 불투명 RGB (iOS 26+ AppIcon 요건 충족)
- 배경: 앱 이름의 MD5 해시에서 유도한 채도 높은 그라디언트 (deterministic — 같은 앱 이름이면 항상 같은 색)
- 글리프: ASCII 이니셜 1~2자 (`SocialFitness` → `SO`), 흰색 + soft drop shadow
- Pillow 미설치 시 `python3 -m pip install --user Pillow` 를 자동 시도

상태 분류 (Phase 2 완료 메타데이터):

| 시나리오 | `app_icon_status` | 다음 단계 |
|----------|-------------------|----------|
| `imagegen` 으로 생성 성공 | `generated` | 그대로 Phase 3 |
| `imagegen` 부재/실패 → Pillow 로 생성 성공 | `pillow` | 그대로 Phase 3 (시각적으로 식별 가능) |
| Pillow 까지 실패 (python3/pip/PIL 부재) | `fallback` | Placeholder 로 진행, `/autobot:resume 2` 안내 |

```bash
# Pillow 성공 시
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 2 \
  --metadata app_icon_status=pillow \
  --metadata app_icon_path=.autobot/app-icon-1024.png
```

진짜 `fallback` (Pillow 까지 실패) 인 경우에만 다음을 기록한다:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 2 --status fallback \
  --metadata app_icon_status=fallback \
  --metadata app_icon_error="<reason: python3 missing, pip install failed, etc.>"
```

## Phase 3: Apply Icon

After `ios-scaffold` creates the asset catalog, apply the generated source:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/app-icon.sh" apply \
  --app-name "<AppName>" \
  --source ".autobot/app-icon-1024.png" \
  --project-dir "."
```

Then verify:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/app-icon.sh" verify \
  --app-name "<AppName>" \
  --project-dir "."
```

If `app_icon_status=fallback`, do not block scaffold on icon application, but report that TestFlight will use the placeholder asset until `/autobot:resume 2` regenerates the icon.
