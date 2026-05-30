"""Guard: a restricted agent must GRANT every MCP tool its body tells it to call.

Regression for the Stitch dogfood bug: agents/ux-designer.md instructs the agent
to call `mcp__stitch__create_project` etc. as the primary path, with an
`npx @_davideast/stitch-mcp ...` CLI fallback "if the MCP tools are unavailable."
But the frontmatter restricted `tools:` to `Read, Write, Bash, Glob, Grep` — no
MCP tools — so the agent could NEVER reach the MCP path and silently ran the npx
fallback on every build.

Claude Code grants subagent MCP access only when each tool is listed by its full
`mcp__<server>__<tool>` name in `tools:` (wildcards are NOT supported); omitting
`tools:` entirely inherits all tools. So: for any agent that DECLARES a `tools:`
allowlist, every `mcp__…` tool referenced in its body must appear in that list.
stdlib-only, no PyYAML.
"""

from __future__ import annotations

import glob
import re
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent

# Full MCP tool identifier: mcp__<server>__<tool> (at least one char each side).
_MCP_TOOL_RE = re.compile(r"mcp__[a-z0-9]+__[a-z0-9_]+")


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    return parts[1], parts[2]


def _tools_line(fm: str) -> str | None:
    """Return the raw value of the `tools:` key, or None if absent."""
    for raw in fm.splitlines():
        m = re.match(r"^\s*tools:\s*(\S.*)$", raw)
        if m:
            return m.group(1).strip()
    return None


def _granted_mcp_tools(tools_value: str) -> set[str]:
    return {tok.strip() for tok in tools_value.split(",") if tok.strip().startswith("mcp__")}


def _referenced_mcp_tools(body: str) -> set[str]:
    # Code-span references (`mcp__x__y`) and bare ones alike — strip backticks.
    return set(_MCP_TOOL_RE.findall(body))


class TestAgentMCPToolGrants(unittest.TestCase):
    def test_referenced_mcp_tools_are_granted(self):
        files = sorted(glob.glob(str(PLUGIN_DIR / "agents/*.md")))
        self.assertGreater(len(files), 0, "no agent markdown discovered")

        offenders: dict[str, set[str]] = {}
        for f in files:
            text = Path(f).read_text(encoding="utf-8")
            fm, body = _split_frontmatter(text)
            if fm is None:
                continue
            tools_value = _tools_line(fm)
            if tools_value is None:
                # No `tools:` key → inherits all tools (incl. MCP). Nothing to enforce.
                continue
            referenced = _referenced_mcp_tools(body)
            if not referenced:
                continue
            granted = _granted_mcp_tools(tools_value)
            missing = referenced - granted
            if missing:
                offenders[Path(f).relative_to(PLUGIN_DIR).as_posix()] = missing

        self.assertEqual(
            offenders,
            {},
            "agent body references MCP tools its `tools:` allowlist does not grant — "
            "the agent cannot call them and is forced onto any CLI fallback:\n"
            + "\n".join(f"  {k}: {sorted(v)}" for k, v in offenders.items()),
        )

    def test_ux_designer_grants_stitch_tools(self):
        # Targeted assertion on the exact regression file.
        text = (PLUGIN_DIR / "agents" / "ux-designer.md").read_text(encoding="utf-8")
        fm, body = _split_frontmatter(text)
        self.assertIsNotNone(fm)
        granted = _granted_mcp_tools(_tools_line(fm) or "")
        self.assertIn("mcp__stitch__create_project", granted)
        self.assertIn("mcp__stitch__generate_screen_from_text", granted)
        # Every Stitch tool named in the body must be granted.
        self.assertEqual(set(), _referenced_mcp_tools(body) - granted)


if __name__ == "__main__":
    unittest.main()
