"""遵循 XDG 目录约定解析管理器用户路径。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .constants import APP_NAME


@dataclass(frozen=True)
class AppPaths:
    home: Path
    config_dir: Path
    data_dir: Path
    state_dir: Path
    cache_dir: Path
    bin_dir: Path

    @classmethod
    def from_home(cls, home: Path | None = None) -> "AppPaths":
        resolved = (home or Path.home()).expanduser().resolve()
        if os.name == "nt":
            if home is not None:
                root = resolved / APP_NAME
            else:
                local = Path(os.environ.get("LOCALAPPDATA") or resolved / "AppData" / "Local")
                root = local / APP_NAME
            config_dir = root / "config"
            data_dir = root / "data"
            state_dir = root / "state"
            cache_dir = root / "cache"
            bin_dir = root / "bin"
        elif home is not None:
            config_dir = resolved / ".config" / APP_NAME
            data_dir = resolved / ".local" / "share" / APP_NAME
            state_dir = resolved / ".local" / "state" / APP_NAME
            cache_dir = resolved / ".cache" / APP_NAME
            bin_dir = resolved / ".local" / "bin"
        else:
            config_dir = Path(os.environ.get("XDG_CONFIG_HOME", resolved / ".config")).expanduser() / APP_NAME
            data_dir = Path(os.environ.get("XDG_DATA_HOME", resolved / ".local" / "share")).expanduser() / APP_NAME
            state_dir = Path(os.environ.get("XDG_STATE_HOME", resolved / ".local" / "state")).expanduser() / APP_NAME
            cache_dir = Path(os.environ.get("XDG_CACHE_HOME", resolved / ".cache")).expanduser() / APP_NAME
            bin_dir = resolved / ".local" / "bin"
        return cls(
            home=resolved,
            config_dir=config_dir,
            data_dir=data_dir,
            state_dir=state_dir,
            cache_dir=cache_dir,
            bin_dir=bin_dir,
        )

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def legacy_config_file(self) -> Path:
        return self.home / ".codex" / "project-workflow.toml"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "install.json"

    @property
    def backups_dir(self) -> Path:
        return self.state_dir / "backups"

    @property
    def versions_dir(self) -> Path:
        return self.data_dir / "versions"

    @property
    def current_link(self) -> Path:
        return self.data_dir / "current"

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def launcher(self) -> Path:
        return self.bin_dir / ("apw.cmd" if os.name == "nt" else "apw")

    @property
    def long_launcher(self) -> Path:
        return self.bin_dir / (f"{APP_NAME}.cmd" if os.name == "nt" else APP_NAME)
