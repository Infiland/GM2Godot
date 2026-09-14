"""Seal the three optional-extension bundles into their consumer manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast

PLATFORMS = ("darwin-arm64", "linux-x64", "win-x64")


def seal_manifest(directory: Path, source_revision: str, client_revision: str, version: str) -> Path:
    packages: dict[str, object] = {}
    for platform in PLATFORMS:
        fragment = cast(dict[str, Any], json.loads((directory / f"manifest-{platform}.json").read_text()))
        if fragment.get("testBuild") is not False:
            raise ValueError(f"{platform}: local test builds cannot be published")
        for key, expected in (("sourceRevision", source_revision), ("clientRevision", client_revision), ("version", version)):
            if fragment.get(key) != expected:
                raise ValueError(f"{platform}: mismatched {key}")
        if fragment.get("protocolVersion") != 1:
            raise ValueError(f"{platform}: unsupported protocol")
        package = cast(dict[str, Any], fragment["packages"][platform])
        name = f"gm2godot-deep-{version}-{platform}.zip"
        expected_url = f"https://github.com/Infiland/GM2Godot/releases/download/deep-v{version}/{name}"
        if package.get("url") != expected_url:
            raise ValueError(f"{platform}: incorrect immutable download URL")
        with (directory / name).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != package.get("sha256"):
            raise ValueError(f"{platform}: package checksum mismatch")
        packages[platform] = package
    path = directory / "deep-manifest.json"
    path.write_text(json.dumps({
        "protocolVersion": 1, "version": version, "minClientVersion": "0.8.0",
        "sourceRevision": source_revision, "clientRevision": client_revision, "packages": packages,
    }, indent=2) + "\n")
    return path


def read_lock(path: Path) -> dict[str, str]:
    value = cast(dict[str, str], json.loads(path.read_text()))
    if value.get("repository") != "Infiland/gm2godot-deep":
        raise ValueError("The extension source must be the official Deep repository")
    if not re.fullmatch(r"[0-9a-f]{40}", value.get("revision", "")):
        raise ValueError("Deep source must be pinned to an exact commit")
    if not re.fullmatch(r"\d+\.\d+\.\d+", value.get("version", "")):
        raise ValueError("Deep version must be a release version")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("packaging/deep.lock.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--client-revision")
    args = parser.parse_args()
    lock = read_lock(args.lock)
    if args.output is None:
        print(f"revision={lock['revision']}\nversion={lock['version']}")
    elif args.client_revision is None:
        parser.error("--client-revision is required to seal bundles")
    else:
        print(seal_manifest(args.output, lock["revision"], args.client_revision, lock["version"]))


if __name__ == "__main__":
    main()
