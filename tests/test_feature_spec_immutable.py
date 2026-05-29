import json
import unittest
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "spec" / "pipeline.json"


class TestFeatureSpecImmutable(unittest.TestCase):
    def setUp(self):
        self.fo = json.loads(SPEC.read_text(encoding="utf-8"))["fileOwnership"]

    def test_feature_spec_is_forbidden_infra(self):
        self.assertIn(".autobot/feature-spec.json", self.fo["forbiddenInfra"])

    def test_only_architect_is_exempt(self):
        # architect produces it; no Phase 4/5 agent may rewrite the verifier spec.
        self.assertEqual(self.fo["forbiddenInfraExempt"], ["architect"])


if __name__ == "__main__":
    unittest.main()
