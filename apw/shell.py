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


if os.name == "nt":
    import ctypes
    import winreg

    _HWND_BROADCAST = 0xFFFF
    _WM_SETTINGCHANGE = 0x001A
    _SMTO_ABORTIFHUNG = 0x0002
    _REG_EXPAND_SZ = winreg.REG_EXPAND_SZ

    def _read_user_path() -> tuple[str, int]:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as key:
            value, value_type = winreg.QueryValueEx(key, "PATH")
            return str(value), int(value_type)

    def _write_user_path(value: str, value_type: int) -> None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "PATH", 0, value_type, value)
        _broadcast_settingchange()

    def _broadcast_settingchange() -> None:
        result = ctypes.c_ulong(0)
        ctypes.windll.user32.SendMessageTimeoutW(
            _HWND_BROADCAST, _WM_SETTINGCHANGE, 0, "Environment",
            _SMTO_ABORTIFHUNG, 1000, ctypes.byref(result),
        )


def user_path_contains(bin_dir: Path) -> bool:
    """判断 bin_dir 是否已在用户 PATH 中；Windows 同时检查进程环境与注册表。"""
    if path_contains(bin_dir):
        return True
    if os.name != "nt":
        return False
    try:
        value, _ = _read_user_path()
    except FileNotFoundError:
        return False
    entries = [Path(item).expanduser() for item in value.split(os.pathsep) if item]
    return any(entry == bin_dir for entry in entries)


def add_user_path(bin_dir: Path, dry_run: bool = False) -> bool:
    """Windows：将 bin_dir 追加到用户 PATH；已存在返回 False。保留 REG_EXPAND_SZ/REG_SZ 类型。"""
    if os.name != "nt":
        raise OSError("用户 PATH 注册表管理仅支持 Windows")
    try:
        value, value_type = _read_user_path()
    except FileNotFoundError:
        value, value_type = "", _REG_EXPAND_SZ
    entries = [item for item in value.split(os.pathsep) if item]
    if any(Path(item).expanduser() == bin_dir for item in entries):
        return False
    entries.append(str(bin_dir))
    if not dry_run:
        _write_user_path(os.pathsep.join(entries), value_type)
    return True


def remove_user_path(bin_dir: Path, dry_run: bool = False) -> bool:
    """Windows：从用户 PATH 移除 bin_dir；不存在返回 False。"""
    if os.name != "nt":
        raise OSError("用户 PATH 注册表管理仅支持 Windows")
    try:
        value, value_type = _read_user_path()
    except FileNotFoundError:
        return False
    entries = [item for item in value.split(os.pathsep) if item]
    remaining = [item for item in entries if Path(item).expanduser() != bin_dir]
    if len(remaining) == len(entries):
        return False
    if not dry_run:
        _write_user_path(os.pathsep.join(remaining), value_type)
    return True

