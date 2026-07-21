#!/usr/bin/env python3
"""检查项目工作流路径、文档状态和基础安全边界。"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


STANDARD_CONFIG = Path.home() / ".config" / "agent-project-workflow" / "config.toml"
LEGACY_CONFIG = Path.home() / ".codex" / "project-workflow.toml"
STANDARD_DIRS = (
    "constraints",
    "explanations",
    "planning/计划中",
    "planning/执行中",
    "planning/已完成",
    "handoff",
    "artifacts",
)
KNOWN_SECRET_NAMES = {
    ".env",
    "local-secrets.env",
    "credentials.json",
    "secrets.json",
}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
CHECKBOX_RE = re.compile(r"^- \[[ xX]\]", re.MULTILINE)
PLAN_REF_RE = re.compile(r"planning/(?:计划中|执行中|已完成)/[^\s`，。；;)]+\.md")
LEGACY_AGENT_RE = re.compile(r"(?<![\w-])\.agent/")
ABSOLUTE_PATH_RE = re.compile(r"(?:/Users/[^/\s]+/|/home/[^/\s]+/|[A-Za-z]:\\Users\\[^\\\s]+\\)")
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE),
    re.compile(
        r"(?:API[_-]?KEY|ACCESS[_-]?TOKEN|SECRET|PASSWORD)\s*[=:]\s*[\"']?"
        r"(?!<|\$\{|your[-_]|example|placeholder|待配置|已省略)[A-Za-z0-9_./+=-]{12,}",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str
    path: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 Obsidian 项目工作流的一致性")
    parser.add_argument("--repo-root", default=".", help="代码仓库根目录，默认当前目录")
    parser.add_argument("--config", default=None, help="显式指定工作流配置")
    parser.add_argument("--workflow-root", default=None, help="显式指定 Obsidian 项目工作区")
    parser.add_argument("--strict", action="store_true", help="存在警告时也返回非零状态")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    return parser.parse_args()


def config_candidates(explicit: str | None) -> list[Path]:
    if explicit:
        return [Path(explicit).expanduser()]
    from_env = os.environ.get("AGENT_PROJECT_WORKFLOW_CONFIG")
    candidates = [Path(from_env).expanduser()] if from_env else []
    candidates.extend((STANDARD_CONFIG, LEGACY_CONFIG))
    return candidates


def find_config(explicit: str | None) -> Path:
    for candidate in config_candidates(explicit):
        if candidate.is_file():
            return candidate.resolve()
    searched = "、".join(str(path) for path in config_candidates(explicit))
    raise ValueError(f"没有找到项目工作流配置；已检查：{searched}")


def safe_relative(value: str, label: str) -> Path:
    relative = Path(value)
    if not value.strip() or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"{label} 必须是安全相对路径：{value!r}")
    return relative


def load_config(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file_obj:
            data = tomllib.load(file_obj)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"无法读取配置 {path}：{exc}") from exc
    if data.get("version") != 1:
        raise ValueError(f"不支持的配置版本：{data.get('version')!r}")
    return data


def resolve_mapping(projects: dict[str, str], repo_root: Path) -> str | None:
    values: set[str] = set()
    for repo_value, project_value in projects.items():
        configured_repo = Path(repo_value).expanduser()
        if not configured_repo.is_absolute():
            raise ValueError(f"[projects] 键必须是仓库绝对路径：{repo_value!r}")
        if configured_repo.resolve() == repo_root:
            values.add(project_value)
    if len(values) > 1:
        raise ValueError(f"同一仓库存在冲突映射：{repo_root}")
    return next(iter(values), None)


def resolve_workflow_root(repo_root: Path, config_path: Path, explicit: str | None) -> Path:
    if explicit:
        workflow_root = Path(explicit).expanduser().resolve()
    else:
        data = load_config(config_path)
        vault_value = data.get("vault_root")
        if not isinstance(vault_value, str) or not vault_value.strip():
            raise ValueError(f"配置缺少有效 vault_root：{config_path}")
        projects = data.get("projects") or {}
        if not isinstance(projects, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in projects.items()):
            raise ValueError(f"[projects] 必须是字符串映射：{config_path}")
        mapped = resolve_mapping(projects, repo_root)
        if mapped:
            relative = safe_relative(mapped, "项目映射")
        else:
            root_value = data.get("projects_root", "Myproject")
            if not isinstance(root_value, str):
                raise ValueError(f"projects_root 必须是字符串：{config_path}")
            relative = safe_relative(root_value, "projects_root") / safe_relative(repo_root.name, "仓库名")
        workflow_root = Path(vault_value).expanduser().resolve() / relative

    try:
        workflow_root.relative_to(repo_root)
    except ValueError:
        return workflow_root
    raise ValueError(f"项目工作区不能位于代码仓库内部：{workflow_root}")


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def current_section(todo_text: str) -> str:
    match = re.search(r"^## (?:当前执行|当前任务)\s*$", todo_text, re.MULTILINE)
    if not match:
        return ""
    remainder = todo_text[match.end() :]
    next_heading = re.search(r"^##\s+", remainder, re.MULTILINE)
    return remainder[: next_heading.start()] if next_heading else remainder


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def add(findings: list[Finding], level: str, code: str, message: str, path: Path | None = None) -> None:
    findings.append(Finding(level, code, message, str(path) if path else None))


def inspect_workspace(repo_root: Path, workflow_root: Path, config_path: Path) -> list[Finding]:
    findings: list[Finding] = []
    if repo_root.joinpath(".agent").exists():
        add(findings, "error", "legacy-agent", "仓库仍存在旧 .agent 工作流", repo_root / ".agent")
    if not workflow_root.is_dir():
        add(findings, "error", "workspace-missing", "项目工作区不存在", workflow_root)
        return findings

    for relative in STANDARD_DIRS:
        path = workflow_root / relative
        if not path.is_dir():
            add(findings, "error", "missing-directory", f"缺少标准目录：{relative}", path)

    todo_path = workflow_root / "TODO.md"
    todo_text = read_text(todo_path)
    if todo_text is None:
        add(findings, "error", "todo-missing", "TODO.md 不存在或不是 UTF-8 文本", todo_path)
        todo_text = ""

    current_text = current_section(todo_text)
    current_count = len(CHECKBOX_RE.findall(current_text))
    if current_count > 1:
        add(findings, "warning", "multiple-current-todos", f"当前执行区存在 {current_count} 个任务；单任务闭环一次只能选择一个")

    all_refs = set(PLAN_REF_RE.findall(todo_text))
    current_refs = set(PLAN_REF_RE.findall(current_text))
    for relative in sorted(all_refs):
        path = workflow_root / relative
        if not path.is_file():
            add(findings, "error", "broken-plan-reference", f"TODO 引用的计划不存在：{relative}", path)

    seen_ids: dict[str, Path] = {}
    expected_status = {"计划中": {"planned", "paused"}, "执行中": {"active"}, "已完成": {"done"}}
    for state, valid_statuses in expected_status.items():
        state_root = workflow_root / "planning" / state
        if not state_root.is_dir():
            continue
        for plan_path in sorted(state_root.glob("*.md")):
            text = read_text(plan_path)
            if text is None:
                add(findings, "error", "plan-unreadable", "计划不是 UTF-8 文本", plan_path)
                continue
            relative = plan_path.relative_to(workflow_root).as_posix()
            metadata = parse_frontmatter(text)
            plan_id = metadata.get("id")
            status_value = metadata.get("status")
            kind = metadata.get("kind", "task")
            if plan_id:
                if plan_id in seen_ids:
                    add(findings, "error", "duplicate-plan-id", f"计划 ID 重复：{plan_id}；首次出现在 {seen_ids[plan_id]}", plan_path)
                else:
                    seen_ids[plan_id] = plan_path
            if metadata and status_value not in valid_statuses:
                add(findings, "error", "status-directory-mismatch", f"目录 {state} 与 status={status_value!r} 不一致", plan_path)
            if state == "执行中" and kind == "task" and relative not in current_refs:
                level = "error" if metadata.get("status") == "active" else "warning"
                add(findings, level, "active-plan-unreferenced", "执行中的任务计划没有被 TODO 当前执行区引用", plan_path)
            if state != "执行中" and relative in current_refs:
                add(findings, "error", "current-todo-wrong-state", f"TODO 当前执行引用了 {state} 计划", plan_path)
            if CHECKBOX_RE.search(text):
                add(findings, "error", "checkbox-outside-todo", "计划文档包含 checkbox；具体待办只能写入 TODO.md", plan_path)

    for path in sorted(workflow_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(workflow_root)
        lower_name = path.name.lower()
        if lower_name in KNOWN_SECRET_NAMES or lower_name.startswith(".env.") or path.suffix.lower() in SECRET_SUFFIXES:
            add(findings, "error", "secret-carrier", "工作区包含已知秘密载体", path)
            continue
        text = read_text(path)
        if text is None:
            add(findings, "warning", "binary-file", "无法读取的二进制文件需要人工确认不含秘密", path)
            continue
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            add(findings, "error", "suspected-secret", "文本疑似包含真实秘密", path)
        if LEGACY_AGENT_RE.search(text):
            add(findings, "warning", "legacy-agent-reference", "文档包含旧 .agent/ 工作流路径", path)
        if ABSOLUTE_PATH_RE.search(text):
            add(findings, "warning", "absolute-user-path", "文档包含疑似个人绝对路径", path)

    try:
        mode = stat.S_IMODE(config_path.stat().st_mode)
        if mode & 0o077:
            add(findings, "warning", "config-permissions", f"配置权限为 {mode:04o}，建议限制为 0600", config_path)
    except OSError:
        pass
    return findings


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.is_dir():
        raise SystemExit(f"仓库根目录不存在：{repo_root}")
    try:
        config_path = find_config(args.config)
        workflow_root = resolve_workflow_root(repo_root, config_path, args.workflow_root)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    findings = inspect_workspace(repo_root, workflow_root, config_path)
    errors = sum(item.level == "error" for item in findings)
    warnings = sum(item.level == "warning" for item in findings)
    report = {
        "version": 1,
        "repo_root": str(repo_root),
        "config": str(config_path),
        "workflow_root": str(workflow_root),
        "errors": errors,
        "warnings": warnings,
        "findings": [asdict(item) for item in findings],
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"仓库：{repo_root}")
        print(f"工作区：{workflow_root}")
        for item in findings:
            location = f"（{item.path}）" if item.path else ""
            print(f"{item.level.upper()} [{item.code}] {item.message}{location}")
        print(f"结果：{errors} 个错误，{warnings} 个警告")
    if errors:
        return 1
    if warnings and args.strict:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
