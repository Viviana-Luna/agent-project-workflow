"""统一读取源码树或 ZipApp 中的安装资源。"""

from __future__ import annotations

import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


@dataclass(frozen=True)
class BundleEntry:
    relative: str
    data: bytes


class Bundle:
    def __init__(self, root: Path | None = None, archive: Path | None = None) -> None:
        if (root is None) == (archive is None):
            raise ValueError("Bundle 必须且只能指定目录或归档")
        self.root = root
        self.archive = archive

    @classmethod
    def discover(cls) -> "Bundle":
        argv0 = Path(sys.argv[0]).expanduser()
        if argv0.is_file() and zipfile.is_zipfile(argv0):
            return cls(archive=argv0.resolve())
        root = Path(__file__).resolve().parent.parent
        if not root.joinpath("adapters").is_dir() or not root.joinpath("skills").is_dir():
            raise RuntimeError("无法定位安装资源；请使用完整源码树或正式 apw.pyz")
        return cls(root=root)

    def read_bytes(self, relative: str) -> bytes:
        normalized = normalize_relative(relative)
        if self.root is not None:
            return self.root.joinpath(normalized).read_bytes()
        assert self.archive is not None
        with zipfile.ZipFile(self.archive) as archive:
            return archive.read(normalized)

    def read_text(self, relative: str) -> str:
        return self.read_bytes(relative).decode("utf-8")

    def names(self, prefix: str = "") -> list[str]:
        normalized = normalize_relative(prefix) if prefix else ""
        if self.root is not None:
            base = self.root / normalized
            if not base.exists():
                return []
            return sorted(path.relative_to(self.root).as_posix() for path in base.rglob("*") if path.is_file())
        assert self.archive is not None
        with zipfile.ZipFile(self.archive) as archive:
            names: list[str] = []
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                safe = normalize_relative(name)
                if not normalized or safe.startswith(f"{normalized}/"):
                    names.append(safe)
            return sorted(names)

    def entries(self, prefix: str) -> Iterable[BundleEntry]:
        for name in self.names(prefix):
            yield BundleEntry(name, self.read_bytes(name))


def normalize_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"安装资源路径不安全：{value!r}")
    return path.as_posix()
