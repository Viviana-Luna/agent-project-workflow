#!/usr/bin/env python3
"""执行仓库结构、Skill 元数据、脚本语法和公开边界检查。"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


REQUIRED_PATHS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "config/project-workflow.example.toml",
    "apw/cli.py",
    "apw/lifecycle.py",
    "apw/updater.py",
    "scripts/install.py",
    "scripts/install.sh.template",
    "scripts/build_release.py",
    "scripts/workflow_doctor.py",
    "adapters/codex/adapter.toml",
    "adapters/claude-code/adapter.toml",
    "adapters/kimi-code/adapter.toml",
    "adapters/opencode/adapter.toml",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "skills/agent-dev-workflow-init/SKILL.md",
    "skills/migrate-project-workflow-to-obsidian/SKILL.md",
    "skills/execute-todo-loop/SKILL.md",
    "templates/workspace/TODO.md",
)
FORBIDDEN_PATTERNS = (
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
)
REQUIRED_ADAPTERS = {"codex", "claude-code", "kimi-code", "opencode"}


def validate_skill(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return [f"Skill frontmatter 无效：{path}"]
    end = text.find("\n---\n", 4)
    frontmatter = text[4:end]
    values: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    if values.get("name") != path.parent.name:
        errors.append(f"Skill 名称与目录不一致：{path}")
    if not values.get("description"):
        errors.append(f"Skill 缺少 description：{path}")
    return errors


def validate_adapters(root: Path) -> list[str]:
    errors: list[str] = []
    discovered: set[str] = set()
    for path in sorted((root / "adapters").glob("*/adapter.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"适配器清单无效：{path}：{exc}")
            continue
        adapter_id = data.get("id")
        if not isinstance(adapter_id, str) or adapter_id != path.parent.name:
            errors.append(f"适配器 ID 与目录不一致：{path}")
            continue
        discovered.add(adapter_id)
        for key in ("display_name", "detect_commands", "rule_template", "rule_target", "skills_target"):
            if not data.get(key):
                errors.append(f"适配器缺少字段 {key}：{path}")
        template = data.get("rule_template")
        if isinstance(template, str):
            template_path = Path(template)
            if template_path.is_absolute() or ".." in template_path.parts or not (root / template_path).is_file():
                errors.append(f"适配器规则模板不存在或路径不安全：{path}：{template}")
    missing = sorted(REQUIRED_ADAPTERS - discovered)
    if missing:
        errors.append(f"缺少首版客户端适配器：{', '.join(missing)}")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors: list[str] = []
    for relative in REQUIRED_PATHS:
        if not (root / relative).exists():
            errors.append(f"缺少必要文件：{relative}")

    if (root / "AGENTS.md").read_bytes() != (root / "CLAUDE.md").read_bytes():
        errors.append("AGENTS.md 与 CLAUDE.md 内容不一致")

    for skill_path in sorted((root / "skills").glob("*/SKILL.md")):
        errors.extend(validate_skill(skill_path))
    errors.extend(validate_adapters(root))

    for script in sorted(root.rglob("*.py")):
        try:
            compile(script.read_text(encoding="utf-8"), str(script), "exec")
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            errors.append(f"脚本语法无效：{script}：{exc}")

    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                errors.append(f"公开文件包含疑似本机路径或秘密：{path}")
                break

    if errors:
        for error in errors:
            print(f"ERROR {error}")
        print(f"验证失败：{len(errors)} 个错误")
        return 1
    print("验证通过：仓库结构、Skill 元数据、脚本语法和公开边界均有效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
