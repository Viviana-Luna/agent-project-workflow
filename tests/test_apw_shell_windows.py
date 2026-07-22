from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from apw import shell


@unittest.skipUnless(os.name == "nt", "Windows 用户 PATH 注册表管理")
class WindowsUserPathTests(unittest.TestCase):
    def _patch(self, state: dict[str, object]):
        return (
            mock.patch("apw.shell._read_user_path", lambda: (state["value"], state["type"])),
            mock.patch("apw.shell._write_user_path", lambda value, vtype: state.update(value=value, type=vtype)),
        )

    def test_add_then_remove(self) -> None:
        state: dict[str, object] = {"value": "", "type": 2}
        bin_dir = Path("C:/some/apw/bin")
        read_patch, write_patch = self._patch(state)
        with read_patch, write_patch:
            self.assertFalse(shell.user_path_contains(bin_dir))
            self.assertTrue(shell.add_user_path(bin_dir))
            self.assertTrue(shell.user_path_contains(bin_dir))
            self.assertFalse(shell.add_user_path(bin_dir))
            self.assertTrue(shell.remove_user_path(bin_dir))
            self.assertFalse(shell.user_path_contains(bin_dir))
            self.assertFalse(shell.remove_user_path(bin_dir))

    def test_preserves_existing_entries_and_type(self) -> None:
        state: dict[str, object] = {"value": "C:\\existing\\bin", "type": 2}
        bin_dir = Path("C:/some/apw/bin")
        read_patch, write_patch = self._patch(state)
        with read_patch, write_patch:
            shell.add_user_path(bin_dir)
            self.assertIn("C:\\existing\\bin", state["value"])
            self.assertEqual(state["type"], 2)
            shell.remove_user_path(bin_dir)
            self.assertEqual(state["value"], "C:\\existing\\bin")

    def test_dry_run_does_not_write(self) -> None:
        state: dict[str, object] = {"value": "", "type": 2}
        bin_dir = Path("C:/some/apw/bin")
        read_patch, write_patch = self._patch(state)
        with read_patch, write_patch:
            self.assertTrue(shell.add_user_path(bin_dir, dry_run=True))
            self.assertEqual(state["value"], "")


if __name__ == "__main__":
    unittest.main()
