from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "workflow_doctor.py"
STANDARD_DIRS = (
    "constraints",
    "explanations",
    "planning/计划中",
    "planning/执行中",
    "planning/已完成",
    "handoff",
    "artifacts",
)


class WorkflowDoctorTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        repo = root / "repo"
        vault = root / "vault"
        workflow = vault / "Myproject" / "repo"
        repo.mkdir()
        for relative in STANDARD_DIRS:
            (workflow / relative).mkdir(parents=True, exist_ok=True)
        plan = workflow / "planning" / "执行中" / "feature.md"
        plan.write_text(
            "---\nid: feature\nstatus: active\nkind: task\ntodo: feature\n---\n\n# 功能计划\n",
            encoding="utf-8",
        )
        (workflow / "TODO.md").write_text(
            "# TODO\n\n## 当前执行\n\n- [ ] [feature] 按 `planning/执行中/feature.md` 执行。\n",
            encoding="utf-8",
        )
        config = root / "config.toml"
        config.write_text(
            f'version = 1\nvault_root = {json.dumps(str(vault))}\nprojects_root = "Myproject"\n\n[projects]\n',
            encoding="utf-8",
        )
        config.chmod(0o600)
        return repo, workflow, config

    def run_doctor(self, repo: Path, config: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo-root", str(repo), "--config", str(config)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_valid_workspace_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo, _, config = self.make_fixture(Path(temp))
            result = self.run_doctor(repo, config)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("0 个错误，0 个警告", result.stdout)

    def test_unreferenced_active_plan_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo, workflow, config = self.make_fixture(Path(temp))
            (workflow / "TODO.md").write_text("# TODO\n\n## 当前执行\n", encoding="utf-8")
            result = self.run_doctor(repo, config)
            self.assertEqual(result.returncode, 1)
            self.assertIn("active-plan-unreferenced", result.stdout)

    def test_checkbox_outside_todo_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo, workflow, config = self.make_fixture(Path(temp))
            plan = workflow / "planning" / "执行中" / "feature.md"
            plan.write_text(plan.read_text(encoding="utf-8") + "\n- [ ] 不应出现在计划中\n", encoding="utf-8")
            result = self.run_doctor(repo, config)
            self.assertEqual(result.returncode, 1)
            self.assertIn("checkbox-outside-todo", result.stdout)


if __name__ == "__main__":
    unittest.main()
