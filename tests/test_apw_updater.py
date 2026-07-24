from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from apw import __version__
from apw.bundle import Bundle
from apw.cli import main
from apw.lifecycle import Finding, LifecycleManager
from apw.paths import AppPaths
from apw.state import save_state
from apw.updater import ReleaseManifest, UpdateError, UpdateManager, version_tuple
from scripts.build_release import build_zipapp


ROOT = Path(__file__).resolve().parents[1]


def next_version() -> str:
    """比当前版本高一个补丁号；模拟“有更新”时避免硬编码版本在发布后过期。"""
    major, minor, patch = (int(part) for part in __version__.split("."))
    return f"{major}.{minor}.{patch + 1}"


def make_manifest(version: str, payload: bytes, url: str = "memory://apw.pyz") -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "version": version,
                "minimum_manager_version": "1.0.0",
                "release_notes": "测试更新",
                "runtime": {"python": "3.12.13", "uv": "0.11.16"},
                "assets": {
                    "apw.pyz": {
                        "url": url,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                },
            }
        ).encode("utf-8")
        + b"\n"
    )


class UpdaterTests(unittest.TestCase):
    def test_bootstrap_keeps_uv_python_and_cache_private(self) -> None:
        installer = (ROOT / "scripts" / "install.sh.template").read_text(encoding="utf-8")
        self.assertIn("--no-bin", installer)
        self.assertIn('UV_CACHE_DIR="$APW_CACHE_DIR/uv"', installer)
        self.assertIn("UV_NO_CONFIG=1", installer)
        self.assertIn("# agent-project-workflow:launcher", installer)
        self.assertIn("启动器路径已被其他程序占用", installer)

    def test_windows_bootstrap_keeps_uv_python_and_cache_private(self) -> None:
        installer = (ROOT / "scripts" / "install.ps1.template").read_text(encoding="utf-8")
        self.assertIn("--no-bin", installer)
        self.assertIn("UV_CACHE_DIR", installer)
        self.assertIn("UV_NO_CONFIG", installer)
        self.assertIn("agent-project-workflow:launcher", installer)
        self.assertIn("启动器路径已被其他程序占用", installer)
        self.assertIn("New-Item -ItemType Junction", installer)
        self.assertIn("chcp 65001", installer)
        self.assertNotIn("Remove-Item $CurrentLink", installer)

    def test_clear_pointer_refuses_real_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_home(Path(temp) / "home")
            real_dir = paths.data_dir / "real"
            real_dir.mkdir(parents=True)
            updater = UpdateManager(paths)
            with self.assertRaises(OSError):
                updater._clear_pointer(real_dir)

    def test_manifest_and_semantic_version_validation(self) -> None:
        payload = b"zipapp"
        manifest = ReleaseManifest.parse(make_manifest("1.2.3", payload))
        self.assertEqual(manifest.version, "1.2.3")
        self.assertLess(version_tuple("1.2.3"), version_tuple("2.0.0"))
        with self.assertRaises(UpdateError):
            version_tuple("1.2")

    def test_zipapp_bundle_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "unsafe.pyz"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("skills/demo/SKILL.md", "正常")
                output.writestr("skills/demo/../../escape.txt", "越界")
            with self.assertRaisesRegex(ValueError, "路径不安全"):
                Bundle(archive=archive).names("skills")

    def test_check_is_the_only_network_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            vault = root / "vault"
            home.mkdir()
            vault.mkdir()
            paths = AppPaths.from_home(home)
            manager = LifecycleManager(paths, Bundle(root=ROOT), environ={})
            manager.install(["codex"])
            calls: list[str] = []

            def fetcher(url: str) -> bytes:
                calls.append(url)
                return make_manifest(__version__, b"unused")

            manager.status()
            manager.doctor()
            self.assertEqual(calls, [])
            checked = UpdateManager(paths, fetcher).check("memory://manifest")
            self.assertFalse(checked.available)
            self.assertEqual(calls, ["memory://manifest"])

    def test_hash_mismatch_stops_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            vault = root / "vault"
            home.mkdir()
            vault.mkdir()
            paths = AppPaths.from_home(home)
            LifecycleManager(paths, Bundle(root=ROOT), environ={}).install(["codex"])
            manifest = make_manifest(next_version(), b"expected")

            def fetcher(url: str) -> bytes:
                return manifest if url == "memory://manifest" else b"wrong"

            with self.assertRaisesRegex(UpdateError, "SHA-256"):
                UpdateManager(paths, fetcher).update(manifest_url="memory://manifest")

    def test_runtime_change_requires_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            vault = root / "vault"
            home.mkdir()
            vault.mkdir()
            paths = AppPaths.from_home(home)
            manager = LifecycleManager(
                paths,
                Bundle(root=ROOT),
                environ={
                    "APW_RUNTIME_PYTHON": str(paths.runtime_dir / "python" / "python3.12"),
                    "APW_RUNTIME_PYTHON_VERSION": "3.12.12",
                    "APW_RUNTIME_UV": "0.11.16",
                },
            )
            manager.install(["codex"])
            manifest = make_manifest(next_version(), b"unused")
            updater = UpdateManager(paths, lambda _url: manifest)
            with self.assertRaisesRegex(UpdateError, "重新运行 Bootstrap"):
                updater.update(manifest_url="memory://manifest")

    def test_invalid_manifest_and_download_failure_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_home(Path(temp) / "home")
            with self.assertRaisesRegex(UpdateError, "有效 JSON"):
                UpdateManager(paths, lambda _url: b"not-json").check("memory://manifest")

            def failed(_url: str) -> bytes:
                raise UpdateError("模拟下载中断")

            with self.assertRaisesRegex(UpdateError, "模拟下载中断"):
                UpdateManager(paths, failed).check("memory://manifest")

    def test_update_stages_zipapp_and_switches_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            vault = root / "vault"
            build = root / "build"
            home.mkdir()
            vault.mkdir()
            build.mkdir()
            paths = AppPaths.from_home(home)
            LifecycleManager(paths, Bundle(root=ROOT), environ={}).install(["codex"])
            pyz = build_zipapp(build)
            payload = pyz.read_bytes()
            manifest = make_manifest(next_version(), payload)

            def fetcher(url: str) -> bytes:
                if url == "memory://manifest":
                    return manifest
                if url == "memory://apw.pyz":
                    return payload
                raise AssertionError(url)

            planned: list[list[object]] = []
            checked, result = UpdateManager(paths, fetcher).update(
                manifest_url="memory://manifest",
                plan_callback=lambda changes: planned.append(list(changes)),
            )
            self.assertTrue(checked.available)
            self.assertIsNotNone(result)
            self.assertTrue(planned)
            self.assertEqual(LifecycleManager(paths, Bundle(root=ROOT), environ={}).state().manager_version, next_version())
            self.assertTrue((paths.current_link / "apw.pyz").is_file())

    def test_failed_post_install_doctor_restores_owned_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            vault = root / "vault"
            build = root / "build"
            home.mkdir()
            vault.mkdir()
            build.mkdir()
            paths = AppPaths.from_home(home)
            manager = LifecycleManager(paths, Bundle(root=ROOT), environ={})
            manager.install(["codex"])
            rule = home / ".codex" / "AGENTS.md"
            original_rule = rule.read_bytes()
            original_state = paths.state_file.read_bytes()
            payload = build_zipapp(build).read_bytes()
            manifest = make_manifest(next_version(), payload)

            def fetcher(url: str) -> bytes:
                return manifest if url == "memory://manifest" else payload

            with (
                mock.patch("apw.state.utc_now", return_value="2099-01-01T00:00:00+00:00"),
                mock.patch(
                    "apw.updater.LifecycleManager.doctor",
                    return_value=[Finding("error", "simulated", "模拟失败")],
                ),
            ):
                with self.assertRaisesRegex(UpdateError, "诊断失败"):
                    UpdateManager(paths, fetcher).update(manifest_url="memory://manifest")
            self.assertEqual(rule.read_bytes(), original_rule)
            self.assertEqual(paths.state_file.read_bytes(), original_state)
            self.assertFalse(paths.current_link.exists())
            self.assertFalse((paths.versions_dir / next_version()).exists())

    def test_cli_downgrade_requires_target_and_second_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            vault = root / "vault"
            home.mkdir()
            vault.mkdir()
            paths = AppPaths.from_home(home)
            manager = LifecycleManager(paths, Bundle(root=ROOT), environ={})
            manager.install(["codex"])
            state = manager.state()
            state.manager_version = "2.0.0"
            save_state(paths.state_file, state)
            manifest_path = root / "release-manifest.json"
            manifest_path.write_bytes(make_manifest("1.0.0", b"unused"))
            common = [
                "--home",
                str(home),
                "update",
                "--manifest-url",
                manifest_path.as_uri(),
                "--non-interactive",
                "--allow-downgrade",
            ]
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(main(common), 1)
                self.assertEqual(main(common + ["--version", "1.0.0"]), 1)
            self.assertIn("--version", output.getvalue())
            self.assertIn("--confirm-downgrade", output.getvalue())


if __name__ == "__main__":
    unittest.main()
