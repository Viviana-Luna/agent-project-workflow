"""以托管区块方式接入用户 PATH。"""

from __future__ import annotations

import os
from pathlib import Path

from .state import atomic_write


PATH_START = "# agent-project-workflow:path:start"
PATH_END = "# agent-project-workflow:path:end"


def path_contains(bin_dir: Path, environ: dict[str, str] | None = None) -> bool:
    values = environ if environ is not None else os.environ
    entries = [Path(item).expanduser() for item in values.get("PATH", "").split(os.pathsep) if item]
    return any(entry == bin_dir for entry in entries)


def shell_profile(home: Path, shell: str | None = None) -> Path | None:
    name = Path(shell or os.environ.get("SHELL", "")).name
    if name == "zsh":
        return home / ".zprofile"
    if name == "bash":
        return home / ".bashrc"
    return None


def render_path_block(bin_dir: Path) -> str:
    quoted = "'" + str(bin_dir).replace("'", "'\\''") + "'"
    return f'{PATH_START}\nexport PATH={quoted}:"$PATH"\n{PATH_END}'


def update_path_profile(profile: Path, bin_dir: Path, dry_run: bool = False) -> str:
    existing = profile.read_text(encoding="utf-8") if profile.is_file() else ""
    block = render_path_block(bin_dir)
    if PATH_START in existing or PATH_END in existing:
        if existing.count(PATH_START) != 1 or existing.count(PATH_END) != 1:
            raise ValueError(f"PATH 托管标记缺失或重复：{profile}")
        start = existing.index(PATH_START)
        end = existing.index(PATH_END, start) + len(PATH_END)
        desired = f"{existing[:start]}{block}{existing[end:]}"
    else:
        prefix = existing.rstrip()
        desired = f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"
    if not dry_run:
        atomic_write(profile, desired.encode("utf-8"), mode=0o600)
    return desired


def remove_path_profile(profile: Path, dry_run: bool = False) -> str:
    if not profile.is_file():
        return ""
    existing = profile.read_text(encoding="utf-8")
    if PATH_START not in existing and PATH_END not in existing:
        return existing
    if existing.count(PATH_START) != 1 or existing.count(PATH_END) != 1:
        raise ValueError(f"PATH 托管标记缺失或重复：{profile}")
    start = existing.index(PATH_START)
    end = existing.index(PATH_END, start) + len(PATH_END)
    desired = f"{existing[:start]}{existing[end:]}".strip()
    desired = f"{desired}\n" if desired else ""
    if not dry_run:
        if desired:
            atomic_write(profile, desired.encode("utf-8"), mode=0o600)
        else:
            profile.unlink(missing_ok=True)
    return desired
