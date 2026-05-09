import os
import platform
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
            download_url, asset_name = self._find_platform_asset(assets)

            return UpdateInfo(
                available=available,
                latest_version=latest_tag,
                release_notes=str(data.get("body", "")),
                download_url=download_url,
                asset_name=asset_name,
                release_page_url=str(data.get("html_url", "https://github.com/Infiland/GM2Godot/releases")),
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
    def _find_platform_asset(assets: Sequence[Mapping[str, Any]]) -> tuple[Optional[str], Optional[str]]:
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
                return (
                    cast(Optional[str], asset.get("browser_download_url")),
                    cast(Optional[str], asset.get("name")),
                )

        return None, None

    @staticmethod
    def download_update(
        url: str,
        dest_path: str,
        progress_callback: Callable[[int], None] | None = None,
    ) -> bool:
        """Download the update binary with progress reporting."""
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(int(downloaded / total_size * 100))

            return True
        except Exception:
            return False

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
