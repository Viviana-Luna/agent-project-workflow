from __future__ import annotations

import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apw.bundle import Bundle
from apw.lifecycle import LifecycleError, LifecycleManager
from apw.managed import MANAGED_END, MANAGED_START
from apw.paths import AppPaths


ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):
    def make_manager(self, root: Path, environ: dict[str, str] | None = None) -> tuple[LifecycleManager, Path]:
        home = root / "home"
        vault = root / "vault"
        home.mkdir()
        vault.mkdir()
        manager = LifecycleManager(AppPaths.from_home(home), Bundle(root=ROOT), environ=environ or {})
        return manager, vault

    def test_four_clients_install_and_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, vault = self.make_manager(Path(temp))
            result = manager.install(
                ["codex", "claude-code", "kimi-code", "opencode"],
                vault_root=vault,
            )
            self.assertFalse(result.conflicts)
            home = manager.paths.home
            self.assertTrue((home / ".codex" / "AGENTS.md").is_file())
            self.assertTrue((home / ".claude" / "CLAUDE.md").is_file())
            self.assertTrue((home / ".kimi-code" / "AGENTS.md").is_file())
            self.assertTrue((home / ".config" / "opencode" / "AGENTS.md").is_file())
            self.assertTrue((home / ".agents" / "skills" / "execute-todo-loop" / "SKILL.md").is_file())
            self.assertTrue((home / ".claude" / "skills" / "execute-todo-loop" / "SKILL.md").is_file())
            init_script = home / ".agents" / "skills" / "agent-dev-workflow-init" / "scripts" / "init_agent_workflow.py"
            self.assertTrue(init_script.stat().st_mode & 0o100)
            self.assertEqual(manager.paths.config_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(manager.paths.state_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(manager.doctor(), [])
            state = manager.state()
            self.assertEqual(
                state.selected_clients,
                ["claude-code", "codex", "kimi-code", "opencode"],
            )

    def test_managed_block_preserves_user_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, vault = self.make_manager(Path(temp))
            target = manager.paths.home / ".codex" / "AGENTS.md"
            target.parent.mkdir(parents=True)
            target.write_text("# 我的规则\n\n自定义内容\n", encoding="utf-8")
            with self.assertRaises(LifecycleError):
                manager.install(["codex"], vault_root=vault)
            manager.install(["codex"], vault_root=vault, conflict_policy="archive")
            installed = target.read_text(encoding="utf-8")
            self.assertIn(MANAGED_START, installed)
            self.assertNotIn("自定义内容", installed)

            installed = f"# 新的用户内容\n\n{installed}"
            target.write_text(installed, encoding="utf-8")
            manager.repair()
            self.assertIn("# 新的用户内容", target.read_text(encoding="utf-8"))

    def test_reversed_managed_markers_fail_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, _ = self.make_manager(Path(temp))
            target = manager.paths.home / ".codex" / "AGENTS.md"
            target.parent.mkdir(parents=True)
            target.write_text(f"{MANAGED_END}\n内容\n{MANAGED_START}\n", encoding="utf-8")
            _, changes = manager.plan_install(["codex"])
            rule = next(change for change in changes if change.key == "rule:codex")
            self.assertTrue(rule.conflict)
            self.assertIn("结束标记", rule.detail)

    def test_archive_contains_manifest_and_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, vault = self.make_manager(Path(temp))
            target = manager.paths.home / ".codex" / "AGENTS.md"
            target.parent.mkdir(parents=True)
            target.write_text("旧规则\n", encoding="utf-8")
            result = manager.install(["codex"], vault_root=vault, conflict_policy="archive")
            self.assertIsNotNone(result.archive)
            assert result.archive is not None
            with tarfile.open(result.archive, "r:gz") as archive:
                names = archive.getnames()
                self.assertIn("manifest.json", names)
                self.assertIn("home/.codex/AGENTS.md", names)
                manifest = json.load(archive.extractfile("manifest.json"))  # type: ignore[arg-type]
                self.assertEqual(len(manifest["targets"]), 1)

    def test_direct_replace_requires_confirmation_and_creates_no_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, vault = self.make_manager(Path(temp))
            target = manager.paths.home / ".codex" / "AGENTS.md"
            target.parent.mkdir(parents=True)
            target.write_text("旧规则\n", encoding="utf-8")
            with self.assertRaises(LifecycleError):
                manager.install(["codex"], vault_root=vault, conflict_policy="replace")
            manager.install(
                ["codex"],
                vault_root=vault,
                conflict_policy="replace",
                confirmed_direct_replace=True,
            )
            self.assertFalse(manager.paths.backups_dir.exists())
            self.assertIn(MANAGED_END, target.read_text(encoding="utf-8"))

    def test_legacy_codex_skills_are_included_in_single_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, vault = self.make_manager(Path(temp))
            legacy_root = manager.paths.home / ".codex" / "skills"
            for name in ("agent-dev-workflow-init", "execute-todo-loop"):
                target = legacy_root / name
                target.mkdir(parents=True)
                (target / "SKILL.md").write_text(f"旧版 {name}\n", encoding="utf-8")
            _, changes = manager.plan_install(["codex"])
            legacy = [change for change in changes if change.kind == "legacy-skill"]
            self.assertEqual(len(legacy), 2)
            result = manager.install(["codex"], vault_root=vault, conflict_policy="archive")
            self.assertIsNotNone(result.archive)
            self.assertFalse(legacy_root.joinpath("agent-dev-workflow-init").exists())
            self.assertFalse(legacy_root.joinpath("execute-todo-loop").exists())
            with tarfile.open(result.archive, "r:gz") as archive:  # type: ignore[arg-type]
                manifests = json.load(archive.extractfile("manifest.json"))  # type: ignore[arg-type]
                archived = {item["archive_path"] for item in manifests["targets"]}
                self.assertIn("home/.codex/skills/agent-dev-workflow-init", archived)
                self.assertIn("home/.codex/skills/execute-todo-loop", archived)

    def test_kimi_home_environment_is_respected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            custom = root / "custom-kimi"
            manager, vault = self.make_manager(root, {"KIMI_CODE_HOME": str(custom)})
            manager.install(["kimi-code"], vault_root=vault)
            self.assertTrue((custom / "AGENTS.md").is_file())

    def test_relative_kimi_home_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, _ = self.make_manager(Path(temp), {"KIMI_CODE_HOME": "relative-kimi"})
            with self.assertRaisesRegex(ValueError, "必须是绝对路径"):
                manager.plan_install(["kimi-code"])

    def test_client_removal_keeps_shared_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, vault = self.make_manager(Path(temp))
            manager.install(["codex", "opencode"], vault_root=vault)
            manager.set_clients(["opencode"])
            self.assertFalse((manager.paths.home / ".codex" / "AGENTS.md").exists())
            self.assertTrue((manager.paths.home / ".agents" / "skills" / "execute-todo-loop").is_dir())
            self.assertEqual(manager.state().selected_clients, ["opencode"])

    def test_repair_detects_drift_and_can_archive_then_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, vault = self.make_manager(Path(temp))
            manager.install(["codex"], vault_root=vault)
            skill = manager.paths.home / ".agents" / "skills" / "execute-todo-loop" / "SKILL.md"
            skill.write_text("用户修改\n", encoding="utf-8")
            self.assertTrue(any(item.code == "target-drift" for item in manager.doctor()))
            with self.assertRaises(LifecycleError):
                manager.repair()
            result = manager.repair(conflict_policy="archive")
            self.assertIsNotNone(result.archive)
            self.assertNotEqual(skill.read_text(encoding="utf-8"), "用户修改\n")
            self.assertEqual(manager.doctor(), [])

    def test_uninstall_preserves_config_and_clears_owned_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, vault = self.make_manager(Path(temp))
            manager.install(["codex", "claude-code"], vault_root=vault)
            manager.paths.cache_dir.mkdir(parents=True)
            manager.paths.cache_dir.joinpath("cache.bin").write_bytes(b"cache")
            manager.uninstall()
            self.assertTrue(manager.paths.config_file.is_file())
            self.assertFalse((manager.paths.home / ".codex" / "AGENTS.md").exists())
            self.assertFalse((manager.paths.home / ".claude" / "CLAUDE.md").exists())
            self.assertFalse((manager.paths.home / ".agents" / "skills" / "execute-todo-loop").exists())
            self.assertFalse((manager.paths.home / ".claude" / "skills" / "execute-todo-loop").exists())
            self.assertFalse(manager.paths.data_dir.exists())
            self.assertFalse(manager.paths.cache_dir.exists())
            self.assertFalse(manager.paths.state_file.exists())

    def test_uninstall_preserves_unowned_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, vault = self.make_manager(Path(temp))
            manager.install(["codex"], vault_root=vault)
            manager.paths.bin_dir.mkdir(parents=True)
            manager.paths.launcher.write_text("#!/bin/sh\necho 其他程序\n", encoding="utf-8")
            manager.paths.long_launcher.write_text("其他程序\n", encoding="utf-8")
            manager.uninstall()
            self.assertTrue(manager.paths.launcher.is_file())
            self.assertTrue(manager.paths.long_launcher.is_file())

    def test_malformed_state_is_reported_by_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, _ = self.make_manager(Path(temp))
            manager.paths.state_file.parent.mkdir(parents=True)
            manager.paths.state_file.write_text(
                '{"schema_version": 1, "installations": {"broken": {}}}',
                encoding="utf-8",
            )
            findings = manager.doctor()
            self.assertEqual(findings[0].code, "state-invalid")

    def test_tampered_state_cannot_delete_outside_adapter_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager, vault = self.make_manager(root)
            manager.install(["codex"], vault_root=vault)
            outside = root / "outside.txt"
            outside.write_text("不能删除\n", encoding="utf-8")
            data = json.loads(manager.paths.state_file.read_text(encoding="utf-8"))
            data["installations"]["rule:codex"]["path"] = str(outside)
            manager.paths.state_file.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(LifecycleError, "不安全目标"):
                manager.uninstall(remove_manager=False)
            self.assertEqual(outside.read_text(encoding="utf-8"), "不能删除\n")
            findings = manager.doctor()
            self.assertTrue(any(item.code == "unsafe-target" for item in findings))

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, vault = self.make_manager(Path(temp))
            manager.install(["codex"], vault_root=vault, dry_run=True)
            self.assertFalse((manager.paths.home / ".codex").exists())
            self.assertFalse(manager.paths.state_file.exists())
            self.assertFalse(manager.paths.config_file.exists())

    def test_skill_directory_switch_restores_original_on_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager, _ = self.make_manager(Path(temp))
            target = manager.paths.home / ".agents" / "skills" / "execute-todo-loop"
            target.mkdir(parents=True)
            original = target / "SKILL.md"
            original.write_text("原始内容\n", encoding="utf-8")
            real_replace = os.replace
            calls = 0

            def fail_staged_switch(source: str | Path, destination: str | Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("模拟切换失败")
                real_replace(source, destination)

            with mock.patch("apw.lifecycle.os.replace", side_effect=fail_staged_switch):
                with self.assertRaisesRegex(OSError, "模拟切换失败"):
                    manager._replace_tree(target, "skills/execute-todo-loop")
            self.assertEqual(original.read_text(encoding="utf-8"), "原始内容\n")


if __name__ == "__main__":
    unittest.main()
