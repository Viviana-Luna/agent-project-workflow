"""apw 命令行与交互式管理入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from . import __version__
from .constants import DIRECT_REPLACE_PHRASE, LATEST_MANIFEST_URL, REPOSITORY_URL
from .lifecycle import Change, LifecycleError, LifecycleManager, OperationResult
from .paths import AppPaths
from .shell import path_contains, shell_profile, update_path_profile
from .tui import Choice, choose_one, confirm, prompt, select_many
from .updater import UpdateError, UpdateManager, version_tuple


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apw", description="Agent Project Workflow 安装与更新管理器")
    parser.add_argument("--version", action="version", version=f"apw {__version__}")
    parser.add_argument("--home", default=None, help="覆盖用户主目录，主要用于隔离测试")
    subparsers = parser.add_subparsers(dest="command")

    install = subparsers.add_parser("install", help="安装或接入客户端")
    install.add_argument("--clients", default=None, help="逗号分隔的客户端 ID")
    install.add_argument("--vault-root", default=None, help="Obsidian Vault 路径")
    install.add_argument("--projects-root", default="Myproject", help="Vault 中的项目根目录名")
    add_write_options(install)

    clients = subparsers.add_parser("clients", help="调整已接入客户端")
    clients.add_argument("--set", dest="clients", default=None, help="逗号分隔的完整客户端集合")
    add_write_options(clients)

    status = subparsers.add_parser("status", help="显示安装状态")
    status.add_argument("--json", action="store_true", help="输出 JSON")

    update = subparsers.add_parser("update", help="手动检查或安装更新")
    update.add_argument("--check", action="store_true", help="只检查，不安装")
    update.add_argument("--version", dest="target_version", default=None, help="显式指定目标稳定版本")
    update.add_argument("--manifest-url", default=None, help=argparse.SUPPRESS)
    update.add_argument("--allow-downgrade", action="store_true", help="允许显式降级")
    update.add_argument("--confirm-downgrade", action="store_true", help="非交互模式确认降级")
    add_write_options(update)

    doctor = subparsers.add_parser("doctor", help="诊断安装一致性")
    doctor.add_argument("--json", action="store_true", help="输出 JSON")

    repair = subparsers.add_parser("repair", help="修复缺失或损坏的托管内容")
    add_write_options(repair)

    uninstall = subparsers.add_parser("uninstall", help="安全卸载管理器和托管内容")
    uninstall.add_argument("--keep-manager", action="store_true", help=argparse.SUPPRESS)
    add_write_options(uninstall)
    return parser


def add_write_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写入")
    parser.add_argument("--non-interactive", action="store_true", help="禁止交互式询问")
    parser.add_argument(
        "--conflict",
        choices=("abort", "archive", "replace"),
        default="abort",
        help="冲突策略：中止、归档后替换或无备份直接替换",
    )
    parser.add_argument(
        "--confirm-direct-replace",
        action="store_true",
        help="确认无备份直接替换；仅与 --conflict replace 同时使用",
    )
    parser.add_argument("--yes", action="store_true", help="确认执行已预览的非冲突操作")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = AppPaths.from_home(Path(args.home) if args.home else None)
    try:
        manager = LifecycleManager(paths)
        if args.command is None:
            return run_menu(paths, manager)
        if args.command == "install":
            return command_install(args, paths, manager)
        if args.command == "clients":
            return command_clients(args, manager)
        if args.command == "status":
            return command_status(args, manager)
        if args.command == "doctor":
            return command_doctor(args, manager)
        if args.command == "repair":
            return command_repair(args, manager)
        if args.command == "uninstall":
            return command_uninstall(args, paths, manager)
        if args.command == "update":
            return command_update(args, paths, manager)
    except KeyboardInterrupt:
        print("\n已取消，未写入任何文件。", file=sys.stderr)
        return 130
    except (LifecycleError, UpdateError, ValueError, OSError, EOFError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    parser.error(f"未知命令：{args.command}")
    return 2


def command_install(args: argparse.Namespace, paths: AppPaths, manager: LifecycleManager) -> int:
    interactive = not args.non_interactive
    clients = parse_clients(args.clients) if args.clients else choose_clients(manager, interactive)
    vault_root = Path(args.vault_root).expanduser() if args.vault_root else None
    if not paths.config_file.is_file() and not paths.legacy_config_file.is_file() and vault_root is None:
        if not interactive:
            raise LifecycleError("非交互首次安装必须指定 --vault-root")
        vault_root = choose_vault(paths.home)
    _, changes = manager.plan_install(clients)
    print("\n安装预览：")
    print(manager.format_changes(changes))
    policy, direct = resolve_conflicts(args, changes, interactive)
    if not args.dry_run and not args.yes and interactive and not confirm("确认执行安装？"):
        print("已取消，未写入任何文件。")
        return 0
    result = manager.install(
        clients,
        conflict_policy=policy,
        confirmed_direct_replace=direct,
        dry_run=args.dry_run,
        vault_root=vault_root,
        projects_root=args.projects_root,
    )
    print_result(result)
    if not args.dry_run:
        maybe_configure_path(paths, interactive)
        print("安装完成。管理器不会安装或登录智能体客户端。")
    return 0


def command_clients(args: argparse.Namespace, manager: LifecycleManager) -> int:
    interactive = not args.non_interactive
    state = manager.assert_safe_state()
    if not state.selected_clients:
        raise LifecycleError("尚未完成首次安装，请先使用 apw install")
    desired = parse_clients(args.clients) if args.clients else choose_clients(manager, interactive, set(state.selected_clients))
    if not desired:
        raise LifecycleError("至少保留一个客户端；如需全部移除请使用 uninstall")
    _, install_changes = manager.plan_install(desired)
    removal_changes = manager._plan_removals(  # 统一预览安装与移除目标。
        set(state.selected_clients) - set(desired), set(desired), state
    )
    changes = install_changes + removal_changes
    print("\n客户端调整预览：")
    print(manager.format_changes(changes))
    policy, direct = resolve_conflicts(args, changes, interactive)
    if not args.dry_run and not args.yes and interactive and not confirm("确认调整客户端？"):
        print("已取消，未写入任何文件。")
        return 0
    result = manager.set_clients(
        desired,
        conflict_policy=policy,
        confirmed_direct_replace=direct,
        dry_run=args.dry_run,
    )
    print_result(result)
    return 0


def command_status(args: argparse.Namespace, manager: LifecycleManager) -> int:
    status = manager.status()
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print(f"管理器版本：{status['manager_version']}")
        clients = status["selected_clients"]
        print(f"已接入客户端：{', '.join(clients) if clients else '无'}")
        print(f"配置：{status['config']}")
        print(f"状态：{status['state']}")
        print(f"诊断：{status['errors']} 个错误，{status['warnings']} 个警告")
    return 1 if status["errors"] else 0


def command_doctor(args: argparse.Namespace, manager: LifecycleManager) -> int:
    findings = manager.doctor()
    errors = sum(item.level == "error" for item in findings)
    warnings = sum(item.level == "warning" for item in findings)
    if args.json:
        print(
            json.dumps(
                {
                    "version": 1,
                    "errors": errors,
                    "warnings": warnings,
                    "findings": [item.__dict__ for item in findings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for item in findings:
            location = f"（{item.path}）" if item.path else ""
            print(f"{item.level.upper()} [{item.code}] {item.message}{location}")
        print(f"结果：{errors} 个错误，{warnings} 个警告")
    return 1 if errors else (2 if warnings else 0)


def command_repair(args: argparse.Namespace, manager: LifecycleManager) -> int:
    interactive = not args.non_interactive
    state = manager.assert_safe_state()
    _, changes = manager.plan_install(state.selected_clients)
    print("\n修复预览：")
    print(manager.format_changes(changes))
    policy, direct = resolve_conflicts(args, changes, interactive)
    if not args.dry_run and not args.yes and interactive and not confirm("确认执行修复？"):
        print("已取消，未写入任何文件。")
        return 0
    result = manager.repair(
        conflict_policy=policy,
        confirmed_direct_replace=direct,
        dry_run=args.dry_run,
    )
    print_result(result)
    return 0


def command_uninstall(args: argparse.Namespace, paths: AppPaths, manager: LifecycleManager) -> int:
    interactive = not args.non_interactive
    state = manager.assert_safe_state()
    changes = manager._plan_removals(state.selected_clients, set(), state)
    profile = shell_profile(paths.home) if not args.keep_manager else None
    if profile and profile.exists():
        from .shell import remove_path_profile

        current_profile = profile.read_text(encoding="utf-8")
        desired_profile = remove_path_profile(profile, dry_run=True)
        if desired_profile != current_profile:
            print(f"计划从 Shell 配置移除 PATH 托管区块：{profile}")
    print("\n卸载预览：")
    print(manager.format_changes(changes))
    print("将保留 Obsidian 工作区、配置文件和压缩归档。")
    policy, direct = resolve_conflicts(args, changes, interactive)
    if not args.dry_run and not args.yes and interactive and not confirm("确认卸载？"):
        print("已取消，未写入任何文件。")
        return 0
    result = manager.uninstall(
        conflict_policy=policy,
        confirmed_direct_replace=direct,
        dry_run=args.dry_run,
        remove_manager=not args.keep_manager,
    )
    print_result(result)
    if not args.dry_run and profile and profile.exists():
        from .shell import remove_path_profile

        remove_path_profile(profile)
    if not args.dry_run:
        print("卸载完成；已保留 Obsidian 工作区、配置文件和压缩归档。")
    return 0


def command_update(args: argparse.Namespace, paths: AppPaths, manager: LifecycleManager) -> int:
    if not manager.assert_safe_state().selected_clients:
        raise LifecycleError("尚未完成首次安装，无法更新")
    target_version = args.target_version.removeprefix("v") if args.target_version else None
    if target_version:
        version_tuple(target_version)
    manifest_url = args.manifest_url or (
        f"{REPOSITORY_URL}/releases/download/v{target_version}/release-manifest.json"
        if target_version
        else LATEST_MANIFEST_URL
    )
    updater = UpdateManager(paths)
    checked = updater.check(manifest_url)
    if target_version and version_tuple(checked.latest_version) != version_tuple(target_version):
        raise UpdateError(f"发布清单版本 {checked.latest_version} 与指定版本 {target_version} 不一致")
    current_tuple = version_tuple(checked.current_version)
    target_tuple = version_tuple(checked.latest_version)
    is_downgrade = target_tuple < current_tuple
    if target_tuple == current_tuple:
        print(f"已是最新版本：{checked.current_version}")
        return 0
    print(f"当前版本：{checked.current_version}")
    print(f"目标版本：{checked.latest_version}")
    if checked.manifest.release_notes:
        print(f"\n更新内容：\n{checked.manifest.release_notes}")
    if args.check:
        return 0
    interactive = not args.non_interactive
    if is_downgrade:
        if not target_version or not args.allow_downgrade:
            raise UpdateError("降级必须通过 --version 明确目标，并同时指定 --allow-downgrade")
        if args.dry_run:
            pass
        elif interactive:
            if not confirm(f"再次确认降级到 {checked.latest_version}？", default=False):
                print("已取消，未写入任何文件。")
                return 0
        elif not args.confirm_downgrade:
            raise UpdateError("非交互降级必须同时指定 --confirm-downgrade")
    if not args.dry_run and not args.yes and interactive and not confirm("确认下载并准备更新？"):
        print("已取消，未写入任何文件。")
        return 0
    policy = args.conflict
    direct = args.confirm_direct_replace
    checked, result = updater.update(
        checked=checked,
        manifest_url=manifest_url,
        conflict_policy=policy,
        confirmed_direct_replace=direct,
        dry_run=args.dry_run,
        allow_downgrade=args.allow_downgrade,
        conflict_resolver=(
            (lambda changes: _resolve_update_conflicts(args, manager, changes))
            if interactive
            else None
        ),
        plan_callback=lambda changes: _preview_update_plan(manager, changes, interactive, args.dry_run),
    )
    if result:
        print_result(result)
    if args.dry_run:
        print(f"更新预览完成：{checked.current_version} -> {checked.latest_version}；未写入任何文件。")
    else:
        print(f"更新完成：{checked.current_version} -> {checked.latest_version}")
    return 0


def run_menu(paths: AppPaths, manager: LifecycleManager) -> int:
    state = manager.state()
    choices = [
        Choice("install", "安装或接入客户端"),
        Choice("clients", "修改客户端选择"),
        Choice("status", "查看状态"),
        Choice("update", "手动检查更新"),
        Choice("doctor", "运行诊断"),
        Choice("repair", "修复安装"),
        Choice("uninstall", "卸载"),
        Choice("exit", "退出"),
    ]
    default = "clients" if state.selected_clients else "install"
    action = choose_one(f"Agent Project Workflow {__version__}", choices, default)
    if action == "exit":
        return 0
    argv = ["--home", str(paths.home), action]
    return main(argv)


def parse_clients(value: str) -> list[str]:
    clients = [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return list(dict.fromkeys(clients))


def choose_clients(
    manager: LifecycleManager,
    interactive: bool,
    selected: set[str] | None = None,
) -> list[str]:
    if not interactive:
        raise LifecycleError("非交互模式必须通过 --clients 或 --set 指定客户端")
    defaults = selected if selected is not None else {
        adapter.id for adapter in manager.available_clients() if adapter.detected()
    }
    choices = [
        Choice(
            adapter.id,
            adapter.display_name,
            "已检测到" if adapter.detected() else "未检测到；只安装工作流文件",
        )
        for adapter in manager.available_clients()
    ]
    result = select_many("请选择需要接入的客户端", choices, defaults)
    if not result:
        raise LifecycleError("至少选择一个客户端")
    return result


def choose_vault(home: Path) -> Path:
    candidates = discover_vaults(home)
    if candidates:
        choices = [Choice(str(path), str(path)) for path in candidates]
        choices.append(Choice("manual", "手动输入其他路径"))
        selected = choose_one("请选择 Obsidian Vault", choices, str(candidates[0]))
        if selected != "manual":
            return Path(selected)
    value = prompt("请输入 Obsidian Vault 路径")
    path = Path(value).expanduser()
    if not path.is_dir():
        raise LifecycleError(f"Obsidian Vault 不存在：{path}")
    return path


def discover_vaults(home: Path) -> list[Path]:
    candidates: set[Path] = set()
    direct = [
        home / "Obsidian",
        home / "Documents" / "Obsidian",
        home / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents",
    ]
    for path in direct:
        if path.is_dir() and (path / ".obsidian").is_dir():
            candidates.add(path.resolve())
    cloud = home / "Library" / "CloudStorage"
    if cloud.is_dir():
        for marker in cloud.glob("*/*/.obsidian"):
            candidates.add(marker.parent.resolve())
        for marker in cloud.glob("*/*/*/.obsidian"):
            candidates.add(marker.parent.resolve())
    return sorted(candidates)


def resolve_conflicts(
    args: argparse.Namespace,
    changes: Iterable[Change],
    interactive: bool,
) -> tuple[str, bool]:
    conflicts = [change for change in changes if change.conflict]
    if not conflicts:
        return args.conflict, args.confirm_direct_replace
    if not interactive:
        if args.conflict == "abort":
            raise LifecycleError("非交互模式发现冲突；必须明确指定 --conflict archive 或 replace")
        if args.conflict == "replace" and not args.confirm_direct_replace:
            raise LifecycleError("无备份直接替换必须同时指定 --confirm-direct-replace")
        return args.conflict, args.confirm_direct_replace
    policy = choose_one(
        "发现冲突，请选择处理方式",
        [
            Choice("archive", "压缩归档后替换", "保留原目录结构、清单和哈希"),
            Choice("replace", "无备份直接替换", "不可恢复"),
            Choice("abort", "返回或退出", "不写入任何文件"),
        ],
        "archive",
    )
    if policy == "abort":
        raise LifecycleError("用户取消操作，未写入任何文件")
    if policy == "replace":
        phrase = prompt(f"请输入“{DIRECT_REPLACE_PHRASE}”确认不可恢复操作")
        if phrase != DIRECT_REPLACE_PHRASE:
            raise LifecycleError("确认短语不匹配，未写入任何文件")
        return policy, True
    return policy, False


def _resolve_update_conflicts(
    args: argparse.Namespace,
    manager: LifecycleManager,
    changes: list[Change],
) -> tuple[str, bool]:
    return resolve_conflicts(args, changes, True)


def _preview_update_plan(
    manager: LifecycleManager,
    changes: list[Change],
    interactive: bool,
    dry_run: bool,
) -> None:
    print("\n更新文件预览：")
    print(manager.format_changes(changes))
    if interactive and not dry_run and not confirm("确认应用以上文件变更并切换版本？"):
        raise LifecycleError("用户取消更新，未写入托管文件")


def maybe_configure_path(paths: AppPaths, interactive: bool) -> None:
    if not paths.launcher.exists() or path_contains(paths.bin_dir):
        return
    profile = shell_profile(paths.home)
    if profile is None:
        print(f"请把 {paths.bin_dir} 添加到 PATH。")
        return
    if interactive and confirm(f"{paths.bin_dir} 不在 PATH，是否写入 {profile}？", default=True):
        update_path_profile(profile, paths.bin_dir)
        print(f"已更新 {profile}；重新打开终端后生效。")
    else:
        print(f"请把 {paths.bin_dir} 添加到 PATH。")


def print_result(result: OperationResult) -> None:
    if result.dry_run:
        print("预览完成，未写入任何文件。")
    if result.archive:
        print(f"已创建归档：{result.archive}")
    for message in result.messages:
        if not result.archive or str(result.archive) not in message:
            print(message)


if __name__ == "__main__":
    raise SystemExit(main())
