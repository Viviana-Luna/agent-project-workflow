from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from apw.paths import AppPaths


class AppPathsTests(unittest.TestCase):
    def test_home_override_layout(self) -> None:
        with TemporaryDirectory() as temp:
            paths = AppPaths.from_home(Path(temp))
            if os.name == "nt":
                root = paths.home / "agent-project-workflow"
                self.assertEqual(paths.config_dir, root / "config")
                self.assertEqual(paths.data_dir, root / "data")
                self.assertEqual(paths.state_dir, root / "state")
                self.assertEqual(paths.cache_dir, root / "cache")
                self.assertEqual(paths.bin_dir, root / "bin")
                self.assertEqual(paths.launcher, root / "bin" / "apw.cmd")
                self.assertEqual(paths.long_launcher, root / "bin" / "agent-project-workflow.cmd")
            else:
                self.assertEqual(paths.config_dir, paths.home / ".config" / "agent-project-workflow")
                self.assertEqual(paths.data_dir, paths.home / ".local" / "share" / "agent-project-workflow")
                self.assertEqual(paths.state_dir, paths.home / ".local" / "state" / "agent-project-workflow")
                self.assertEqual(paths.cache_dir, paths.home / ".cache" / "agent-project-workflow")
                self.assertEqual(paths.bin_dir, paths.home / ".local" / "bin")
                self.assertEqual(paths.launcher, paths.home / ".local" / "bin" / "apw")
                self.assertEqual(paths.long_launcher, paths.home / ".local" / "bin" / "agent-project-workflow")

    @unittest.skipUnless(os.name == "nt", "Windows LOCALAPPDATA 布局")
    def test_real_home_uses_localappdata(self) -> None:
        paths = AppPaths.from_home(None)
        root = Path(os.environ["LOCALAPPDATA"]) / "agent-project-workflow"
        self.assertEqual(paths.config_dir, root / "config")
        self.assertEqual(paths.bin_dir, root / "bin")
        self.assertEqual(paths.launcher, root / "bin" / "apw.cmd")

    def test_legacy_config_under_home(self) -> None:
        with TemporaryDirectory() as temp:
            paths = AppPaths.from_home(Path(temp))
            self.assertEqual(paths.legacy_config_file, paths.home / ".codex" / "project-workflow.toml")


if __name__ == "__main__":
    unittest.main()
