#!/usr/bin/env python3
"""安全安装 Agent Project Workflow 的规则适配器和 Skill。"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

SKILL_NAMES = (
    "agent-dev-workflow-init",
    "migrate-project-workflow-to-obsidian",
    "execute-todo-loop",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="旧版兼容安装入口；新安装请使用 apw")
    parser.add_argument(
        "--client",
        required=True,
        choices=("codex", "claude-code", "kimi-code", "opencode"),
        help="目标客户端",
    )
    parser.add_argument("--home", default=None, help="覆盖用户主目录，主要用于隔离测试")
    parser.add_argument("--skills-target", default=None, help="覆盖 Skill 安装目录")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写入")
    parser.add_argument("--force", action="store_true", help="备份后替换存在差异的目标")
    return parser.parse_args()


def files_equal(left: Path, right: Path) -> bool:
    return left.is_file() and right.is_file() and left.read_bytes() == right.read_bytes()


def directories_equal(left: Path, right: Path) -> bool:
    comparison = filecmp.dircmp(left, right)
    if comparison.left_only or comparison.right_only or comparison.funny_files:
        return False
    if any(not files_equal(left / name, right / name) for name in comparison.common_files):
        return False
    return all(directories_equal(left / name, right / name) for name in comparison.common_dirs)


def target_paths(args: argparse.Namespace, repo_root: Path) -> tuple[Path, Path, Path]:
    import sys

    sys.path.insert(0, str(repo_root))
    from apw.adapters import load_adapters
    from apw.bundle import Bundle

    home = Path(args.home).expanduser().resolve() if args.home else Path.home()
    adapters = load_adapters(Bundle(root=repo_root))
    adapter = adapters[args.client]
    skills_target = (
        Path(args.skills_target).expanduser().resolve()
        if args.skills_target
        else adapter.skills_path(home)
    )
    rules_source = repo_root / adapter.rule_template
    environment = dict(os.environ)
    if args.home and adapter.rule_home_env:
        environment.pop(adapter.rule_home_env, None)
    rules_target = adapter.rule_path(home, environment)
    return skills_target, rules_source, rules_target


def backup_target(target: Path, home: Path, backup_stamp: str) -> Path:
    relative = target.relative_to(home) if target.is_relative_to(home) else Path(target.name)
    backup = home / ".local" / "state" / "agent-project-workflow" / "backups" / backup_stamp / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(backup))
    return backup


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    home = Path(args.home).expanduser().resolve() if args.home else Path.home()
    skills_target, rules_source, rules_target = target_paths(args, repo_root)
    planned: list[tuple[str, Path, Path]] = [("file", rules_source, rules_target)]
    planned.extend(("dir", repo_root / "skills" / name, skills_target / name) for name in SKILL_NAMES)

    print("提示：scripts/install.py 仅用于旧版兼容；新安装请使用 apw。")

    conflicts: list[Path] = []
    changes: list[tuple[str, Path, Path]] = []
    for kind, source, target in planned:
        if not source.exists():
            raise SystemExit(f"安装源不存在：{source}")
        if not target.exists():
            changes.append((kind, source, target))
            continue
        same = files_equal(source, target) if kind == "file" else target.is_dir() and directories_equal(source, target)
        if same:
            print(f"未变化：{target}")
        else:
            conflicts.append(target)
            changes.append((kind, source, target))

    if conflicts and not args.force:
        for target in conflicts:
            print(f"冲突：{target}")
        print("未写入任何文件。请先审阅差异；确认替换时使用 --force，原文件会被备份。")
        return 2

    action = "计划安装" if args.dry_run else "已安装"
    backup_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for kind, source, target in changes:
        if args.dry_run:
            if target.exists():
                print(f"计划备份：{target}")
            print(f"{action}：{source} -> {target}")
            continue
        if target.exists():
            backup = backup_target(target, home, backup_stamp)
            print(f"已备份：{target} -> {backup}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind == "file":
            shutil.copy2(source, target)
        else:
            shutil.copytree(source, target)
        print(f"{action}：{source} -> {target}")

    print("安装完成后请启动新会话，让客户端重新发现规则与 Skill。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
