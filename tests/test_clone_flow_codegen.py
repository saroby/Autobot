"""Observed-flow Swift generation is deterministic and refuses guesses."""

from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "clone_flow_codegen.py"
SPEC = importlib.util.spec_from_file_location("clone_flow_codegen", SCRIPT)
codegen = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(codegen)


class CodegenCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.directory = Path(self._directory.name)
        self.flow = self.directory / "flow.jsonl"
        self.manifest = self.directory / "views.json"
        self.output = self.directory / "ObservedFlow.swift"
        self.addCleanup(self._directory.cleanup)

    def write_flow(self, events: list[dict]) -> None:
        self.flow.write_text(
            "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
            encoding="utf-8",
        )

    def run_codegen(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(SCRIPT), *arguments], capture_output=True, text=True
        )


class TestManifest(CodegenCase):
    def test_manifest_supports_new_and_old_state_fields(self):
        self.write_flow([
            {"type": "screen", "state": "home", "name": "00-home"},
            {"type": "screen", "node": "legacy-detail", "name": "01-detail"},
        ])
        result = self.run_codegen("manifest", str(self.flow), str(self.manifest))
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["initial_state"], "home")
        self.assertEqual(manifest["views"], {
            "home": "HomeView",
            "legacy-detail": "DetailView",
        })

    def test_manifest_is_deterministic_and_disambiguates_suggestions(self):
        self.write_flow([
            {"type": "screen", "state": "b", "name": "profile"},
            {"type": "screen", "state": "a", "name": "profile"},
        ])
        first = codegen.manifest_template(codegen.load_flow(self.flow))
        second = codegen.manifest_template(codegen.load_flow(self.flow))
        self.assertEqual(first, second)
        self.assertNotEqual(first["views"]["a"], first["views"]["b"])
        self.assertTrue(all(value.endswith("View") for value in first["views"].values()))


class TestProducerFieldNames(CodegenCase):
    """The router must key on the field names `device_wda.sh` actually writes.

    flow v2 emits `statekey`/`from_statekey`/`to_statekey`. Reading only the
    underscored aliases silently falls back to the coarse `node`/`from`/`to`,
    which collapses two interaction states of one screen (a focused search field
    and an unfocused one) into a single view — with no error anywhere. The repo
    already shipped this exact class of drift once (lessons, 2026-08-16).
    """

    def test_manifest_keys_on_the_state_key_not_the_coarse_node(self):
        self.write_flow([
            {"type": "screen", "node": "n1", "statekey": "home-idle", "name": "00-home"},
            {"type": "screen", "node": "n1", "statekey": "home-search", "name": "01-search"},
        ])
        result = self.run_codegen("manifest", str(self.flow), str(self.manifest))
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["initial_state"], "home-idle")
        self.assertEqual(sorted(manifest["views"]), ["home-idle", "home-search"])

    def test_transitions_use_the_state_key_endpoints(self):
        self.write_flow([
            {"type": "screen", "node": "n1", "statekey": "home-idle", "name": "00-home"},
            {"type": "screen", "node": "n1", "statekey": "home-search", "name": "01-search"},
            {"type": "tap", "from": "n1", "to": "n1",
             "from_statekey": "home-idle", "to_statekey": "home-search",
             "label": "검색", "changed": "true"},
        ])
        self.manifest.write_text(json.dumps({
            "version": 1, "initial_state": "home-idle",
            "views": {"home-idle": "HomeView", "home-search": "SearchView"},
        }), encoding="utf-8")
        result = self.run_codegen(
            "generate", str(self.flow), str(self.manifest), str(self.output)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        swift = self.output.read_text(encoding="utf-8")
        self.assertIn('"home-idle": [', swift)
        self.assertIn('"검색": "home-search",', swift)
        self.assertNotIn('"n1"', swift)
        self.assertIn("SearchView(onAction: { router.send(action: $0) })", swift)


class TestSwiftGeneration(CodegenCase):
    def complete_manifest(self, views: dict[str, str], initial_state: str = "home") -> None:
        self.manifest.write_text(json.dumps({
            "version": 1,
            "initial_state": initial_state,
            "views": views,
        }), encoding="utf-8")

    def test_generates_router_exact_labels_swipes_and_root_switch(self):
        label = '열기 "상세"\n\\(literal)'
        self.write_flow([
            {"type": "screen", "state": "home", "name": "home"},
            {"type": "screen", "state": "detail", "name": "detail"},
            {"type": "screen", "node": "legacy", "name": "legacy"},
            {"type": "tap", "from_state": "home", "to_state": "detail",
             "label": label, "changed": True},
            {"type": "swipe", "from_state": "detail", "to_state": "legacy",
             "x1": 180, "y1": 700, "x2": 180, "y2": 200, "changed": "true"},
            {"type": "tap", "from": "legacy", "to": "home",
             "label": "뒤로", "changed": "true"},
            {"type": "tap", "from": "home", "to": "legacy",
             "label": "ignored-no-op", "changed": False},
            {"type": "tap", "from": "home", "to": "?",
             "label": "ignored-unresolved", "changed": True},
        ])
        self.complete_manifest({
            "home": "HomeView", "detail": "DetailView", "legacy": "LegacyView"
        })

        result = self.run_codegen(
            "generate", str(self.flow), str(self.manifest), str(self.output)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        swift = self.output.read_text(encoding="utf-8")
        self.assertIn("final class ObservedFlowRouter: ObservableObject", swift)
        self.assertIn("func send(action: String)", swift)
        self.assertIn('"swipe:up": "legacy"', swift)
        self.assertIn('"열기 \\"상세\\"\\n\\\\(literal)": "detail"', swift)
        self.assertNotIn("ignored-no-op", swift)
        self.assertNotIn("ignored-unresolved", swift)
        self.assertIn("HomeView(onAction: { router.send(action: $0) })", swift)
        self.assertIn("LegacyView(onAction: { router.send(action: $0) })", swift)

    def test_duplicate_observations_dedupe_but_ambiguous_actions_fail(self):
        base = [
            {"type": "screen", "state": state, "name": state}
            for state in ("home", "a", "b")
        ]
        transition = {
            "type": "tap", "from_state": "home", "to_state": "a",
            "label": "same", "changed": True,
        }
        self.write_flow(base + [transition, transition.copy()])
        self.complete_manifest({"home": "HomeView", "a": "AView", "b": "BView"})
        generated = codegen.generate_swift(
            codegen.load_flow(self.flow), codegen.load_manifest(self.manifest)
        )
        self.assertEqual(generated.count('"same": "a"'), 1)

        conflicting = transition | {"to_state": "b"}
        self.write_flow(base + [transition, conflicting])
        result = self.run_codegen("generate", str(self.flow), str(self.manifest))
        self.assertEqual(result.returncode, 1)
        self.assertIn("ambiguous transition", result.stderr)

    def test_missing_view_mapping_fails_instead_of_guessing(self):
        self.write_flow([
            {"type": "screen", "state": "home", "name": "home"},
            {"type": "screen", "state": "detail", "name": "detail"},
        ])
        self.complete_manifest({"home": "HomeView"})
        result = self.run_codegen("generate", str(self.flow), str(self.manifest))
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing view mappings for: detail", result.stderr)

    def test_generated_swift_typechecks_when_xcode_swiftc_is_available(self):
        if not shutil.which("xcrun"):
            self.skipTest("xcrun is unavailable")
        sdk = subprocess.run(
            ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"],
            capture_output=True, text=True,
        )
        if sdk.returncode != 0:
            self.skipTest("iPhone Simulator SDK is unavailable")

        self.write_flow([
            {"type": "screen", "state": "home", "name": "home"},
            {"type": "screen", "state": "detail", "name": "detail"},
            {"type": "tap", "from_state": "home", "to_state": "detail",
             "label": 'quote " and newline\n', "changed": True},
        ])
        self.complete_manifest({"home": "HomeView", "detail": "DetailView"})
        self.output.write_text(codegen.generate_swift(
            codegen.load_flow(self.flow), codegen.load_manifest(self.manifest)
        ), encoding="utf-8")
        stubs = self.directory / "Screens.swift"
        stubs.write_text("""import SwiftUI
struct HomeView: View {
    let onAction: (String) -> Void
    var body: some View { EmptyView() }
}
struct DetailView: View {
    let onAction: (String) -> Void
    var body: some View { EmptyView() }
}
""", encoding="utf-8")
        arch = "arm64" if platform.machine() == "arm64" else "x86_64"
        result = subprocess.run([
            "xcrun", "swiftc", "-typecheck", "-parse-as-library",
            "-sdk", sdk.stdout.strip(), "-target", f"{arch}-apple-ios17.0-simulator",
            str(self.output), str(stubs),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()


class TestBackActions(unittest.TestCase):
    """A back button lands wherever you came from.

    Measured 2026-08-23: one screen's `돌아가기` was observed going to three
    different places, and refusing to model that blocked the whole pipeline.
    A fixed state->action->state table cannot say it; a history stack can.
    """

    def flow(self, edges: list[tuple[str, str, str]]) -> list[dict]:
        events: list[dict] = []
        seen: set[str] = set()
        for source, action, destination in edges:
            for state in (source, destination):
                if state not in seen:
                    seen.add(state)
                    events.append({"type": "screen", "statekey": state, "name": state})
            events.append({"type": "tap", "from_statekey": source,
                           "to_statekey": destination, "label": action,
                           "changed": "true"})
        return events

    def transitions(self, edges):
        events = self.flow(edges)
        return codegen.observed_transitions(events, set(codegen.captured_states(events)))

    def test_several_destinations_that_are_all_places_you_came_from_is_a_pop(self):
        found = self.transitions([
            ("home", "열기", "detail"),
            ("search", "열기", "detail"),
            ("detail", "돌아가기", "home"),
            ("detail", "돌아가기", "search"),
        ])
        self.assertIn(("detail", "돌아가기", codegen.POP), found)

    def test_a_destination_you_never_came_from_is_still_a_contradiction(self):
        with self.assertRaises(codegen.FlowCodegenError) as caught:
            self.transitions([
                ("home", "열기", "detail"),
                ("detail", "저장", "saved"),
                ("detail", "저장", "settings"),
            ])
        self.assertIn("ambiguous transition", str(caught.exception))

    def test_a_single_destination_is_left_alone(self):
        found = self.transitions([("home", "열기", "detail")])
        self.assertEqual(found, [("home", "열기", "detail")])

    def test_the_router_pops_its_history(self):
        events = self.flow([
            ("home", "열기", "detail"),
            ("search", "열기", "detail"),
            ("detail", "돌아가기", "home"),
            ("detail", "돌아가기", "search"),
        ])
        manifest = {"initial_state": "home",
                    "views": {state: f"V{index}" for index, state
                              in enumerate(codegen.captured_states(events))}}
        swift = codegen.generate_swift(events, manifest)
        self.assertIn("private var history: [String] = []", swift)
        self.assertIn("history.popLast()", swift)
        self.assertIn("history.append(state)", swift)
