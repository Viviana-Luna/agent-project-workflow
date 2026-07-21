from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "migrate-project-workflow-to-obsidian" / "scripts" / "prepare_migration.py"


class PrepareMigrationTests(unittest.TestCase):
    def run_script(self, repo: Path, output: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo-root", str(repo), "--output-root", str(output), *extra],
            text=True,
            capture_output=True,
            check=False,
        )

    def make_fixture(self, root: Path) -> Path:
        repo = root / "repo"
        source = repo / ".agent"
        source.mkdir(parents=True)
        (source / "README.md").write_text("# 工作区\n", encoding="utf-8")
        (source / "TODO.md").write_text("- [ ] 任务\n", encoding="utf-8")
        (source / "local-secrets.env").write_text("TOKEN=synthetic-secret-value\n", encoding="utf-8")
        (source / "token.md").write_text("API_KEY=aaaaaaaaaaaa\n", encoding="utf-8")
        (source / "image.bin").write_bytes(b"\x00\xff\x10")
        return repo

    def test_default_excludes_secrets_and_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.make_fixture(root)
            output = root / "output"
            result = self.run_script(repo, output)
            self.assertEqual(result.returncode, 2)
            report = json.loads((output / "migration-report.json").read_text(encoding="utf-8"))
            excluded = {item["path"]: item["reason"] for item in report["excluded"]}
            self.assertIn("local-secrets.env", excluded)
            self.assertIn("token.md", excluded)
            self.assertIn("image.bin", excluded)
            self.assertFalse((output / "project" / "image.bin").exists())

    def test_binary_requires_explicit_flag_and_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.make_fixture(root)
            output = root / "output"
            result = self.run_script(repo, output, "--include-binary")
            self.assertEqual(result.returncode, 2)
            report = json.loads((output / "migration-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["included_binary"], ["image.bin"])
            self.assertTrue((output / "project" / "image.bin").is_file())


if __name__ == "__main__":
    unittest.main()
