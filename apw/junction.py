"""Windows 目录联接（junction）创建与移除，普通用户即可使用，无需管理员权限。

联接是本地目录的 reparse point，对应用透明地指向目标目录。Windows 上符号链接需要特权，
联接不需要，因此 ``current`` 指针在 Windows 上用联接实现。

创建通过 ``cmd /c mklink /J`` 完成（Python 子进程以 Unicode 传参，支持中文与空格路径）；
判别与读取用 ``os.lstat`` 和 ``os.readlink``；移除用 ``os.rmdir``（仅删除联接，不动目标）。
非 Windows 平台调用本模块函数会抛出 :class:`OSError`。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_IS_NT = os.name == "nt"
_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def _require_nt() -> None:
    if not _IS_NT:
        raise OSError("目录联接仅支持 Windows")


def is_junction(path: Path) -> bool:
    """判断路径是否为联接（mount point reparse point）。"""
    if not _IS_NT:
        return False
    try:
        result = os.lstat(path)
    except (OSError, ValueError):
        return False
    return getattr(result, "st_reparse_tag", 0) == _IO_REPARSE_TAG_MOUNT_POINT


def read_junction(path: Path) -> Path:
    """读取联接目标，去掉 ``\\\\?\\`` 前缀，返回普通 Win32 路径。"""
    _require_nt()
    target = os.readlink(path)
    if target.startswith("\\\\?\\"):
        target = target[4:]
    return Path(target)


def create_junction(link: Path, target: Path) -> None:
    """在 ``link`` 处创建指向 ``target`` 的联接；``link`` 必须不存在。"""
    _require_nt()
    if link.exists() or is_junction(link):
        raise FileExistsError(f"联接路径已存在：{link}")
    link.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), os.path.abspath(str(target))],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not is_junction(link):
        raise OSError(f"创建联接失败：{link} -> {target}（退出码 {completed.returncode}）")


def remove_junction(link: Path) -> None:
    """移除联接本身（不删除目标内容）；``link`` 必须是联接。"""
    _require_nt()
    if not is_junction(link):
        raise OSError(f"不是联接，无法移除：{link}")
    os.rmdir(link)
