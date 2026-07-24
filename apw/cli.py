"""apw 命令行与交互式管理入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable

from . import __version__
from .constants import DIRECT_REPLACE_PHRASE, LATEST_MANIFEST_URL, REPOSITORY_URL
from .lifecycle import Change, LifecycleError, LifecycleManager, OperationResult
from .paths import AppPaths
from .shell import (
    add_user_path,
    path_contains,
    remove_path_profile,
    remove_user_path,
    shell_profile,
    update_path_profile,
    user_path_contains,
)
from .tui import Choice, choose_one, confirm, prompt, select_many
from .updater import UpdateError, UpdateManager, version_tuple


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apw", description="Agent Project Workflow 安装与更新管理器")
    parser.add_argument("--version", action="version", version=f"apw {__version__}")
    parser.add_argument("--home", default=None, help="覆盖用户主目录，主要用于隔离测试")
    subparsers = parser.add_subparsers(dest="command")

    install = subparsers.add_parser("install", help="安装一个工作流内容")
    install.add_argument("--skills", action="store_true", help="只安装共享工作流 Skill（Codex、Kimi Code、OpenCode）")
    install.add_argument("--rule", choices=("codex", "claude-code", "kimi-code", "opencode"), help="只安装一个客户端规则")
    install.add_argument("--clients", default=None, help="兼容旧版：逗号分隔的客户端 ID")
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


def _utf8_stdio() -> None:
    """Windows 重定向输出默认使用 ANSI 代码页，强制 UTF-8 避免中文输出崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
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
    modes = sum(bool(value) for value in (args.skills, args.rule, args.clients))
    if modes > 1:
        raise LifecycleError("--skills、--rule 和 --clients 只能指定一个")
    mode = "clients"
    client_id: str | None = None
    skill_names: list[str] | None = None
    if args.skills:
        mode = "skills"
    elif args.rule:
        mode = "rule"
        client_id = args.rule
    elif args.clients:
        clients = parse_clients(args.clients)
    elif interactive:
        show_client_detection(manager)
        mode = choose_install_content()
        if mode == "exit":
            print("已取消，未写入任何文件。")
            return 0
        if mode == "rule":
            client_id = choose_detected_client(manager)
    else:
        raise LifecycleError("非交互模式必须指定 --skills、--rule 或兼容的 --clients")
    if mode == "skills":
        _, all_skill_changes = manager.plan_install_skills()
        if interactive:
            skill_names = choose_skills(all_skill_changes)
            if not skill_names:
                print("未选择任何工作流 Skill，未写入任何文件。")
                return 0
        _, changes = manager.plan_install_skills(skill_names)
        title = "共享工作流 Skill"
    elif mode == "rule":
        assert client_id is not None
        _, changes = manager.plan_install_rule(client_id)
        title = f"{manager.adapters[client_id].display_name} 规则"
    else:
        _, changes = manager.plan_install(clients)
        title = "兼容批量客户端接入"
    print(f"\n{title}安装预览：")
    print(manager.format_changes(changes))
    policy, direct = resolve_conflicts(args, changes, interactive)
    if not args.dry_run and not args.yes and interactive and not confirm(f"确认安装{title}？"):
        print("已取消，未写入任何文件。")
        return 0
    if mode == "skills":
        result = manager.install_skills(
            skill_names=skill_names,
            conflict_policy=policy,
            confirmed_direct_replace=direct,
            dry_run=args.dry_run,
        )
    elif mode == "rule":
        assert client_id is not None
        result = manager.install_rule(
            client_id,
            conflict_policy=policy,
            confirmed_direct_replace=direct,
            dry_run=args.dry_run,
        )
    else:
        result = manager.install(
            clients,
            conflict_policy=policy,
            confirmed_direct_replace=direct,
            dry_run=args.dry_run,
        )
    print_result(result)
    if interactive and mode == "skills" and not args.dry_run:
        install_follow_up_rule(args, manager)
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
        print(f"共享工作流 Skill：{'已安装' if status['shared_skills_installed'] else '未安装'}")
        config = status["config"]
        print(f"项目工作区配置：{config if config else '尚未创建，将在首次项目初始化时选择'}")
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
    _, changes = manager.plan_repair()
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
    if not args.keep_manager:
        _preview_path_removal(paths)
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
    if not args.dry_run and not args.keep_manager:
        _remove_path(paths)
    if not args.dry_run:
        print("卸载完成；已保留 Obsidian 工作区、配置文件和压缩归档。")
    return 0


def _preview_path_removal(paths: AppPaths) -> None:
    if os.name == "nt":
        if user_path_contains(paths.bin_dir):
            print(f"计划从用户 PATH 移除：{paths.bin_dir}")
        return
    profile = shell_profile(paths.home)
    if profile and profile.exists():
        current = profile.read_text(encoding="utf-8")
        desired = remove_path_profile(profile, dry_run=True)
        if desired != current:
            print(f"计划从 Shell 配置移除 PATH 托管区块：{profile}")


def _remove_path(paths: AppPaths) -> None:
    if os.name == "nt":
        remove_user_path(paths.bin_dir)
        return
    profile = shell_profile(paths.home)
    if profile and profile.exists():
        remove_path_profile(profile)


def command_update(args: argparse.Namespace, paths: AppPaths, manager: LifecycleManager) -> int:
    state = manager.assert_safe_state()
    if not state.installations:
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
    choices = [
        Choice("install", "安装一个工作流内容"),
        Choice("clients", "批量调整客户端（兼容入口）"),
        Choice("status", "查看状态"),
        Choice("update", "手动检查更新"),
        Choice("doctor", "运行诊断"),
        Choice("repair", "修复安装"),
        Choice("uninstall", "卸载"),
        Choice("exit", "退出"),
    ]
    default = "install"
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


def show_client_detection(manager: LifecycleManager) -> None:
    print("\n支持的客户端检测结果：")
    for adapter in manager.available_clients():
        status = "已检测到" if adapter.detected() else "未检测到"
        print(f"- {adapter.display_name}：{status}")


def choose_install_content() -> str:
    return choose_one(
        "请选择本次要安装的内容（每次只处理一个内容）",
        [
            Choice("skills", "共享工作流 Skill", "安装到 ~/.agents/skills；供 Codex、Kimi Code、OpenCode 发现"),
            Choice("rule", "客户端规则文件", "安装一个 AGENTS.md；Claude Code 使用 CLAUDE.md"),
            Choice("exit", "暂不安装", "只完成客户端检测，不写入文件"),
        ],
        "exit",
    )


def choose_detected_client(manager: LifecycleManager) -> str:
    choices = [
        Choice(adapter.id, adapter.display_name)
        for adapter in manager.available_clients()
        if adapter.detected()
    ]
    if not choices:
        raise LifecycleError("没有检测到受支持客户端；请先安装客户端程序后再安装规则")
    return choose_one("请选择要安装规则的客户端", choices)


def choose_follow_up_rule(manager: LifecycleManager) -> str | None:
    choices = [
        Choice(adapter.id, adapter.display_name)
        for adapter in manager.available_clients()
        if adapter.detected()
    ]
    if not choices:
        print("没有检测到客户端，已跳过规则安装。")
        return None
    choices.append(Choice("skip", "暂不安装客户端规则", "仅完成本次 Skill 安装"))
    selected = choose_one("接下来请选择要安装的客户端规则", choices, "skip")
    return None if selected == "skip" else selected


def install_follow_up_rule(args: argparse.Namespace, manager: LifecycleManager) -> None:
    client_id = choose_follow_up_rule(manager)
    if client_id is None:
        print("已跳过客户端规则安装。")
        return
    _, changes = manager.plan_install_rule(client_id)
    title = f"{manager.adapters[client_id].display_name} 规则"
    print(f"\n{title}安装预览：")
    print(manager.format_changes(changes))
    policy, direct = resolve_conflicts(args, changes, True)
    if not args.yes and not confirm(f"确认安装{title}？"):
        print("已取消客户端规则安装，已保留本次 Skill 安装结果。")
        return
    result = manager.install_rule(
        client_id,
        conflict_policy=policy,
        confirmed_direct_replace=direct,
    )
    print_result(result)


def choose_skills(changes: Iterable[Change]) -> list[str]:
    status = {
        "missing": "未安装",
        "current": "已是当前版本",
        "different": "版本有差异",
        "unreadable": "无法比较版本",
        "unmanaged": "未托管内容",
    }
    items = list(changes)
    choices = [
        Choice(
            change.bundle_prefix.rsplit("/", 1)[-1] if change.bundle_prefix else change.key,
            change.bundle_prefix.rsplit("/", 1)[-1] if change.bundle_prefix else change.key,
            status.get(change.version_status, change.action),
        )
        for change in items
    ]
    defaults = {
        choice.value
        for choice, change in zip(choices, items, strict=True)
        if change.version_status in {"missing", "different"}
    }
    return select_many("请选择要安装的工作流 Skill", choices, defaults)


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
    if os.name == "nt":
        if not paths.launcher.exists() or user_path_contains(paths.bin_dir):
            return
        if interactive and confirm(f"{paths.bin_dir} 不在 PATH，是否写入用户环境变量？", default=True):
            add_user_path(paths.bin_dir)
            print(f"已将 {paths.bin_dir} 加入用户 PATH；重新打开终端后生效。")
        else:
            print(f"请把 {paths.bin_dir} 添加到用户 PATH。")
        return
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
