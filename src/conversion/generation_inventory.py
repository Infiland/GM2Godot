"""Deterministic, bounded inventories for one managed-output generation."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import stat
import sys
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, cast

from src.conversion.anchored_artifacts import VerifiedDirectory, modes_match
from src.conversion.conversion_artifact_generation import (
    is_conversion_generation_auxiliary,
)
from src.conversion.conversion_plan import conversion_step_map
from src.conversion.managed_output_workspace import (
    DESTINATION_LOCK_NAME,
    WORKSPACE_PARENT_NAME,
    WORKSPACE_STAGE_MARKER_NAME,
    ManagedFileSnapshot,
    ManagedOutputWorkspace,
    StagedFileReceipt,
)
from src.conversion.project_godot import (
    GODOT_PROJECT_FILENAME,
    MANAGED_OUTPUT_DIRECTORIES,
    MANAGED_OUTPUT_FILES,
)


GENERATION_INVENTORY_FORMAT_VERSION = 1
GENERATION_INVENTORY_MAX_BYTES = 32 * 1024 * 1024
GENERATION_INVENTORY_MAX_ENTRIES = 100_000
GENERATION_INVENTORY_MAX_PATH_BYTES = 4096

_MANIFEST_RELATIVE_PATH = "gm2godot/conversion_manifest.json"
_ATTEMPT_RELATIVE_PATH = "gm2godot/conversion_attempt.json"
_READ_CHUNK_BYTES = 1024 * 1024
_MAX_DIRECTORY_COUNT = GENERATION_INVENTORY_MAX_ENTRIES * 2
_MAX_DIRECTORY_DEPTH = 128
_MAX_FILE_BYTE_COUNT = (1 << 63) - 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_KIND_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_OWNER_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_PRIVATE_FILE_PATTERN = re.compile(
    r"\..+\.[A-Za-z0-9_-]{1,128}\."
    r"(?:tmp|backup|recovery\.backup|tombstone)\Z"
)
_WINDOWS_RESERVED_NAMES = frozenset(
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
_IMAGE_EXTENSIONS = frozenset(
    {".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
)
_AUDIO_EXTENSIONS = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
)
_FONT_EXTENSIONS = frozenset({".otf", ".ttf", ".woff", ".woff2"})

InventoryOwnerClass = Literal["converter_step", "shared_owner"]


@dataclass(frozen=True, slots=True)
class GenerationInventoryOwner:
    """The converter step or shared ownership class for one output."""

    owner_class: InventoryOwnerClass
    name: str

    def __post_init__(self) -> None:
        if self.owner_class not in {"converter_step", "shared_owner"}:
            raise ValueError("Generation inventory owner class is invalid.")
        if _OWNER_NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError(
                f"Generation inventory owner name is invalid: {self.name!r}"
            )
        if (
            self.owner_class == "converter_step"
            and self.name not in conversion_step_map()
        ):
            raise ValueError(
                f"Generation inventory owner names an unknown converter: {self.name!r}"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "class": self.owner_class,
            "name": self.name,
        }

    @classmethod
    def from_value(cls, value: object) -> GenerationInventoryOwner:
        payload = _string_key_mapping(value, "inventory owner")
        if payload.keys() != {"class", "name"}:
            raise OSError("Invalid generation inventory owner fields")
        owner_class = payload["class"]
        name = payload["name"]
        if not isinstance(owner_class, str) or owner_class not in {
            "converter_step",
            "shared_owner",
        }:
            raise OSError("Invalid generation inventory owner class")
        if not isinstance(name, str):
            raise OSError("Invalid generation inventory owner name")
        try:
            return cls(cast(InventoryOwnerClass, owner_class), name)
        except ValueError as error:
            raise OSError(str(error)) from error


@dataclass(frozen=True, slots=True)
class GenerationInventoryEntry:
    """Immutable content and rollback metadata for one managed regular file."""

    path: str
    kind: str
    owner: GenerationInventoryOwner
    byte_count: int
    sha256: str
    mode: int

    def __post_init__(self) -> None:
        normalized_path = normalize_generation_inventory_path(self.path)
        object.__setattr__(self, "path", normalized_path)
        if _is_inventory_auxiliary(normalized_path):
            raise ValueError(
                f"Generation inventory path targets private transaction state: "
                f"{normalized_path!r}"
            )
        if not _is_managed_output_path(normalized_path):
            raise ValueError(
                f"Generation inventory path is outside documented managed output: "
                f"{normalized_path!r}"
            )
        expected_kind = generation_output_kind(normalized_path)
        if self.kind != expected_kind:
            raise ValueError(
                f"Generation inventory kind for {normalized_path!r} must be "
                f"{expected_kind!r}, got {self.kind!r}."
            )
        expected_owner = generation_output_owner(normalized_path)
        if self.owner != expected_owner:
            raise ValueError(
                f"Generation inventory owner for {normalized_path!r} must be "
                f"{expected_owner!r}, got {self.owner!r}."
            )
        if (
            type(self.byte_count) is not int
            or self.byte_count < 0
            or self.byte_count > _MAX_FILE_BYTE_COUNT
        ):
            raise ValueError(
                f"Generation inventory byte count is invalid: {self.byte_count!r}"
            )
        if _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError(
                f"Generation inventory digest is invalid: {self.sha256!r}"
            )
        if type(self.mode) is not int or not 0 <= self.mode <= 0o7777:
            raise ValueError(
                f"Generation inventory mode is invalid: {self.mode!r}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "owner": self.owner.to_dict(),
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "mode": self.mode,
        }

    def to_generated_file_dict(self) -> dict[str, object]:
        """Render the backward-compatible format-v2 generated-files view."""

        return {
            "path": self.path,
            "kind": self.kind,
            "sha256": self.sha256,
        }

    @classmethod
    def from_value(cls, value: object) -> GenerationInventoryEntry:
        payload = _string_key_mapping(value, "inventory entry")
        expected_fields = {
            "path",
            "kind",
            "owner",
            "byte_count",
            "sha256",
            "mode",
        }
        if payload.keys() != expected_fields:
            raise OSError("Invalid generation inventory entry fields")
        path = payload["path"]
        kind = payload["kind"]
        byte_count = payload["byte_count"]
        digest = payload["sha256"]
        mode = payload["mode"]
        if not isinstance(path, str) or not isinstance(kind, str):
            raise OSError("Invalid generation inventory entry path or kind")
        if type(byte_count) is not int or not isinstance(digest, str):
            raise OSError("Invalid generation inventory entry content receipt")
        if type(mode) is not int:
            raise OSError("Invalid generation inventory entry mode")
        try:
            entry = cls(
                path=path,
                kind=kind,
                owner=GenerationInventoryOwner.from_value(payload["owner"]),
                byte_count=byte_count,
                sha256=digest,
                mode=mode,
            )
        except ValueError as error:
            raise OSError(str(error)) from error
        if entry.path != path:
            raise OSError("Generation inventory entry path is not canonical")
        return entry


@dataclass(frozen=True, slots=True)
class GenerationInventory:
    """A canonical immutable inventory sorted independently of enumeration."""

    entries: tuple[GenerationInventoryEntry, ...] = ()

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        if len(entries) > GENERATION_INVENTORY_MAX_ENTRIES:
            raise ValueError(
                "Generation inventory exceeds "
                f"{GENERATION_INVENTORY_MAX_ENTRIES} entries."
            )
        ordered = tuple(sorted(entries, key=lambda entry: entry.path))
        _validate_inventory_paths(ordered)
        object.__setattr__(self, "entries", ordered)
        if len(self.to_bytes()) > GENERATION_INVENTORY_MAX_BYTES:
            raise ValueError(
                "Generation inventory exceeds "
                f"{GENERATION_INVENTORY_MAX_BYTES} canonical bytes."
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": GENERATION_INVENTORY_FORMAT_VERSION,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def by_path(self) -> dict[str, GenerationInventoryEntry]:
        return {entry.path: entry for entry in self.entries}

    @classmethod
    def from_value(cls, value: object) -> GenerationInventory:
        payload = _string_key_mapping(value, "inventory")
        if payload.keys() != {"format_version", "entries"}:
            raise OSError("Invalid generation inventory fields")
        if payload["format_version"] != GENERATION_INVENTORY_FORMAT_VERSION:
            raise OSError("Unsupported generation inventory format")
        raw_entries = payload["entries"]
        if not isinstance(raw_entries, list):
            raise OSError("Invalid generation inventory entries")
        typed_entries = cast(list[object], raw_entries)
        if len(typed_entries) > GENERATION_INVENTORY_MAX_ENTRIES:
            raise OSError("Generation inventory contains too many entries")
        entries = tuple(
            GenerationInventoryEntry.from_value(entry) for entry in typed_entries
        )
        try:
            inventory = cls(entries)
        except (TypeError, ValueError) as error:
            raise OSError(str(error)) from error
        if entries != inventory.entries:
            raise OSError("Generation inventory entries are not canonically sorted")
        return inventory


def normalize_generation_inventory_path(path: str | os.PathLike[str]) -> str:
    """Return one NFC, slash-separated, destination-relative path."""

    raw_value = os.fspath(path)
    value = unicodedata.normalize("NFC", raw_value.replace("\\", "/"))
    if (
        not value
        or value.startswith("/")
        or "\x00" in value
        or posixpath.normpath(value) != value
        or len(value.encode("utf-8")) > GENERATION_INVENTORY_MAX_PATH_BYTES
    ):
        raise ValueError(
            f"Generation inventory path is not normalized and relative: {raw_value!r}"
        )
    components = value.split("/")
    for component in components:
        windows_stem = component.rstrip(" .").split(".", 1)[0].upper()
        if (
            component in {"", ".", ".."}
            or component.endswith((" ", "."))
            or ":" in component
            or any(ord(character) < 32 for character in component)
            or windows_stem in _WINDOWS_RESERVED_NAMES
        ):
            raise ValueError(
                f"Generation inventory path component is unsafe: {component!r}"
            )
    if components[0] in {".godot", DESTINATION_LOCK_NAME, WORKSPACE_PARENT_NAME}:
        raise ValueError(
            f"Generation inventory path targets excluded private state: {value!r}"
        )
    if any(component == WORKSPACE_STAGE_MARKER_NAME for component in components):
        raise ValueError(
            f"Generation inventory path targets a workspace marker: {value!r}"
        )
    return value


def generation_output_kind(path: str | os.PathLike[str]) -> str:
    normalized = normalize_generation_inventory_path(path)
    if normalized == GODOT_PROJECT_FILENAME:
        return "project"
    if normalized.endswith(".gmlmap.json"):
        return "source_map"
    if normalized.endswith(".gdshader"):
        return "shader"
    if normalized.endswith(".gd"):
        return "gdscript"
    if normalized.endswith(".tscn"):
        return "scene"
    if normalized.endswith(".tres"):
        return "resource"
    if normalized.endswith((".json", ".md")):
        return "report"
    extension = posixpath.splitext(normalized)[1].lower()
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension in _AUDIO_EXTENSIONS:
        return "audio"
    if extension in _FONT_EXTENSIONS:
        return "font"
    if extension == ".import":
        return "import_metadata"
    return "file"


def generation_output_owner(
    path: str | os.PathLike[str],
) -> GenerationInventoryOwner:
    normalized = normalize_generation_inventory_path(path)
    components = normalized.split("/")
    if normalized == GODOT_PROJECT_FILENAME:
        return GenerationInventoryOwner("shared_owner", "project_configuration")
    if normalized in {"icon.ico", "icon.png"}:
        return GenerationInventoryOwner("converter_step", "game_icon")
    if normalized == "default_bus_layout.tres":
        return GenerationInventoryOwner("converter_step", "audio_buses")
    root = components[0]
    root_owner = {
        "fonts": "fonts",
        "included_files": "included_files",
        "notes": "notes",
        "objects": "objects",
        "paths": "asset_registry",
        "rooms": "rooms",
        "scripts": "scripts",
        "shaders": "shaders",
        "sounds": "sounds",
        "sprites": "sprites",
        "tilesets": "tilesets",
    }.get(root)
    if root_owner is not None:
        return GenerationInventoryOwner("converter_step", root_owner)
    if components[:2] == ["addons", "gm2godot_extensions"]:
        return GenerationInventoryOwner("converter_step", "asset_registry")
    if root != "gm2godot":
        raise ValueError(f"Unknown managed generation owner for {normalized!r}")
    relative = "/".join(components[1:])
    if relative == "gml_script_registry.gd":
        return GenerationInventoryOwner("converter_step", "scripts")
    if relative == "gml_room_node.gd":
        return GenerationInventoryOwner("converter_step", "rooms")
    if relative == "gml_included_file_registry.gd":
        return GenerationInventoryOwner("converter_step", "included_files")
    if (
        relative in {"gml_runtime.gd"}
        or relative.startswith("managers/")
    ):
        return GenerationInventoryOwner("shared_owner", "runtime_support")
    if relative in {
        "architecture_policy.json",
        "conversion_diagnostics.json",
        "conversion_diagnostics.md",
    }:
        return GenerationInventoryOwner("shared_owner", "conversion_evidence")
    if relative == "godot_validation_report.json":
        return GenerationInventoryOwner("shared_owner", "validation_evidence")
    if (
        relative
        in {
            "gml_asset_registry.gd",
            "gml_path_registry.gd",
            "gml_animation_curve_registry.gd",
            "group_compatibility_report.json",
            "extension_compatibility_report.json",
        }
        or relative.startswith("timelines/")
    ):
        return GenerationInventoryOwner("converter_step", "asset_registry")
    return GenerationInventoryOwner("shared_owner", "conversion_support")


def capture_generation_inventory(
    root_path: str | os.PathLike[str],
    *,
    previous_inventory: GenerationInventory | None = None,
    enabled_converters: Iterable[str] | None = None,
) -> GenerationInventory:
    """Capture every documented managed file through verified bindings."""

    root_value = os.fspath(root_path)
    try:
        root_stat = os.lstat(root_value)
    except FileNotFoundError:
        inventory = GenerationInventory()
        if previous_inventory is not None and enabled_converters is not None:
            _validate_disabled_carry_forward(
                previous_inventory,
                inventory,
                enabled_converters,
            )
        return inventory
    if _path_is_redirected(root_value, root_stat) or not stat.S_ISDIR(
        root_stat.st_mode
    ):
        raise OSError(
            f"Refusing redirected or non-directory generation root: {root_value}"
        )

    entries: list[GenerationInventoryEntry] = []
    directory_counter = [0]
    with VerifiedDirectory.open(
        root_value,
        description="generation inventory root",
    ) as root:
        root_stat = _binding_stat(root)
        root_device = root_stat.st_dev
        root_mount_id = _linux_mount_id(root)
        _capture_named_file_if_present(
            root,
            GODOT_PROJECT_FILENAME,
            GODOT_PROJECT_FILENAME,
            entries,
            root_device=root_device,
            root_mount_id=root_mount_id,
        )
        for relative_path in MANAGED_OUTPUT_FILES:
            normalized = normalize_generation_inventory_path(relative_path)
            _capture_named_file_if_present(
                root,
                normalized,
                normalized,
                entries,
                root_device=root_device,
                root_mount_id=root_mount_id,
            )
        for managed_root in MANAGED_OUTPUT_DIRECTORIES:
            components = tuple(
                normalize_generation_inventory_path(managed_root).split("/")
            )
            _capture_managed_root(
                root,
                components,
                entries,
                directory_counter=directory_counter,
                root_device=root_device,
                root_mount_id=root_mount_id,
            )
        root.verify_path()

    inventory = GenerationInventory(tuple(entries))
    if previous_inventory is not None and enabled_converters is not None:
        _validate_disabled_carry_forward(
            previous_inventory,
            inventory,
            enabled_converters,
        )
    return inventory


def validate_generation_inventory(
    root_path: str | os.PathLike[str],
    inventory: GenerationInventory,
) -> None:
    """Rehash a generation and require exact topology, bytes, and modes."""

    actual = capture_generation_inventory(root_path)
    if actual == inventory:
        return
    expected_by_path = inventory.by_path()
    actual_by_path = actual.by_path()
    changed = sorted(
        path
        for path in expected_by_path.keys() & actual_by_path.keys()
        if expected_by_path[path] != actual_by_path[path]
    )
    missing = sorted(expected_by_path.keys() - actual_by_path.keys())
    unexpected = sorted(actual_by_path.keys() - expected_by_path.keys())
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(repr(path) for path in missing[:5]))
    if unexpected:
        details.append(
            "unexpected " + ", ".join(repr(path) for path in unexpected[:5])
        )
    if changed:
        details.append("changed " + ", ".join(repr(path) for path in changed[:5]))
    raise OSError(
        "Managed generation no longer matches its frozen inventory"
        + (": " + "; ".join(details) if details else "")
    )


def stage_inventory_carry_forward(
    workspace: ManagedOutputWorkspace,
    previous_inventory: GenerationInventory,
    *,
    enabled_converters: Iterable[str],
) -> tuple[StagedFileReceipt, ...]:
    """Copy disabled-step and shared-owner files into the private stage."""

    enabled = _normalized_enabled_converters(enabled_converters)
    carried_entries = tuple(
        entry
        for entry in previous_inventory.entries
        if entry.owner.owner_class == "shared_owner"
        or entry.owner.name not in enabled
    )
    if not carried_entries:
        workspace.verify()
        return ()
    snapshots = workspace.snapshot_files(
        entry.path for entry in carried_entries
    )
    _validate_workspace_snapshots(carried_entries, snapshots)
    receipts = workspace.copy_snapshots(snapshots)
    _validate_staged_receipts(carried_entries, receipts)
    workspace.verify()
    return receipts


def validate_staged_generation_inventory(
    workspace: ManagedOutputWorkspace,
    inventory: GenerationInventory,
) -> None:
    workspace.verify()
    validate_generation_inventory(workspace.stage_path, inventory)
    workspace.verify()


def migrate_generation_inventory(
    root_path: str | os.PathLike[str],
) -> GenerationInventory:
    """Load format-v1 inventory data or migrate a bounded format-v2 manifest."""

    before = _read_existing_manifest(root_path)
    actual = capture_generation_inventory(root_path)
    after = _read_existing_manifest(root_path)
    if before != after:
        raise OSError("Conversion manifest changed while migrating its inventory")
    if before is None:
        return actual
    payload = _decode_manifest(before)
    if payload.get("format_version") != 2:
        raise OSError(
            "Legacy conversion manifest digest mismatch or unsupported "
            "format-v2 schema"
        )
    raw_inventory = payload.get("generation_inventory")
    if raw_inventory is not None:
        previous = GenerationInventory.from_value(raw_inventory)
        _validate_existing_inventory(previous, actual)
        return _refresh_shared_entries(previous, actual)
    _validate_legacy_generated_files(payload.get("generated_files"), actual)
    return actual


def _validate_inventory_paths(
    entries: tuple[GenerationInventoryEntry, ...],
) -> None:
    seen_casefold: dict[str, str] = {}
    paths_by_components: dict[tuple[str, ...], str] = {}
    for entry in entries:
        folded = entry.path.casefold()
        prior = seen_casefold.get(folded)
        if prior is not None:
            raise ValueError(
                "Generation inventory paths collide case-insensitively: "
                f"{prior!r}, {entry.path!r}"
            )
        seen_casefold[folded] = entry.path
        components = tuple(component.casefold() for component in entry.path.split("/"))
        paths_by_components[components] = entry.path
    for components, path in paths_by_components.items():
        for component_count in range(1, len(components)):
            ancestor = paths_by_components.get(components[:component_count])
            if ancestor is not None:
                raise ValueError(
                    "Generation inventory paths are structurally ambiguous: "
                    f"{ancestor!r}, {path!r}"
                )


def _is_managed_output_path(path: str) -> bool:
    if path == GODOT_PROJECT_FILENAME or path in {
        relative.replace(os.sep, "/") for relative in MANAGED_OUTPUT_FILES
    }:
        return True
    return any(
        path.startswith(root.replace(os.sep, "/") + "/")
        for root in MANAGED_OUTPUT_DIRECTORIES
    )


def _is_inventory_auxiliary(path: str) -> bool:
    if path in {_MANIFEST_RELATIVE_PATH, _ATTEMPT_RELATIVE_PATH}:
        return True
    components = path.split("/")
    filename = components[-1]
    if (
        len(components) == 2
        and components[0] == "gm2godot"
        and is_conversion_generation_auxiliary(filename)
    ):
        return True
    return (
        filename == WORKSPACE_STAGE_MARKER_NAME
        or filename.startswith(".gm2godot-cleanup-")
        or _PRIVATE_FILE_PATTERN.fullmatch(filename) is not None
    )


def _reserved_private_path(path: str) -> bool:
    filename = path.rsplit("/", 1)[-1]
    return filename.startswith(
        (
            ".conversion_",
            ".gm2godot-",
            ".gml_included_file_registry.",
        )
    )


def _path_is_redirected(path: str, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    file_attributes = cast(int, getattr(path_stat, "st_file_attributes", 0))
    if file_attributes & 0x00000400:
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Any, junction_candidate)
    return bool(junction_checker(path))


def _binding_stat(binding: VerifiedDirectory) -> os.stat_result:
    if binding.strategy == "posix_dir_fd":
        return os.fstat(binding.descriptor)
    return os.lstat(binding.path)


def _linux_mount_id(binding: VerifiedDirectory) -> int | None:
    if not sys.platform.startswith("linux") or binding.strategy != "posix_dir_fd":
        return None
    try:
        with open(
            f"/proc/self/fdinfo/{binding.descriptor}",
            encoding="ascii",
        ) as descriptor_info:
            values = [
                line.partition(":")[2].strip()
                for line in descriptor_info
                if line.startswith("mnt_id:")
            ]
    except OSError:
        return None
    if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
        raise OSError("Could not verify generation inventory mount boundary")
    return int(values[0])


def _verify_directory_boundary(
    binding: VerifiedDirectory,
    *,
    root_device: int,
    root_mount_id: int | None,
    allow_root_mount: bool = False,
) -> None:
    binding.verify_path()
    path_stat = _binding_stat(binding)
    if (
        path_stat.st_dev != root_device
        or (not allow_root_mount and os.path.ismount(binding.path))
    ):
        raise OSError(
            f"Refusing mounted or cross-device managed generation path: {binding.path}"
        )
    mount_id = _linux_mount_id(binding)
    if (
        root_mount_id is not None
        and mount_id is not None
        and mount_id != root_mount_id
    ):
        raise OSError(
            f"Refusing mounted managed generation path: {binding.path}"
        )


def _capture_managed_root(
    root: VerifiedDirectory,
    components: tuple[str, ...],
    entries: list[GenerationInventoryEntry],
    *,
    directory_counter: list[int],
    root_device: int,
    root_mount_id: int | None,
) -> None:
    opened: list[VerifiedDirectory] = []
    current = root
    relative_components: list[str] = []
    try:
        for component in components:
            relative_components.append(component)
            try:
                component_stat = current.stat(component)
            except FileNotFoundError:
                return
            path = current.child_path(component)
            if _path_is_redirected(path, component_stat):
                raise OSError(
                    f"Refusing redirected managed generation directory: {path}"
                )
            if not stat.S_ISDIR(component_stat.st_mode):
                raise OSError(
                    f"Managed generation root is not a directory: {path}"
                )
            child = current.open_child(
                component,
                expected_identity=(component_stat.st_dev, component_stat.st_ino),
                description="managed generation directory",
            )
            opened.append(child)
            _verify_directory_boundary(
                child,
                root_device=root_device,
                root_mount_id=root_mount_id,
            )
            current = child
        _walk_managed_directory(
            current,
            "/".join(relative_components),
            entries,
            directory_counter=directory_counter,
            depth=len(relative_components),
            root_device=root_device,
            root_mount_id=root_mount_id,
        )
    finally:
        for binding in reversed(opened):
            binding.close()


def _walk_managed_directory(
    directory: VerifiedDirectory,
    relative_directory: str,
    entries: list[GenerationInventoryEntry],
    *,
    directory_counter: list[int],
    depth: int,
    root_device: int,
    root_mount_id: int | None,
) -> None:
    if depth > _MAX_DIRECTORY_DEPTH:
        raise OSError("Managed generation exceeds the directory-depth limit")
    directory_counter[0] += 1
    if directory_counter[0] > _MAX_DIRECTORY_COUNT:
        raise OSError("Managed generation contains too many directories")
    for name in directory.list_names():
        raw_relative_path = f"{relative_directory}/{name}"
        relative_path = normalize_generation_inventory_path(raw_relative_path)
        if relative_path != raw_relative_path:
            raise OSError(
                "Managed generation contains a non-canonical filesystem name: "
                + repr(raw_relative_path)
            )
        path = directory.child_path(name)
        path_stat = directory.stat(name)
        if _is_inventory_auxiliary(relative_path):
            continue
        if _reserved_private_path(relative_path):
            raise OSError(
                f"Malformed private managed-generation entry was preserved: {path}"
            )
        if _path_is_redirected(path, path_stat):
            raise OSError(
                f"Refusing redirected managed generation entry: {path}"
            )
        if stat.S_ISDIR(path_stat.st_mode):
            child = directory.open_child(
                name,
                expected_identity=(path_stat.st_dev, path_stat.st_ino),
                description="managed generation directory",
            )
            try:
                _verify_directory_boundary(
                    child,
                    root_device=root_device,
                    root_mount_id=root_mount_id,
                )
                _walk_managed_directory(
                    child,
                    relative_path,
                    entries,
                    directory_counter=directory_counter,
                    depth=depth + 1,
                    root_device=root_device,
                    root_mount_id=root_mount_id,
                )
            finally:
                child.close()
            continue
        if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
            raise OSError(
                "Refusing non-regular or multiply-linked managed generation "
                f"entry: {path}"
            )
        entries.append(
            _capture_regular_file(
                directory,
                name,
                relative_path,
                path_stat,
                root_device=root_device,
                root_mount_id=root_mount_id,
            )
        )
        if len(entries) > GENERATION_INVENTORY_MAX_ENTRIES:
            raise OSError("Managed generation contains too many files")
    directory.verify_path()


def _capture_named_file_if_present(
    root: VerifiedDirectory,
    name: str,
    relative_path: str,
    entries: list[GenerationInventoryEntry],
    *,
    root_device: int,
    root_mount_id: int | None,
) -> None:
    try:
        path_stat = root.stat(name)
    except FileNotFoundError:
        return
    path = root.child_path(name)
    if (
        _path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_nlink != 1
    ):
        raise OSError(
            f"Refusing redirected, non-regular, or multiply-linked managed file: {path}"
        )
    entries.append(
        _capture_regular_file(
            root,
            name,
            relative_path,
            path_stat,
            root_device=root_device,
            root_mount_id=root_mount_id,
        )
    )


def _capture_regular_file(
    parent: VerifiedDirectory,
    name: str,
    relative_path: str,
    initial_stat: os.stat_result,
    *,
    root_device: int,
    root_mount_id: int | None,
) -> GenerationInventoryEntry:
    path = parent.child_path(name)
    descriptor = parent.open_file(
        name,
        os.O_RDONLY | getattr(os, "O_BINARY", 0),
    )
    try:
        opened_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_nlink != 1
            or not os.path.samestat(initial_stat, opened_stat)
            or opened_stat.st_dev != root_device
            or os.path.ismount(path)
        ):
            raise OSError(
                f"Managed generation file changed or crosses a mount: {path}"
            )
        if sys.platform.startswith("linux") and root_mount_id is not None:
            file_mount_id = _linux_file_mount_id(descriptor)
            if file_mount_id is not None and file_mount_id != root_mount_id:
                raise OSError(f"Refusing mounted managed generation file: {path}")
        digest = hashlib.sha256()
        byte_count = 0
        while True:
            chunk = os.read(descriptor, _READ_CHUNK_BYTES)
            if not chunk:
                break
            byte_count += len(chunk)
            digest.update(chunk)
        final_opened_stat = os.fstat(descriptor)
        final_path_stat = parent.stat(name)
        if (
            _content_fingerprint(final_opened_stat)
            != _content_fingerprint(opened_stat)
            or _content_fingerprint(final_path_stat)
            != _content_fingerprint(opened_stat)
            or byte_count != opened_stat.st_size
        ):
            raise OSError(
                f"Managed generation file changed while hashing: {path}"
            )
        return GenerationInventoryEntry(
            path=relative_path,
            kind=generation_output_kind(relative_path),
            owner=generation_output_owner(relative_path),
            byte_count=byte_count,
            sha256="sha256:" + digest.hexdigest(),
            mode=stat.S_IMODE(opened_stat.st_mode),
        )
    finally:
        os.close(descriptor)


def _linux_file_mount_id(file_descriptor: int) -> int | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open(
            f"/proc/self/fdinfo/{file_descriptor}",
            encoding="ascii",
        ) as descriptor_info:
            values = [
                line.partition(":")[2].strip()
                for line in descriptor_info
                if line.startswith("mnt_id:")
            ]
    except OSError:
        return None
    if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
        raise OSError("Could not verify managed generation file mount boundary")
    return int(values[0])


def _content_fingerprint(path_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_ctime_ns,
    )


def _normalized_enabled_converters(
    enabled_converters: Iterable[str],
) -> frozenset[str]:
    if isinstance(enabled_converters, (str, bytes)):
        raise TypeError("Enabled converters must be an iterable of step names.")
    raw_enabled = cast(tuple[object, ...], tuple(enabled_converters))
    if not all(type(name) is str for name in raw_enabled):
        raise TypeError("Enabled converter names must be strings.")
    enabled = cast(tuple[str, ...], raw_enabled)
    unknown = sorted(set(enabled) - conversion_step_map().keys())
    if unknown:
        raise ValueError("Unknown enabled converter(s): " + ", ".join(unknown))
    return frozenset(enabled)


def _validate_disabled_carry_forward(
    previous: GenerationInventory,
    desired: GenerationInventory,
    enabled_converters: Iterable[str],
) -> None:
    enabled = _normalized_enabled_converters(enabled_converters)
    previous_by_path = previous.by_path()
    desired_by_path = desired.by_path()
    for path, entry in previous_by_path.items():
        if (
            entry.owner.owner_class == "converter_step"
            and entry.owner.name not in enabled
            and desired_by_path.get(path) != entry
        ):
            raise OSError(
                "Disabled converter output was not carried forward exactly: "
                + repr(path)
            )
    for path, entry in desired_by_path.items():
        if (
            entry.owner.owner_class == "converter_step"
            and entry.owner.name not in enabled
            and path not in previous_by_path
        ):
            raise OSError(
                "Disabled converter unexpectedly produced a new managed output: "
                + repr(path)
            )


def _validate_workspace_snapshots(
    entries: tuple[GenerationInventoryEntry, ...],
    snapshots: tuple[ManagedFileSnapshot, ...],
) -> None:
    expected = {entry.path: entry for entry in entries}
    if {snapshot.relative_path for snapshot in snapshots} != expected.keys():
        raise OSError("Managed-output carry-forward snapshot topology changed")
    for snapshot in snapshots:
        entry = expected[snapshot.relative_path]
        if (
            snapshot.byte_count != entry.byte_count
            or snapshot.sha256 != entry.sha256
            or not modes_match(snapshot.mode, entry.mode)
        ):
            raise OSError(
                "Managed-output carry-forward source changed: "
                + repr(snapshot.relative_path)
            )


def _validate_staged_receipts(
    entries: tuple[GenerationInventoryEntry, ...],
    receipts: tuple[StagedFileReceipt, ...],
) -> None:
    expected = {entry.path: entry for entry in entries}
    if {receipt.relative_path for receipt in receipts} != expected.keys():
        raise OSError("Managed-output carry-forward stage topology changed")
    for receipt in receipts:
        entry = expected[receipt.relative_path]
        if (
            receipt.byte_count != entry.byte_count
            or receipt.sha256 != entry.sha256
            or not modes_match(receipt.mode, entry.mode)
        ):
            raise OSError(
                "Managed-output carry-forward stage changed: "
                + repr(receipt.relative_path)
            )


def _read_existing_manifest(
    root_path: str | os.PathLike[str],
) -> bytes | None:
    root_value = os.fspath(root_path)
    try:
        root_stat = os.lstat(root_value)
    except FileNotFoundError:
        return None
    if _path_is_redirected(root_value, root_stat) or not stat.S_ISDIR(
        root_stat.st_mode
    ):
        raise OSError(
            f"Refusing redirected or non-directory generation root: {root_value}"
        )
    with VerifiedDirectory.open(
        root_value,
        description="generation inventory manifest root",
    ) as root:
        root_device = _binding_stat(root).st_dev
        root_mount_id = _linux_mount_id(root)
        try:
            artifact_stat = root.stat("gm2godot")
        except FileNotFoundError:
            return None
        artifact_path = root.child_path("gm2godot")
        if (
            _path_is_redirected(artifact_path, artifact_stat)
            or not stat.S_ISDIR(artifact_stat.st_mode)
            or artifact_stat.st_dev != root_device
            or os.path.ismount(artifact_path)
        ):
            raise OSError(
                "Refusing redirected, mounted, or cross-device conversion "
                f"artifact directory: {artifact_path}"
            )
        artifact_directory = root.open_child(
            "gm2godot",
            expected_identity=(artifact_stat.st_dev, artifact_stat.st_ino),
            description="generation inventory artifact directory",
        )
        try:
            _verify_directory_boundary(
                artifact_directory,
                root_device=root_device,
                root_mount_id=root_mount_id,
            )
            try:
                manifest_stat = artifact_directory.stat("conversion_manifest.json")
            except FileNotFoundError:
                return None
            manifest_path = artifact_directory.child_path("conversion_manifest.json")
            if (
                _path_is_redirected(manifest_path, manifest_stat)
                or not stat.S_ISREG(manifest_stat.st_mode)
                or manifest_stat.st_nlink != 1
                or manifest_stat.st_size > GENERATION_INVENTORY_MAX_BYTES
            ):
                raise OSError(
                    "Refusing redirected, multiply-linked, or oversized conversion "
                    f"manifest: {manifest_path}"
                )
            descriptor = artifact_directory.open_file(
                "conversion_manifest.json",
                os.O_RDONLY | getattr(os, "O_BINARY", 0),
            )
            try:
                opened_stat = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened_stat.st_mode)
                    or opened_stat.st_nlink != 1
                    or not os.path.samestat(manifest_stat, opened_stat)
                ):
                    raise OSError(
                        f"Conversion manifest changed while opening: {manifest_path}"
                    )
                content = _read_bounded_descriptor(
                    descriptor,
                    GENERATION_INVENTORY_MAX_BYTES + 1,
                )
                final_stat = os.fstat(descriptor)
                final_path_stat = artifact_directory.stat(
                    "conversion_manifest.json"
                )
                if (
                    len(content) > GENERATION_INVENTORY_MAX_BYTES
                    or _content_fingerprint(final_stat)
                    != _content_fingerprint(opened_stat)
                    or _content_fingerprint(final_path_stat)
                    != _content_fingerprint(opened_stat)
                ):
                    raise OSError(
                        f"Conversion manifest changed while reading: {manifest_path}"
                    )
                return content
            finally:
                os.close(descriptor)
        finally:
            artifact_directory.close()


def _read_bounded_descriptor(file_descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum
    while remaining > 0:
        chunk = os.read(file_descriptor, min(_READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _decode_manifest(content: bytes) -> dict[str, object]:
    try:
        decoded = content.decode("utf-8")
        raw_payload = json.loads(
            decoded,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise OSError("Invalid format-v2 conversion manifest") from error
    return _string_key_mapping(raw_payload, "conversion manifest")


def _validate_existing_inventory(
    previous: GenerationInventory,
    actual: GenerationInventory,
) -> None:
    previous_by_path = previous.by_path()
    actual_by_path = actual.by_path()
    if previous_by_path.keys() != actual_by_path.keys():
        raise OSError(
            "Existing managed generation topology disagrees with its inventory"
        )
    for path, entry in previous_by_path.items():
        current = actual_by_path[path]
        if entry.owner.owner_class == "shared_owner":
            continue
        if current != entry:
            raise OSError(
                f"Existing managed generation entry disagrees with its inventory: {path}"
            )


def _refresh_shared_entries(
    previous: GenerationInventory,
    actual: GenerationInventory,
) -> GenerationInventory:
    actual_by_path = actual.by_path()
    return GenerationInventory(
        tuple(
            actual_by_path[entry.path]
            if entry.owner.owner_class == "shared_owner"
            else entry
            for entry in previous.entries
        )
    )


def _validate_legacy_generated_files(
    value: object,
    actual: GenerationInventory,
) -> None:
    if not isinstance(value, list):
        raise OSError("Legacy format-v2 manifest has invalid generated_files")
    raw_entries = cast(list[object], value)
    if len(raw_entries) > GENERATION_INVENTORY_MAX_ENTRIES + 1:
        raise OSError("Legacy format-v2 manifest contains too many generated files")
    actual_by_path = actual.by_path()
    seen: set[str] = set()
    seen_casefold: dict[str, str] = {}
    for value_entry in raw_entries:
        payload = _string_key_mapping(value_entry, "legacy generated-file entry")
        path = payload.get("path")
        kind = payload.get("kind")
        digest = payload.get("sha256")
        if not isinstance(path, str) or not isinstance(kind, str):
            raise OSError("Invalid legacy generated-file path or kind")
        try:
            normalized = normalize_generation_inventory_path(path)
        except (TypeError, ValueError) as error:
            raise OSError(str(error)) from error
        if normalized != path:
            raise OSError("Legacy generated-file path is not canonical")
        if normalized == _MANIFEST_RELATIVE_PATH:
            if kind != "manifest" or digest != "self":
                raise OSError("Invalid legacy canonical-manifest self entry")
            continue
        if _is_inventory_auxiliary(normalized) or not _is_managed_output_path(
            normalized
        ):
            # Invocation-local format-v2 manifests could record an explicitly
            # selected report directory nested under the destination. It is not
            # part of the documented destination-managed generation.
            continue
        if normalized in seen:
            raise OSError("Duplicate legacy generated-file path")
        folded = normalized.casefold()
        if folded in seen_casefold:
            raise OSError(
                "Case-colliding legacy generated-file paths: "
                f"{seen_casefold[folded]!r}, {normalized!r}"
            )
        seen.add(normalized)
        seen_casefold[folded] = normalized
        current = actual_by_path.get(normalized)
        if current is None:
            raise OSError(
                f"Legacy generated-file entry is unavailable: {normalized!r}"
            )
        if kind not in {
            current.kind,
            _legacy_generation_output_kind(normalized),
        }:
            raise OSError(
                f"Legacy generated-file kind is invalid: {normalized!r}"
            )
        if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
            raise OSError(
                f"Legacy generated-file digest is invalid: {normalized!r}"
            )
        if (
            current.owner.owner_class != "shared_owner"
            and digest != current.sha256
        ):
            raise OSError(
                f"Legacy generated-file digest mismatch: {normalized!r}"
            )


def _string_key_mapping(value: object, description: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OSError(f"Invalid generation {description}")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise OSError(f"Invalid generation {description}")
    return cast(dict[str, object], raw)


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"Non-finite JSON number is unsupported: {value}")


def _legacy_generation_output_kind(path: str) -> str:
    if path == GODOT_PROJECT_FILENAME:
        return "project"
    if path.endswith(".gmlmap.json"):
        return "source_map"
    if path.endswith(".json"):
        return "report"
    if path.endswith(".gd"):
        return "gdscript"
    if path.endswith(".gdshader"):
        return "shader"
    if path.endswith(".tscn"):
        return "scene"
    if path.endswith(".tres"):
        return "resource"
    extension = posixpath.splitext(path)[1].lower()
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension in _AUDIO_EXTENSIONS:
        return "audio"
    if extension in _FONT_EXTENSIONS:
        return "font"
    if extension == ".import":
        return "import_metadata"
    return "file"


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "GENERATION_INVENTORY_FORMAT_VERSION",
    "GENERATION_INVENTORY_MAX_BYTES",
    "GENERATION_INVENTORY_MAX_ENTRIES",
    "GENERATION_INVENTORY_MAX_PATH_BYTES",
    "GenerationInventory",
    "GenerationInventoryEntry",
    "GenerationInventoryOwner",
    "capture_generation_inventory",
    "generation_output_kind",
    "generation_output_owner",
    "migrate_generation_inventory",
    "normalize_generation_inventory_path",
    "stage_inventory_carry_forward",
    "validate_generation_inventory",
    "validate_staged_generation_inventory",
]
