#!/usr/bin/env python3
"""构建可发布 ZipApp、Bootstrap、清单和校验文件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipapp
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PYTHON_VERSION = "3.12.13"
UV_VERSION = "0.11.16"
REPOSITORY = "https://github.com/Viviana-Luna/agent-project-workflow"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建 Agent Project Workflow Release 资产")
    parser.add_argument("--version", default=None, help="发布版本，默认读取 apw.__version__")
    parser.add_argument("--output", default="dist", help="输出目录")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_version() -> str:
    namespace: dict[str, str] = {}
    exec((ROOT / "apw" / "__init__.py").read_text(encoding="utf-8"), namespace)
    return str(namespace["__version__"])


def build_zipapp(output: Path) -> Path:
    target = output / "apw.pyz"
    with tempfile.TemporaryDirectory(prefix="apw-build-") as temp:
        staging = Path(temp)
        for name in ("apw", "adapters", "skills", "templates"):
            shutil.copytree(ROOT / name, staging / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (staging / "__main__.py").write_text(
            "from apw.cli import main\nraise SystemExit(main())\n",
            encoding="utf-8",
        )
        zipapp.create_archive(staging, target=target, interpreter="/usr/bin/env python3", compressed=True)
    target.chmod(0o755)
    return target


def build_installer(output: Path, version: str, pyz_sha256: str) -> Path:
    template = (ROOT / "scripts" / "install.sh.template").read_text(encoding="utf-8")
    rendered = (
        template.replace("@VERSION@", version)
        .replace("@PYTHON_VERSION@", PYTHON_VERSION)
        .replace("@UV_VERSION@", UV_VERSION)
        .replace("@APW_SHA256@", pyz_sha256)
    )
    target = output / "install.sh"
    target.write_text(rendered, encoding="utf-8")
    target.chmod(0o755)
    return target


def build_installer_windows(output: Path, version: str, pyz_sha256: str) -> Path:
    template = (ROOT / "scripts" / "install.ps1.template").read_text(encoding="utf-8")
    rendered = (
        template.replace("@VERSION@", version)
        .replace("@PYTHON_VERSION@", PYTHON_VERSION)
        .replace("@UV_VERSION@", UV_VERSION)
        .replace("@APW_SHA256@", pyz_sha256)
    )
    target = output / "install.ps1"
    target.write_text(rendered, encoding="utf-8-sig")
    return target


def main() -> int:
    args = parse_args()
    version = args.version or current_version()
    if version.startswith("v"):
        version = version[1:]
    if version != current_version():
        raise SystemExit(f"发布版本 {version} 与代码版本 {current_version()} 不一致")
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    pyz = build_zipapp(output)
    installer = build_installer(output, version, sha256(pyz))
    installer_windows = build_installer_windows(output, version, sha256(pyz))
    base = f"{REPOSITORY}/releases/download/v{version}"
    manifest = {
        "schema_version": 1,
        "version": version,
        "minimum_manager_version": "1.0.0",
        "release_notes": "首个稳定版安装与更新管理器。",
        "runtime": {"python": PYTHON_VERSION, "uv": UV_VERSION},
        "assets": {
            "apw.pyz": {"url": f"{base}/apw.pyz", "sha256": sha256(pyz)},
            "install.sh": {"url": f"{base}/install.sh", "sha256": sha256(installer)},
            "install.ps1": {"url": f"{base}/install.ps1", "sha256": sha256(installer_windows)},
        },
    }
    manifest_path = output / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assets = (pyz, installer, installer_windows, manifest_path)
    sums = "".join(f"{sha256(path)}  {path.name}\n" for path in assets)
    (output / "SHA256SUMS").write_text(sums, encoding="utf-8")
    print(f"构建完成：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
