"""Guard: plugin frontmatter (skills/commands/agents) must not contain
YAML-breaking scalar values.

Regression for build-20260529 dogfood: autobot-peer-review-bridge and
autobot-upload-build had unquoted `description:` values containing ': '
(colon-space). That is valid Markdown but invalid YAML — strict parsers (codex
`exec` loading the skill set, any YAML frontmatter reader) failed with "mapping
values are not allowed in this context" and silently dropped the skill. Claude
Code's lenient reader hid it; the dropped autobot-peer-review-bridge skill broke
the codex peer review path.

stdlib-only (the suite intentionally avoids third-party deps, so no PyYAML): we
don't run a full YAML parser — we flag the specific break, an unquoted block
scalar value that contains ': ' or ends with ':'. Quoting the value fixes it.
"""

from __future__ import annotations

import glob
import re
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
_QUOTE_OR_BLOCK_STARTS = ('"', "'", "[", "{", "|", ">")


def _frontmatter(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else None


def _yaml_breaking_lines(fm: str) -> list[str]:
    bad: list[str] = []
    for raw in fm.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("- "):
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s+(\S.*)$", raw)
        if not m:
            continue
        value = m.group(2).strip()
        if value.startswith(_QUOTE_OR_BLOCK_STARTS):
            continue
        if ": " in value or value.endswith(":"):
            bad.append(stripped)
    return bad


class TestFrontmatterYAML(unittest.TestCase):
    def test_no_yaml_breaking_scalars_in_frontmatter(self):
        files = sorted(
            glob.glob(str(PLUGIN_DIR / "skills/**/SKILL.md"), recursive=True)
            + glob.glob(str(PLUGIN_DIR / "commands/*.md"))
            + glob.glob(str(PLUGIN_DIR / "agents/*.md"))
        )
        self.assertGreater(len(files), 0, "no plugin markdown discovered")
        offenders: dict[str, list[str]] = {}
        for f in files:
            fm = _frontmatter(Path(f).read_text(encoding="utf-8"))
            if fm is None:
                continue
            bad = _yaml_breaking_lines(fm)
            if bad:
                offenders[Path(f).relative_to(PLUGIN_DIR).as_posix()] = bad
        self.assertEqual(
            offenders,
            {},
            "frontmatter scalar values containing ': ' must be quoted "
            "(unquoted = invalid YAML, strict parsers drop the file):\n"
            + "\n".join(f"  {k}: {v}" for k, v in offenders.items()),
        )


if __name__ == "__main__":
    unittest.main()
