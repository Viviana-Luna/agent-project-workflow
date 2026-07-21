"""仅由显式命令触发的 GitHub Release 更新。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .bundle import Bundle
from .constants import LATEST_MANIFEST_URL, RELEASE_MANIFEST_SCHEMA_VERSION
from .lifecycle import Change, LifecycleManager, OperationResult
from .managed import sha256_bytes
from .paths import AppPaths
from .state import atomic_write, load_state, save_state


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseAsset:
    url: str
    sha256: str


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    minimum_manager_version: str
    release_notes: str
    python_version: str
    uv_version: str
    assets: dict[str, ReleaseAsset]

    @classmethod
    def parse(cls, payload: bytes) -> "ReleaseManifest":
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError(f"发布清单不是有效 JSON：{exc}") from exc
        if not isinstance(data, dict) or data.get("schema_version") != RELEASE_MANIFEST_SCHEMA_VERSION:
            raise UpdateError(f"不支持的发布清单版本：{data.get('schema_version') if isinstance(data, dict) else None!r}")
        assets_data = data.get("assets")
        if not isinstance(assets_data, dict):
            raise UpdateError("发布清单缺少 assets")
        assets: dict[str, ReleaseAsset] = {}
        for name, value in assets_data.items():
            if not isinstance(value, dict) or not isinstance(value.get("url"), str) or not isinstance(value.get("sha256"), str):
                raise UpdateError(f"发布资产无效：{name}")
            assets[str(name)] = ReleaseAsset(value["url"], value["sha256"])
        runtime = data.get("runtime") or {}
        return cls(
            version=str(data.get("version", "")),
            minimum_manager_version=str(data.get("minimum_manager_version", "1.0.0")),
            release_notes=str(data.get("release_notes", "")),
            python_version=str(runtime.get("python", "")),
            uv_version=str(runtime.get("uv", "")),
            assets=assets,
        )


@dataclass(frozen=True)
class UpdateCheck:
    current_version: str
    latest_version: str
    available: bool
    manifest: ReleaseManifest


Fetcher = Callable[[str], bytes]
ConflictResolver = Callable[[list[Change]], tuple[str, bool]]
PlanCallback = Callable[[list[Change]], None]
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"apw/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_DOWNLOAD_BYTES:
                raise UpdateError(f"下载内容超过 {MAX_DOWNLOAD_BYTES} 字节限制：{url}")
            payload = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(payload) > MAX_DOWNLOAD_BYTES:
                raise UpdateError(f"下载内容超过 {MAX_DOWNLOAD_BYTES} 字节限制：{url}")
            return payload
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"下载失败：{url}：{exc}") from exc


def version_tuple(value: str) -> tuple[int, int, int]:
    normalized = value.removeprefix("v").split("-", 1)[0]
    parts = normalized.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise UpdateError(f"版本号必须是 major.minor.patch：{value!r}")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


class UpdateManager:
    def __init__(self, paths: AppPaths, fetcher: Fetcher = fetch_url) -> None:
        self.paths = paths
        self.fetcher = fetcher

    def check(self, manifest_url: str = LATEST_MANIFEST_URL) -> UpdateCheck:
        manifest = ReleaseManifest.parse(self.fetcher(manifest_url))
        current = load_state(self.paths.state_file, __version__).manager_version or __version__
        if version_tuple(current) < version_tuple(manifest.minimum_manager_version):
            raise UpdateError(
                f"当前管理器 {current} 低于更新所需最低版本 {manifest.minimum_manager_version}；请重新运行 Bootstrap"
            )
        return UpdateCheck(current, manifest.version, version_tuple(manifest.version) > version_tuple(current), manifest)

    def update(
        self,
        *,
        checked: UpdateCheck | None = None,
        manifest_url: str = LATEST_MANIFEST_URL,
        conflict_policy: str = "abort",
        confirmed_direct_replace: bool = False,
        dry_run: bool = False,
        allow_downgrade: bool = False,
        conflict_resolver: ConflictResolver | None = None,
        plan_callback: PlanCallback | None = None,
    ) -> tuple[UpdateCheck, OperationResult | None]:
        checked = checked or self.check(manifest_url)
        installed_state = load_state(self.paths.state_file, __version__)
        installed_python = installed_state.runtime.get("python_version")
        installed_uv = installed_state.runtime.get("uv")
        if installed_python and checked.manifest.python_version and installed_python != checked.manifest.python_version:
            raise UpdateError(
                f"目标版本需要私有 Python {checked.manifest.python_version}，当前为 {installed_python}；请重新运行 Bootstrap"
            )
        if installed_uv and checked.manifest.uv_version and installed_uv != checked.manifest.uv_version:
            raise UpdateError(
                f"目标版本需要私有 uv {checked.manifest.uv_version}，当前为 {installed_uv}；请重新运行 Bootstrap"
            )
        current_tuple = version_tuple(checked.current_version)
        latest_tuple = version_tuple(checked.latest_version)
        if latest_tuple < current_tuple and not allow_downgrade:
            raise UpdateError("默认禁止降级；必须显式允许并确认目标版本")
        if latest_tuple == current_tuple:
            return checked, None
        asset = checked.manifest.assets.get("apw.pyz")
        if asset is None:
            raise UpdateError("发布清单缺少 apw.pyz")
        if dry_run:
            return checked, OperationResult(dry_run=True, messages=[f"计划下载：{asset.url}"])
        payload = self.fetcher(asset.url)
        actual = sha256_bytes(payload)
        if actual != asset.sha256:
            raise UpdateError(f"apw.pyz SHA-256 不匹配：期望 {asset.sha256}，实际 {actual}")

        version_dir = self.paths.versions_dir / checked.latest_version
        created_version_dir = not version_dir.exists()
        if not created_version_dir:
            staged_pyz = version_dir / "apw.pyz"
            if not staged_pyz.is_file() or sha256_bytes(staged_pyz.read_bytes()) != asset.sha256:
                raise UpdateError(f"版本目录已存在但内容不一致：{version_dir}")
        else:
            temp_dir = Path(tempfile.mkdtemp(prefix=f".{checked.latest_version}.", dir=self._ensure_versions_dir()))
            try:
                atomic_write(temp_dir / "apw.pyz", payload, mode=0o755)
                os.replace(temp_dir, version_dir)
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        staged_pyz = version_dir / "apw.pyz"
        self._validate_staged(staged_pyz)

        state = load_state(self.paths.state_file, __version__)
        manager = LifecycleManager(self.paths, bundle=Bundle(archive=staged_pyz))
        manager.assert_safe_state(state)
        _, planned = manager.plan_install(state.selected_clients)
        if plan_callback is not None:
            try:
                plan_callback(planned)
            except Exception:
                if created_version_dir:
                    shutil.rmtree(version_dir, ignore_errors=True)
                raise
        conflicts = [change for change in planned if change.conflict]
        if conflicts and conflict_resolver is not None:
            conflict_policy, confirmed_direct_replace = conflict_resolver(planned)
        snapshot_paths = [Path(record.path) for record in state.installations.values()]
        snapshot_paths.extend(change.path for change in planned)
        excluded = {change.path.resolve() for change in conflicts} if conflict_policy == "replace" else set()
        previous_current = self._current_target()
        with tempfile.TemporaryDirectory(prefix="apw-update-rollback-") as temp:
            rollback_root = Path(temp)
            snapshots = self._snapshot([path for path in snapshot_paths if path.resolve() not in excluded], rollback_root)
            try:
                result = manager.install(
                    state.selected_clients,
                    conflict_policy=conflict_policy,
                    confirmed_direct_replace=confirmed_direct_replace,
                    configure=False,
                )
                findings = manager.doctor()
                if any(item.level == "error" for item in findings):
                    raise UpdateError("新版安装后诊断失败")
                self._switch_current(version_dir)
                updated = load_state(self.paths.state_file, __version__)
                updated.manager_version = checked.latest_version
                save_state(self.paths.state_file, updated)
                return checked, result
            except Exception:
                self._restore(snapshots)
                save_state(self.paths.state_file, state)
                self._restore_current(previous_current)
                shutil.rmtree(version_dir, ignore_errors=True)
                raise

    def _ensure_versions_dir(self) -> Path:
        self.paths.versions_dir.mkdir(parents=True, exist_ok=True)
        return self.paths.versions_dir

    def _validate_staged(self, pyz: Path) -> None:
        state = load_state(self.paths.state_file, __version__)
        runtime_python = state.runtime.get("python_executable")
        if runtime_python:
            executable = Path(runtime_python).expanduser().resolve(strict=False)
            runtime_root = self.paths.runtime_dir.resolve(strict=False)
            try:
                executable.relative_to(runtime_root)
            except ValueError as exc:
                raise UpdateError(f"私有 Python 路径超出运行时目录：{executable}") from exc
        else:
            executable = Path(sys.executable)
        result = subprocess.run(
            [str(executable), str(pyz), "--home", str(self.paths.home), "doctor", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode not in {0, 2}:
            raise UpdateError(f"新版管理器自检失败：{result.stdout}{result.stderr}".strip())

    def _switch_current(self, version_dir: Path) -> None:
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        temp = self.paths.data_dir / ".current.new"
        temp.unlink(missing_ok=True)
        temp.symlink_to(version_dir.relative_to(self.paths.data_dir), target_is_directory=True)
        os.replace(temp, self.paths.current_link)

    def _current_target(self) -> str | None:
        if not self.paths.current_link.is_symlink():
            return None
        return os.readlink(self.paths.current_link)

    def _restore_current(self, target: str | None) -> None:
        if target is None:
            self.paths.current_link.unlink(missing_ok=True)
            return
        temp = self.paths.data_dir / ".current.rollback"
        temp.unlink(missing_ok=True)
        temp.symlink_to(target, target_is_directory=True)
        os.replace(temp, self.paths.current_link)

    def _snapshot(self, paths: list[Path], root: Path) -> list[tuple[Path, Path | None]]:
        snapshots: list[tuple[Path, Path | None]] = []
        for index, path in enumerate(sorted(set(paths), key=str)):
            if not path.exists() and not path.is_symlink():
                snapshots.append((path, None))
                continue
            destination = root / str(index)
            if path.is_dir() and not path.is_symlink():
                shutil.copytree(path, destination, symlinks=True)
            elif path.is_symlink():
                destination.symlink_to(os.readlink(path))
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            snapshots.append((path, destination))
        return snapshots

    def _restore(self, snapshots: list[tuple[Path, Path | None]]) -> None:
        for target, snapshot in snapshots:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
            if snapshot is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if snapshot.is_dir() and not snapshot.is_symlink():
                shutil.copytree(snapshot, target, symlinks=True)
            elif snapshot.is_symlink():
                target.symlink_to(os.readlink(snapshot))
            else:
                shutil.copy2(snapshot, target)
