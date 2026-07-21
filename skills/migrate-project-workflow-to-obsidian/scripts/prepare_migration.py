#!/usr/bin/env python3
"""为旧 .agent 工作流生成去密的 Obsidian 迁移包。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import tempfile
from pathlib import Path


SECRET_NAMES = {
    ".env",
    "local-secrets.env",
    "credentials.json",
    "secrets.json",
}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
SKIP_DIR_NAMES = {"__pycache__", ".cache", "node_modules", "target", "dist", "runtime", "logs"}
SKIP_FILE_NAMES = {".DS_Store"}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AK[A-Z0-9]{14,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE),
    re.compile(
        r"(?:API[_-]?KEY|ACCESS[_-]?TOKEN|SECRET|PASSWORD)\s*[=:]\s*[\"']?"
        r"(?!<|\$\{|your[-_]|example|placeholder|待配置|已省略)[A-Za-z0-9_./+=-]{12,}",
        re.IGNORECASE,
    ),
)
STANDARD_DIRS = (
    "constraints",
    "explanations",
    "planning/计划中",
    "planning/执行中",
    "planning/已完成",
    "handoff",
    "artifacts",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成去密的 Obsidian 项目工作流迁移包")
    parser.add_argument("--repo-root", required=True, help="代码仓库根目录")
    parser.add_argument("--source", default=None, help="旧工作流目录，默认 <repo-root>/.agent")
    parser.add_argument("--output-root", default=None, help="输出目录；默认创建系统临时目录")
    parser.add_argument("--max-file-size-mb", type=int, default=25, help="单文件大小上限，默认 25 MiB")
    parser.add_argument(
        "--include-binary",
        action="store_true",
        help="显式复制无法按 UTF-8 检查的二进制文件；默认排除并要求人工复核",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_known_secret(path: Path) -> bool:
    name = path.name.lower()
    return name in SECRET_NAMES or name.startswith(".env.") or path.suffix.lower() in SECRET_SUFFIXES


def read_utf8(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def contains_suspected_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def rewrite_workflow_paths(text: str, repo_root: Path) -> str:
    absolute_prefix = f"{repo_root}/.agent/"
    return text.replace(absolute_prefix, "").replace(".agent/", "")


def should_skip_dir(path: Path) -> bool:
    return path.name in SKIP_DIR_NAMES


def prepare(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    repo_root = Path(args.repo_root).expanduser().resolve()
    source = Path(args.source).expanduser().resolve() if args.source else repo_root / ".agent"
    if not repo_root.is_dir():
        raise SystemExit(f"仓库根目录不存在：{repo_root}")
    if not source.is_dir():
        raise SystemExit(f"旧工作流目录不存在：{source}")
    if args.max_file_size_mb <= 0:
        raise SystemExit("--max-file-size-mb 必须大于 0")

    if args.output_root:
        output_root = Path(args.output_root).expanduser().resolve()
        if output_root.exists():
            raise SystemExit(f"输出目录已存在，为避免覆盖请换一个路径：{output_root}")
        output_root.mkdir(parents=True)
    else:
        output_root = Path(tempfile.mkdtemp(prefix=f"{repo_root.name}-obsidian-migration-"))

    project_root = output_root / "project"
    project_root.mkdir()
    for relative_dir in STANDARD_DIRS:
        (project_root / relative_dir).mkdir(parents=True, exist_ok=True)

    max_bytes = args.max_file_size_mb * 1024 * 1024
    copied: list[dict[str, object]] = []
    excluded: list[dict[str, str]] = []
    suspected_secrets: list[str] = []
    included_binary: list[str] = []
    warnings: list[str] = []

    for source_path in sorted(source.rglob("*")):
        relative = source_path.relative_to(source)
        if any(part in SKIP_DIR_NAMES for part in relative.parts[:-1]):
            continue
        if source_path.is_symlink():
            excluded.append({"path": str(relative), "reason": "符号链接"})
            continue
        if source_path.is_dir():
            if not should_skip_dir(source_path):
                (project_root / relative).mkdir(parents=True, exist_ok=True)
            continue
        if not source_path.is_file():
            excluded.append({"path": str(relative), "reason": "非普通文件"})
            continue
        if source_path.name in SKIP_FILE_NAMES:
            excluded.append({"path": str(relative), "reason": "系统临时文件"})
            continue
        if is_known_secret(source_path):
            excluded.append({"path": str(relative), "reason": "已知秘密载体"})
            continue
        if source_path.stat().st_size > max_bytes:
            excluded.append({"path": str(relative), "reason": f"超过 {args.max_file_size_mb} MiB"})
            continue

        text = read_utf8(source_path)
        if text is not None and contains_suspected_secret(text):
            suspected_secrets.append(str(relative))
            excluded.append({"path": str(relative), "reason": "疑似包含真实秘密，需人工复核"})
            continue
        if text is None and not args.include_binary:
            excluded.append({"path": str(relative), "reason": "二进制文件默认排除，需人工复核后显式包含"})
            continue

        destination = project_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            shutil.copyfile(source_path, destination)
            included_binary.append(str(relative))
        else:
            rewritten = rewrite_workflow_paths(text, repo_root)
            destination.write_text(rewritten.rstrip() + "\n", encoding="utf-8")
        destination.chmod(stat.S_IMODE(source_path.stat().st_mode))
        copied.append(
            {
                "path": str(relative),
                "size": destination.stat().st_size,
                "sha256": sha256(destination),
            }
        )

    if not (project_root / "TODO.md").exists():
        warnings.append("迁移包缺少 TODO.md；迁移前应确认项目是否使用其他任务入口。")
    if not (project_root / "README.md").exists():
        warnings.append("迁移包缺少 README.md；可由 agent-dev-workflow-init 补齐。")
    if suspected_secrets:
        warnings.append("存在疑似秘密文件；人工复核前不得把迁移包写入 Obsidian。")
    if included_binary:
        warnings.append("迁移包包含无法执行内容扫描的二进制文件；写入 Obsidian 前必须人工复核。")

    report: dict[str, object] = {
        "version": 1,
        "repo_root": str(repo_root),
        "source": str(source),
        "project_root": str(project_root),
        "copied_count": len(copied),
        "excluded_count": len(excluded),
        "copied": copied,
        "excluded": excluded,
        "suspected_secrets": suspected_secrets,
        "included_binary": included_binary,
        "warnings": warnings,
    }
    report_path = output_root / "migration-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_root, report


def main() -> int:
    args = parse_args()
    output_root, report = prepare(args)
    print(f"迁移包：{output_root / 'project'}")
    print(f"迁移报告：{output_root / 'migration-report.json'}")
    print(f"已复制：{report['copied_count']} 个文件")
    print(f"已排除：{report['excluded_count']} 个文件")
    print(f"疑似秘密：{len(report['suspected_secrets'])} 个文件")
    print(f"显式包含二进制：{len(report['included_binary'])} 个文件")
    for warning in report["warnings"]:
        print(f"警告：{warning}")
    return 2 if report["suspected_secrets"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
