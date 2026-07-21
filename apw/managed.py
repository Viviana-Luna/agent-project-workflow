"""规则托管区块、哈希和差异处理。"""

from __future__ import annotations

import difflib
import hashlib
import os
from pathlib import Path

from .constants import MANAGED_END, MANAGED_START


class ManagedBlockError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    if path.is_symlink():
        return sha256_bytes(f"symlink:{os.readlink(path)}".encode("utf-8"))
    if path.is_file():
        return sha256_bytes(path.read_bytes())
    if path.is_dir():
        digest = hashlib.sha256()
        for child in sorted(item for item in path.rglob("*") if item.is_file() or item.is_symlink()):
            relative = child.relative_to(path).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(sha256_path(child).encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()
    return ""


def render_block(content: str) -> str:
    body = content.strip()
    return f"{MANAGED_START}\n{body}\n{MANAGED_END}"


def block_content(text: str) -> str | None:
    starts = text.count(MANAGED_START)
    ends = text.count(MANAGED_END)
    if not starts and not ends:
        return None
    if starts != 1 or ends != 1:
        raise ManagedBlockError("托管区块标记缺失或重复")
    start = text.index(MANAGED_START)
    try:
        end = text.index(MANAGED_END, start)
    except ValueError as exc:
        raise ManagedBlockError("托管区块结束标记位于开始标记之前") from exc
    return text[start + len(MANAGED_START) : end].strip("\n")


def merge_block(existing: str, content: str) -> str:
    rendered = render_block(content)
    current = block_content(existing)
    if current is None:
        prefix = existing.rstrip()
        return f"{prefix}\n\n{rendered}\n" if prefix else f"{rendered}\n"
    start = existing.index(MANAGED_START)
    end = existing.index(MANAGED_END, start) + len(MANAGED_END)
    return f"{existing[:start]}{rendered}{existing[end:]}"


def remove_block(existing: str) -> str:
    if block_content(existing) is None:
        return existing
    start = existing.index(MANAGED_START)
    end = existing.index(MANAGED_END, start) + len(MANAGED_END)
    result = f"{existing[:start]}{existing[end:]}".strip()
    return f"{result}\n" if result else ""


def unified_diff(old: str, new: str, path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"{path}（当前）",
            tofile=f"{path}（计划）",
        )
    )
