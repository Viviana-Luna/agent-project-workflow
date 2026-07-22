from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from apw.adapters import load_adapters
from apw.bundle import Bundle

ROOT = Path(__file__).resolve().parents[1]


class AdapterOsAwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapters = load_adapters(Bundle(root=ROOT))

    def test_opencode_rule_path_same_across_os(self) -> None:
        home = Path("/home/user")
        opencode = self.adapters["opencode"]
        with mock.patch("apw.adapters.os.name", "posix"):
            self.assertEqual(opencode.rule_path(home), home / ".config" / "opencode" / "AGENTS.md")
        with mock.patch("apw.adapters.os.name", "nt"):
            self.assertEqual(opencode.rule_path(home), home / ".config" / "opencode" / "AGENTS.md")

    def test_codex_rule_path_same_across_os(self) -> None:
        home = Path("/home/user")
        codex = self.adapters["codex"]
        with mock.patch("apw.adapters.os.name", "posix"):
            self.assertEqual(codex.rule_path(home), home / ".codex" / "AGENTS.md")
        with mock.patch("apw.adapters.os.name", "nt"):
            self.assertEqual(codex.rule_path(home), home / ".codex" / "AGENTS.md")


if __name__ == "__main__":
    unittest.main()
