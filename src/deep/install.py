"""Verified, atomic optional dependency installation without a source checkout."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from src.deep.settings import data_directory
from src.version import get_version

DEFAULT_MANIFEST_URL = "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.0/deep-manifest.json"


def platform_key() -> str:
    system = {"Darwin": "darwin", "Windows": "win", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "AMD64": "x64", "x86_64": "x64"}.get(platform.machine())
    key = f"{system}-{arch}"
    if key not in {"darwin-arm64", "win-x64", "linux-x64"}:
        raise ValueError(f"Deep packages are unavailable for {key}")
    return key


def _relative_path(value: str) -> Path:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise ValueError("Unsafe package path")
    return Path(*path.parts)


def download_verified_transport(url: str, destination: Path) -> None:
    if not url.startswith("https://"):
        raise ValueError("Dependency downloads require HTTPS")
    with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as stream:
        if not response.url.startswith("https://"):
            raise ValueError("Download redirected to insecure URL")
        shutil.copyfileobj(response, stream)


def _extract_zip(archive: Path, target: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = target / _relative_path(member.filename.rstrip("/"))
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("Package symlinks are not allowed")
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                path.chmod(0o755 if mode & 0o111 else 0o644)


def _extract_tar(archive: Path, target: Path) -> None:
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            relative = _relative_path(member.name.rstrip("/"))
            if not member.isfile() and not member.isdir():
                raise ValueError("Package links and special files are not allowed")
            path = target / relative
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise ValueError("Unreadable package member")
                with source, path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)


def extract_package(archive: Path, target: Path) -> None:
    if zipfile.is_zipfile(archive):
        _extract_zip(archive, target)
    else:
        _extract_tar(archive, target)


def _validate_manifest(manifest: dict[str, Any]) -> str:
    if manifest.get("protocolVersion") != 1:
        raise ValueError("Incompatible Deep protocol version")
    required = str(manifest.get("minClientVersion", "0.0.0"))
    def version_parts(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in re.findall(r"\d+", value)[:3])
    if version_parts(get_version()) < version_parts(required):
        raise ValueError(f"Deep requires GM2Godot {required} or later")
    version = str(manifest["version"])
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", version) or version in {".", ".."}:
        raise ValueError("Invalid extension version")
    return version


class ExtensionManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_directory()

    def install(self, manifest_url: str = DEFAULT_MANIFEST_URL) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root, prefix="install-") as temporary:
            staging = Path(temporary)
            manifest_path = staging / "manifest.json"
            download_verified_transport(manifest_url, manifest_path)
            manifest: dict[str, Any] = json.loads(manifest_path.read_text())
            version = _validate_manifest(manifest)
            package: dict[str, Any] = manifest["packages"][platform_key()]
            archive = staging / "package"
            digest = str(package["sha256"])
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid package checksum")
            cache = self.root / "cache" / digest
            cache_valid = False
            if cache.is_file():
                with cache.open("rb") as cached_stream:
                    cache_valid = hashlib.file_digest(cached_stream, "sha256").hexdigest() == digest
            if cache_valid:
                shutil.copyfile(cache, archive)
            else:
                download_verified_transport(str(package["url"]), archive)
            with archive.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError("Deep package checksum mismatch")
            cache.parent.mkdir(exist_ok=True)
            shutil.copyfile(archive, cache)
            extracted = staging / "extracted"
            extracted.mkdir()
            extract_package(archive, extracted)
            for field in ("runtime", "entrypoint"):
                if not (extracted / _relative_path(str(package[field]))).is_file():
                    raise ValueError(f"Package missing {field}")
            file_hashes: dict[str, str] = {}
            for file in extracted.rglob("*"):
                if file.is_file():
                    with file.open("rb") as stream:
                        file_hashes[file.relative_to(extracted).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
            (extracted / "install.json").write_text(json.dumps({"manifest": manifest, "package": package, "fileHashes": file_hashes}))
            versions = self.root / "versions"
            versions.mkdir(exist_ok=True)
            # Content addressed directories retain versions pinned by existing jobs.
            destination = versions / f"{version}-{digest[:16]}"
            if destination.exists():
                try:
                    self.command(destination)
                except (ValueError, OSError, KeyError):
                    destination = versions / f"{version}-{digest[:16]}-repair-{uuid.uuid4().hex[:8]}"
            if not destination.exists():
                extracted.replace(destination)
            active = self.root / "active.tmp"
            active.write_text(destination.name)
            active.replace(self.root / "active")
            return destination

    def installation(self) -> Path:
        active = self.root / "active"
        if not active.is_file():
            raise FileNotFoundError("Deep components are not installed. Open Settings → Deep setup.")
        return self.root / "versions" / _relative_path(active.read_text().strip())

    def command(self, installation: Path | None = None) -> list[str]:
        location = installation or self.installation()
        descriptor: dict[str, Any] = json.loads((location / "install.json").read_text())
        package: dict[str, Any] = descriptor["package"]
        hashes: dict[str, str] = descriptor.get("fileHashes", {})
        if not hashes:
            raise ValueError("Installed Deep package lacks integrity records; repair its installation")
        for name, expected in hashes.items():
            with (location / _relative_path(name)).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError("Installed Deep package changed; repair its installation")
        return [str(location / _relative_path(str(package["runtime"]))), str(location / _relative_path(str(package["entrypoint"])))]


def opencode_path(root: Path | None = None) -> str | None:
    existing = shutil.which("opencode")
    if existing:
        return existing
    managed = (root or data_directory()) / "opencode" / ("opencode.exe" if os.name == "nt" else "opencode")
    return str(managed) if managed.is_file() else None
