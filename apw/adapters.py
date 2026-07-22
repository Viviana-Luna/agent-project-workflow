"""声明式客户端适配器注册表。"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .bundle import Bundle


@dataclass(frozen=True)
class Adapter:
    id: str
    display_name: str
    detect_commands: tuple[str, ...]
    rule_template: str
    rule_target: str
    skills_target: str
    rule_home_env: str | None = None
    validator: tuple[str, ...] = ()
    rule_target_windows: str | None = None
    skills_target_windows: str | None = None

    def detected(self) -> bool:
        return any(shutil.which(command) for command in self.detect_commands)

    def rule_path(self, home: Path, environ: dict[str, str] | None = None) -> Path:
        values = environ if environ is not None else os.environ
        if self.rule_home_env and values.get(self.rule_home_env):
            override = Path(values[self.rule_home_env]).expanduser()
            if not override.is_absolute():
                raise ValueError(f"{self.rule_home_env} 必须是绝对路径：{override}")
            return override.resolve() / Path(self.rule_target).name
        target = self.rule_target_windows if os.name == "nt" and self.rule_target_windows else self.rule_target
        return expand_home(target, home)

    def skills_path(self, home: Path) -> Path:
        target = self.skills_target_windows if os.name == "nt" and self.skills_target_windows else self.skills_target
        return expand_home(target, home)


def expand_home(value: str, home: Path) -> Path:
    if value == "~":
        return home
    if value.startswith("~/"):
        return home / value[2:]
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"客户端目标必须是用户目录或绝对路径：{value!r}")
    return path


def load_adapters(bundle: Bundle) -> dict[str, Adapter]:
    registry: dict[str, Adapter] = {}
    for name in bundle.names("adapters"):
        if not name.endswith("/adapter.toml"):
            continue
        data = tomllib.loads(bundle.read_text(name))
        required = {
            "id",
            "display_name",
            "detect_commands",
            "rule_template",
            "rule_target",
            "skills_target",
        }
        missing = sorted(required - data.keys())
        if missing:
            raise ValueError(f"适配器缺少字段 {', '.join(missing)}：{name}")
        adapter = Adapter(
            id=str(data["id"]),
            display_name=str(data["display_name"]),
            detect_commands=tuple(str(item) for item in data["detect_commands"]),
            rule_template=str(data["rule_template"]),
            rule_target=str(data["rule_target"]),
            skills_target=str(data["skills_target"]),
            rule_home_env=str(data["rule_home_env"]) if data.get("rule_home_env") else None,
            validator=tuple(str(item) for item in data.get("validator", [])),
            rule_target_windows=str(data["rule_target_windows"]) if data.get("rule_target_windows") else None,
            skills_target_windows=str(data["skills_target_windows"]) if data.get("skills_target_windows") else None,
        )
        template = Path(adapter.rule_template)
        if template.is_absolute() or ".." in template.parts:
            raise ValueError(f"适配器规则模板路径不安全：{name}：{adapter.rule_template}")
        if adapter.id in registry:
            raise ValueError(f"适配器 ID 重复：{adapter.id}")
        registry[adapter.id] = adapter
    if not registry:
        raise ValueError("没有发现客户端适配器")
    return dict(sorted(registry.items()))
