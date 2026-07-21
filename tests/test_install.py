from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install.py"


class InstallTests(unittest.TestCase):
    def run_install(self, home: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--client", "codex", "--home", str(home), *extra],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_install_is_repeatable_and_conflicts_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            first = self.run_install(home)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertTrue((home / ".codex" / "AGENTS.md").is_file())
            self.assertTrue((home / ".agents" / "skills" / "execute-todo-loop" / "SKILL.md").is_file())

            second = self.run_install(home)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

            rules = home / ".codex" / "AGENTS.md"
            rules.write_text("用户已有规则\n", encoding="utf-8")
            conflict = self.run_install(home)
            self.assertEqual(conflict.returncode, 2)
            self.assertEqual(rules.read_text(encoding="utf-8"), "用户已有规则\n")

            forced = self.run_install(home, "--force")
            self.assertEqual(forced.returncode, 0, forced.stdout + forced.stderr)
            self.assertNotEqual(rules.read_text(encoding="utf-8"), "用户已有规则\n")
            backups = list((home / ".local" / "state" / "agent-project-workflow" / "backups").rglob("AGENTS.md"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "用户已有规则\n")

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            result = self.run_install(home, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((home / ".codex").exists())
            self.assertFalse((home / ".agents").exists())


if __name__ == "__main__":
    unittest.main()
