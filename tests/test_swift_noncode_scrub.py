"""Unit test for gate_checks._helpers.strip_swift_noncode.

Two HARD gate checks (design_system_components_exist, no_stubs_in_app) route
their matching through this scrubber, so a parser slip is a hard-check false
result. Lock the nasty comment/string vectors.
"""

from __future__ import annotations

import unittest

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks._helpers import strip_swift_noncode  # noqa: E402


class TestStripSwiftNoncode(unittest.TestCase):
    def test_line_comment_removed(self):
        self.assertNotIn("Mock", strip_swift_noncode("let x = 1 // MockRepo()"))

    def test_trailing_comment_after_code_kept_code(self):
        out = strip_swift_noncode("let r = ItemRepository() // MockRepo() here")
        self.assertIn("ItemRepository()", out)
        self.assertNotIn("MockRepo", out)

    def test_block_comment_removed_line_numbers_preserved(self):
        src = "line1()\n/* MockRepo()\nstill comment */\nStubRepo()"
        out = strip_swift_noncode(src)
        lines = out.splitlines()
        self.assertEqual(len(lines), 4)  # newlines inside block comment preserved
        self.assertNotIn("MockRepo", out)
        self.assertIn("StubRepo()", lines[3])

    def test_string_literal_removed(self):
        out = strip_swift_noncode('let s = "MockItemRepository()"')
        self.assertNotIn("MockItemRepository", out)

    def test_url_slashes_inside_string_do_not_truncate_code(self):
        # `//` inside a string must not be treated as a comment start.
        out = strip_swift_noncode('let u = "https://x" ; let r = ItemRepository()')
        self.assertIn("ItemRepository()", out)

    def test_multiline_string_removed(self):
        src = 'let s = """\nStubRepo()\n"""\nReal()'
        out = strip_swift_noncode(src)
        self.assertNotIn("StubRepo", out)
        self.assertIn("Real()", out)

    def test_public_struct_in_comment_not_matched(self):
        out = strip_swift_noncode("// public struct DemoCard {}")
        self.assertNotIn("public struct", out)


if __name__ == "__main__":
    unittest.main()
