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

Slash commands have the same failure mode through `allowed-tools:` and were NOT
covered here, which is how /autobot:copy shipped with a Step 1 built entirely on
mcp-appstore and an allowlist that granted none of it — the same bug as the
Stitch one, one directory over. Commands are checked below too, but only in the
grant direction: a command delegates its procedure to a skill, so its own body
legitimately names no tool while the skill it loads calls several.
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


def _allowed_tools_list(fm: str) -> list[str] | None:
    """Values of a YAML block-sequence `allowed-tools:` key, or None if absent.

    Commands spell the allowlist as a block sequence, not the comma-separated
    scalar agents use:

        allowed-tools:
          - Bash
          - mcp__mcp-appstore__search_app
    """
    lines = fm.splitlines()
    for i, raw in enumerate(lines):
        if not re.match(r"^\s*allowed-tools:\s*$", raw):
            continue
        items = []
        for follow in lines[i + 1:]:
            m = re.match(r"^\s*-\s*(\S.*?)\s*$", follow)
            if not m:
                break
            items.append(m.group(1))
        return items
    return None


# The mcp-appstore tools `skills/autobot-copy-analyze/SKILL.md` Step 1 calls by
# name. /autobot:copy cannot reach any of them unless commands/copy.md grants
# them, and Step 1 is where every review, keyword and similar-app signal in the
# brief comes from — without it the skill silently falls back to device captures
# alone and the Hook & Retention section loses its evidence.
_COPY_APPSTORE_TOOLS = {
    "mcp__mcp-appstore__search_app",
    "mcp__mcp-appstore__get_app_details",
    "mcp__mcp-appstore__fetch_reviews",
    "mcp__mcp-appstore__analyze_reviews",
    "mcp__mcp-appstore__get_similar_apps",
    "mcp__mcp-appstore__analyze_top_keywords",
    "mcp__mcp-appstore__get_keyword_scores",
}


class TestCommandMCPToolGrants(unittest.TestCase):
    def test_referenced_mcp_tools_are_granted(self):
        files = sorted(glob.glob(str(PLUGIN_DIR / "commands/*.md")))
        self.assertGreater(len(files), 0, "no command markdown discovered")

        offenders: dict[str, set[str]] = {}
        for f in files:
            text = Path(f).read_text(encoding="utf-8")
            fm, body = _split_frontmatter(text)
            if fm is None:
                continue
            allowed = _allowed_tools_list(fm)
            if allowed is None:
                # No allowlist → inherits all tools. Nothing to enforce.
                continue
            referenced = _referenced_mcp_tools(body)
            if not referenced:
                continue
            granted = {t for t in allowed if t.startswith("mcp__")}
            missing = referenced - granted
            if missing:
                offenders[Path(f).relative_to(PLUGIN_DIR).as_posix()] = missing

        self.assertEqual(
            offenders,
            {},
            "command body references MCP tools its `allowed-tools:` does not grant — "
            "the command can never call them:\n"
            + "\n".join(f"  {k}: {sorted(v)}" for k, v in offenders.items()),
        )

    def test_copy_command_grants_the_appstore_tools_its_skill_calls(self):
        fm, _ = _split_frontmatter(
            (PLUGIN_DIR / "commands" / "copy.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(fm)
        granted = set(_allowed_tools_list(fm) or [])
        self.assertEqual(set(), _COPY_APPSTORE_TOOLS - granted)

    def test_the_copy_skill_still_calls_those_appstore_tools(self):
        """Guard the other end: if Step 1 drops a tool, the grant list is stale.

        A hardcoded expectation is only worth having while the thing it mirrors
        still exists — otherwise it quietly protects a call nobody makes.
        """
        skill = (PLUGIN_DIR / "skills" / "autobot-copy-analyze" / "SKILL.md").read_text(
            encoding="utf-8")
        missing = {t for t in _COPY_APPSTORE_TOOLS
                   if t.rsplit("__", 1)[1] not in skill}
        self.assertEqual(
            set(), missing,
            "commands/copy.md grants mcp-appstore tools the skill no longer names: "
            f"{sorted(missing)}")


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
