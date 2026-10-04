"""Application asset lookup for source, frozen roots, and unpacked wheel installs.

The existing callers handle their frozen branch before selecting a source or
wheel base. Packaged assets are immutable defaults; only wheel preferences use
the user-owned application directory.
"""

from __future__ import annotations

import os


def packaged_application_asset_base() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "application_assets")


def application_resource_base(source_base: str) -> str:
    packaged_base = packaged_application_asset_base()
    if os.path.isfile(os.path.join(packaged_base, "Current Language")):
        return packaged_base
    return source_base


def is_packaged_application_base(base: str) -> bool:
    return base == packaged_application_asset_base()


def application_preferences_directory() -> str:
    return os.path.join(os.path.expanduser("~"), ".gm2godot")


def language_preference_read_path(base: str) -> str:
    if is_packaged_application_base(base):
        user_path = os.path.join(application_preferences_directory(), "Current Language")
        if os.path.exists(user_path):
            return user_path
    return os.path.join(base, "Current Language")


def language_preference_write_path(base: str) -> str:
    if is_packaged_application_base(base):
        user_directory = application_preferences_directory()
        os.makedirs(user_directory, exist_ok=True)
        return os.path.join(user_directory, "Current Language")
    return os.path.join(base, "Current Language")
