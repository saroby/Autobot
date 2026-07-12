"""Doc-contract guards for the /autobot:meta → /autobot:app-review unattended chain.

Two drift classes broke unattended runs twice and are sealed here:
  1. the age-rating config heredoc forking between commands/meta.md and the
     app-review SKILL.md (a fork re-opens the age_rating_missing dead-end), and
  2. commands/app-review.md re-enumerating (and staling) the SKILL.md phase
     machine instead of delegating to it.
"""

from __future__ import annotations

import json
import re
import unittest

from conftest import PLUGIN_DIR

SKILL = (PLUGIN_DIR / "skills/autobot-app-review/SKILL.md").read_text(encoding="utf-8")
META_CMD = (PLUGIN_DIR / "commands/meta.md").read_text(encoding="utf-8")
REVIEW_CMD = (PLUGIN_DIR / "commands/app-review.md").read_text(encoding="utf-8")
DEPLOYER = (PLUGIN_DIR / "agents/deployer.md").read_text(encoding="utf-8")
UPLOAD_SH = (
    PLUGIN_DIR / "skills/autobot-upload-build/scripts/upload.sh"
).read_text(encoding="utf-8")

RATING_HEREDOC = re.compile(
    r"cat > fastlane/metadata/app_store_rating_config\.json <<'JSON'\s*\n"
    r"(.*?)\n[ \t]*JSON[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


def _rating_config(doc: str, name: str) -> dict:
    match = RATING_HEREDOC.search(doc)
    if match is None:
        raise AssertionError(f"{name}: app_store_rating_config.json heredoc not found")
    return json.loads(match.group(1))


class TestRatingConfigContract(unittest.TestCase):

    def test_meta_and_skill_rating_heredocs_are_identical(self):
        skill_cfg = _rating_config(SKILL, "app-review SKILL.md")
        meta_cfg = _rating_config(META_CMD, "commands/meta.md")
        self.assertEqual(skill_cfg, meta_cfg)

    def test_rating_config_declares_every_asc_field(self):
        cfg = _rating_config(SKILL, "app-review SKILL.md")
        enums = [k for k, v in cfg.items() if v == "NONE"]
        booleans = [k for k, v in cfg.items() if v is False]
        # 13 content-descriptor enums + 9 capability booleans; an omitted field
        # is treated by ASC as *unanswered* and re-triggers age_rating_missing.
        self.assertEqual(13, len(enums), msg=sorted(cfg))
        self.assertEqual(9, len(booleans), msg=sorted(cfg))
        self.assertEqual(len(cfg), len(enums) + len(booleans))

    def test_skill_phase_b_checks_rating_config_independently(self):
        # The META_COUNT .txt gate alone deterministically skips 2b for
        # /autobot:meta-produced trees — the rating config must be its own gate.
        self.assertIn('[ -f "$META_DIR/app_store_rating_config.json" ]', SKILL)
        self.assertIn("RATING_CONFIG_PRESENT", SKILL)
        self.assertNotIn("**If `META_COUNT > 0`:** skip Phase B", SKILL)

    def test_meta_command_always_writes_rating_config(self):
        self.assertIn("app_store_rating_config.json", META_CMD)
        self.assertIn("Step 3b", META_CMD)


class TestMetaCommandNonInteractive(unittest.TestCase):

    def test_upload_flags_declared_and_wired(self):
        frontmatter = META_CMD.split("---")[1]
        self.assertIn("--upload", frontmatter)  # argument-hint
        self.assertIn("--no-upload", META_CMD)
        # Flag must bypass the AskUserQuestion gate, not merely exist.
        self.assertRegex(META_CMD, r"--upload.*→.*Step 6")
        self.assertRegex(META_CMD, r"--no-upload.*→.*Step 7")


class TestAppReviewCommandDelegates(unittest.TestCase):

    def test_command_references_skill_as_ssot(self):
        self.assertIn("skills/autobot-app-review/SKILL.md", REVIEW_CMD)
        self.assertIn("0b", REVIEW_CMD)  # register-first visible in the summary

    def test_command_keeps_anti_laundering_gate(self):
        self.assertIn('run-gate --gate "5->6"', REVIEW_CMD)

    def test_command_does_not_inline_phase_scripts(self):
        # Re-inlining phase bodies is the drift class that twice regressed the
        # unattended path (register-first omitted, age-rating step omitted).
        for script in (
            "write-metadata.sh",
            "upload-metadata.sh",
            "register-on-homepage.sh",
            "upload-screenshots.sh",
            "submit-for-review.sh",
            "capture-marketing.sh",
            "register-app.sh",
        ):
            self.assertNotIn(script, REVIEW_CMD, msg=script)

    def test_command_recovery_is_automated_first(self):
        self.assertNotIn("ASC 웹에서 등급 답변 수동 입력", REVIEW_CMD)
        self.assertIn("age_rating_missing", REVIEW_CMD)
        self.assertIn("최후 수단", REVIEW_CMD)


class TestRegisterAuthModelAlignment(unittest.TestCase):

    def test_skill_register_matrix_uses_current_reasons(self):
        # register-app.sh classifies via the Apple ID web session model.
        self.assertNotIn("api_key_insufficient_role", SKILL)
        self.assertIn("asc_session_expired", SKILL)
        self.assertIn("spaceauth", SKILL)


class TestTransientRetries(unittest.TestCase):

    def test_upload_sh_has_bounded_retries(self):
        self.assertIn("--retries", UPLOAD_SH)
        self.assertIn("RETRIES=2", UPLOAD_SH)

    def test_deployer_retries_transient_register_only(self):
        self.assertNotIn("단일 시도", DEPLOYER)
        self.assertIn("1회 자동 재시도", DEPLOYER)
        # asc_session_expired stays a halt — spaceauth needs a human.
        session_row = next(
            line for line in DEPLOYER.splitlines()
            if line.startswith("| `failed` | `asc_session_expired`")
        )
        self.assertIn("중단", session_row)


if __name__ == "__main__":
    unittest.main()
