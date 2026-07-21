"""冲突目标的可恢复压缩归档。"""

from __future__ import annotations

import json
import io
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from .managed import sha256_path


def archive_name(path: Path, home: Path) -> str:
    try:
        return f"home/{path.absolute().relative_to(home.absolute()).as_posix()}"
    except ValueError:
        safe = path.name or "target"
        return f"external/{sha256_path(path)[:12]}-{safe}"


def create_archive(targets: list[Path], home: Path, backups_dir: Path) -> Path:
    existing = sorted({path.absolute() for path in targets if path.exists() or path.is_symlink()})
    if not existing:
        raise ValueError("没有可归档的冲突目标")
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive_path = backups_dir / f"migration-{stamp}.tar.gz"
    manifest = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "targets": [
            {"path": str(path), "archive_path": archive_name(path, home), "sha256": sha256_path(path)}
            for path in existing
        ],
    }
    with tarfile.open(archive_path, "x:gz") as archive:
        for path in existing:
            archive.add(path, arcname=archive_name(path, home), recursive=True)
        payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        info.mode = 0o600
        archive.addfile(info, fileobj=io.BytesIO(payload))
    archive_path.chmod(0o600)
    return archive_path
