from __future__ import annotations

import hashlib
import os
from typing import Any

from src.conversion.included_file_registry import INCLUDED_FILE_REGISTRY_RELATIVE_PATH
from src.conversion.included_files_parts import constants as _included_constants
from src.conversion.included_files_parts.models import (
    IncludedRecoveryJournal as _IncludedRecoveryJournal,
)

_WINDOWS_RESERVED_RECOVERY_DEVICE_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
    }
    | {f"COM{suffix}" for suffix in "123456789¹²³"}
    | {f"LPT{suffix}" for suffix in "123456789¹²³"}
)

WINDOWS_RESERVED_RECOVERY_DEVICE_NAMES = _WINDOWS_RESERVED_RECOVERY_DEVICE_NAMES


def _windows_extended_included_path(path: str) -> str:
    """Return an absolute Win32 path that does not depend on MAX_PATH policy."""

    absolute_path = os.path.abspath(path)
    if absolute_path.startswith(("\\\\?\\", "\\\\.\\")):
        return absolute_path
    if absolute_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute_path[2:]
    return "\\\\?\\" + absolute_path


def _included_registry_path(project_path: str) -> str:
    return os.path.join(project_path, INCLUDED_FILE_REGISTRY_RELATIVE_PATH)


def _included_registry_backup_location(
    journal: _IncludedRecoveryJournal,
) -> str:
    transaction = journal.transaction
    project_path = os.path.dirname(transaction.stage_container_path)
    registry_directory = os.path.dirname(included_registry_path(project_path))
    registry_backup_parent = os.path.dirname(journal.registry_backup_path)
    if os.path.normcase(os.path.abspath(registry_backup_parent)) == os.path.normcase(
        os.path.abspath(project_path)
    ):
        registry_backup_location = "project"
    elif os.path.normcase(os.path.abspath(registry_backup_parent)) == os.path.normcase(
        os.path.abspath(registry_directory)
    ):
        registry_backup_location = "registry"
    else:
        raise OSError("Included File registry backup escaped its managed parents")
    return registry_backup_location


def _included_windows_recovery_component_is_ambiguous(component: str) -> bool:
    if len(component) >= 2 and component[1] == ":":
        # A drive-relative component such as ``D:payload`` can discard every
        # previously joined component when reconstructed with Windows paths.
        return True
    if component.startswith(" ") or component.endswith((" ", ".")):
        return True
    if any(
        ord(character) < 32 or character in '<>:"|?*'
        for character in component
    ):
        # This includes NTFS alternate-data-stream separators.
        return True
    device_stem = component.split(".", 1)[0].rstrip(" ").upper()
    return device_stem in WINDOWS_RESERVED_RECOVERY_DEVICE_NAMES


def _included_recovery_relative_path(value: Any) -> str:
    if not isinstance(value, str):
        raise OSError("Invalid Included Files recovery tree path")
    components = value.split("/")
    if (
        value == ""
        or value.startswith("/")
        or "\0" in value
        or "\\" in value
        or any(component in {"", ".", ".."} for component in components)
    ):
        raise OSError("Invalid Included Files recovery tree path")
    if os.name == "nt" and any(
        included_windows_recovery_component_is_ambiguous(component)
        for component in components
    ):
        raise OSError("Windows-ambiguous Included Files recovery tree path")
    return value


def _included_recovery_tree_entry_path(
    root_path: str,
    relative_path: str,
) -> str:
    """Reconstruct one journal path without permitting platform path resets."""

    validated_relative_path = included_recovery_relative_path(relative_path)
    components = validated_relative_path.split("/")
    absolute_root = os.path.abspath(root_path)
    native_relative_path = os.path.join(*components)
    absolute_entry = os.path.abspath(
        os.path.join(absolute_root, native_relative_path)
    )
    try:
        common_root = os.path.commonpath((absolute_root, absolute_entry))
        round_trip = os.path.relpath(absolute_entry, absolute_root)
    except ValueError as error:
        raise OSError(
            "Included Files recovery tree path escaped its recorded root"
        ) from error
    if (
        os.path.normcase(common_root) != os.path.normcase(absolute_root)
        or os.path.isabs(round_trip)
        or os.path.normcase(round_trip)
        != os.path.normcase(native_relative_path)
    ):
        raise OSError(
            "Included Files recovery tree path escaped its recorded root"
        )
    return absolute_entry


def _included_recovery_token(value: Any, length: int, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OSError(f"Invalid Included Files recovery {label}")
    return value


def _included_recovery_managed_name(
    value: Any,
    *,
    prefix: str,
    suffix: str,
    label: str,
) -> str:
    if not isinstance(value, str) or not value.startswith(prefix) or not value.endswith(suffix):
        raise OSError(f"Invalid Included Files recovery {label}")
    token = value[len(prefix):len(value) - len(suffix)]
    included_recovery_token(token, 16, label + " token")
    return value


def _included_recovery_record_tombstone_path(path: str) -> str:
    return included_cleanup_tombstone_path(
        path,
        "recovery-record",
        "record",
        os.path.basename(path),
        expect_directory=False,
    )


def _included_cleanup_tombstone_path(
    path: str,
    transaction_id: str,
    role: str,
    relative_path: str,
    *,
    expect_directory: bool,
) -> str:
    digest = hashlib.sha256(
        (transaction_id + "\0" + role + "\0" + relative_path).encode("utf-8")
    ).hexdigest()
    suffix = "dir" if expect_directory else "file"
    return os.path.join(
        os.path.dirname(os.path.abspath(path)),
        _included_constants.INCLUDED_FILES_CLEANUP_PREFIX + digest + "." + suffix,
    )


def _included_output_components(
    project_path: str,
    output_path: str,
) -> tuple[str, ...]:
    project_root = os.path.abspath(project_path)
    absolute_output = os.path.abspath(output_path)
    try:
        contained = os.path.normcase(
            os.path.commonpath((project_root, absolute_output))
        ) == os.path.normcase(project_root)
    except ValueError:
        contained = False
    relative_path = (
        os.path.relpath(absolute_output, project_root)
        if contained
        else os.pardir
    )
    components = tuple(relative_path.split(os.sep))
    if (
        not contained
        or os.path.isabs(relative_path)
        or len(components) < 2
        or components[0] != "included_files"
        or any(component in {"", ".", ".."} for component in components)
    ):
        raise ValueError(
            f"Generated Included File output escapes its managed root: {output_path}"
        )
    return components


# Finite compatibility exports; each operation has one actual owner.
windows_extended_included_path = _windows_extended_included_path
included_registry_path = _included_registry_path
included_registry_backup_location = _included_registry_backup_location
included_windows_recovery_component_is_ambiguous = _included_windows_recovery_component_is_ambiguous
included_recovery_relative_path = _included_recovery_relative_path
included_recovery_tree_entry_path = _included_recovery_tree_entry_path
included_recovery_token = _included_recovery_token
included_recovery_managed_name = _included_recovery_managed_name
included_recovery_record_tombstone_path = _included_recovery_record_tombstone_path
included_cleanup_tombstone_path = _included_cleanup_tombstone_path
included_output_components = _included_output_components
