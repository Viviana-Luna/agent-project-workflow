"""客户端规则与 Skill 的安装、修复、移除和诊断生命周期。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import __version__
from .adapters import Adapter, load_adapters
from .archive import create_archive
from .bundle import Bundle
from .constants import LAUNCHER_MARKER
from .managed import (
    ManagedBlockError,
    block_content,
    merge_block,
    remove_block,
    render_block,
    sha256_bytes,
    sha256_path,
    unified_diff,
)
from .paths import AppPaths
from .state import InstallationRecord, InstallState, atomic_write, load_state, save_state


class LifecycleError(RuntimeError):
    pass


@dataclass
class Change:
    key: str
    path: Path
    kind: str
    action: str
    clients: list[str]
    desired_digest: str = ""
    desired_text: str | None = None
    bundle_prefix: str | None = None
    conflict: bool = False
    detail: str = ""


@dataclass
class OperationResult:
    changes: list[Change] = field(default_factory=list)
    archive: Path | None = None
    messages: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def conflicts(self) -> list[Change]:
        return [change for change in self.changes if change.conflict]

    @property
    def changed(self) -> list[Change]:
        return [change for change in self.changes if change.action not in {"unchanged", "retain"}]


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str
    path: str | None = None


class LifecycleManager:
    def __init__(
        self,
        paths: AppPaths,
        bundle: Bundle | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        self.paths = paths
        self.bundle = bundle or Bundle.discover()
        self.environ = dict(os.environ if environ is None else environ)
        self.adapters = load_adapters(self.bundle)

    def state(self) -> InstallState:
        return load_state(self.paths.state_file, __version__)

    def assert_safe_state(self, state: InstallState | None = None) -> InstallState:
        current = state or self.state()
        problems = [
            message
            for record in current.installations.values()
            if (message := self._unsafe_record_message(record)) is not None
        ]
        if problems:
            raise LifecycleError("安装状态包含不安全目标：" + "；".join(problems))
        return current

    def available_clients(self) -> list[Adapter]:
        return list(self.adapters.values())

    def validate_clients(self, client_ids: Iterable[str]) -> list[str]:
        normalized = list(dict.fromkeys(client_ids))
        unknown = sorted(set(normalized) - self.adapters.keys())
        if unknown:
            raise LifecycleError(f"不支持的客户端：{', '.join(unknown)}")
        if not normalized:
            raise LifecycleError("至少选择一个客户端")
        return normalized

    def plan_install(self, client_ids: Iterable[str]) -> tuple[InstallState, list[Change]]:
        selected = self.validate_clients(client_ids)
        state = self.assert_safe_state()
        changes: list[Change] = []
        for client_id in selected:
            adapter = self.adapters[client_id]
            changes.append(self._plan_rule(adapter, state))

        skill_clients: dict[Path, list[str]] = {}
        for client_id in selected:
            target = self.adapters[client_id].skills_path(self.paths.home)
            skill_clients.setdefault(target, []).append(client_id)
        for target, clients in sorted(skill_clients.items(), key=lambda item: str(item[0])):
            changes.extend(self._plan_skills(target, clients, state))
        changes.extend(self._plan_legacy_duplicates(selected, set(skill_clients)))
        return state, changes

    def install(
        self,
        client_ids: Iterable[str],
        *,
        conflict_policy: str = "abort",
        confirmed_direct_replace: bool = False,
        dry_run: bool = False,
        vault_root: Path | None = None,
        projects_root: str = "Myproject",
        configure: bool = True,
    ) -> OperationResult:
        selected = self.validate_clients(client_ids)
        state, changes = self.plan_install(selected)
        result = OperationResult(changes=changes, dry_run=dry_run)
        self._resolve_conflicts(result, conflict_policy, confirmed_direct_replace, dry_run)
        if dry_run:
            return result
        if configure:
            self._ensure_config(vault_root, projects_root)
        for change in changes:
            self._apply_change(change)
            if change.kind == "legacy-skill":
                continue
            state.installations[change.key] = InstallationRecord(
                key=change.key,
                path=str(change.path),
                kind=change.kind,
                digest=change.desired_digest,
                clients=sorted(change.clients),
            )
        state.selected_clients = sorted(set(state.selected_clients) | set(selected))
        state.manager_version = __version__
        if self.environ.get("APW_RUNTIME_PYTHON"):
            state.runtime["python_executable"] = self.environ["APW_RUNTIME_PYTHON"]
        if self.environ.get("APW_RUNTIME_PYTHON_VERSION"):
            state.runtime["python_version"] = self.environ["APW_RUNTIME_PYTHON_VERSION"]
        if self.environ.get("APW_RUNTIME_UV"):
            state.runtime["uv"] = self.environ["APW_RUNTIME_UV"]
        save_state(self.paths.state_file, state)
        return result

    def set_clients(
        self,
        client_ids: Iterable[str],
        *,
        conflict_policy: str = "abort",
        confirmed_direct_replace: bool = False,
        dry_run: bool = False,
    ) -> OperationResult:
        desired = self.validate_clients(client_ids)
        state, install_changes = self.plan_install(desired)
        removing = sorted(set(state.selected_clients) - set(desired))
        removal_changes = self._plan_removals(removing, set(desired), state)
        result = OperationResult(changes=install_changes + removal_changes, dry_run=dry_run)
        self._resolve_conflicts(result, conflict_policy, confirmed_direct_replace, dry_run)
        if dry_run:
            return result
        for change in install_changes:
            self._apply_change(change)
            if change.kind == "legacy-skill":
                continue
            state.installations[change.key] = InstallationRecord(
                key=change.key,
                path=str(change.path),
                kind=change.kind,
                digest=change.desired_digest,
                clients=sorted(change.clients),
            )
        for change in removal_changes:
            self._apply_change(change)
            state.installations.pop(change.key, None)
        state.selected_clients = sorted(desired)
        state.manager_version = __version__
        save_state(self.paths.state_file, state)
        return result

    def repair(
        self,
        *,
        conflict_policy: str = "abort",
        confirmed_direct_replace: bool = False,
        dry_run: bool = False,
    ) -> OperationResult:
        state = self.assert_safe_state()
        if not state.selected_clients:
            raise LifecycleError("尚未记录已安装客户端，无法修复")
        return self.install(
            state.selected_clients,
            conflict_policy=conflict_policy,
            confirmed_direct_replace=confirmed_direct_replace,
            dry_run=dry_run,
            configure=False,
        )

    def uninstall(
        self,
        *,
        conflict_policy: str = "abort",
        confirmed_direct_replace: bool = False,
        dry_run: bool = False,
        remove_manager: bool = True,
    ) -> OperationResult:
        state = self.assert_safe_state()
        changes = self._plan_removals(state.selected_clients, set(), state)
        result = OperationResult(changes=changes, dry_run=dry_run)
        self._resolve_conflicts(result, conflict_policy, confirmed_direct_replace, dry_run)
        if dry_run:
            return result
        for change in changes:
            self._apply_change(change)
        if remove_manager:
            self._remove_owned_launchers()
            if self.paths.data_dir.exists():
                shutil.rmtree(self.paths.data_dir)
            if self.paths.cache_dir.exists():
                shutil.rmtree(self.paths.cache_dir)
            self.paths.state_file.unlink(missing_ok=True)
        else:
            state.selected_clients = []
            state.installations = {}
            save_state(self.paths.state_file, state)
        return result

    def doctor(self) -> list[Finding]:
        findings: list[Finding] = []
        try:
            state = self.state()
        except ValueError as exc:
            return [Finding("error", "state-invalid", str(exc), str(self.paths.state_file))]
        if not self.paths.config_file.is_file() and not self.paths.legacy_config_file.is_file():
            findings.append(Finding("error", "config-missing", "没有找到工作流配置", str(self.paths.config_file)))
        for client_id in state.selected_clients:
            if client_id not in self.adapters:
                findings.append(Finding("error", "adapter-missing", f"缺少客户端适配器：{client_id}"))
        for record in state.installations.values():
            path = Path(record.path)
            unsafe = self._unsafe_record_message(record)
            if unsafe:
                findings.append(Finding("error", "unsafe-target", unsafe, str(path)))
                continue
            if not path.exists() and not path.is_symlink():
                findings.append(Finding("error", "target-missing", "托管目标不存在", str(path)))
                continue
            current = self._record_digest(record, path)
            if current != record.digest:
                findings.append(Finding("warning", "target-drift", "托管目标已被修改", str(path)))
        duplicate_names = self._legacy_duplicate_skills(state)
        for path in duplicate_names:
            findings.append(Finding("warning", "duplicate-skill", "发现旧版同名 Skill，可能导致发现冲突", str(path)))
        return findings

    def status(self) -> dict[str, object]:
        state = self.state()
        findings = self.doctor()
        return {
            "manager_version": state.manager_version or __version__,
            "selected_clients": state.selected_clients,
            "config": str(self.paths.config_file if self.paths.config_file.exists() else self.paths.legacy_config_file),
            "state": str(self.paths.state_file),
            "errors": sum(item.level == "error" for item in findings),
            "warnings": sum(item.level == "warning" for item in findings),
            "findings": [item.__dict__ for item in findings],
        }

    def format_changes(self, changes: Iterable[Change]) -> str:
        labels = {
            "create": "创建",
            "update": "更新",
            "replace": "替换",
            "remove": "移除",
            "unchanged": "未变化",
            "retain": "保留",
        }
        lines: list[str] = []
        for change in changes:
            conflict = " [冲突]" if change.conflict else ""
            lines.append(f"{labels.get(change.action, change.action)}：{change.path}{conflict}")
            if change.detail:
                lines.append(change.detail.rstrip())
        return "\n".join(lines)

    def _plan_rule(self, adapter: Adapter, state: InstallState) -> Change:
        path = adapter.rule_path(self.paths.home, self.environ)
        template = self.bundle.read_text(adapter.rule_template).strip()
        rendered = render_block(template)
        desired_digest = sha256_bytes(template.encode("utf-8"))
        record = state.installations.get(f"rule:{adapter.id}")
        if not path.exists():
            return Change(
                key=f"rule:{adapter.id}",
                path=path,
                kind="managed-rule",
                action="create",
                clients=[adapter.id],
                desired_digest=desired_digest,
                desired_text=f"{rendered}\n",
            )
        try:
            existing = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return Change(
                key=f"rule:{adapter.id}",
                path=path,
                kind="managed-rule",
                action="replace",
                clients=[adapter.id],
                desired_digest=desired_digest,
                desired_text=f"{rendered}\n",
                conflict=True,
                detail=f"无法读取现有规则：{exc}",
            )
        try:
            current_block = block_content(existing)
        except ManagedBlockError as exc:
            return Change(
                key=f"rule:{adapter.id}",
                path=path,
                kind="managed-rule",
                action="replace",
                clients=[adapter.id],
                desired_digest=desired_digest,
                desired_text=f"{rendered}\n",
                conflict=True,
                detail=str(exc),
            )
        if current_block is None:
            desired_text = f"{rendered}\n"
            return Change(
                key=f"rule:{adapter.id}",
                path=path,
                kind="managed-rule",
                action="replace",
                clients=[adapter.id],
                desired_digest=desired_digest,
                desired_text=desired_text,
                conflict=True,
                detail=unified_diff(existing, desired_text, path),
            )
        current_digest = sha256_bytes(current_block.encode("utf-8"))
        desired_text = merge_block(existing, template)
        if current_digest == desired_digest:
            action = "unchanged"
        else:
            action = "update"
        drift = bool(record and current_digest != record.digest)
        unknown = record is None and current_digest != desired_digest
        return Change(
            key=f"rule:{adapter.id}",
            path=path,
            kind="managed-rule",
            action=action,
            clients=[adapter.id],
            desired_digest=desired_digest,
            desired_text=desired_text,
            conflict=drift or unknown,
            detail=unified_diff(existing, desired_text, path) if action != "unchanged" else "",
        )

    def _plan_skills(self, target_root: Path, clients: list[str], state: InstallState) -> list[Change]:
        changes: list[Change] = []
        for skill_name in self._skill_names():
            prefix = f"skills/{skill_name}"
            path = target_root / skill_name
            key = f"skill:{path}"
            desired = self._bundle_tree_digest(prefix)
            record = state.installations.get(key)
            if not path.exists():
                action = "create"
                conflict = False
                detail = ""
            else:
                current = sha256_path(path)
                if current == desired:
                    action = "unchanged"
                    conflict = False
                    detail = ""
                else:
                    action = "replace"
                    conflict = record is None or current != record.digest
                    detail = self._directory_diff(path, prefix)
            changes.append(
                Change(
                    key=key,
                    path=path,
                    kind="skill",
                    action=action,
                    clients=sorted(clients),
                    desired_digest=desired,
                    bundle_prefix=prefix,
                    conflict=conflict,
                    detail=detail,
                )
            )
        return changes

    def _plan_legacy_duplicates(self, selected: list[str], managed_roots: set[Path]) -> list[Change]:
        kimi_home = self.adapters["kimi-code"].rule_path(self.paths.home, self.environ).parent
        roots: dict[str, tuple[Path, ...]] = {
            "codex": (self.paths.home / ".codex" / "skills",),
            "kimi-code": (kimi_home / "skills",),
            "opencode": (self.paths.home / ".config" / "opencode" / "skills",),
            "claude-code": (),
        }
        changes: list[Change] = []
        seen: set[Path] = set()
        for client_id in selected:
            for root in roots.get(client_id, ()):
                if root in managed_roots:
                    continue
                for skill_name in self._skill_names():
                    path = root / skill_name
                    absolute = path.absolute()
                    if absolute in seen or not (path.exists() or path.is_symlink()):
                        continue
                    seen.add(absolute)
                    changes.append(
                        Change(
                            key=f"legacy:{absolute}",
                            path=path,
                            kind="legacy-skill",
                            action="remove",
                            clients=[client_id],
                            conflict=True,
                            detail="发现非托管的同名旧 Skill；移除前必须归档或明确确认直接替换。",
                        )
                    )
        return changes

    def _plan_removals(
        self,
        removing: Iterable[str],
        remaining: set[str],
        state: InstallState,
    ) -> list[Change]:
        changes: list[Change] = []
        removing_set = set(removing)
        for client_id in sorted(removing_set):
            record = state.installations.get(f"rule:{client_id}")
            if not record:
                continue
            path = Path(record.path)
            if not path.exists():
                changes.append(Change(record.key, path, record.kind, "remove", [client_id]))
                continue
            try:
                text = path.read_text(encoding="utf-8")
                current_block = block_content(text)
            except (OSError, UnicodeDecodeError, ManagedBlockError) as exc:
                changes.append(
                    Change(record.key, path, record.kind, "remove", [client_id], conflict=True, detail=str(exc))
                )
                continue
            digest = sha256_bytes((current_block or "").encode("utf-8"))
            desired_text = remove_block(text) if current_block is not None else ""
            changes.append(
                Change(
                    record.key,
                    path,
                    record.kind,
                    "remove",
                    [client_id],
                    desired_text=desired_text,
                    conflict=digest != record.digest,
                    detail=unified_diff(text, desired_text, path),
                )
            )

        remaining_skill_roots = {
            self.adapters[client].skills_path(self.paths.home) for client in remaining if client in self.adapters
        }
        for key, record in sorted(state.installations.items()):
            if record.kind != "skill" or not removing_set.intersection(record.clients):
                continue
            path = Path(record.path)
            if any(path.parent == root for root in remaining_skill_roots):
                continue
            current = sha256_path(path) if path.exists() else ""
            changes.append(
                Change(
                    key=key,
                    path=path,
                    kind="skill",
                    action="remove",
                    clients=record.clients,
                    conflict=bool(path.exists() and current != record.digest),
                    detail=f"当前 SHA-256：{current}\n记录 SHA-256：{record.digest}" if current != record.digest else "",
                )
            )
        return changes

    def _resolve_conflicts(
        self,
        result: OperationResult,
        policy: str,
        confirmed_direct_replace: bool,
        dry_run: bool,
    ) -> None:
        conflicts = result.conflicts
        if not conflicts:
            return
        if policy not in {"abort", "archive", "replace"}:
            raise LifecycleError(f"未知冲突策略：{policy}")
        if policy == "abort":
            raise LifecycleError("发现现有规则或 Skill 冲突；请先查看差异并选择归档或直接替换")
        if policy == "replace" and not confirmed_direct_replace:
            raise LifecycleError("无备份直接替换需要明确确认")
        if policy == "archive" and not dry_run:
            result.archive = create_archive([change.path for change in conflicts], self.paths.home, self.paths.backups_dir)
            result.messages.append(f"已归档：{result.archive}")

    def _apply_change(self, change: Change) -> None:
        if change.action in {"unchanged", "retain"}:
            return
        if change.action == "remove":
            if change.kind == "managed-rule" and change.path.exists():
                if change.desired_text:
                    atomic_write(change.path, change.desired_text.encode("utf-8"), mode=0o600)
                else:
                    change.path.unlink(missing_ok=True)
            elif change.path.is_dir() and not change.path.is_symlink():
                shutil.rmtree(change.path)
            else:
                change.path.unlink(missing_ok=True)
            return
        if change.kind == "managed-rule":
            assert change.desired_text is not None
            atomic_write(change.path, change.desired_text.encode("utf-8"), mode=0o600)
            return
        if change.kind == "skill":
            assert change.bundle_prefix is not None
            self._replace_tree(change.path, change.bundle_prefix)
            return
        raise LifecycleError(f"不支持的变更类型：{change.kind}")

    def _replace_tree(self, target: Path, prefix: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_root = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
        staged = temp_root / target.name
        previous = temp_root / f"{target.name}.previous"
        try:
            for entry in self.bundle.entries(prefix):
                relative = Path(entry.relative).relative_to(prefix)
                destination = staged / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(entry.data)
                destination.chmod(0o755 if relative.parts[:1] == ("scripts",) and entry.data.startswith(b"#!") else 0o644)
            moved_previous = target.exists() or target.is_symlink()
            if moved_previous:
                os.replace(target, previous)
            try:
                os.replace(staged, target)
            except Exception:
                if moved_previous and (previous.exists() or previous.is_symlink()):
                    os.replace(previous, target)
                raise
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def _ensure_config(self, vault_root: Path | None, projects_root: str) -> None:
        if self.paths.config_file.is_file() or self.paths.legacy_config_file.is_file():
            return
        if vault_root is None:
            raise LifecycleError("首次安装需要指定 Obsidian Vault 路径")
        root = vault_root.expanduser().resolve()
        if not root.is_dir():
            raise LifecycleError(f"Obsidian Vault 不存在：{root}")
        if (
            not projects_root.strip()
            or "/" in projects_root
            or "\\" in projects_root
            or projects_root in {".", ".."}
            or any(ord(character) < 32 for character in projects_root)
        ):
            raise LifecycleError(f"projects_root 不是安全目录名：{projects_root!r}")
        payload = (
            f"version = 1\nvault_root = {json.dumps(str(root), ensure_ascii=False)}\n"
            f"projects_root = {json.dumps(projects_root, ensure_ascii=False)}\n\n[projects]\n"
        )
        atomic_write(self.paths.config_file, payload.encode("utf-8"), mode=0o600)

    def _skill_names(self) -> list[str]:
        names = {
            Path(name).parts[1]
            for name in self.bundle.names("skills")
            if len(Path(name).parts) >= 3 and Path(name).name == "SKILL.md"
        }
        return sorted(names)

    def _bundle_tree_digest(self, prefix: str) -> str:
        parts: list[bytes] = []
        for entry in self.bundle.entries(prefix):
            relative = Path(entry.relative).relative_to(prefix).as_posix()
            parts.extend((relative.encode("utf-8"), b"\0", sha256_bytes(entry.data).encode("ascii"), b"\0"))
        return sha256_bytes(b"".join(parts))

    def _directory_diff(self, target: Path, prefix: str) -> str:
        current = {
            path.relative_to(target).as_posix(): sha256_path(path)
            for path in target.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        desired = {
            Path(entry.relative).relative_to(prefix).as_posix(): sha256_bytes(entry.data)
            for entry in self.bundle.entries(prefix)
        }
        lines: list[str] = []
        for name in sorted(current.keys() | desired.keys()):
            if name not in current:
                lines.append(f"+ {name}")
            elif name not in desired:
                lines.append(f"- {name}")
            elif current[name] != desired[name]:
                lines.append(f"~ {name}")
        return "\n".join(lines)

    def _record_digest(self, record: InstallationRecord, path: Path) -> str:
        if record.kind != "managed-rule":
            return sha256_path(path)
        try:
            content = block_content(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ManagedBlockError):
            return ""
        return sha256_bytes((content or "").encode("utf-8"))

    def _legacy_duplicate_skills(self, state: InstallState) -> list[Path]:
        managed = {Path(record.path).resolve() for record in state.installations.values() if record.kind == "skill"}
        candidates = []
        kimi_home = self.adapters["kimi-code"].rule_path(self.paths.home, self.environ).parent
        for root in (
            self.paths.home / ".codex" / "skills",
            kimi_home / "skills",
            self.paths.home / ".config" / "opencode" / "skills",
            self.paths.home / ".claude" / "skills",
        ):
            for skill_name in self._skill_names():
                path = root / skill_name
                if path.exists() and path.resolve() not in managed:
                    candidates.append(path)
        return sorted(candidates)

    def _unsafe_record_message(self, record: InstallationRecord) -> str | None:
        path = Path(record.path).expanduser()
        if not path.is_absolute():
            return f"状态目标不是绝对路径：{record.path}"
        normalized = path.resolve(strict=False)
        if record.kind == "managed-rule":
            if not record.key.startswith("rule:"):
                return f"规则记录键无效：{record.key}"
            client_id = record.key.removeprefix("rule:")
            adapter = self.adapters.get(client_id)
            if adapter is None:
                return f"规则记录引用未知客户端：{client_id}"
            expected = adapter.rule_path(self.paths.home, self.environ).resolve(strict=False)
            if normalized != expected:
                return f"规则目标不符合适配器声明：{record.path}"
            return None
        if record.kind == "skill":
            allowed_roots = {
                adapter.skills_path(self.paths.home).resolve(strict=False) for adapter in self.adapters.values()
            }
            if normalized.parent not in allowed_roots or normalized.name not in self._skill_names():
                return f"Skill 目标超出允许范围：{record.path}"
            if record.key != f"skill:{path}":
                return f"Skill 记录键与路径不一致：{record.key}"
            return None
        return f"不支持的状态记录类型：{record.kind}"

    def _remove_owned_launchers(self) -> None:
        long_launcher = self.paths.long_launcher
        if long_launcher.is_symlink() and long_launcher.resolve(strict=False) == self.paths.launcher.resolve(strict=False):
            long_launcher.unlink()
        launcher = self.paths.launcher
        if not launcher.is_file() or launcher.is_symlink():
            return
        try:
            lines = launcher.read_text(encoding="utf-8").splitlines()
            first_line, second_line = lines[:2]
        except (OSError, UnicodeDecodeError, IndexError):
            return
        if first_line == "#!/bin/sh" and second_line == LAUNCHER_MARKER:
            launcher.unlink()
