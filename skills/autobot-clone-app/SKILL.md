---
name: autobot-clone-app
description: "Reproduce an installed iOS app’s screens and behavior as SwiftUI using a connected iPhone (/autobot:clone)."
---

# Autobot Clone

Reproduce the target app's observed screens and behavior as a buildable SwiftUI app. A connected iPhone is required for observation; `/autobot:copy` produces an original product brief instead.

## Execution

Run the script-owned path; load detailed references only for the current operation, diagnosis, or optional handoff. Project paths resolve from the project root; runtime scripts are under `$CLAUDE_PLUGIN_ROOT/scripts/`.

```bash
# In plugin-development checkouts, verify the installed package first.
python3 "$CLAUDE_PLUGIN_ROOT/scripts/clone_skill_sync.py" check
bash "$CLAUDE_PLUGIN_ROOT/scripts/clone_run.sh" observe '<app name or bundle id>'
bash "$CLAUDE_PLUGIN_ROOT/scripts/clone_run.sh" functional
bash "$CLAUDE_PLUGIN_ROOT/scripts/clone_run.sh" polish
```

`observe` owns workspace preparation, device/bundle binding, exploration, measurements, assets, flow mapping, and codegen. `verify` runs functional then polish and stops on functional failure. Retry the same interrupted command to resume from preserved evidence. Do not launch the clone before observing the target.

## Boundaries

- Use measured layout/color/type values. Mark necessary approximations explicitly.
- 별도 확인 질문 없이 `research-only`로 생성한다. Record source, acquisition method, and frame in `assets/manifest.json`; use accessible approved files or screen crops. Do not bypass sandbox/encryption/signing or promise extraction of App Store binaries. Before external sharing or distribution, review asset licensing, trademarks, and copy.
- Screen crops belong in asset slots. Do not replace the layout with the target screenshot; preserve the asset-coverage gate.
- Require observed flows before reproduction, and both functional and passing comparison evidence before claiming completion. Preserve structure-extraction checks; explain any deliberate mismatch-threshold change.
- Keep incomplete exploration, missing trees, unobserved destinations, and data-gated screens explicit. Never invent evidence or write build-state.json/architecture.json for a clone.
- Confirm the target bundle on the selected UDID with `--include-all-apps`; never infer it from the foreground app. Physical device, signing, Appium/xcuitest, Developer Mode, Trust, UI automation, disk, and required administrator-auth failures stop the operation.
- Default scope/mapping/exploration choices are autonomous. Only technical blockers or the explicit `CLONE_ASK_FOR_DATA=1` data-request option involve the user.

## Reference routing

| Need | Read |
|------|------|
| Device, tunnel, bundle binding, installed-package check | [Device gate](references/device.md) |
| Safe exploration and resuming partial evidence | [Observe](references/observe.md) |
| Inspect the flow map or select scope | [Flow map](references/flow-map.md), [Scope](references/scope.md) |
| Measurements or repeated-group declarations | [Measure](references/measure.md), [Structure](references/structure.md) |
| Generate or repair SwiftUI/state aliases without the device | [Codegen](references/codegen.md) |
| Functional failure | [Functional gate](references/functional.md) |
| Visual/structure failure or measured polish | [Polish](references/polish.md) |
| Optional install after verification | [Install](references/install.md) |
| Explicit mvp handoff | [Reverse brief](references/reverse-brief.md), [Screen specs](references/screen-spec.md) |
| Report artifacts/coverage | [Artifacts](references/artifacts.md) |

Before manual device exploration, read observe.md's candidate safety rules. The scripts enforce only observable labels/roles; visually inspect ambiguous controls and stop at login/payment/consent boundaries.
