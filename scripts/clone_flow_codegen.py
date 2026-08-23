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


def _identifier(event: dict[str, Any], *keys: str) -> str | None:
    """First usable identifier among ``keys``, in priority order.

    The flow v2 producer writes ``statekey``/``from_statekey``/``to_statekey``;
    logs released before that used the underscored aliases, and the oldest ones
    only had the coarse ``node``/``from``/``to``. Reading all three keeps the
    router on the interaction state (a focused search field is not the same
    screen as an unfocused one) instead of silently collapsing to the coarse
    node whenever the canonical name is not the one being looked for.
    """
    for key in keys:
        value = event.get(key)
        if value is None:
            continue
        value = str(value).strip()
        if value and value != "?":
            return value
    return None


def captured_states(events: Iterable[dict[str, Any]]) -> "OrderedDict[str, dict[str, Any]]":
    states: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for event in events:
        if event.get("type") != "screen":
            continue
        state = _identifier(event, "statekey", "state", "node")
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
            "changed", "from", "from_state", "from_statekey", "to", "to_state",
            "to_statekey", "state", "statekey", "node", "nodekey",
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


# The destination of an action that goes back. The router pops its history
# instead of jumping to a fixed screen.
POP = "\u0000pop"


def observed_transitions(
    events: list[dict[str, Any]], captured: set[str]
) -> list[tuple[str, str, str]]:
    destinations: dict[tuple[str, str], set[str]] = {}
    for event in events:
        if event.get("type") not in {"tap", "swipe"} or not _is_changed(event):
            continue
        source = _identifier(event, "from_statekey", "from_state", "from")
        destination = _identifier(event, "to_statekey", "to_state", "to")
        action = _action_id(event)
        if not source or not destination or not action:
            continue
        if source not in captured or destination not in captured:
            continue
        destinations.setdefault((source, action), set()).add(destination)

    # An action with several destinations is not automatically a contradiction.
    # A back button legitimately lands wherever you came from — measured
    # 2026-08-23: '돌아가기' from one screen went to three different places, and
    # refusing to model that blocked the whole pipeline. When every destination
    # is a screen the source was actually reached FROM, the action is a pop, and
    # a history stack reproduces it exactly. Anything else is still a genuine
    # contradiction and still refuses.
    predecessors: dict[str, set[str]] = {}
    for (source, _action), targets in destinations.items():
        for target in targets:
            predecessors.setdefault(target, set()).add(source)

    pops = {
        (source, action)
        for (source, action), targets in destinations.items()
        if len(targets) > 1 and targets <= predecessors.get(source, set())
    }
    ambiguous = [
        (source, action, sorted(targets))
        for (source, action), targets in destinations.items()
        if len(targets) > 1 and (source, action) not in pops
    ]
    if ambiguous:
        source, action, targets = sorted(ambiguous)[0]
        raise FlowCodegenError(
            f"ambiguous transition from {source!r} for action {action!r}: "
            + ", ".join(repr(target) for target in targets)
        )

    return sorted(
        (source, action, POP if (source, action) in pops else next(iter(targets)))
        for (source, action), targets in destinations.items()
    )


def _element_keys(measurement: dict[str, Any]) -> set[tuple[str, str, int, int, int, int]]:
    """Identity of every labelled element: label, role, frame on an 8pt grid."""
    keys = set()
    for element in measurement.get("elements") or []:
        label = str(element.get("label") or "").strip()
        frame = element.get("frame") or {}
        if not label or not frame:
            continue
        try:
            keys.add((label, str(element.get("role") or ""),
                      round(float(frame.get("x", 0)) / 8), round(float(frame.get("y", 0)) / 8),
                      round(float(frame.get("width", 0)) / 8), round(float(frame.get("height", 0)) / 8)))
        except (TypeError, ValueError):
            continue
    return keys


def _element_keys_by_state(events: list[dict[str, Any]], screens_dir: Path) -> dict[str, set]:
    """Per state, the element identities present in EVERY capture of it.

    Chrome survives every capture of a screen; feed content does not. Taking
    the intersection is what makes a tab bar qualify and a post row not.
    """
    per_state: dict[str, set | None] = {}
    for event in events:
        if event.get("type") != "screen":
            continue
        state = _identifier(event, "statekey", "state", "node")
        name = str(event.get("name") or "")
        path = screens_dir / f"{name}.json"
        if not state or not name or not path.is_file():
            continue
        try:
            keys = _element_keys(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        per_state[state] = keys if per_state.get(state) is None else (per_state[state] & keys)
    return {state: keys for state, keys in per_state.items() if keys}


def inferred_transitions(
    events: list[dict[str, Any]], captured: set[str], screens_dir: Path | str,
) -> list[tuple[str, str, str]]:
    """Transitions the clone may carry on screens where they were NOT observed.

    A tab bar is the same control on every screen that shows it, and tapping
    "프로필" from any of them goes to the same place. Observing it once per
    screen would cost a tap per screen per control — and until then every
    unobserved copy is a dead button, which is most of what a user feels when
    a clone "does nothing" (Codex review, 2026-08-23: coverage, not rendering).

    The rule is narrow on purpose: the control must be the SAME element — label,
    role and frame on an 8pt grid — on the source where it was observed AND
    present in every capture of the target screen (chrome passes, content does
    not). Back actions (pops) are never inferred: where they land depends on
    history. These are guesses, so callers report them separately from what was
    observed; they never replace an observed transition.
    """
    screens_dir = Path(screens_dir)
    observed = observed_transitions(events, captured)
    present = _element_keys_by_state(events, screens_dir)
    have: dict[str, set[str]] = {}
    for source, action, _destination in observed:
        have.setdefault(source, set()).add(action)

    # Which observed controls are PERSISTENT — still there on the screen they
    # lead to. A tab bar is; a back or close button is not (you land somewhere
    # that does not have it). That structural fact is what separates "tap this
    # anywhere and you get there" from "tap this and you go back to wherever
    # you came from", and it needs no vocabulary of back-button labels.
    # Measured 2026-08-23: keyed on destination statekey alone, the tab bar
    # looked history-dependent too, because the same profile screen was
    # captured under several interaction states.
    by_action: dict[str, list[tuple[str, str, set]]] = {}
    for source, action, destination in observed:
        if destination == POP:
            continue
        keys = {key for key in present.get(source, set()) if key[0] == action}
        if keys:
            by_action.setdefault(action, []).append((source, destination, keys))

    # Coarse screen identity, so "the profile screen in three interaction
    # states" reads as one destination — the selected tab's label changes on
    # its own screen, which defeats the persistence test, yet the tab still
    # goes to one place from everywhere.
    node_of: dict[str, str] = {}
    for event in events:
        if event.get("type") == "screen":
            state = _identifier(event, "statekey", "state", "node")
            node = _identifier(event, "node", "nodekey") or state
            if state and state not in node_of:
                node_of[state] = node

    inferred: list[tuple[str, str, str]] = []
    for action, sightings in sorted(by_action.items()):
        persistent = all(keys & present.get(destination, set())
                         for _source, destination, keys in sightings)
        distinct = {node_of.get(destination, destination) for _s, destination, _k in sightings}
        if len(distinct) > 1 and not persistent:
            continue                      # history-dependent: where it goes depends on where you were
        # The landing: what this control was most often seen to reach.
        counts: dict[str, int] = {}
        for _s, destination, _k in sightings:
            counts[destination] = counts.get(destination, 0) + 1
        landing = max(sorted(counts), key=counts.__getitem__)
        keys = set().union(*(k for _s, _d, k in sightings))
        for target, target_keys in present.items():
            if target not in captured or action in have.get(target, set()):
                continue
            if target == landing:
                continue              # the tab you are already on: a no-op, not a transition
            if keys & target_keys:
                inferred.append((target, action, landing))
                have.setdefault(target, set()).add(action)
    return sorted(inferred)


def all_transitions(
    events: list[dict[str, Any]], captured: set[str], screens_dir: Path | str | None,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """(observed, inferred). Inference needs the measurements; without them it is empty."""
    observed = observed_transitions(events, captured)
    if not screens_dir:
        return observed, []
    return observed, inferred_transitions(events, captured, screens_dir)


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


def generate_swift(events: list[dict[str, Any]], manifest: dict[str, Any],
                   screens_dir: Path | str | None = None) -> str:
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
    observed, inferred = all_transitions(events, set(states), screens_dir)
    grouped: dict[str, list[tuple[str, str]]] = {}
    for source, action, destination in observed + inferred:
        grouped.setdefault(source, []).append((action, destination))
    inferred_keys = {(source, action) for source, action, _d in inferred}

    lines = [
        "// Generated by clone_flow_codegen.py. Do not hand-edit.",
        "import SwiftUI",
        "import Combine",
        "",
        "@MainActor",
        "final class ObservedFlowRouter: ObservableObject {",
        "    @Published private(set) var state: String",
        "",
        "    /// Where a forward move came from. A back action lands wherever you",
        "    /// arrived from, which a fixed state->action->state table cannot say:",
        "    /// one screen\u2019s back button was observed going to three different",
        "    /// places. The app keeps a stack, so the reproduction keeps one.",
        "    private var history: [String] = []",
        "",
        f"    static let popDestination = {swift_string(POP)}",
        "",
        "    static let observedTransitions: [String: [String: String]] = [",
    ]
    for source in sorted(grouped):
        lines.append(f"        {swift_string(source)}: [")
        for action, destination in sorted(grouped[source]):
            note = "  // inferred: persistent control, observed elsewhere" \
                if (source, action) in inferred_keys else ""
            lines.append(
                f"            {swift_string(action)}: {swift_string(destination)},{note}"
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
        "        if nextState == Self.popDestination {",
        "            guard let previous = history.popLast() else { return }",
        "            state = previous",
        "            return",
        "        }",
        "        history.append(state)",
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
        if mode in {"generate", "swift"} and len(argv) in {4, 5, 6}:
            # Optional 6th argument: the measurements directory. With it the
            # router also carries inferred chrome transitions (see
            # inferred_transitions); without it, observed only.
            screens = argv[5] if len(argv) == 6 else None
            source = generate_swift(load_flow(argv[2]), load_manifest(argv[3]), screens)
            _write(source, argv[4] if len(argv) == 5 or len(argv) == 6 else None)
            return 0
    except (FlowCodegenError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "ERROR: usage: clone_flow_codegen.py manifest <flow.jsonl> [manifest.json] | "
        "generate <flow.jsonl> <manifest.json> [output.swift [screens-dir]]",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
