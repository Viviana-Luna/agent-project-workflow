#!/usr/bin/env python3
"""初始化或更新仓库外的 Obsidian 项目开发工作区。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
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
    parser.add_argument(
        "--vault-root",
        default=None,
        help="首次初始化配置时指定 Obsidian Vault；已有配置不会被此参数改写",
    )
    parser.add_argument(
        "--workflow-root",
        default=None,
        help="临时指定绝对工作区，仅用于路径诊断；正式初始化请使用 --project-path",
    )
    parser.add_argument(
        "--project-path",
        "--project-name",
        dest="project_path",
        default=None,
        help="当前项目相对于 vault_root 的完整路径；确认初始化后写入 [projects]",
    )
    location_mode = parser.add_mutually_exclusive_group()
    location_mode.add_argument(
        "--relocate",
        action="store_true",
        help="旧工作区存在且目标不存在时，整体移动后再更新项目映射",
    )
    location_mode.add_argument(
        "--adopt-existing",
        action="store_true",
        help="旧工作区不存在且目标已存在时，显式接管目标并更新项目映射",
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
            "请先让用户选择 Obsidian Vault 和当前项目路径；不要回退到仓库创建 .agent。"
        )
    try:
        with path.open("rb") as config_file:
            data = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"无法读取项目工作流配置 {path}：{exc}") from exc
    if data.get("version") != 1:
        raise SystemExit(f"不支持的项目工作流配置版本：{data.get('version')!r}；当前只支持 version = 1")
    return data


def load_or_prepare_config(path: Path, vault_value: str | None) -> tuple[dict[str, Any], str, bool]:
    if path.is_file():
        data = load_config(path)
        configured_vault = data.get("vault_root")
        if not isinstance(configured_vault, str) or not configured_vault.strip():
            raise SystemExit(f"配置缺少有效的 vault_root：{path}")
        existing = Path(configured_vault).expanduser().resolve()
        if not existing.is_dir():
            raise SystemExit(f"配置中的 Obsidian Vault 不存在：{existing}")
        if vault_value:
            requested = Path(vault_value).expanduser().resolve()
            if requested != existing:
                raise SystemExit(
                    f"已有配置使用其他 Obsidian Vault：{existing}；"
                    "本 Skill 只调整 Vault 内的项目位置，不会静默切换整个 Vault。"
                )
        return data, path.read_text(encoding="utf-8"), False

    if not vault_value:
        raise SystemExit(
            f"项目工作流配置不存在：{path}\n"
            "首次初始化时必须先让用户选择 Obsidian Vault，并通过 --vault-root 指定。"
        )
    vault_root = Path(vault_value).expanduser().resolve()
    if not vault_root.is_dir():
        raise SystemExit(f"Obsidian Vault 不存在：{vault_root}")
    return {"version": 1, "vault_root": str(vault_root), "projects": {}}, "", True


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


def validate_workflow_root(workflow_root: Path, repo_root: Path) -> Path:
    try:
        workflow_root.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise SystemExit(f"项目工作区不能位于代码仓库内部：{workflow_root}")
    return workflow_root


def resolve_vault_workflow_root(vault_root: Path, project_dir: Path, repo_root: Path) -> Path:
    workflow_root = (vault_root / project_dir).resolve()
    try:
        workflow_root.relative_to(vault_root)
    except ValueError as exc:
        raise SystemExit(f"项目工作区必须位于 Obsidian Vault 内：{workflow_root}") from exc
    return validate_workflow_root(workflow_root, repo_root)


def project_table(data: dict[str, Any], config_path: Path) -> dict[str, str]:
    projects = data.get("projects", {})
    if projects is None:
        projects = {}
    if not isinstance(projects, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in projects.items()
    ):
        raise SystemExit(f"配置中的 [projects] 必须是字符串到字符串的映射：{config_path}")
    return dict(projects)


def legacy_workflow_root(data: dict[str, Any], repo_root: Path, vault_root: Path, config_path: Path) -> Path:
    projects_root_value = data.get("projects_root", "Myproject")
    if not isinstance(projects_root_value, str) or not projects_root_value.strip():
        raise SystemExit(f"配置中的 projects_root 必须是安全的相对路径：{config_path}")
    projects_root = validate_project_dir(projects_root_value)
    return vault_root / projects_root / validate_project_dir(repo_root.name)


def render_projects_table(projects: dict[str, str]) -> str:
    lines = ["[projects]\n"]
    for repo_value, project_value in sorted(projects.items()):
        lines.append(
            f"{json.dumps(repo_value, ensure_ascii=False)} = "
            f"{json.dumps(project_value, ensure_ascii=False)}\n"
        )
    return "".join(lines)


def replace_projects_table(original: str, projects: dict[str, str]) -> str:
    rendered = render_projects_table(projects)
    if not original:
        raise ValueError("缺少基础配置内容")
    lines = original.splitlines(keepends=True)
    projects_header = re.compile(r"^\s*\[projects\]\s*(?:#.*)?$")
    any_header = re.compile(r"^\s*\[\[?.+?\]?\]\s*(?:#.*)?$")
    start = next(
        (index for index, line in enumerate(lines) if projects_header.fullmatch(line.rstrip("\r\n"))),
        None,
    )
    if start is None:
        return original.rstrip() + "\n\n" + rendered
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if any_header.fullmatch(lines[index].rstrip("\r\n"))
        ),
        len(lines),
    )
    return "".join(lines[:start]) + rendered + "".join(lines[end:])


def atomic_write_config(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_value = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_value)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_obj:
            file_obj.write(content.rstrip() + "\n")
            file_obj.flush()
            os.fsync(file_obj.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_project_mapping(
    config_path: Path,
    data: dict[str, Any],
    original: str,
    repo_root: Path,
    project_path: str,
) -> None:
    projects = project_table(data, config_path)
    projects[str(repo_root)] = project_path
    if original:
        content = replace_projects_table(original, projects)
    else:
        vault_value = str(Path(str(data["vault_root"])).expanduser().resolve())
        content = (
            f"version = 1\nvault_root = {json.dumps(vault_value, ensure_ascii=False)}\n\n"
            f"{render_projects_table(projects)}"
        )
    atomic_write_config(config_path, content)


def paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


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

    if args.workflow_root:
        if args.project_path or args.relocate or args.adopt_existing:
            raise SystemExit("--workflow-root 不能与项目映射或迁移参数同时使用")
        if not args.print_workflow_root and not args.dry_run:
            raise SystemExit("--workflow-root 只允许用于 --print-workflow-root 或 --dry-run；正式初始化请使用 --project-path")
        workflow_root = validate_workflow_root(Path(args.workflow_root).expanduser().resolve(), repo_root)
        config_path: Path | None = None
        data: dict[str, Any] = {}
        original_config = ""
        mapping_value: str | None = None
        source_root: Path | None = None
        mapping_changed = False
    else:
        config_path = Path(args.config).expanduser().resolve()
        data, original_config, _ = load_or_prepare_config(config_path, args.vault_root)
        vault_value = data.get("vault_root")
        assert isinstance(vault_value, str)
        vault_root = Path(vault_value).expanduser().resolve()
        projects = project_table(data, config_path)
        configured_mapping = find_project_mapping(projects, repo_root, config_path)
        selected_mapping = args.project_path or configured_mapping
        if not selected_mapping:
            raise SystemExit(
                "当前项目尚未选择 Obsidian 文档位置。"
                "请先让用户选择 Vault 内的完整相对路径，再使用 --project-path；"
                "不要自动放入 Myproject。"
            )
        project_dir = validate_project_dir(selected_mapping)
        mapping_value = project_dir.as_posix()
        workflow_root = resolve_vault_workflow_root(vault_root, project_dir, repo_root)
        mapping_changed = configured_mapping != mapping_value
        if configured_mapping:
            source_root = resolve_vault_workflow_root(
                vault_root,
                validate_project_dir(configured_mapping),
                repo_root,
            )
        else:
            legacy_value = legacy_workflow_root(data, repo_root, vault_root, config_path)
            legacy_root = resolve_vault_workflow_root(
                vault_root,
                legacy_value.relative_to(vault_root),
                repo_root,
            )
            source_root = legacy_root if legacy_root.exists() else None

    if args.print_workflow_root:
        print(workflow_root)
        return 0

    actions: list[str] = [f"项目工作区：{workflow_root}"]
    moved_from: Path | None = None
    if mapping_changed:
        assert config_path is not None
        assert mapping_value is not None
        actions.append(
            f"{'计划记录' if args.dry_run else '已记录'}项目映射："
            f"{repo_root} -> {mapping_value}（{config_path}）"
        )

        if source_root and source_root != workflow_root and source_root.exists():
            if paths_overlap(source_root, workflow_root):
                raise SystemExit(f"旧工作区与新工作区不能互相包含：{source_root} -> {workflow_root}")
            if workflow_root.exists():
                raise SystemExit(
                    f"旧工作区和目标工作区同时存在，不能自动合并：{source_root}、{workflow_root}"
                )
            if not args.relocate:
                raise SystemExit(
                    f"检测到旧工作区：{source_root}\n"
                    f"先使用 --relocate --dry-run 预览，再显式执行整体移动到：{workflow_root}"
                )
            actions.append(f"{'计划移动' if args.dry_run else '已移动'}工作区：{source_root} -> {workflow_root}")
            if not args.dry_run:
                workflow_root.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source_root, workflow_root)
                moved_from = source_root
        elif workflow_root.exists() and source_root != workflow_root:
            if not args.adopt_existing:
                raise SystemExit(
                    f"目标工作区已存在：{workflow_root}\n"
                    "确认它属于当前项目后，使用 --adopt-existing --dry-run 预览，再显式接管。"
                )
            actions.append(f"{'计划接管' if args.dry_run else '已接管'}已有工作区：{workflow_root}")
        elif args.relocate:
            raise SystemExit("没有发现可迁移的旧工作区，不能使用 --relocate")
        elif args.adopt_existing:
            raise SystemExit("目标工作区不存在，不能使用 --adopt-existing")

        if not args.dry_run:
            try:
                save_project_mapping(config_path, data, original_config, repo_root, mapping_value)
            except Exception:
                if moved_from is not None and workflow_root.exists():
                    moved_from.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(workflow_root, moved_from)
                raise
    elif args.relocate or args.adopt_existing:
        raise SystemExit("项目映射没有变化，无需使用 --relocate 或 --adopt-existing")

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
