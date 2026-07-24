from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "agent-dev-workflow-init" / "scripts" / "init_agent_workflow.py"


class InitWorkflowTests(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def load_script_module(self):
        spec = importlib.util.spec_from_file_location("init_agent_workflow_under_test", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_selected_path_is_persisted_and_existing_readme_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "sample-repo"
            vault = root / "vault"
            repo.mkdir()
            vault.mkdir()
            readme = repo / "README.md"
            readme.write_text("# 已有说明\n", encoding="utf-8")
            config = root / "config.toml"
            config.write_text(
                f'version = 1\nvault_root = {json.dumps(str(vault))}\nprojects_root = "Myproject"\n\n[projects]\n',
                encoding="utf-8",
            )

            result = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--project-path",
                "Myproject/sample-repo",
            )
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
            data = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(data["projects"][str(repo.resolve())], "Myproject/sample-repo")

    def test_explicit_mapping_matches_normalized_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            vault = root / "vault"
            repo.mkdir()
            vault.mkdir()
            config = root / "config.toml"
            config.write_text(
                f'version = 1\nvault_root = {json.dumps(str(vault))}\nprojects_root = "Myproject"\n\n'
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

    def test_unmapped_project_requires_user_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            vault = root / "vault"
            repo.mkdir()
            vault.mkdir()
            config = root / "config.toml"
            config.write_text(
                f'version = 1\nvault_root = {json.dumps(str(vault))}\n\n[projects]\n',
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
            self.assertIn("尚未选择 Obsidian 文档位置", result.stderr)

    def test_first_project_initialization_creates_private_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            vault = root / "vault"
            config = root / "config" / "config.toml"
            repo.mkdir()
            vault.mkdir()

            result = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--vault-root",
                str(vault),
                "--project-path",
                "Rsit/product/repo",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(data["vault_root"], str(vault.resolve()))
            self.assertEqual(data["projects"][str(repo.resolve())], "Rsit/product/repo")
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertTrue((vault / "Rsit" / "product" / "repo" / "TODO.md").is_file())

    def test_existing_legacy_workspace_requires_previewed_relocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            vault = root / "vault"
            source = vault / "Myproject" / "repo"
            target = vault / "Rsit" / "product" / "repo"
            config = root / "config.toml"
            repo.mkdir()
            source.mkdir(parents=True)
            source.joinpath("private-note.md").write_text("保留内容\n", encoding="utf-8")
            config.write_text(
                f'version = 1\nvault_root = "{vault}"\nprojects_root = "Myproject"\n\n[projects]\n',
                encoding="utf-8",
            )

            rejected = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--project-path",
                "Rsit/product/repo",
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("--relocate --dry-run", rejected.stderr)
            self.assertTrue(source.is_dir())
            self.assertFalse(target.exists())

            preview = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--project-path",
                "Rsit/product/repo",
                "--relocate",
                "--dry-run",
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("计划移动工作区", preview.stdout)
            self.assertTrue(source.is_dir())
            self.assertFalse(target.exists())

            moved = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--project-path",
                "Rsit/product/repo",
                "--relocate",
            )
            self.assertEqual(moved.returncode, 0, moved.stderr)
            self.assertFalse(source.exists())
            self.assertEqual(target.joinpath("private-note.md").read_text(encoding="utf-8"), "保留内容\n")
            data = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(data["projects"][str(repo.resolve())], "Rsit/product/repo")

    def test_existing_target_requires_explicit_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            vault = root / "vault"
            target = vault / "Rsit" / "repo"
            config = root / "config.toml"
            repo.mkdir()
            target.mkdir(parents=True)
            target.joinpath("TODO.md").write_text("# 已有 TODO\n", encoding="utf-8")
            config.write_text(
                f'version = 1\nvault_root = "{vault}"\n\n[projects]\n',
                encoding="utf-8",
            )

            rejected = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--project-path",
                "Rsit/repo",
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("--adopt-existing --dry-run", rejected.stderr)

            adopted = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--project-path",
                "Rsit/repo",
                "--adopt-existing",
            )
            self.assertEqual(adopted.returncode, 0, adopted.stderr)
            self.assertEqual(target.joinpath("TODO.md").read_text(encoding="utf-8"), "# 已有 TODO\n")
            data = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(data["projects"][str(repo.resolve())], "Rsit/repo")

    def test_mapping_update_preserves_other_projects_and_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            other_repo = root / "other"
            vault = root / "vault"
            config = root / "config.toml"
            repo.mkdir()
            other_repo.mkdir()
            vault.mkdir()
            config.write_text(
                f'# 保留说明\nversion = 1\nvault_root = "{vault}"\n\n'
                f'[projects]\n"{other_repo}" = "Myproject/other"\n\n'
                '[preferences]\nmode = "manual"\n',
                encoding="utf-8",
            )

            result = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--project-path",
                "Rsit/repo",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            content = config.read_text(encoding="utf-8")
            data = tomllib.loads(content)
            self.assertIn("# 保留说明", content)
            self.assertEqual(data["projects"][str(other_repo)], "Myproject/other")
            self.assertEqual(data["projects"][str(repo.resolve())], "Rsit/repo")
            self.assertEqual(data["preferences"]["mode"], "manual")

    def test_symlink_cannot_escape_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            vault = root / "vault"
            outside = root / "outside"
            config = root / "config.toml"
            repo.mkdir()
            vault.mkdir()
            outside.mkdir()
            vault.joinpath("escape").symlink_to(outside, target_is_directory=True)
            config.write_text(
                f'version = 1\nvault_root = "{vault}"\n\n[projects]\n',
                encoding="utf-8",
            )

            result = self.run_script(
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--project-path",
                "escape/repo",
                "--print-workflow-root",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("必须位于 Obsidian Vault 内", result.stderr)

    def test_relocation_rolls_back_when_config_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            vault = root / "vault"
            source = vault / "Myproject" / "repo"
            target = vault / "Rsit" / "repo"
            config = root / "config.toml"
            repo.mkdir()
            source.mkdir(parents=True)
            source.joinpath("note.md").write_text("不能丢失\n", encoding="utf-8")
            config.write_text(
                f'version = 1\nvault_root = "{vault}"\nprojects_root = "Myproject"\n\n[projects]\n',
                encoding="utf-8",
            )
            module = self.load_script_module()
            argv = [
                str(SCRIPT),
                "--repo-root",
                str(repo),
                "--config",
                str(config),
                "--project-path",
                "Rsit/repo",
                "--relocate",
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(module, "save_project_mapping", side_effect=OSError("模拟配置写入失败")),
                self.assertRaisesRegex(OSError, "模拟配置写入失败"),
            ):
                module.main()
            self.assertTrue(source.joinpath("note.md").is_file())
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
