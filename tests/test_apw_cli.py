from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from apw.cli import main


class CliInstallFlowTests(unittest.TestCase):
    def test_interactive_skills_selection_only_installs_shared_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            output = io.StringIO()
            with (
                mock.patch("apw.cli.choose_one", return_value="skills"),
                mock.patch("apw.cli.choose_skills", return_value=["execute-todo-loop"]),
                mock.patch("apw.cli.choose_follow_up_rule", return_value=None),
                mock.patch("apw.cli.confirm", return_value=True),
                redirect_stdout(output),
            ):
                result = main(["--home", str(home), "install"])
            self.assertEqual(result, 0)
            self.assertIn("支持的客户端检测结果", output.getvalue())
            self.assertTrue((home / ".agents" / "skills" / "execute-todo-loop" / "SKILL.md").is_file())
            self.assertFalse((home / ".agents" / "skills" / "agent-dev-workflow-init").exists())
            self.assertFalse((home / ".codex" / "AGENTS.md").exists())
            self.assertFalse((home / ".config" / "agent-project-workflow" / "config.toml").exists())

    def test_interactive_rule_selection_only_installs_one_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            output = io.StringIO()
            with (
                mock.patch("apw.cli.choose_one", side_effect=["rule", "codex"]),
                mock.patch("apw.cli.confirm", return_value=True),
                redirect_stdout(output),
            ):
                result = main(["--home", str(home), "install"])
            self.assertEqual(result, 0)
            self.assertTrue((home / ".codex" / "AGENTS.md").is_file())
            self.assertFalse((home / ".agents" / "skills" / "execute-todo-loop").exists())

    def test_non_interactive_install_requires_one_content_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "--home",
                        str(home),
                        "install",
                        "--non-interactive",
                        "--yes",
                    ]
                )
            self.assertEqual(result, 1)

    def test_interactive_skills_show_version_difference_and_only_replace_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            skill = home / ".agents" / "skills" / "execute-todo-loop"
            skill.mkdir(parents=True)
            skill.joinpath("SKILL.md").write_text("旧版本\n", encoding="utf-8")
            output = io.StringIO()
            with (
                mock.patch("apw.cli.choose_one", side_effect=["skills", "replace"]),
                mock.patch("apw.cli.choose_skills", return_value=["execute-todo-loop"]),
                mock.patch("apw.cli.choose_follow_up_rule", return_value=None),
                mock.patch("apw.cli.confirm", return_value=True),
                mock.patch("apw.cli.prompt", return_value="直接替换"),
                redirect_stdout(output),
            ):
                result = main(["--home", str(home), "install"])
            self.assertEqual(result, 0)
            self.assertIn("版本有差异", output.getvalue())
            self.assertNotEqual(skill.joinpath("SKILL.md").read_text(encoding="utf-8"), "旧版本\n")
            self.assertFalse((home / ".agents" / "skills" / "agent-dev-workflow-init").exists())

    def test_skills_install_continues_to_one_client_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            with (
                mock.patch("apw.cli.choose_one", return_value="skills"),
                mock.patch("apw.cli.choose_skills", return_value=["execute-todo-loop"]),
                mock.patch("apw.cli.choose_follow_up_rule", return_value="codex"),
                mock.patch("apw.cli.confirm", return_value=True),
            ):
                result = main(["--home", str(home), "install"])
            self.assertEqual(result, 0)
            self.assertTrue((home / ".agents" / "skills" / "execute-todo-loop" / "SKILL.md").is_file())
            self.assertTrue((home / ".codex" / "AGENTS.md").is_file())
            self.assertFalse((home / ".config" / "opencode" / "AGENTS.md").exists())


if __name__ == "__main__":
    unittest.main()
