"""Opt-in managed OpenCode release, pinned to published GitHub asset digests."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from src.deep.install import (
    download_verified_transport,
    extract_package,
    opencode_path,
    platform_key,
)
from src.deep.settings import data_directory

OPENCODE_VERSION = "v1.18.30"
_ASSETS = {
    "darwin-arm64": ("opencode-darwin-arm64.zip", "a5e43d6887386efc7d68ce49ae28e3bbdfdee3dfd1d7169b612c3ce67e53b1e8"),
    "linux-x64": ("opencode-linux-x64.tar.gz", "55007246858165496ff85ba1c2b648f7421e8e2013bf4189a680c9ff8e699d17"),
    "win-x64": ("opencode-windows-x64.zip", "c8c0e0d05ac3dac544a0edfad8de9eb244bf46c6c7a131c38619d40fcf31bd1f"),
}


def install_opencode(root: Path | None = None) -> str:
    root = root or data_directory()
    existing = opencode_path(root)
    if existing:
        return existing
    root.mkdir(parents=True, exist_ok=True)
    name, digest = _ASSETS[platform_key()]
    with tempfile.TemporaryDirectory(dir=root, prefix="opencode-") as temporary:
        staging = Path(temporary)
        archive = staging / "download"
        download_verified_transport(f"https://github.com/anomalyco/opencode/releases/download/{OPENCODE_VERSION}/{name}", archive)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("OpenCode package checksum mismatch")
        extracted = staging / "extracted"
        extracted.mkdir()
        extract_package(archive, extracted)
        binary_name = "opencode.exe" if os.name == "nt" else "opencode"
        binaries = list(extracted.rglob(binary_name))
        if len(binaries) != 1:
            raise ValueError("OpenCode release must contain exactly one executable")
        destination = root / "opencode"
        destination.mkdir(exist_ok=True)
        target = destination / binary_name
        shutil.copyfile(binaries[0], target.with_suffix(".tmp"))
        target.with_suffix(".tmp").chmod(0o755)
        target.with_suffix(".tmp").replace(target)
        return str(target)
