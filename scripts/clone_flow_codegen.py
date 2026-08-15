#!/usr/bin/env python3
"""Generate a small SwiftUI router from an observed clone exploration flow.

Two commands form the workflow:

    clone_flow_codegen.py manifest flow.jsonl views.json
    clone_flow_codegen.py generate flow.jsonl views.json ObservedFlow.swift

The manifest is intentionally editable. Its ``views`` object maps durable flow
state IDs to Swift view types. Generated screens use one uniform initializer:
``ScreenView(onAction: (String) -> Void)``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, OrderedDict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


class FlowCodegenError(ValueError):
    """An observed flow or manifest cannot be translated without guessing."""


def load_flow(path: str | Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise FlowCodegenError(
                    f"invalid JSON on line {line_number} of {path}: {exc.msg}"
                ) from exc
            if not isinstance(event, dict):
                raise FlowCodegenError(
                    f"flow line {line_number} must be a JSON object"
                )
            events.append(event)
    return events


def _identifier(event: dict[str, Any], primary: str, fallback: str) -> str | None:
    value = event.get(primary) or event.get(fallback)
    if value is None:
        return None
    value = str(value).strip()
    return value if value and value != "?" else None


def captured_states(events: Iterable[dict[str, Any]]) -> "OrderedDict[str, dict[str, Any]]":
    states: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for event in events:
        if event.get("type") != "screen":
            continue
        state = _identifier(event, "state", "node")
        if state and state not in states:
            states[state] = event
    return states


def _swift_type_suggestion(state: str, event: dict[str, Any]) -> str:
    source = str(event.get("name") or state)
    source = re.sub(r"^\s*\d+[\s._-]*", "", source)
    words = re.findall(r"[A-Za-z0-9]+", source)
    if not words or not any(any(c.isalpha() for c in word) for word in words):
        stem = "State" + hashlib.sha256(state.encode("utf-8")).hexdigest()[:8].upper()
    else:
        stem = "".join(word[:1].upper() + word[1:] for word in words)
        if stem[:1].isdigit():
            stem = "State" + stem
    return stem if stem.endswith("View") else stem + "View"


def manifest_template(events: list[dict[str, Any]]) -> dict[str, Any]:
    states = captured_states(events)
    if not states:
        raise FlowCodegenError("flow contains no captured screen states")

    suggestions = {
        state: _swift_type_suggestion(state, event)
        for state, event in states.items()
    }
    collisions = Counter(suggestions.values())
    for state, suggestion in list(suggestions.items()):
        if collisions[suggestion] > 1:
            suffix = hashlib.sha256(state.encode("utf-8")).hexdigest()[:6].upper()
            stem = suggestion[:-4] if suggestion.endswith("View") else suggestion
            suggestions[state] = f"{stem}{suffix}View"

    return {
        "version": 1,
        "initial_state": next(iter(states)),
        "views": {state: suggestions[state] for state in sorted(states)},
    }


def _is_changed(event: dict[str, Any]) -> bool:
    value = event.get("changed", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"true", "1", "yes"}


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _swipe_action_id(event: dict[str, Any]) -> str:
    explicit = event.get("action_id")
    if isinstance(explicit, str) and explicit:
        return explicit

    direction = event.get("direction")
    if isinstance(direction, str) and direction.strip():
        return "swipe:" + direction.strip().lower()

    x1, y1, x2, y2 = (_decimal(event.get(key)) for key in ("x1", "y1", "x2", "y2"))
    if None not in (x1, y1, x2, y2):
        dx = x2 - x1  # type: ignore[operator]
        dy = y2 - y1  # type: ignore[operator]
        if dx != 0 or dy != 0:
            if abs(dy) >= abs(dx):
                return "swipe:down" if dy > 0 else "swipe:up"
            return "swipe:right" if dx > 0 else "swipe:left"

    stable_action = {
        key: event[key]
        for key in sorted(event)
        if key not in {
            "changed", "from", "from_state", "to", "to_state", "state", "node",
            "timestamp", "time", "ts", "png", "tree", "sig",
        }
    }
    digest = hashlib.sha256(
        json.dumps(stable_action, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()[:12]
    return f"swipe:{digest}"


def _action_id(event: dict[str, Any]) -> str | None:
    label = event.get("label")
    if isinstance(label, str) and label:
        return label
    if event.get("type") == "swipe":
        return _swipe_action_id(event)
    return None


def observed_transitions(
    events: list[dict[str, Any]], captured: set[str]
) -> list[tuple[str, str, str]]:
    destinations: dict[tuple[str, str], set[str]] = {}
    for event in events:
        if event.get("type") not in {"tap", "swipe"} or not _is_changed(event):
            continue
        source = _identifier(event, "from_state", "from")
        destination = _identifier(event, "to_state", "to")
        action = _action_id(event)
        if not source or not destination or not action:
            continue
        if source not in captured or destination not in captured:
            continue
        destinations.setdefault((source, action), set()).add(destination)

    ambiguous = [
        (source, action, sorted(targets))
        for (source, action), targets in destinations.items()
        if len(targets) > 1
    ]
    if ambiguous:
        source, action, targets = sorted(ambiguous)[0]
        raise FlowCodegenError(
            f"ambiguous transition from {source!r} for action {action!r}: "
            + ", ".join(repr(target) for target in targets)
        )

    return sorted(
        (source, action, next(iter(targets)))
        for (source, action), targets in destinations.items()
    )


_SWIFT_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def _manifest_views(manifest: dict[str, Any]) -> dict[str, str]:
    raw = manifest.get("views")
    if raw is None:
        raw = manifest.get("states")
    if not isinstance(raw, dict):
        raise FlowCodegenError("manifest must contain a 'views' object")

    views: dict[str, str] = {}
    for state, value in raw.items():
        if isinstance(value, dict):
            value = value.get("view")
        if isinstance(state, str) and isinstance(value, str) and value.strip():
            views[state] = value.strip()
    return views


def load_manifest(path: str | Path) -> dict[str, Any]:
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FlowCodegenError(f"invalid manifest JSON in {path}: {exc.msg}") from exc
    if not isinstance(manifest, dict):
        raise FlowCodegenError("manifest root must be a JSON object")
    return manifest


def swift_string(value: str) -> str:
    escaped: list[str] = ['"']
    for character in value:
        scalar = ord(character)
        if 0xD800 <= scalar <= 0xDFFF:
            raise FlowCodegenError("state and action strings may not contain Unicode surrogates")
        replacements = {
            "\\": "\\\\",
            '"': '\\"',
            "\0": "\\0",
            "\n": "\\n",
            "\r": "\\r",
            "\t": "\\t",
        }
        if character in replacements:
            escaped.append(replacements[character])
        elif scalar < 0x20 or scalar in {0x7F, 0x2028, 0x2029}:
            escaped.append(f"\\u{{{scalar:X}}}")
        else:
            escaped.append(character)
    escaped.append('"')
    return "".join(escaped)


def generate_swift(events: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    states = captured_states(events)
    if not states:
        raise FlowCodegenError("flow contains no captured screen states")
    views = _manifest_views(manifest)
    missing = sorted(set(states) - set(views))
    if missing:
        raise FlowCodegenError("manifest is missing view mappings for: " + ", ".join(missing))
    invalid = sorted(
        (state, views[state]) for state in states if not _SWIFT_TYPE.fullmatch(views[state])
    )
    if invalid:
        state, view = invalid[0]
        raise FlowCodegenError(f"invalid Swift view type {view!r} for state {state!r}")

    initial_state = str(manifest.get("initial_state") or next(iter(states)))
    if initial_state not in states:
        raise FlowCodegenError(f"initial state {initial_state!r} was not captured")
    transitions = observed_transitions(events, set(states))
    grouped: dict[str, list[tuple[str, str]]] = {}
    for source, action, destination in transitions:
        grouped.setdefault(source, []).append((action, destination))

    lines = [
        "// Generated by clone_flow_codegen.py. Do not hand-edit.",
        "import SwiftUI",
        "import Combine",
        "",
        "@MainActor",
        "final class ObservedFlowRouter: ObservableObject {",
        "    @Published private(set) var state: String",
        "",
        "    static let observedTransitions: [String: [String: String]] = [",
    ]
    for source in sorted(grouped):
        lines.append(f"        {swift_string(source)}: [")
        for action, destination in sorted(grouped[source]):
            lines.append(
                f"            {swift_string(action)}: {swift_string(destination)},"
            )
        lines.append("        ],")
    lines.extend([
        "    ]",
        "",
        f"    init(initialState: String = {swift_string(initial_state)}) {{",
        "        self.state = initialState",
        "    }",
        "",
        "    func send(action: String) {",
        "        guard let nextState = Self.observedTransitions[state]?[action] else { return }",
        "        state = nextState",
        "    }",
        "}",
        "",
        "struct ObservedFlowRootView: View {",
        "    @StateObject private var router: ObservedFlowRouter",
        "",
        f"    init(initialState: String = {swift_string(initial_state)}) {{",
        "        _router = StateObject(wrappedValue: ObservedFlowRouter(initialState: initialState))",
        "    }",
        "",
        "    var body: some View {",
        "        switch router.state {",
    ])
    for state in sorted(states):
        lines.extend([
            f"        case {swift_string(state)}:",
            f"            {views[state]}(onAction: {{ router.send(action: $0) }})",
        ])
    lines.extend([
        "        default:",
        "            EmptyView()",
        "        }",
        "    }",
        "}",
        "",
    ])
    return "\n".join(lines)


def _write(text: str, output: str | None) -> None:
    if output is None or output == "-":
        sys.stdout.write(text)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    try:
        if mode == "manifest" and len(argv) in {3, 4}:
            manifest = manifest_template(load_flow(argv[2]))
            _write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                   argv[3] if len(argv) == 4 else None)
            return 0
        if mode in {"generate", "swift"} and len(argv) in {4, 5}:
            source = generate_swift(load_flow(argv[2]), load_manifest(argv[3]))
            _write(source, argv[4] if len(argv) == 5 else None)
            return 0
    except (FlowCodegenError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "ERROR: usage: clone_flow_codegen.py manifest <flow.jsonl> [manifest.json] | "
        "generate <flow.jsonl> <manifest.json> [output.swift]",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
