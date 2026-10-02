## Phase C — Screenshot plan

The orchestrator-LLM applies `aso-skills:screenshot-optimization` principles inline — do **not** Skill-invoke (that would prompt Q&A). The principles to apply:

- **Slot 1 = The Hook.** Benefit headline + key UI. "Does this solve my problem?" answered in 3 seconds. Avoid welcome/login/settings.
- **Slots 2-3 = Core Value.** Top 2 features with benefit-driven captions (not feature names).
- **Slots 4-N = Feature showcase.** One feature per slide. `[Benefit Headline] + [Feature UI] + [Supporting Detail]`.
- **Last slot = Trust/Closing.** "Made for [audience]" or a clear differentiator.

Output a 5-slot plan derived from `app-marketing-context.md`'s top features + value proposition. Persist to `.autobot/screenshot-plan.md` (atomic write). This file becomes the input contract for Phase D-1 (which screens to capture) and Phase D-2 (which headlines to overlay).

**Slot defaults** (used if the optimizer fails to produce a plan):

| Slot | Headline | Screen |
|------|----------|--------|
| 1 | Elevator pitch (from context) | Home / main view |
| 2 | Top feature #1 | Feature screen |
| 3 | Top feature #2 | Feature screen |
| 4 | Top feature #3 | Feature screen |
| 5 | "Made for [target audience]" | Hero / closing screen |
