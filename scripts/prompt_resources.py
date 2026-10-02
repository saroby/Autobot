"""Inspect explicitly linked local Markdown resources for packaging and checks.

This is not an agent context loader. Runtime readers choose the reference for
their current operation; packaging and regression checks inspect the full bundle.
"""

from __future__ import annotations

import re
from pathlib import Path


_LINK = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)\)")


def documents(entry: Path) -> list[Path]:
    """Return entry and linked Markdown, in order, once per path.

    Links outside the entry's directory, remote links, and image/fragment links
    are not bundled. A missing local Markdown resource is a contract error.
    """
    entry = entry.resolve()
    root = entry.parent
    seen: set[Path] = set()
    result: list[Path] = []

    def visit(path: Path) -> None:
        if path in seen:
            return
        seen.add(path)
        text = path.read_text(encoding="utf-8")
        result.append(path)
        for raw in _LINK.findall(text):
            target = raw.strip("<>").split("#", 1)[0]
            if not target or ":" in target or not target.endswith(".md"):
                continue
            linked = (path.parent / target).resolve()
            if linked.is_relative_to(root):
                visit(linked)

    visit(entry)
    return result


def read_bundle(entry: Path) -> str:
    return "\n\n".join(path.read_text(encoding="utf-8") for path in documents(entry))
