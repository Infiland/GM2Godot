import hashlib
import hmac
import os
import platform
import re
import stat
import tempfile
import requests
from dataclasses import dataclass
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Optional, cast

from src.version import get_version


@dataclass
class UpdateInfo:
    available: bool
    latest_version: str
    release_notes: str
    download_url: Optional[str]
    asset_name: Optional[str]
    release_page_url: str
    asset_digest: Optional[str] = None
    asset_size: Optional[int] = None


class UpdateChecker:
    GITHUB_API_URL = "https://api.github.com/repos/Infiland/GM2Godot/releases/latest"

    def check_for_update(self) -> Optional[UpdateInfo]:
        """Check GitHub for a newer release. Returns UpdateInfo or None on error."""
        try:
            response = requests.get(
                self.GITHUB_API_URL,
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=10,
            )
            response.raise_for_status()
            data = cast(Mapping[str, Any], response.json())

            latest_tag = str(data.get("tag_name", "")).lstrip("v")
            current = get_version()

            available = self._is_newer(latest_tag, current)

            # Find platform-appropriate asset
            assets = cast(Sequence[Mapping[str, Any]], data.get("assets", []))
            download_url, asset_name, asset_digest, asset_size = self._find_platform_asset(assets)

            return UpdateInfo(
                available=available,
                latest_version=latest_tag,
                release_notes=str(data.get("body", "")),
                download_url=download_url,
                asset_name=asset_name,
                release_page_url=str(data.get("html_url", "https://github.com/Infiland/GM2Godot/releases")),
                asset_digest=asset_digest,
                asset_size=asset_size,
            )
        except Exception:
            return None

    @staticmethod
    def _is_newer(latest: str, current: str) -> bool:
        """Compare version strings (e.g., '0.1.3' vs '0.1.2')."""
        try:
            latest_parts = [int(x) for x in latest.split(".")]
            current_parts = [int(x) for x in current.split(".")]
            return latest_parts > current_parts
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _find_platform_asset(
        assets: Sequence[Mapping[str, Any]],
    ) -> tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
        """Find the download URL for the current platform."""
        system = platform.system().lower()
        platform_keywords = {
            "windows": ["windows", "win", ".exe"],
            "darwin": ["macos", "mac", "darwin"],
            "linux": ["linux"],
        }
        keywords = platform_keywords.get(system, [])

        for asset in assets:
            name = str(asset.get("name", "")).lower()
            if any(kw in name for kw in keywords):
                raw_size = asset.get("size")
                asset_size = (
                    raw_size
                    if isinstance(raw_size, int) and not isinstance(raw_size, bool) and raw_size > 0
                    else None
                )
                return (
                    cast(Optional[str], asset.get("browser_download_url")),
                    cast(Optional[str], asset.get("name")),
                    UpdateChecker._normalize_sha256_digest(asset.get("digest")),
                    asset_size,
                )

        return None, None, None, None

    @staticmethod
    def _normalize_sha256_digest(value: object) -> Optional[str]:
        if not isinstance(value, str):
            return None
        match = re.fullmatch(r"(?i)sha256:([0-9a-f]{64})", value.strip())
        if match is None:
            return None
        return "sha256:" + match.group(1).lower()

    @staticmethod
    def download_update(
        url: str,
        dest_path: str,
        progress_callback: Callable[[int], None] | None = None,
        *,
        expected_digest: str | None = None,
        expected_size: int | None = None,
    ) -> bool:
        """Download, verify, and atomically publish an update artifact."""
        response: requests.Response | None = None
        temp_path: Optional[str] = None
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            normalized_digest = (
                UpdateChecker._normalize_sha256_digest(expected_digest)
                if expected_digest is not None
                else None
            )
            if expected_digest is not None and normalized_digest is None:
                raise ValueError("Expected digest must be a sha256:<64 hex characters> value")
            if expected_size is not None and (
                isinstance(expected_size, bool) or expected_size <= 0
            ):
                raise ValueError("Expected size must be a positive integer")

            content_length = response.headers.get("content-length")
            total_size: int | None = None
            if content_length is not None:
                normalized_content_length = content_length.strip(" \t")
                if (
                    not normalized_content_length
                    or not normalized_content_length.isascii()
                    or not normalized_content_length.isdecimal()
                ):
                    raise ValueError("Content-Length must contain only ASCII digits")
                total_size = int(normalized_content_length)
                if total_size == 0:
                    raise ValueError("Content-Length cannot be zero")
                if expected_size is not None and total_size != expected_size:
                    raise ValueError("Content-Length does not match release asset size")

            downloaded = 0
            digest = hashlib.sha256()
            absolute_dest_path = os.path.abspath(dest_path)
            dest_dir = os.path.dirname(absolute_dest_path)
            dest_name = os.path.basename(absolute_dest_path) or "update"
            existing_mode = (
                stat.S_IMODE(os.stat(absolute_dest_path).st_mode)
                if os.path.isfile(absolute_dest_path)
                else None
            )

            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{dest_name}.",
                suffix=".part",
                dir=dest_dir,
                delete=False,
            ) as f:
                temp_path = f.name
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    if total_size is not None and downloaded + len(chunk) > total_size:
                        return False
                    if expected_size is not None and downloaded + len(chunk) > expected_size:
                        return False
                    f.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size is not None and total_size > 0:
                        progress_callback(min(100, downloaded * 100 // total_size))

            if downloaded == 0:
                return False
            if total_size is not None and downloaded != total_size:
                return False
            if expected_size is not None and downloaded != expected_size:
                return False
            if normalized_digest is not None and not hmac.compare_digest(
                "sha256:" + digest.hexdigest(),
                normalized_digest,
            ):
                return False
            if existing_mode is not None:
                os.chmod(temp_path, existing_mode)

            os.replace(temp_path, absolute_dest_path)
            temp_path = None
            return True
        except Exception:
            return False
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if temp_path is not None:
                try:
                    os.remove(temp_path)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

    @staticmethod
    def get_skipped_version() -> Optional[str]:
        """Read the skipped version from config file."""
        config_dir = os.path.join(os.path.expanduser("~"), ".gm2godot")
        skip_file = os.path.join(config_dir, "skipped_version")
        try:
            with open(skip_file, "r") as f:
                return f.read().strip()
        except (OSError, IOError):
            return None

    @staticmethod
    def set_skipped_version(version: str) -> None:
        """Save a version to skip."""
        config_dir = os.path.join(os.path.expanduser("~"), ".gm2godot")
        os.makedirs(config_dir, exist_ok=True)
        skip_file = os.path.join(config_dir, "skipped_version")
        with open(skip_file, "w") as f:
            f.write(version)
