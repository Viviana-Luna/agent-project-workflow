"""管理器安装状态模型与原子持久化。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import STATE_SCHEMA_VERSION


@dataclass
class InstallationRecord:
    key: str
    path: str
    kind: str
    digest: str
    clients: list[str] = field(default_factory=list)


@dataclass
class InstallState:
    schema_version: int = STATE_SCHEMA_VERSION
    manager_version: str = ""
    selected_clients: list[str] = field(default_factory=list)
    installations: dict[str, InstallationRecord] = field(default_factory=dict)
    runtime: dict[str, str] = field(default_factory=dict)
    installed_at: str = ""
    updated_at: str = ""

    @classmethod
    def empty(cls, version: str) -> "InstallState":
        now = utc_now()
        return cls(manager_version=version, installed_at=now, updated_at=now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstallState":
        if data.get("schema_version") != STATE_SCHEMA_VERSION:
            raise ValueError(f"不支持的安装状态版本：{data.get('schema_version')!r}")
        records = {
            key: InstallationRecord(
                key=key,
                path=str(value["path"]),
                kind=str(value["kind"]),
                digest=str(value["digest"]),
                clients=[str(item) for item in value.get("clients", [])],
            )
            for key, value in dict(data.get("installations", {})).items()
        }
        return cls(
            schema_version=STATE_SCHEMA_VERSION,
            manager_version=str(data.get("manager_version", "")),
            selected_clients=[str(item) for item in data.get("selected_clients", [])],
            installations=records,
            runtime={str(key): str(value) for key, value in dict(data.get("runtime", {})).items()},
            installed_at=str(data.get("installed_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["installations"] = {key: asdict(record) for key, record in sorted(self.installations.items())}
        return data


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state(path: Path, version: str) -> InstallState:
    if not path.is_file():
        return InstallState.empty(version)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取安装状态 {path}：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"安装状态必须是 JSON 对象：{path}")
    try:
        return InstallState.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"安装状态结构无效 {path}：{exc}") from exc


def atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as file_obj:
            file_obj.write(data)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        if mode is not None:
            temp_path.chmod(mode)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def save_state(path: Path, state: InstallState) -> None:
    state.updated_at = utc_now()
    payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    atomic_write(path, payload, mode=0o600)
