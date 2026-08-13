"""Guard: a restricted agent must GRANT every MCP tool its body tells it to call.

Regression for a historical dogfood bug (the since-removed Stitch integration):
agents/ux-designer.md instructed the agent to call `mcp__stitch__create_project`
etc. as the primary path, but the frontmatter restricted `tools:` to
`Read, Write, Bash, Glob, Grep` — no MCP tools — so the agent could NEVER reach
the MCP path and silently ran the CLI fallback on every build. The guard is
generic: it applies to every agent that declares a `tools:` allowlist.

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

# Signals that an agent body instructs shell execution (lessons #23 builtin
# variant — a granted-tool/body mismatch is not limited to MCP tools):
#   - fenced shell code block
#   - plugin script invocation (`bash $CLAUDE_PLUGIN_ROOT/scripts/...`)
#   - swiftc compile verification
#   - the learning-bootstrap protocol, whose recording step is a
#     `bash $CLAUDE_PLUGIN_ROOT/scripts/build-log.sh --event learning_applied`
#     call (the only path that fills phases.<N>.learningsConsumed for gates)
_BASH_SIGNAL_RES = (
    re.compile(r"^```(?:bash|sh|zsh)\b", re.MULTILINE),
    re.compile(r"bash \"?\$\{?CLAUDE_PLUGIN_ROOT\}?"),
    re.compile(r"\bswiftc\s"),
    re.compile(r"learning-bootstrap\.md"),
)


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

    def test_bash_instructions_require_bash_grant(self):
        """A body that instructs shell execution must grant the builtin Bash tool.

        Regression for the architect gap: architect.md mandated swiftc typecheck
        and the learning-bootstrap `build-log.sh --event learning_applied` call
        (which Gate 1→2 `architect_consumed_learnings` hard-requires), but its
        `tools:` allowlist omitted Bash — the instructions were unexecutable.
        """
        offenders: dict[str, list[str]] = {}
        for f in sorted(glob.glob(str(PLUGIN_DIR / "agents/*.md"))):
            text = Path(f).read_text(encoding="utf-8")
            fm, body = _split_frontmatter(text)
            if fm is None:
                continue
            tools_value = _tools_line(fm)
            if tools_value is None:
                continue  # inherits all tools, incl. Bash
            granted = {tok.strip() for tok in tools_value.split(",")}
            if "Bash" in granted:
                continue
            signals = [r.pattern for r in _BASH_SIGNAL_RES if r.search(body)]
            if signals:
                offenders[Path(f).relative_to(PLUGIN_DIR).as_posix()] = signals

        self.assertEqual(
            offenders,
            {},
            "agent body instructs shell execution but `tools:` does not grant Bash:\n"
            + "\n".join(f"  {k}: {v}" for k, v in offenders.items()),
        )

    def test_no_phantom_mcp_grants(self):
        """Reverse of the grant check: every granted mcp__ tool must be referenced
        by the body. A granted-but-never-mentioned tool is drift — e.g. the four
        phantom Stitch grants (batch_generate_screens, fetch_screen_image,
        fetch_screen_code, check_antigravity_auth) that no longer exist on the
        server and that the body itself contradicted.
        """
        offenders: dict[str, set[str]] = {}
        for f in sorted(glob.glob(str(PLUGIN_DIR / "agents/*.md"))):
            text = Path(f).read_text(encoding="utf-8")
            fm, body = _split_frontmatter(text)
            if fm is None:
                continue
            tools_value = _tools_line(fm)
            if tools_value is None:
                continue
            phantom = _granted_mcp_tools(tools_value) - _referenced_mcp_tools(body)
            if phantom:
                offenders[Path(f).relative_to(PLUGIN_DIR).as_posix()] = phantom

        self.assertEqual(
            offenders,
            {},
            "agent grants MCP tools its body never references — phantom grants "
            "drift from the live server tool list:\n"
            + "\n".join(f"  {k}: {sorted(v)}" for k, v in offenders.items()),
        )

if __name__ == "__main__":
    unittest.main()
