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
        if home is not None:
            config_home = resolved / ".config"
            data_home = resolved / ".local" / "share"
            state_home = resolved / ".local" / "state"
            cache_home = resolved / ".cache"
        else:
            config_home = Path(os.environ.get("XDG_CONFIG_HOME", resolved / ".config")).expanduser()
            data_home = Path(os.environ.get("XDG_DATA_HOME", resolved / ".local" / "share")).expanduser()
            state_home = Path(os.environ.get("XDG_STATE_HOME", resolved / ".local" / "state")).expanduser()
            cache_home = Path(os.environ.get("XDG_CACHE_HOME", resolved / ".cache")).expanduser()
        return cls(
            home=resolved,
            config_dir=config_home / APP_NAME,
            data_dir=data_home / APP_NAME,
            state_dir=state_home / APP_NAME,
            cache_dir=cache_home / APP_NAME,
            bin_dir=resolved / ".local" / "bin",
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
        return self.bin_dir / "apw"

    @property
    def long_launcher(self) -> Path:
        return self.bin_dir / APP_NAME
