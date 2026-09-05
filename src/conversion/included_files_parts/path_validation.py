from __future__ import annotations

import os

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


def output_components(
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


def recovery_relative_path(value: object) -> str:
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
        windows_recovery_component_is_ambiguous(component)
        for component in components
    ):
        raise OSError("Windows-ambiguous Included Files recovery tree path")
    return value


def recovery_tree_entry_path(
    root_path: str,
    relative_path: str,
) -> str:
    """Reconstruct one journal path without permitting platform path resets."""

    validated_relative_path = recovery_relative_path(relative_path)
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


def windows_recovery_component_is_ambiguous(component: str) -> bool:
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
    return device_stem in _WINDOWS_RESERVED_RECOVERY_DEVICE_NAMES
