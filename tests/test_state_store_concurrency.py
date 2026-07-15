"""Concurrency regression tests for schema-validated build-state mutation."""

from __future__ import annotations

import json
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from state_store import mutate_state_with_validation  # noqa: E402


SPEC = {
    "schemaVersion": 1,
    "stateSchema": {
        "required": ["schemaVersion", "phases"],
        "phaseRequired": ["status"],
        "recommended": [],
    },
    "statuses": ["pending"],
    "phases": {"0": {}},
}


def _append_item(state_path: str, item: int) -> None:
    def mutate(state: dict) -> None:
        # Hold the read-modify-write window open so concurrent workers overlap.
        time.sleep(0.05)
        state.setdefault("items", []).append(item)

    mutate_state_with_validation(Path(state_path), SPEC, mutate)


class TestStateStoreConcurrency(unittest.TestCase):
    def test_concurrent_mutations_do_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / ".autobot" / "build-state.json"
            state_path.parent.mkdir()
            state_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "phases": {"0": {"status": "pending"}},
                        "items": [],
                    }
                )
            )

            workers = [
                multiprocessing.Process(target=_append_item, args=(str(state_path), item))
                for item in range(6)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)

            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual([worker.exitcode for worker in workers], [0] * len(workers))
            final_state = json.loads(state_path.read_text())
            self.assertEqual(sorted(final_state["items"]), list(range(6)))


if __name__ == "__main__":
    unittest.main()
