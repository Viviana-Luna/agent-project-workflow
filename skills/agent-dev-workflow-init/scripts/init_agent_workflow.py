#!/usr/bin/env python3
"""初始化或更新仓库外的 Obsidian 项目开发工作区。"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path
from typing import Any


MANAGED_START = "<!-- agent-dev-workflow-init:start -->"
MANAGED_END = "<!-- agent-dev-workflow-init:end -->"
LEGACY_MANAGED_START = "<!-- project-doc-structure:start -->"
LEGACY_MANAGED_END = "<!-- project-doc-structure:end -->"


def standard_config() -> Path:
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return local / "agent-project-workflow" / "config" / "config.toml"
    return Path.home() / ".config" / "agent-project-workflow" / "config.toml"


LEGACY_CONFIG = Path.home() / ".codex" / "project-workflow.toml"


def default_config() -> Path:
    from_env = os.environ.get("AGENT_PROJECT_WORKFLOW_CONFIG")
    if from_env:
        return Path(from_env).expanduser()
    standard = standard_config()
    if standard.is_file():
        return standard
    if LEGACY_CONFIG.is_file():
        return LEGACY_CONFIG
    return standard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化或更新 Obsidian 项目开发工作区与仓库公开入口")
    parser.add_argument(
        "--repo-root",
        "--root",
        dest="repo_root",
        default=".",
        help="代码仓库根目录，默认当前目录；--root 作为旧参数别名保留",
    )
    parser.add_argument("--config", default=str(default_config()), help="项目工作流配置文件")
    parser.add_argument("--workflow-root", default=None, help="显式指定项目工作区；通常由配置自动解析")
    parser.add_argument(
        "--project-name",
        default=None,
        help="覆盖当前项目相对于 vault_root 的完整路径，不自动补 projects_root",
    )
    parser.add_argument("--print-workflow-root", action="store_true", help="只输出解析后的项目工作区路径")
    parser.add_argument("--date", default=None, help="兼容旧参数；模板不写入日期元信息")
    parser.add_argument("--remove-development", action="store_true", help="显式删除已完成内容迁移的 DEVELOPMENT.md")
    parser.add_argument("--dry-run", action="store_true", help="只输出将要执行的动作，不写入文件")
    return parser.parse_args()


def normalize_text(text: str) -> str:
    return text.rstrip() + "\n"


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str, dry_run: bool, actions: list[str]) -> None:
    normalized = normalize_text(content)
    if path.exists() and read_text(path) == normalized:
        actions.append(f"未变化：{path}")
        return
    actions.append(f"{'计划写入' if dry_run else '已写入'}：{path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(normalized, encoding="utf-8")


def write_if_missing(path: Path, content: str, dry_run: bool, actions: list[str]) -> None:
    if path.exists():
        actions.append(f"保留已有文件：{path}")
        return
    write_text(path, content, dry_run, actions)


def ensure_dir(path: Path, dry_run: bool, actions: list[str]) -> None:
    if path.exists():
        if not path.is_dir():
            raise SystemExit(f"目标路径不是目录：{path}")
        actions.append(f"目录已存在：{path}")
        return
    actions.append(f"{'计划创建' if dry_run else '已创建'}目录：{path}")
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(
            f"项目工作流配置不存在：{path}\n"
            "请先配置 version = 1、vault_root 和可选的 projects_root；不要回退到仓库创建 .agent。"
        )
    try:
        with path.open("rb") as config_file:
            data = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"无法读取项目工作流配置 {path}：{exc}") from exc
    if data.get("version") != 1:
        raise SystemExit(f"不支持的项目工作流配置版本：{data.get('version')!r}；当前只支持 version = 1")
    return data


def validate_project_dir(value: str) -> Path:
    project_dir = Path(value)
    if not value.strip() or project_dir.is_absolute() or any(part in {"", ".", ".."} for part in project_dir.parts):
        raise SystemExit(f"项目目录名必须是 Obsidian 仓库内的安全相对路径：{value!r}")
    return project_dir


def find_project_mapping(projects: dict[str, str], repo_root: Path, config_path: Path) -> str | None:
    matched_values: set[str] = set()
    for repo_value, project_value in projects.items():
        configured_repo = Path(repo_value).expanduser()
        if not configured_repo.is_absolute():
            raise SystemExit(f"配置中的 [projects] 键必须是仓库绝对路径：{repo_value!r}")
        if configured_repo.resolve() == repo_root:
            matched_values.add(project_value)

    if len(matched_values) > 1:
        raise SystemExit(f"同一仓库存在冲突的项目映射：{repo_root}（配置：{config_path}）")
    return next(iter(matched_values), None)


def resolve_workflow_root(args: argparse.Namespace, repo_root: Path) -> Path:
    if args.workflow_root:
        workflow_root = Path(args.workflow_root).expanduser().resolve()
    else:
        config_path = Path(args.config).expanduser().resolve()
        data = load_config(config_path)
        vault_value = data.get("vault_root")
        if not isinstance(vault_value, str) or not vault_value.strip():
            raise SystemExit(f"配置缺少有效的 vault_root：{config_path}")
        vault_root = Path(vault_value).expanduser().resolve()
        projects = data.get("projects", {})
        if projects is None:
            projects = {}
        if not isinstance(projects, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in projects.items()):
            raise SystemExit(f"配置中的 [projects] 必须是字符串到字符串的映射：{config_path}")
        project_value = args.project_name or find_project_mapping(projects, repo_root, config_path)
        if project_value:
            project_dir = validate_project_dir(project_value)
        else:
            projects_root_value = data.get("projects_root", "Myproject")
            if not isinstance(projects_root_value, str) or not projects_root_value.strip():
                raise SystemExit(f"配置中的 projects_root 必须是安全的相对路径：{config_path}")
            projects_root = validate_project_dir(projects_root_value)
            project_dir = projects_root / validate_project_dir(repo_root.name)
        workflow_root = vault_root / project_dir

    try:
        workflow_root.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise SystemExit(f"项目工作区不能位于代码仓库内部：{workflow_root}")
    return workflow_root


def strip_managed_blocks(original: str) -> str:
    text = original
    for start, end in (
        (MANAGED_START, MANAGED_END),
        (LEGACY_MANAGED_START, LEGACY_MANAGED_END),
    ):
        while start in text and end in text:
            before, rest = text.split(start, 1)
            _, after = rest.split(end, 1)
            text = f"{before.rstrip()}\n\n{after.lstrip()}"
    return normalize_text(text.strip()) if text.strip() else ""


def default_entry_text() -> str:
    return """# 仓库协作约束

## 公共协作原则

- 本文件只记录开源贡献者和自动化代理都应遵守的最小项目规则，不承载维护者个人开发习惯、私有计划或敏感上下文。
- 不提交密钥、令牌、本机绝对路径、私有模型资产或运行日志。
- 新增实现优先复用项目既有模块和 helper，避免重复造轮子；新增抽象必须能减少真实复杂度或降低耦合。
- 代码注释只解释复杂边界、设计原因或风险点，不添加空泛重复注释。
- 公开文档以简体中文维护；代码标识符、依赖包名、接口路径、配置键、协议字段和第三方专有名称按既有命名约定保留。
"""


def entry_text(existing: str) -> str:
    cleaned = strip_managed_blocks(existing)
    return cleaned if cleaned.strip() else default_entry_text()


def workflow_readme_text() -> str:
    return """# 项目开发工作区

这里是本项目个人开发文档的唯一事实源，由 Obsidian 编辑并通过同步盘同步，不属于代码仓库。

## 目录

- `TODO.md`：当前仍未完成的跨计划任务。
- `constraints/`：长期约束和架构边界。
- `explanations/`：产品、需求和设计说明。
- `planning/计划中/`：已经立项、尚未开始的方案。
- `planning/执行中/`：正在实施或验收的方案。
- `planning/已完成/`：完成摘要。
- `handoff/`：跨机器或跨人员交接材料。
- `artifacts/`：需要长期保留的小型图像或验证材料。

## 规则

- 具体待办只写入 `TODO.md`，计划正文不维护 checkbox 和每日流水。
- 废弃方案直接删除；有价值的结论先提炼到有效文档。
- 不保存 API Key、令牌、密码、真实用户数据、运行日志、构建缓存或依赖目录。
- 需要外发的内容先去敏、重整，再进入代码仓库的公共文档。
"""


def constraints_readme_text() -> str:
    return """# 长期约束

本目录保存长期有效的协作规则、架构边界和安全要求。项目专项方案放在 `planning/`，产品与设计说明放在 `explanations/`。

不要在这里保存密钥、令牌、真实用户数据或运行日志。
"""


def explanations_readme_text() -> str:
    return """# 产品与设计说明

本目录保存产品目的、需求说明、技术设计和对外口径草稿。内容默认只在个人 Obsidian 工作区使用；需要公开时先去敏并重写到代码仓库的公共文档。
"""


def planning_readme_text() -> str:
    return """# 计划文档

- `计划中/`：已经立项、尚未开始执行的方案。
- `执行中/`：正在实施或验收的方案。
- `已完成/`：完成摘要，只保留结果、验证和后续依据。

计划文档说明背景、目标、边界、方案、影响范围、验证口径、风险和失效条件，不写 checkbox 和执行流水。具体待办统一放在项目根目录 `TODO.md`。
"""


def plan_template_text() -> str:
    return """---
id: change-id
status: planned
kind: task
todo: ""
---

# 计划名称

## 背景

## 目标

## 边界

## 方案

## 影响范围

## 验证口径

## 风险

## 失效条件
"""


def handoff_readme_text() -> str:
    return """# 交接材料

只保存跨机器或跨人员继续工作所需的去敏材料，不保存秘密、构建缓存和运行日志。
"""


def artifacts_readme_text() -> str:
    return """# 长期产物

只保存小型、可复用、适合长期同步且不含秘密的图像或验证材料。
"""


def todo_text() -> str:
    return """# 总体开发任务列表

本文件只记录当前仍未完成的跨计划任务。完成后直接删除事项，不保留勾选历史；任务应标明来源计划、模块或必要上下文。

## 当前执行

## 后期事项（当前不执行）
"""


def github_readme_text(repo_root: Path) -> str:
    return f"""# {repo_root.name}

一句话介绍这个项目解决什么问题、面向谁、核心价值是什么。

## Overview

说明项目背景、典型使用场景和当前边界。

## Features

- 核心能力一
- 核心能力二
- 核心能力三

## Quick Start

```bash
# TODO: 填写项目真实安装和启动命令
```

## Documentation

- [AGENTS.md](AGENTS.md)：自动化代理与贡献者协作约束
- [CLAUDE.md](CLAUDE.md)：与 AGENTS.md 保持一致的代理约束入口

## License

待补充。
"""


def maybe_create_repo_readme(repo_root: Path, dry_run: bool, actions: list[str]) -> None:
    readme = repo_root / "README.md"
    if readme.exists():
        actions.append(f"保留已有 README.md：{readme}")
        return
    write_text(readme, github_readme_text(repo_root), dry_run, actions)


def maybe_remove_development(repo_root: Path, remove: bool, dry_run: bool, actions: list[str]) -> None:
    development = repo_root / "DEVELOPMENT.md"
    if not development.exists():
        actions.append("DEVELOPMENT.md 不存在，无需处理。")
        return
    if not remove:
        actions.append(f"检测到 DEVELOPMENT.md：{development}；默认保留。")
        return
    actions.append(f"{'计划删除' if dry_run else '已删除'}：{development}")
    if not dry_run:
        development.unlink()


def report_legacy(repo_root: Path, actions: list[str]) -> None:
    legacy_root = repo_root / ".agent"
    if legacy_root.exists():
        actions.append(
            f"检测到旧工作流：{legacy_root}；请使用 $migrate-project-workflow-to-obsidian 完成去密、迁移和收口。"
        )

    gitignore = repo_root / ".gitignore"
    ignored = {
        line.strip()
        for line in read_text(gitignore).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if ".agent" in ignored or ".agent/" in ignored:
        actions.append(
            f"检测到旧忽略规则：{gitignore}；由 $migrate-project-workflow-to-obsidian 在迁移验收后处理。"
        )


def _utf8_stdio() -> None:
    """Windows 重定向输出默认使用 ANSI 代码页，强制 UTF-8 避免中文输出崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _utf8_stdio()
    args = parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.is_dir():
        raise SystemExit(f"代码仓库根目录不存在：{repo_root}")

    workflow_root = resolve_workflow_root(args, repo_root)
    if args.print_workflow_root:
        print(workflow_root)
        return 0

    actions: list[str] = [f"项目工作区：{workflow_root}"]
    planning_root = workflow_root / "planning"
    for directory in (
        workflow_root,
        workflow_root / "constraints",
        workflow_root / "explanations",
        planning_root,
        planning_root / "计划中",
        planning_root / "执行中",
        planning_root / "已完成",
        workflow_root / "handoff",
        workflow_root / "artifacts",
    ):
        ensure_dir(directory, args.dry_run, actions)

    write_if_missing(workflow_root / "README.md", workflow_readme_text(), args.dry_run, actions)
    write_if_missing(workflow_root / "TODO.md", todo_text(), args.dry_run, actions)
    write_if_missing(workflow_root / "constraints" / "README.md", constraints_readme_text(), args.dry_run, actions)
    write_if_missing(workflow_root / "explanations" / "README.md", explanations_readme_text(), args.dry_run, actions)
    write_if_missing(planning_root / "README.md", planning_readme_text(), args.dry_run, actions)
    write_if_missing(planning_root / "计划模板.md", plan_template_text(), args.dry_run, actions)
    write_if_missing(workflow_root / "handoff" / "README.md", handoff_readme_text(), args.dry_run, actions)
    write_if_missing(workflow_root / "artifacts" / "README.md", artifacts_readme_text(), args.dry_run, actions)

    agents_path = repo_root / "AGENTS.md"
    claude_path = repo_root / "CLAUDE.md"
    agents_original = read_text(agents_path)
    claude_original = read_text(claude_path)
    agents_source = agents_original or claude_original
    claude_source = claude_original or agents_original
    agents_updated = entry_text(agents_source)
    claude_updated = entry_text(claude_source)
    write_text(agents_path, agents_updated, args.dry_run, actions)
    write_text(claude_path, claude_updated, args.dry_run, actions)

    maybe_create_repo_readme(repo_root, args.dry_run, actions)
    maybe_remove_development(repo_root, args.remove_development, args.dry_run, actions)
    report_legacy(repo_root, actions)

    if args.date:
        actions.append("--date 已兼容接收，但模板不写入日期元信息。")
    if agents_updated == claude_updated:
        actions.append("AGENTS.md 与 CLAUDE.md 内容一致。")
    else:
        actions.append("AGENTS.md 与 CLAUDE.md 仍有差异，请人工复核。")

    for action in actions:
        print(action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
