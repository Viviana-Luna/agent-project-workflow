from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "agent-dev-workflow-init" / "scripts" / "init_agent_workflow.py"


class InitWorkflowTests(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_default_path_and_existing_readme_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "sample-repo"
            vault = root / "vault"
            repo.mkdir()
            readme = repo / "README.md"
            readme.write_text("# 已有说明\n", encoding="utf-8")
            config = root / "config.toml"
            config.write_text(
                f'version = 1\nvault_root = {json.dumps(str(vault))}\nprojects_root = "Myproject"\n\n[projects]\n',
                encoding="utf-8",
            )

            result = self.run_script("--repo-root", str(repo), "--config", str(config))
            self.assertEqual(result.returncode, 0, result.stderr)
            workflow = vault / "Myproject" / "sample-repo"
            self.assertTrue((workflow / "TODO.md").is_file())
            self.assertTrue((workflow / "planning" / "执行中").is_dir())
            self.assertEqual(readme.read_text(encoding="utf-8"), "# 已有说明\n")
            self.assertFalse((repo / ".agent").exists())
            template_root = ROOT / "templates" / "workspace"
            for relative in (
                "README.md",
                "TODO.md",
                "constraints/README.md",
                "explanations/README.md",
                "planning/README.md",
                "planning/计划模板.md",
                "handoff/README.md",
                "artifacts/README.md",
            ):
                self.assertEqual(
                    (workflow / relative).read_text(encoding="utf-8"),
                    (template_root / relative).read_text(encoding="utf-8"),
                    relative,
                )

    def test_explicit_mapping_matches_normalized_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            config = root / "config.toml"
            config.write_text(
                f'version = 1\nvault_root = {json.dumps(str(root / "vault"))}\nprojects_root = "Myproject"\n\n'
                f'[projects]\n{json.dumps(str(repo))} = "Special/project"\n',
                encoding="utf-8",
            )
            result = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--print-workflow-root",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()), (root / "vault" / "Special" / "project").resolve())

    def test_unsafe_projects_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            config = root / "config.toml"
            config.write_text(
                f'version = 1\nvault_root = {json.dumps(str(root / "vault"))}\nprojects_root = "../outside"\n',
                encoding="utf-8",
            )
            result = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--print-workflow-root",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("安全相对路径", result.stderr)


if __name__ == "__main__":
    unittest.main()
