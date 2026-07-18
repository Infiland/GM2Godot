from __future__ import annotations

import json
import os
import posixpath
import secrets
import stat
import tempfile
from dataclasses import dataclass, field
from typing import Callable, ClassVar, Iterable, cast

from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectManifestDiagnostic,
    ProjectTextureGroup,
    load_gamemaker_project_manifest,
)
from src.conversion.gml_transpiler import GMLTranspileError, transpile_gml_code
from src.conversion.fonts import (
    bundled_font_output_filename,
    resolve_system_font_source,
)
from src.conversion.generated_paths import (
    generated_flat_resource_path,
    generated_nested_resource_path,
    generated_path_segment,
    generated_resource_stem,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    is_safe_project_source_component,
    validate_project_resource_source_path,
)
from src.conversion.script_functions import modern_script_function_names
from src.conversion.type_defs import (
    ConversionRunning,
    JsonDict,
    LogCallback,
    ProgressCallback,
    StrPath,
)
from src.conversion.path_registry import write_path_registry
from src.conversion.animation_curve_registry import write_animation_curve_registry
from src.conversion.extension_registry import (
    collision_safe_extension_stub_resource_paths,
    extension_entry_from_yy,
    extension_entry_metadata,
    extension_stub_resource_path,
    write_extension_compatibility_outputs,
)

ASSET_REGISTRY_RELATIVE_PATH = os.path.join("gm2godot", "gml_asset_registry.gd")
ASSET_REGISTRY_RESOURCE_PATH = "res://gm2godot/gml_asset_registry.gd"
GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH = os.path.join("gm2godot", "group_compatibility_report.json")
STATIC_ASSET_ID_MASK = 0x3FFFFFFF


def _empty_int_list() -> list[int]:
    return []


def _empty_str_list() -> list[str]:
    return []


def _path_is_redirected(path: str, path_stat: os.stat_result) -> bool:
    """Return whether a path is a symbolic link or Windows junction."""
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(path)


def _asset_output_components(root: str, output_path: str) -> tuple[str, ...]:
    try:
        contained = os.path.commonpath((root, output_path)) == root
    except ValueError:
        contained = False
    relative_path = os.path.relpath(output_path, root) if contained else os.pardir
    components = tuple(relative_path.split(os.sep))
    if (
        not contained
        or os.path.isabs(relative_path)
        or any(component in {"", ".", ".."} for component in components)
    ):
        raise ValueError(
            f"Generated asset output escapes its confinement root: {output_path}"
        )
    return components


def _ensure_asset_output_root(root: str) -> tuple[int, int]:
    os.makedirs(root, exist_ok=True)
    root_stat = os.lstat(root)
    if _path_is_redirected(root, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise OSError(
            f"Refusing redirected asset-registry output directory: {root}"
        )
    return (root_stat.st_dev, root_stat.st_ino)


def _confined_asset_output_supported() -> bool:
    return (
        os.name != "nt"
        and os.chmod in os.supports_fd
        and all(
            operation in os.supports_dir_fd
            for operation in (os.open, os.mkdir, os.stat, os.rename, os.unlink)
        )
    )


def _atomic_write_asset_text_at(
    root: str,
    components: tuple[str, ...],
    content: str,
) -> None:
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(root, directory_flags)
    current_fd = root_fd
    try:
        _verify_open_asset_output_directory(root, root, root_fd)
        for component in components[:-1]:
            child_fd = _open_or_create_asset_output_directory(
                current_fd,
                component,
                directory_flags,
            )
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = child_fd

        output_directory = os.path.join(root, *components[:-1])
        _verify_open_asset_output_directory(root, output_directory, current_fd)
        _atomic_write_asset_text_in_directory(
            current_fd,
            components[-1],
            content,
        )
        _verify_open_asset_output_directory(root, output_directory, current_fd)
    finally:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def _open_or_create_asset_output_directory(
    parent_fd: int,
    component: str,
    flags: int,
) -> int:
    try:
        return os.open(component, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(component, 0o755, dir_fd=parent_fd)
        except FileExistsError:
            pass
        return os.open(component, flags, dir_fd=parent_fd)
    except OSError as error:
        raise OSError(
            f"Refusing redirected asset-registry output directory: {component}"
        ) from error


def _verify_open_asset_output_directory(
    root: str,
    directory_path: str,
    directory_fd: int,
) -> None:
    try:
        path_stat = os.lstat(directory_path)
        open_stat = os.fstat(directory_fd)
    except OSError as error:
        raise OSError(
            f"Asset-registry output directory changed: {directory_path}"
        ) from error
    root_real = os.path.realpath(root)
    directory_real = os.path.realpath(directory_path)
    try:
        contained = os.path.commonpath((directory_real, root_real)) == root_real
    except ValueError:
        contained = False
    if (
        _path_is_redirected(directory_path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino)
        != (open_stat.st_dev, open_stat.st_ino)
        or not contained
    ):
        raise OSError(
            f"Refusing redirected asset-registry output directory: {directory_path}"
        )


def _asset_output_state_at(
    directory_fd: int,
    filename: str,
) -> tuple[tuple[int, int] | None, int | None]:
    try:
        output_stat = os.stat(
            filename,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None, None
    if not stat.S_ISREG(output_stat.st_mode):
        raise OSError(f"Refusing to replace non-regular asset registry: {filename}")
    return (
        (output_stat.st_dev, output_stat.st_ino),
        stat.S_IMODE(output_stat.st_mode),
    )


def _verify_asset_output_state_at(
    directory_fd: int,
    filename: str,
    expected_identity: tuple[int, int] | None,
) -> None:
    current_identity, _mode = _asset_output_state_at(directory_fd, filename)
    if current_identity != expected_identity:
        raise OSError(f"Asset registry changed during publication: {filename}")


def _atomic_write_asset_text_in_directory(
    directory_fd: int,
    filename: str,
    content: str,
) -> None:
    output_identity, output_mode = _asset_output_state_at(directory_fd, filename)
    temporary_name = ""
    file_descriptor = -1
    for _attempt in range(100):
        temporary_name = f".{filename}.{secrets.token_hex(8)}.tmp"
        try:
            file_descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            break
        except FileExistsError:
            continue
    if file_descriptor < 0:
        raise OSError(f"Could not stage generated asset output: {filename}")

    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    temporary_pending = True
    try:
        if output_mode is not None:
            os.chmod(file_descriptor, output_mode)
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as temporary_file:
            file_descriptor = -1
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        staged_stat = os.stat(
            temporary_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(staged_stat.st_mode)
            or (staged_stat.st_dev, staged_stat.st_ino) != temporary_identity
        ):
            raise OSError(f"Generated asset staging file changed: {filename}")
        _verify_asset_output_state_at(directory_fd, filename, output_identity)
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_pending = False
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def _atomic_write_asset_text_fallback(
    root: str,
    components: tuple[str, ...],
    content: str,
) -> None:
    directory_identities = _prepare_asset_output_directories_fallback(
        root,
        components[:-1],
    )
    output_directory = os.path.join(root, *components[:-1])
    output_path = os.path.join(output_directory, components[-1])
    output_identity, output_mode = _asset_output_state(output_path)
    file_descriptor, staged_path = tempfile.mkstemp(
        dir=output_directory,
        prefix=f".{components[-1]}.",
        suffix=".tmp",
    )
    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    staged_pending = True
    try:
        if output_mode is not None:
            os.chmod(staged_path, output_mode)
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as staged_file:
            file_descriptor = -1
            staged_file.write(content)
            staged_file.flush()
            os.fsync(staged_file.fileno())
        _verify_asset_output_directories_fallback(directory_identities)
        staged_stat = os.lstat(staged_path)
        if (
            not stat.S_ISREG(staged_stat.st_mode)
            or (staged_stat.st_dev, staged_stat.st_ino) != temporary_identity
        ):
            raise OSError(
                f"Generated asset staging file changed: {components[-1]}"
            )
        _verify_asset_output_state(output_path, output_identity)
        os.replace(staged_path, output_path)
        staged_pending = False
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if staged_pending:
            try:
                _verify_asset_output_directories_fallback(directory_identities)
                current_stage_stat = os.lstat(staged_path)
                if (
                    current_stage_stat.st_dev,
                    current_stage_stat.st_ino,
                ) == temporary_identity:
                    os.unlink(staged_path)
            except OSError:
                pass


def _prepare_asset_output_directories_fallback(
    root: str,
    directory_components: tuple[str, ...],
) -> tuple[tuple[str, tuple[int, int]], ...]:
    root_real = os.path.realpath(root)
    directory_path = root
    identities: list[tuple[str, tuple[int, int]]] = []
    for component in (None, *directory_components):
        if component is not None:
            directory_path = os.path.join(directory_path, component)
            try:
                directory_stat = os.lstat(directory_path)
            except FileNotFoundError:
                os.mkdir(directory_path)
                directory_stat = os.lstat(directory_path)
        else:
            directory_stat = os.lstat(directory_path)
        directory_real = os.path.realpath(directory_path)
        try:
            contained = os.path.commonpath((directory_real, root_real)) == root_real
        except ValueError:
            contained = False
        if (
            _path_is_redirected(directory_path, directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or not contained
        ):
            raise OSError(
                "Refusing redirected asset-registry output directory: "
                f"{directory_path}"
            )
        identities.append(
            (
                directory_path,
                (directory_stat.st_dev, directory_stat.st_ino),
            )
        )
    return tuple(identities)


def _verify_asset_output_directories_fallback(
    identities: tuple[tuple[str, tuple[int, int]], ...],
) -> None:
    for directory_path, expected_identity in identities:
        try:
            directory_stat = os.lstat(directory_path)
        except OSError as error:
            raise OSError(
                f"Asset-registry output directory changed: {directory_path}"
            ) from error
        if (
            _path_is_redirected(directory_path, directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or (directory_stat.st_dev, directory_stat.st_ino)
            != expected_identity
        ):
            raise OSError(
                f"Asset-registry output directory changed: {directory_path}"
            )


def _asset_output_state(
    output_path: str,
) -> tuple[tuple[int, int] | None, int | None]:
    try:
        output_stat = os.lstat(output_path)
    except FileNotFoundError:
        return None, None
    if not stat.S_ISREG(output_stat.st_mode):
        raise OSError(
            f"Refusing to replace non-regular asset registry: {output_path}"
        )
    return (
        (output_stat.st_dev, output_stat.st_ino),
        stat.S_IMODE(output_stat.st_mode),
    )


def _verify_asset_output_state(
    output_path: str,
    expected_identity: tuple[int, int] | None,
) -> None:
    current_identity, _mode = _asset_output_state(output_path)
    if current_identity != expected_identity:
        raise OSError(f"Asset registry changed during publication: {output_path}")


@dataclass(frozen=True)
class AssetRegistryEntry:
    id: int
    name: str
    kind: str
    asset_type: str
    type_name: str
    source_path: str
    godot_path: str
    legacy_id: str
    tags: tuple[str, ...] = ()
    dynamic: bool = False
    metadata: JsonDict | None = None

    def to_godot_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "type": self.asset_type,
            "type_name": self.type_name,
            "source_path": self.source_path,
            "godot_path": self.godot_path,
            "legacy_id": self.legacy_id,
            "tags": list(self.tags),
            "dynamic": self.dynamic,
            "metadata": self.metadata or {},
        }


@dataclass(frozen=True)
class _ProjectResource:
    kind: str
    name: str
    yy_path: str
    source_path: str
    raw_data: JsonDict


@dataclass(frozen=True)
class _DeclaredRegistryResource:
    kind: str
    name: str
    source_path: str | None
    owner_source_path: str | None
    manifest_field: str | None


@dataclass(frozen=True)
class _UnavailableRegistryResource:
    declaration: _DeclaredRegistryResource
    outcome_key: str
    reason: str


@dataclass(frozen=True)
class _AssetRegistryConversionPlan:
    resources: tuple[_ProjectResource, ...]
    resource_keys: tuple[str, ...]
    requested_keys: tuple[str, ...]
    unavailable: tuple[_UnavailableRegistryResource, ...]


@dataclass
class _TextureGroupRegistryEntry:
    name: str
    parent: str = ""
    dynamic: bool = False
    dynamic_path: str = ""
    targets: tuple[str, ...] = ()
    asset_ids: list[int] = field(default_factory=_empty_int_list)
    asset_names: list[str] = field(default_factory=_empty_str_list)

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "parent": self.parent,
            "dynamic": self.dynamic,
            "dynamic_path": self.dynamic_path,
            "targets": list(self.targets),
            "asset_ids": sorted(self.asset_ids),
            "asset_names": sorted(self.asset_names),
        }


@dataclass
class _AudioGroupRegistryEntry:
    name: str
    targets: tuple[str, ...] = ()
    loaded: bool = False
    gain: float = 1.0
    asset_ids: list[int] = field(default_factory=_empty_int_list)
    asset_names: list[str] = field(default_factory=_empty_str_list)

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "targets": list(self.targets),
            "loaded": self.loaded,
            "gain": self.gain,
            "asset_ids": sorted(self.asset_ids),
            "asset_names": sorted(self.asset_names),
        }


class AssetRegistryConverter(BaseConverter):
    """Generate a stable GameMaker asset registry for GMRuntime helpers."""

    RESOURCE_TYPE_BY_KIND: ClassVar[dict[str, str]] = {
        "sprites": "sprite",
        "sounds": "sound",
        "rooms": "room",
        "objects": "object",
        "scripts": "script",
        "fonts": "font",
        "paths": "path",
        "animcurves": "animation_curve",
        "shaders": "shader",
        "tilesets": "tileset",
        "particles": "particle_system",
        "particlesystems": "particle_system",
        "timelines": "timeline",
        "sequences": "sequence",
        "extensions": "extension",
        "included_files": "included_file",
    }
    TYPE_NAME_BY_KIND: ClassVar[dict[str, str]] = {
        "sprites": "Sprite",
        "sounds": "Sound",
        "rooms": "Room",
        "objects": "Object",
        "scripts": "Script",
        "fonts": "Font",
        "paths": "Path",
        "animcurves": "Animation Curve",
        "shaders": "Shader",
        "tilesets": "Tile Set",
        "particles": "Particle System",
        "particlesystems": "Particle System",
        "timelines": "Timeline",
        "sequences": "Sequence",
        "extensions": "Extension",
        "included_files": "Included File",
    }
    STATIC_RESOURCE_EXTENSIONS: ClassVar[dict[str, str]] = {
        "sprites": ".tscn",
        "objects": ".tscn",
        "rooms": ".tscn",
        "tilesets": ".tres",
        "paths": ".tscn",
    }
    KIND_ORDER: ClassVar[dict[str, int]] = {
        kind: index for index, kind in enumerate(RESOURCE_TYPE_BY_KIND)
    }
    FOLDER_BY_KIND: ClassVar[dict[str, str]] = {
        **{kind: kind for kind in RESOURCE_TYPE_BY_KIND if kind != "included_files"},
        "included_files": "datafiles",
    }
    MANIFEST_KIND_BY_RESOURCE_TYPE: ClassVar[dict[str, str]] = {
        "gmanimationcurve": "animcurves",
        "gmextension": "extensions",
        "gmfont": "fonts",
        "gmincludedfile": "included_files",
        "gmobject": "objects",
        "gmparticlesystem": "particlesystems",
        "gmpath": "paths",
        "gmroom": "rooms",
        "gmscript": "scripts",
        "gmsequence": "sequences",
        "gmshader": "shaders",
        "gmsound": "sounds",
        "gmsprite": "sprites",
        "gmtileset": "tilesets",
        "gmtimeline": "timelines",
    }

    def __init__(
        self,
        gm_project_path: StrPath,
        godot_project_path: StrPath,
        log_callback: LogCallback = print,
        progress_callback: ProgressCallback | None = None,
        conversion_running: ConversionRunning | None = None,
        update_log_callback: LogCallback | None = None,
        compact_logging: bool = False,
        max_workers: int | None = None,
        organize_sounds_by_audio_group: bool = False,
        macro_configuration: str | None = None,
        diagnostics: DiagnosticCollector | None = None,
    ) -> None:
        super().__init__(
            gm_project_path,
            godot_project_path,
            log_callback,
            progress_callback,
            conversion_running,
            update_log_callback,
            compact_logging,
            max_workers=max_workers,
            diagnostics=diagnostics,
        )
        self.organize_sounds_by_audio_group = bool(organize_sounds_by_audio_group)
        self.macro_configuration = macro_configuration
        self.project_manifest: GameMakerProjectManifest = load_gamemaker_project_manifest(
            self.gm_project_path
        )
        self._system_font_paths: dict[str, str | None] = {}
        self._timeline_action_source_failures: set[tuple[str, str]] = set()

    def build_entries(self) -> tuple[AssetRegistryEntry, ...]:
        resources = self._ordered_project_resources()
        entries, _processed_count = self._build_entries_from_resources(resources)
        return entries

    def _ordered_project_resources(self) -> tuple[_ProjectResource, ...]:
        """Return every discoverable base resource in stable registry order."""
        return tuple(
            sorted(
                self._load_project_resources(),
                key=lambda resource: (
                    self.KIND_ORDER.get(resource.kind, len(self.KIND_ORDER)),
                    resource.name.lower(),
                    resource.source_path,
                ),
            )
        )

    def _conversion_plan(self) -> _AssetRegistryConversionPlan:
        """Plan logical registry resources before filtering unavailable input."""
        resources = self._ordered_project_resources()
        manifest_is_valid = (
            self.project_manifest.yyp_path is not None
            and not any(
                diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
                for diagnostic in self.project_manifest.diagnostics
            )
        )
        if not manifest_is_valid:
            resource_keys = tuple(
                self._outcome_resource_key(resource)
                for resource in resources
            )
            return _AssetRegistryConversionPlan(
                resources=resources,
                resource_keys=resource_keys,
                requested_keys=resource_keys,
                unavailable=(),
            )

        declaration_groups = self._declared_registry_resources()
        available_by_identity = {
            self._resource_identity(resource.kind, resource.name): resource
            for resource in resources
        }
        selected_by_identity: dict[tuple[str, str], _ProjectResource] = {}
        declared_identities: set[tuple[str, str]] = set()
        requested_keys: list[str] = []
        unavailable: list[_UnavailableRegistryResource] = []

        for declarations in declaration_groups:
            declaration = declarations[0]
            identity = self._resource_identity(
                declaration.kind,
                declaration.name,
            )
            declared_identities.add(identity)
            available = available_by_identity.get(identity)
            unavailable_reason = (
                "its manifest source path was rejected"
                if all(item.source_path is None for item in declarations)
                else "none of its declared source paths could be validated and read"
            )

            if declaration.kind == "included_files":
                allowed_sources: set[str] = set()
                reasons: list[str] = []
                for item in declarations:
                    source_path, reason = self._declared_included_file_source(
                        item
                    )
                    if source_path is not None:
                        allowed_sources.add(source_path)
                    elif reason:
                        reasons.append(reason)
                if (
                    available is None
                    or available.source_path not in allowed_sources
                ):
                    available = None
                if reasons:
                    unavailable_reason = reasons[-1]

            if available is not None:
                resource_key = self._outcome_resource_key(available)
                selected_by_identity[identity] = available
                requested_keys.append(resource_key)
                continue

            outcome_key = self._unavailable_outcome_resource_key(declaration)
            requested_keys.append(outcome_key)
            unavailable.append(
                _UnavailableRegistryResource(
                    declaration=declaration,
                    outcome_key=outcome_key,
                    reason=unavailable_reason,
                )
            )

        # GameMaker's Included Files surface mirrors the physical datafiles
        # tree. Keep contained disk files in the registry even when an older
        # YYP does not list them, while still accounting for stale declarations.
        for resource in resources:
            identity = self._resource_identity(resource.kind, resource.name)
            if (
                resource.kind != "included_files"
                or identity in declared_identities
            ):
                continue
            selected_by_identity[identity] = resource
            requested_keys.append(self._outcome_resource_key(resource))

        selected_resources = tuple(
            resource
            for resource in resources
            if self._resource_identity(resource.kind, resource.name)
            in selected_by_identity
        )
        resource_keys = tuple(
            self._outcome_resource_key(resource)
            for resource in selected_resources
        )
        return _AssetRegistryConversionPlan(
            resources=selected_resources,
            resource_keys=resource_keys,
            requested_keys=tuple(requested_keys),
            unavailable=tuple(unavailable),
        )

    def _declared_registry_resources(
        self,
    ) -> tuple[tuple[_DeclaredRegistryResource, ...], ...]:
        """Return unique supported YYP base assets, including rejected paths."""
        declared_by_identity: dict[
            tuple[str, str],
            list[_DeclaredRegistryResource],
        ] = {}
        seen_declarations: set[tuple[str, str, str | None]] = set()

        def add(resource: _DeclaredRegistryResource) -> None:
            identity = self._resource_identity(resource.kind, resource.name)
            declaration_key = (*identity, resource.source_path)
            if (
                not resource.name
                or resource.kind not in self.RESOURCE_TYPE_BY_KIND
                or declaration_key in seen_declarations
            ):
                return
            seen_declarations.add(declaration_key)
            declared_by_identity.setdefault(identity, []).append(resource)

        for resource in self.project_manifest.resources:
            kind = self._manifest_registry_kind(
                resource.kind,
                resource.resource_type,
            )
            if kind is None:
                continue
            manifest_field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None
                and resource.source.field_path
                else "resources[].id.path"
            )
            add(
                _DeclaredRegistryResource(
                    kind=kind,
                    name=resource.name,
                    source_path=resource.path,
                    owner_source_path=self.project_manifest.yyp_path,
                    manifest_field=manifest_field,
                )
            )

        for diagnostic in self.project_manifest.diagnostics:
            if (
                diagnostic.code != "GM2GD-SOURCE-PATH-REJECTED"
                or not diagnostic.resource
            ):
                continue
            kind = self._manifest_diagnostic_registry_kind(diagnostic)
            if kind is None:
                continue
            add(
                _DeclaredRegistryResource(
                    kind=kind,
                    name=diagnostic.resource,
                    source_path=None,
                    owner_source_path=(
                        diagnostic.source.path
                        if diagnostic.source is not None
                        else self.project_manifest.yyp_path
                    ),
                    manifest_field=(
                        diagnostic.source.field_path
                        if diagnostic.source is not None
                        else None
                    ),
                )
            )

        for included_file in self.project_manifest.included_files:
            raw_field = next(
                (
                    key
                    for key in ("path", "filePath", "filename")
                    if key in included_file.raw_data
                ),
                "path",
            )
            source_path = included_file.path
            if (
                raw_field == "filePath"
                and included_file.name
                and posixpath.basename(source_path) != included_file.name
            ):
                # Current GameMaker projects store the containing datafiles
                # directory in filePath and the payload filename in name.
                source_path = posixpath.join(source_path, included_file.name)
            logical_name = self._included_file_logical_name(
                source_path,
                included_file.name,
            )
            manifest_field = (
                f"{included_file.source.field_path}.{raw_field}"
                if included_file.source is not None
                and included_file.source.field_path
                else f"IncludedFiles[].{raw_field}"
            )
            add(
                _DeclaredRegistryResource(
                    kind="included_files",
                    name=logical_name,
                    source_path=source_path or None,
                    owner_source_path=self.project_manifest.yyp_path,
                    manifest_field=manifest_field,
                )
            )

        return tuple(
            tuple(declarations)
            for declarations in declared_by_identity.values()
        )

    @classmethod
    def _manifest_registry_kind(
        cls,
        kind: str | None,
        resource_type: str | None,
    ) -> str | None:
        normalized_kind = (kind or "").casefold()
        if normalized_kind == "datafiles":
            normalized_kind = "included_files"
        if normalized_kind in cls.RESOURCE_TYPE_BY_KIND:
            return normalized_kind
        return cls.MANIFEST_KIND_BY_RESOURCE_TYPE.get(
            (resource_type or "").casefold()
        )

    @classmethod
    def _manifest_diagnostic_registry_kind(
        cls,
        diagnostic: ProjectManifestDiagnostic,
    ) -> str | None:
        return cls._manifest_registry_kind(
            diagnostic.resource_kind,
            diagnostic.resource_type,
        )

    @staticmethod
    def _resource_identity(kind: str, name: str) -> tuple[str, str]:
        return (kind, name)

    @staticmethod
    def _included_file_logical_name(path: str, name: str) -> str:
        normalized = posixpath.normpath(path.replace("\\", "/"))
        if normalized.startswith("datafiles/"):
            relative_path = normalized.removeprefix("datafiles/")
            if relative_path and relative_path != ".":
                return relative_path
        return name or posixpath.basename(normalized)

    def _declared_included_file_source(
        self,
        resource: _DeclaredRegistryResource,
    ) -> tuple[str | None, str]:
        if resource.source_path is None:
            return None, "its manifest source path was rejected"
        resolved = self._resolve_project_source(
            resource.source_path,
            owner_source_path=resource.owner_source_path,
            resource=resource.name,
            resource_type="included_file",
            field=resource.manifest_field,
        )
        if resolved is None:
            return None, "its manifest source path was rejected"
        try:
            source_kind, separator, _remainder = (
                resolved.source_path.partition("/")
            )
            if not separator or source_kind.casefold() != "datafiles":
                raise ProjectSourcePathError(
                    "Resolved GameMaker included-file path must remain under "
                    "the 'datafiles' directory after normalization: "
                    f"{resolved.source_path!r}"
                )
            canonical_datafiles = os.path.realpath(
                os.path.join(self.gm_project_path, "datafiles")
            )
            canonical_source = os.path.realpath(resolved.filesystem_path)
            if os.path.normcase(
                os.path.commonpath(
                    (canonical_datafiles, canonical_source)
                )
            ) != os.path.normcase(canonical_datafiles):
                raise ProjectSourcePathError(
                    "Resolved GameMaker included-file target must remain "
                    "under the 'datafiles' directory after symbolic-link "
                    f"resolution: {resolved.source_path!r}"
                )
        except ProjectSourcePathError as exc:
            self._report_source_path_rejection(
                resource.source_path,
                exc,
                owner_source_path=resource.owner_source_path,
                resource=resource.name,
                resource_type="included_file",
                field=resource.manifest_field,
            )
            return None, "its manifest source path was rejected"
        except ValueError as exc:
            self._report_source_path_rejection(
                resource.source_path,
                ProjectSourcePathError(str(exc)),
                owner_source_path=resource.owner_source_path,
                resource=resource.name,
                resource_type="included_file",
                field=resource.manifest_field,
            )
            return None, "its manifest source path was rejected"
        if (
            resolved.source_path.endswith(".yy")
            or not os.path.isfile(resolved.filesystem_path)
        ):
            return (
                None,
                f"the declared file is missing at {resolved.source_path!r}",
            )
        return resolved.source_path, ""

    @staticmethod
    def _unavailable_outcome_resource_key(
        resource: _DeclaredRegistryResource,
    ) -> str:
        source_label = resource.source_path or resource.manifest_field or ""
        return f"{resource.kind}:{resource.name}:{source_label}"

    def _report_unavailable_registry_resource(
        self,
        resource: _UnavailableRegistryResource,
    ) -> None:
        declaration = resource.declaration
        asset_type = self.RESOURCE_TYPE_BY_KIND[declaration.kind]
        message = (
            "Warning: Skipping manifest-declared GameMaker asset-registry "
            f"{asset_type} {declaration.name!r} because {resource.reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-ASSET-REGISTRY-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    declaration.owner_source_path
                ),
                resource=declaration.name,
                resource_type=asset_type,
                manifest_entry=declaration.manifest_field,
                workaround=(
                    "Restore the declared GameMaker resource inside the "
                    "project root or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def _build_entries_from_resources(
        self,
        resources: tuple[_ProjectResource, ...],
        *,
        track_outcomes: bool = False,
    ) -> tuple[tuple[AssetRegistryEntry, ...], int]:
        """Build entries and report how many base resources began processing."""
        self._timeline_action_source_failures.clear()
        room_order_indices = self._room_order_indices(resources)
        godot_paths = self._stable_godot_paths(resources)
        timeline_script_stems = self._stable_timeline_script_stems(resources)
        used_ids: set[int] = set()
        entries: list[AssetRegistryEntry] = []
        processed_count = 0

        for resource in resources:
            if not self.conversion_running():
                break
            if track_outcomes:
                self._resource_started(self._outcome_resource_key(resource))
            asset_type = self.RESOURCE_TYPE_BY_KIND[resource.kind]
            entry = AssetRegistryEntry(
                id=self._stable_asset_id(asset_type, resource.name, used_ids),
                name=resource.name,
                kind=resource.kind,
                asset_type=asset_type,
                type_name=self.TYPE_NAME_BY_KIND[resource.kind],
                source_path=resource.source_path,
                godot_path=godot_paths[self._resource_key(resource)],
                legacy_id=self._legacy_id(resource),
                tags=self._extract_tags(resource.raw_data),
                metadata=self._metadata(
                    resource,
                    room_order_indices,
                    timeline_script_stem=timeline_script_stems.get(
                        self._resource_key(resource)
                    ),
                    godot_path=godot_paths[self._resource_key(resource)],
                ),
            )
            entries.append(entry)
            if resource.kind == "scripts":
                for function_name in self._script_function_names(resource):
                    if function_name == resource.name:
                        continue
                    entries.append(
                        AssetRegistryEntry(
                            id=self._stable_asset_id(asset_type, function_name, used_ids),
                            name=function_name,
                            kind=resource.kind,
                            asset_type=asset_type,
                            type_name=self.TYPE_NAME_BY_KIND[resource.kind],
                            source_path=resource.source_path,
                            godot_path=entry.godot_path,
                            legacy_id=f"{self._legacy_id(resource)}#function:{function_name}",
                            tags=self._extract_tags(resource.raw_data),
                            metadata={
                                "script_function": True,
                                "script_asset": resource.name,
                                "script_source_path": resource.source_path,
                            },
                        )
                    )
            processed_count += 1

        return tuple(entries), processed_count

    def convert_all(self) -> str:
        self._reset_resource_outcomes()
        plan = self._conversion_plan()
        resources = plan.resources
        for resource_key in plan.requested_keys:
            self._resource_requested(resource_key)
        for unavailable in plan.unavailable:
            self._resource_skipped(unavailable.outcome_key)
            self._report_unavailable_registry_resource(unavailable)

        entries, processed_count = self._build_entries_from_resources(
            resources,
            track_outcomes=True,
        )
        registry_path = os.path.join(self.godot_project_path, ASSET_REGISTRY_RELATIVE_PATH)
        if processed_count < len(resources) or not self.conversion_running():
            return registry_path

        try:
            texture_groups, audio_groups = self.build_group_registries(entries)
            self._write_group_compatibility_report(
                entries,
                texture_groups,
                audio_groups,
            )
            timeline_completeness = self._write_timeline_action_scripts(entries)
            write_path_registry(
                self.gm_project_path,
                self.godot_project_path,
                entries,
            )
            write_animation_curve_registry(
                self.gm_project_path,
                self.godot_project_path,
                entries,
            )
            write_extension_compatibility_outputs(
                self.gm_project_path,
                self.godot_project_path,
                diagnostics=self.diagnostics,
                log_callback=self.log_callback,
                asset_entries=entries,
            )
            registry_script = render_asset_registry_script(
                entries,
                texture_groups=texture_groups,
                audio_groups=audio_groups,
            )
            self._atomic_write_text(
                registry_path,
                registry_script,
                confinement_root=self.godot_project_path,
            )
        except Exception:
            for resource_key in plan.resource_keys:
                self._resource_failed(resource_key)
            raise

        for resource in resources:
            resource_key = self._outcome_resource_key(resource)
            timeline_key = (resource.name, resource.source_path)
            if (
                resource.kind == "timelines"
                and not timeline_completeness.get(timeline_key, True)
            ):
                self._resource_skipped(resource_key)
            else:
                self._resource_completed(resource_key)

        self.log_callback(
            "Generated GameMaker asset registry: {path} ({count} assets)".format(
                path=ASSET_REGISTRY_RELATIVE_PATH.replace(os.sep, "/"),
                count=len(entries),
            )
        )
        return registry_path

    @staticmethod
    def _atomic_write_text(
        output_path: str,
        content: str,
        *,
        confinement_root: str | None = None,
    ) -> None:
        """Publish generated UTF-8 text through a confined, no-follow path."""
        output_absolute = os.path.abspath(output_path)
        output_directory = os.path.dirname(output_absolute) or os.curdir
        root = os.path.abspath(confinement_root or output_directory)
        components = _asset_output_components(root, output_absolute)
        _ensure_asset_output_root(root)
        if _confined_asset_output_supported():
            _atomic_write_asset_text_at(root, components, content)
            return
        _atomic_write_asset_text_fallback(root, components, content)

    @staticmethod
    def _outcome_resource_key(resource: _ProjectResource) -> str:
        """Return an opaque lifecycle key for one deduplicated base resource."""
        return f"{resource.kind}:{resource.name}:{resource.source_path}"

    def build_group_registries(
        self,
        entries: tuple[AssetRegistryEntry, ...],
    ) -> tuple[tuple[JsonDict, ...], tuple[JsonDict, ...]]:
        """Return generated texture/audio group registry entries."""
        return (
            self._texture_group_registry(entries),
            self._audio_group_registry(entries),
        )

    def _load_project_resources(self) -> tuple[_ProjectResource, ...]:
        manifest_rejected_fields = (
            self._record_project_manifest_source_path_diagnostics(
                self.project_manifest,
                include_project_sources=True,
            )
        )
        yyp_path = self.project_manifest.yyp_path
        manifest_parse_failed = any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in self.project_manifest.diagnostics
        )
        yyp_source_path = self._diagnostic_source_path(yyp_path)
        if (
            yyp_path is not None
            and yyp_source_path is not None
            and not manifest_parse_failed
        ):
            resources = list(
                self._resources_from_yyp(
                    self.project_manifest.raw_data,
                    yyp_source_path,
                    manifest_rejected_fields,
                )
            )
            resources.extend(self._included_files_from_disk())
            return tuple(self._dedupe_resources(resources))

        if yyp_path is not None:
            self._safe_log("Warning: Could not parse GameMaker project .yyp; using disk asset scan.")

        resources = list(self._resources_from_disk())
        resources.extend(self._included_files_from_disk())
        return tuple(self._dedupe_resources(resources))

    def _resources_from_yyp(
        self,
        yyp_data: JsonDict,
        yyp_source_path: str,
        manifest_rejected_fields: frozenset[str],
    ) -> tuple[_ProjectResource, ...]:
        resource_entries = yyp_data.get("resources")
        if not isinstance(resource_entries, list):
            return ()

        resources: list[_ProjectResource] = []
        for index, raw_entry in enumerate(cast(list[object], resource_entries)):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(JsonDict, raw_entry)
            raw_id = entry.get("id")
            if not isinstance(raw_id, dict):
                continue
            resource_id = cast(JsonDict, raw_id)
            field = f"resources[{index}].id.path"
            if field in manifest_rejected_fields:
                continue
            raw_path = resource_id.get("path")
            if not isinstance(raw_path, str) or not raw_path:
                continue

            raw_name = resource_id.get("name")
            name = (
                raw_name
                if isinstance(raw_name, str) and raw_name
                else self._name_from_path(raw_path.replace("\\", "/"))
            )
            kind_hint = self._normalize_yyp_kind(raw_path.replace("\\", "/"))
            resolved_path = self._resolve_project_source(
                raw_path,
                owner_source_path=yyp_source_path,
                resource=name or "<unnamed>",
                resource_type=self.RESOURCE_TYPE_BY_KIND.get(
                    kind_hint,
                    kind_hint or "asset",
                ),
                field=field,
            )
            if resolved_path is None:
                continue

            declared_kind = self.FOLDER_BY_KIND.get(kind_hint, kind_hint)
            try:
                validate_project_resource_source_path(
                    resolved_path,
                    declared_kind,
                )
            except ProjectSourcePathError as exc:
                self._report_source_path_rejection(
                    raw_path,
                    exc,
                    owner_source_path=yyp_source_path,
                    resource=name or "<unnamed>",
                    resource_type=self.RESOURCE_TYPE_BY_KIND.get(
                        kind_hint,
                        kind_hint or "asset",
                    ),
                    field=field,
                )
                continue

            kind = kind_hint
            if kind not in self.RESOURCE_TYPE_BY_KIND or kind == "included_files":
                continue

            if not name:
                continue

            yy_path = resolved_path.filesystem_path
            source_path = resolved_path.source_path
            if not os.path.isfile(yy_path):
                self._safe_log(f"Warning: Skipping missing GameMaker asset {name}: {yy_path}")
                continue

            raw_data = self._read_yy_file(yy_path)
            if raw_data is None:
                self._safe_log(
                    "Warning: Skipping unreadable or malformed GameMaker "
                    f"asset metadata for {name}: {yy_path}"
                )
                continue

            resources.append(
                _ProjectResource(
                    kind=kind,
                    name=name,
                    yy_path=yy_path,
                    source_path=source_path,
                    raw_data=raw_data,
                )
            )
        return tuple(resources)

    def _resources_from_disk(self) -> tuple[_ProjectResource, ...]:
        resources: list[_ProjectResource] = []
        for kind in self.RESOURCE_TYPE_BY_KIND:
            if kind == "included_files":
                continue
            folder = self.FOLDER_BY_KIND[kind]
            resource_type = self.RESOURCE_TYPE_BY_KIND[kind]
            kind_source = self._resolve_discovered_project_source(
                os.path.join(self.gm_project_path, folder),
                resource_type=resource_type,
                field="disk fallback kind directory",
            )
            if kind_source is None or not os.path.isdir(
                kind_source.filesystem_path
            ):
                continue

            try:
                resource_names = sorted(os.listdir(kind_source.filesystem_path))
            except OSError:
                continue

            for name in resource_names:
                resource_source = self._resolve_discovered_project_source(
                    os.path.join(kind_source.filesystem_path, name),
                    owner_source_path=kind_source.source_path,
                    resource=name,
                    resource_type=resource_type,
                    field="disk fallback resource directory",
                )
                if resource_source is None or not os.path.isdir(
                    resource_source.filesystem_path
                ):
                    continue
                yy_source = self._resolve_discovered_project_source(
                    os.path.join(
                        resource_source.filesystem_path,
                        name + ".yy",
                    ),
                    owner_source_path=resource_source.source_path,
                    resource=name,
                    resource_type=resource_type,
                    field="disk fallback resource metadata",
                )
                if yy_source is None:
                    continue
                try:
                    validate_project_resource_source_path(
                        yy_source,
                        folder,
                    )
                except ProjectSourcePathError as exc:
                    self._report_source_path_rejection(
                        yy_source.source_path,
                        exc,
                        owner_source_path=resource_source.source_path,
                        resource=name,
                        resource_type=resource_type,
                        field="disk fallback resource metadata",
                    )
                    continue
                if not os.path.isfile(yy_source.filesystem_path):
                    continue
                raw_data = self._read_yy_file(yy_source.filesystem_path)
                if raw_data is None:
                    self._safe_log(
                        "Warning: Skipping unreadable or malformed GameMaker "
                        f"asset metadata for {name}: "
                        f"{yy_source.filesystem_path}"
                    )
                    continue
                resources.append(
                    _ProjectResource(
                        kind=kind,
                        name=name,
                        yy_path=yy_source.filesystem_path,
                        source_path=yy_source.source_path,
                        raw_data=raw_data,
                    )
                )
        return tuple(resources)

    def _script_source_gml_path(self, resource: _ProjectResource) -> str | None:
        yy_source = self._resolve_project_source(
            resource.source_path,
            resource=resource.name,
            resource_type="script",
            field="script .yy",
        )
        if yy_source is None or not os.path.isfile(yy_source.filesystem_path):
            return None

        script_directory = self._resolve_discovered_project_source(
            os.path.dirname(yy_source.filesystem_path),
            owner_source_path=yy_source.source_path,
            resource=resource.name,
            resource_type="script",
            field="script source directory",
        )
        if script_directory is None or not os.path.isdir(
            script_directory.filesystem_path
        ):
            return None

        preferred_filename = resource.name + ".gml"
        excluded_filenames = {preferred_filename}
        preferred_source = None
        if not is_safe_project_source_component(resource.name):
            normalized_preferred_filename = posixpath.basename(
                posixpath.normpath(preferred_filename.replace("\\", "/"))
            )
            if normalized_preferred_filename:
                excluded_filenames.add(normalized_preferred_filename)
            self._report_source_path_rejection(
                preferred_filename,
                ProjectSourcePathError(
                    "GameMaker script resource names used to derive source "
                    "filenames must identify exactly one path component: "
                    f"{resource.name!r}"
                ),
                owner_source_path=yy_source.source_path,
                resource=resource.name,
                resource_type="script",
                field="preferred script source",
            )
        else:
            preferred_source = self._resolve_project_source(
                preferred_filename,
                owner_source_path=yy_source.source_path,
                resource=resource.name,
                resource_type="script",
                field="preferred script source",
            )
        if preferred_source is not None:
            owner_directory = posixpath.dirname(yy_source.source_path)
            preferred_directory = posixpath.dirname(preferred_source.source_path)
            if preferred_directory != owner_directory:
                self._report_source_path_rejection(
                    preferred_filename,
                    ProjectSourcePathError(
                        "GameMaker script source derived from the resource name "
                        "must be next to its script .yy owner: "
                        f"{preferred_filename!r}"
                    ),
                    owner_source_path=yy_source.source_path,
                    resource=resource.name,
                    resource_type="script",
                    field="preferred script source",
                )
                preferred_source = None
            elif os.path.isfile(preferred_source.filesystem_path):
                return preferred_source.filesystem_path

        try:
            filenames = sorted(os.listdir(script_directory.filesystem_path))
        except OSError:
            return None
        for filename in filenames:
            if not filename.endswith(".gml") or filename in excluded_filenames:
                continue
            discovered_source = self._resolve_discovered_project_source(
                os.path.join(script_directory.filesystem_path, filename),
                owner_source_path=yy_source.source_path,
                resource=resource.name,
                resource_type="script",
                field="discovered script source",
            )
            if discovered_source is None or not os.path.isfile(
                discovered_source.filesystem_path
            ):
                continue
            return discovered_source.filesystem_path
        return None

    def _script_function_names(self, resource: _ProjectResource) -> tuple[str, ...]:
        source_path = self._script_source_gml_path(resource)
        if source_path is None:
            return ()
        try:
            with open(source_path, "r", encoding="utf-8") as source_file:
                return modern_script_function_names(
                    source_file.read(),
                    macro_configuration=self.macro_configuration,
                )
        except (OSError, GMLTranspileError):
            return ()

    def _included_files_from_disk(self) -> tuple[_ProjectResource, ...]:
        datafiles_source = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, "datafiles"),
            resource_type="included_file",
            field="datafiles directory",
        )
        if datafiles_source is None or not os.path.isdir(
            datafiles_source.filesystem_path
        ):
            return ()

        resources: list[_ProjectResource] = []
        pending_directories = [
            (
                datafiles_source.filesystem_path,
                datafiles_source.source_path,
            )
        ]
        visited_directories: set[str] = set()
        while pending_directories:
            directory_path, directory_source_path = pending_directories.pop()
            canonical_directory = os.path.normcase(os.path.realpath(directory_path))
            if canonical_directory in visited_directories:
                continue
            visited_directories.add(canonical_directory)
            try:
                entry_names = sorted(os.listdir(directory_path), reverse=True)
            except OSError:
                continue
            for entry_name in entry_names:
                entry_path = os.path.join(directory_path, entry_name)
                entry_is_symlink = os.path.islink(entry_path)
                entry_source = self._resolve_discovered_project_source(
                    entry_path,
                    owner_source_path=directory_source_path,
                    resource=entry_name,
                    resource_type="included_file",
                    field="discovered datafiles entry",
                )
                if entry_source is None:
                    continue
                if os.path.isdir(entry_source.filesystem_path):
                    if not entry_is_symlink:
                        pending_directories.append(
                            (
                                entry_source.filesystem_path,
                                entry_source.source_path,
                            )
                        )
                    continue
                if entry_name.endswith(".yy") or not os.path.isfile(
                    entry_source.filesystem_path
                ):
                    continue
                rel_path = posixpath.relpath(
                    entry_source.source_path,
                    datafiles_source.source_path,
                )
                resources.append(
                    _ProjectResource(
                        kind="included_files",
                        name=rel_path,
                        yy_path="",
                        source_path=entry_source.source_path,
                        raw_data={},
                    )
                )
        return tuple(sorted(resources, key=lambda resource: resource.source_path))

    @staticmethod
    def _dedupe_resources(resources: list[_ProjectResource]) -> tuple[_ProjectResource, ...]:
        deduped: dict[tuple[str, str], _ProjectResource] = {}
        for resource in resources:
            deduped.setdefault((resource.kind, resource.name), resource)
        return tuple(deduped.values())

    def _stable_godot_paths(
        self,
        resources: Iterable[_ProjectResource],
    ) -> dict[tuple[str, str, str], str]:
        ordered_resources = tuple(resources)
        extension_paths = collision_safe_extension_stub_resource_paths(
            (resource.name, resource.source_path)
            for resource in ordered_resources
            if resource.kind == "extensions"
        )
        paths: dict[tuple[str, str, str], str] = {}
        used_paths: set[str] = set()
        for resource in ordered_resources:
            if resource.kind == "extensions":
                path = extension_paths[(resource.name, resource.source_path)]
                used_paths.add(path.casefold())
                paths[self._resource_key(resource)] = path
                continue
            suffix_index = 0
            base_path = ""
            while True:
                suffix = "" if suffix_index == 0 else f"_{suffix_index + 1}"
                path = self._godot_path(resource, suffix=suffix)
                if suffix_index == 0:
                    base_path = path
                elif path == base_path:
                    path = self._suffix_resource_path(path, suffix)
                folded_path = path.casefold()
                if not folded_path or folded_path not in used_paths:
                    break
                suffix_index += 1
            if path:
                used_paths.add(folded_path)
            paths[self._resource_key(resource)] = path
        return paths

    @classmethod
    def _stable_timeline_script_stems(
        cls,
        resources: Iterable[_ProjectResource],
    ) -> dict[tuple[str, str, str], str]:
        """Return order-independent, case-insensitively unique timeline stems."""
        timeline_resources = sorted(
            (
                resource
                for resource in resources
                if resource.kind == "timelines"
            ),
            key=lambda resource: (
                generated_resource_stem(resource.name).casefold(),
                resource.name.casefold(),
                resource.name,
                resource.source_path.casefold(),
                resource.source_path,
            ),
        )
        stems: dict[tuple[str, str, str], str] = {}
        used_stems: set[str] = set()
        for resource in timeline_resources:
            base_stem = generated_resource_stem(resource.name)
            suffix_index = 0
            while True:
                suffix = "" if suffix_index == 0 else f"_{suffix_index + 1}"
                stem = base_stem + suffix
                if stem.casefold() not in used_stems:
                    break
                suffix_index += 1
            used_stems.add(stem.casefold())
            stems[cls._resource_key(resource)] = stem
        return stems

    @staticmethod
    def _resource_key(resource: _ProjectResource) -> tuple[str, str, str]:
        return (resource.kind, resource.name, resource.source_path)

    @staticmethod
    def _suffix_resource_path(path: str, suffix: str) -> str:
        if not suffix:
            return path
        stem, extension = os.path.splitext(path)
        return f"{stem}{suffix}{extension}"

    def _godot_path(self, resource: _ProjectResource, *, suffix: str = "") -> str:
        if resource.kind in self.STATIC_RESOURCE_EXTENSIONS:
            return self._nested_resource_path(
                resource.kind,
                self._get_subfolder_from_resource(resource),
                resource.name,
                self.STATIC_RESOURCE_EXTENSIONS[resource.kind],
                suffix=suffix,
            )
        if resource.kind == "sounds":
            return self._sound_godot_path(resource, suffix=suffix)
        if resource.kind == "fonts":
            return self._font_godot_path(resource, suffix=suffix)
        if resource.kind == "scripts":
            return self._flat_resource_path("scripts", self._get_subfolder_from_resource(resource), resource.name, ".gd", suffix=suffix)
        if resource.kind == "shaders":
            return self._flat_resource_path("shaders", self._get_subfolder_from_resource(resource), resource.name, ".gdshader", suffix=suffix)
        if resource.kind == "included_files":
            return "res://included_files/" + resource.name
        if resource.kind == "extensions":
            return extension_stub_resource_path(
                resource.name,
                suffix=suffix,
            )
        return ""

    def _sound_godot_path(self, resource: _ProjectResource, *, suffix: str = "") -> str:
        sound_file_reference = resource.raw_data.get("soundFile")
        if not isinstance(sound_file_reference, str) or not sound_file_reference:
            return ""
        sound_source = self._resolve_project_source(
            sound_file_reference,
            owner_source_path=resource.source_path,
            resource=resource.name,
            resource_type="sound",
            field="soundFile",
        )
        if sound_source is None:
            return ""
        sound_filename = os.path.basename(sound_source.filesystem_path)

        parts = ["sounds"]
        if self.organize_sounds_by_audio_group:
            audio_group = self._reference_name(resource.raw_data.get("audioGroupId"))
            parts.append(generated_path_segment(audio_group or "audiogroup_default", "audiogroup_default"))
        subfolder = self._get_subfolder_from_resource(resource)
        parts.extend(part for part in subfolder.split("/") if part)
        parts.extend([generated_resource_stem(resource.name) + suffix, sound_filename])
        return "res://" + "/".join(parts)

    def _metadata(
        self,
        resource: _ProjectResource,
        room_order_indices: dict[str, int] | None = None,
        *,
        timeline_script_stem: str | None = None,
        godot_path: str = "",
    ) -> JsonDict:
        if resource.kind == "rooms":
            room_settings = resource.raw_data.get("roomSettings")
            settings = cast(JsonDict, room_settings) if isinstance(room_settings, dict) else {}
            return {
                "room_order": (room_order_indices or {}).get(resource.name, -1),
                "width": self._metadata_int(settings.get("Width"), 1024),
                "height": self._metadata_int(settings.get("Height"), 768),
                "persistent": bool(settings.get("persistent", False)),
                "volume": self._metadata_float(resource.raw_data.get("volume"), 1.0),
            }

        if resource.kind == "sequences":
            return self._sequence_metadata(resource.raw_data)

        if resource.kind == "timelines":
            return self._timeline_metadata(
                resource,
                script_stem=timeline_script_stem,
            )

        if resource.kind in {"particles", "particlesystems"}:
            return self._particle_system_metadata(resource.raw_data)

        if resource.kind == "extensions":
            return extension_entry_metadata(
                extension_entry_from_yy(
                    self.gm_project_path,
                    resource.yy_path,
                    resource.raw_data,
                ),
                stub_path=godot_path or None,
            )

        if resource.kind in {"sprites", "fonts", "tilesets"}:
            texture_group = self._reference_name(resource.raw_data.get("textureGroupId"))
            if texture_group:
                return self._texture_group_asset_metadata(texture_group)
            return {}

        if resource.kind != "sounds":
            return {}

        audio_group = self._reference_name(resource.raw_data.get("audioGroupId"))
        sound_file = resource.raw_data.get("soundFile")
        return {
            "audio_group": audio_group or "audiogroup_default",
            "sound_file": sound_file if isinstance(sound_file, str) else "",
            "volume": self._metadata_float(resource.raw_data.get("volume"), 1.0),
            "duration": self._metadata_float(resource.raw_data.get("duration"), 0.0),
            "preload": bool(resource.raw_data.get("preload", True)),
            "compression": self._metadata_int(resource.raw_data.get("compression"), 0),
            "type": self._metadata_int(resource.raw_data.get("type"), 0),
        }

    def _texture_group_asset_metadata(self, texture_group: str) -> JsonDict:
        metadata: JsonDict = {"texture_group": texture_group}
        group = self._manifest_texture_group(texture_group)
        if group is None:
            return metadata
        metadata["texture_group_dynamic"] = group.is_dynamic
        metadata["texture_group_targets"] = list(group.targets)
        if group.dynamic_path:
            metadata["texture_group_dynamic_path"] = group.dynamic_path
        return metadata

    def _texture_group_registry(self, entries: tuple[AssetRegistryEntry, ...]) -> tuple[JsonDict, ...]:
        groups: dict[str, _TextureGroupRegistryEntry] = {}
        for manifest_group in self.project_manifest.texture_groups:
            if not manifest_group.name:
                continue
            groups[manifest_group.name] = _TextureGroupRegistryEntry(
                name=manifest_group.name,
                parent=manifest_group.parent,
                dynamic=manifest_group.is_dynamic,
                dynamic_path=manifest_group.dynamic_path,
                targets=manifest_group.targets,
            )

        for entry in entries:
            if entry.asset_type not in {"sprite", "font", "tileset"}:
                continue
            metadata = entry.metadata or {}
            group_name = self._metadata_string(metadata.get("texture_group"), "Default")
            group = groups.setdefault(group_name, _TextureGroupRegistryEntry(name=group_name))
            group.asset_ids.append(entry.id)
            group.asset_names.append(entry.name)

        return tuple(groups[name].to_dict() for name in sorted(groups))

    def _audio_group_registry(self, entries: tuple[AssetRegistryEntry, ...]) -> tuple[JsonDict, ...]:
        groups: dict[str, _AudioGroupRegistryEntry] = {}
        for manifest_group in self.project_manifest.audio_groups:
            if not manifest_group.name:
                continue
            groups[manifest_group.name] = _AudioGroupRegistryEntry(
                name=manifest_group.name,
                targets=manifest_group.targets,
                loaded=self._audio_group_initial_loaded(manifest_group.name, manifest_group.raw_data),
                gain=self._metadata_float(manifest_group.raw_data.get("gain"), 1.0),
            )

        groups.setdefault(
            "audiogroup_default",
            _AudioGroupRegistryEntry(name="audiogroup_default", loaded=True),
        )
        for entry in entries:
            if entry.asset_type != "sound":
                continue
            metadata = entry.metadata or {}
            group_name = self._metadata_string(metadata.get("audio_group"), "audiogroup_default")
            group = groups.setdefault(
                group_name,
                _AudioGroupRegistryEntry(
                    name=group_name,
                    loaded=group_name in {"", "audiogroup_default"},
                ),
            )
            group.asset_ids.append(entry.id)
            group.asset_names.append(entry.name)

        return tuple(groups[name].to_dict() for name in sorted(groups))

    def _write_group_compatibility_report(
        self,
        entries: tuple[AssetRegistryEntry, ...],
        texture_groups: tuple[JsonDict, ...],
        audio_groups: tuple[JsonDict, ...],
    ) -> str:
        report_path = os.path.join(self.godot_project_path, GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH)
        payload = self._group_compatibility_report(entries, texture_groups, audio_groups)
        self._atomic_write_text(
            report_path,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            confinement_root=self.godot_project_path,
        )
        return report_path

    def _group_compatibility_report(
        self,
        entries: tuple[AssetRegistryEntry, ...],
        texture_groups: tuple[JsonDict, ...],
        audio_groups: tuple[JsonDict, ...],
    ) -> JsonDict:
        diagnostics: list[JsonDict] = []
        for group in texture_groups:
            name = self._metadata_string(group.get("name"), "Default")
            if bool(group.get("dynamic", False)):
                diagnostics.append(self._group_diagnostic(
                    "texture_group_dynamic_runtime",
                    "warning",
                    name,
                    "Godot imports textures as resources; GM2Godot tracks dynamic texture-group load state but cannot evict packed texture pages exactly like GameMaker.",
                ))
            if group.get("targets"):
                diagnostics.append(self._group_diagnostic(
                    "texture_group_platform_targets",
                    "info",
                    name,
                    "Texture group platform export targets are preserved in metadata; Godot export filtering must be handled by export presets or project-specific tooling.",
                ))

        for group in audio_groups:
            name = self._metadata_string(group.get("name"), "audiogroup_default")
            if name != "audiogroup_default":
                diagnostics.append(self._group_diagnostic(
                    "audio_group_memory_runtime",
                    "warning",
                    name,
                    "Audio group load/unload updates GM2Godot compatibility state; Godot ResourceLoader may still cache imported streams after unload.",
                ))
            if group.get("targets"):
                diagnostics.append(self._group_diagnostic(
                    "audio_group_platform_targets",
                    "info",
                    name,
                    "Audio group platform export targets are preserved in metadata; Godot export filtering must be handled by export presets or project-specific tooling.",
                ))

        for entry in entries:
            if entry.asset_type != "sound":
                continue
            metadata = entry.metadata or {}
            if metadata.get("preload") is False:
                diagnostics.append(self._group_diagnostic(
                    "sound_preload_lazy",
                    "info",
                    entry.name,
                    "Sound preload=false is preserved; runtime loading occurs through ResourceLoader when the sound or audio group is used.",
                ))
            if self._metadata_int(metadata.get("compression"), 0) != 0 or self._metadata_int(metadata.get("type"), 0) != 0:
                diagnostics.append(self._group_diagnostic(
                    "sound_import_semantics",
                    "warning",
                    entry.name,
                    "Sound compression/type metadata is preserved, but Godot import parameters cannot exactly reproduce every GameMaker audio packaging mode.",
                ))

        return {
            "format_version": 1,
            "texture_groups": list(texture_groups),
            "audio_groups": list(audio_groups),
            "diagnostics": diagnostics,
        }

    @staticmethod
    def _group_diagnostic(code: str, severity: str, subject: str, message: str) -> JsonDict:
        return {
            "code": code,
            "severity": severity,
            "subject": subject,
            "message": message,
        }

    def _manifest_texture_group(self, name: str) -> ProjectTextureGroup | None:
        for group in self.project_manifest.texture_groups:
            if group.name == name:
                return group
        return None

    @staticmethod
    def _audio_group_initial_loaded(name: str, raw_data: JsonDict) -> bool:
        if name in {"", "audiogroup_default"}:
            return True
        for key in ("loaded", "preload", "loadOnStartup"):
            value = raw_data.get(key)
            if isinstance(value, bool):
                return value
        return False

    def _sequence_metadata(self, raw_data: JsonDict) -> JsonDict:
        length = raw_data.get("length")
        if length is None:
            length = raw_data.get("duration")
        playback_speed = raw_data.get("playbackSpeed")
        loopmode = raw_data.get("playback")
        if loopmode is None:
            loopmode = raw_data.get("loopmode")
        tracks = raw_data.get("tracks")
        return {
            "length": self._metadata_float(length, 0.0),
            "playback_speed": self._metadata_float(playback_speed, 1.0),
            "loopmode": self._metadata_int(loopmode, 0),
            "tracks": tracks if isinstance(tracks, list) else [],
            "moments": self._sequence_event_metadata(raw_data, ("moments", "momentEvents")),
            "broadcasts": self._sequence_event_metadata(raw_data, ("broadcastMessages", "broadcasts")),
        }

    def _timeline_metadata(
        self,
        resource: _ProjectResource,
        *,
        script_stem: str | None = None,
    ) -> JsonDict:
        resolved_script_stem = script_stem or generated_resource_stem(
            resource.name
        )
        moments = self._timeline_moment_metadata(
            resource,
            script_stem=resolved_script_stem,
        )
        frames = [
            self._metadata_int(moment.get("frame"), 0)
            for moment in moments
            if isinstance(moment.get("frame"), int | float)
        ]
        return {
            "moments": moments,
            "moment_count": len(moments),
            "max_moment": max(frames, default=-1),
        }

    def _timeline_moment_metadata(
        self,
        resource: _ProjectResource,
        *,
        script_stem: str | None = None,
    ) -> list[JsonDict]:
        resolved_script_stem = script_stem or generated_resource_stem(
            resource.name
        )
        raw_moments = resource.raw_data.get("momentList")
        if not isinstance(raw_moments, list):
            raw_moments = resource.raw_data.get("moments")
        if not isinstance(raw_moments, list):
            raw_moments = []

        moments: list[JsonDict] = []
        for index, raw_moment in enumerate(cast(list[object], raw_moments)):
            if not isinstance(raw_moment, dict):
                continue
            moment = cast(JsonDict, raw_moment)
            frame = self._metadata_int(
                moment.get("moment", moment.get("frame", moment.get("time", index))),
                index,
            )
            actions = self._timeline_action_metadata(
                resource,
                moment,
                frame,
                script_stem=resolved_script_stem,
            )
            moments.append({
                "frame": frame,
                "actions": actions,
                "source_path": resource.source_path,
            })

        if not moments:
            discovered_actions = self._timeline_discovered_source_actions(
                resource,
                script_stem=resolved_script_stem,
            )
            for frame, actions in discovered_actions:
                moments.append({
                    "frame": frame,
                    "actions": actions,
                    "source_path": resource.source_path,
                })
        return sorted(moments, key=lambda item: self._metadata_int(item.get("frame"), 0))

    def _timeline_action_metadata(
        self,
        resource: _ProjectResource,
        moment: JsonDict,
        frame: int,
        *,
        script_stem: str | None = None,
    ) -> list[JsonDict]:
        actions: list[JsonDict] = []
        for raw_action in self._raw_action_items(moment):
            action = self._timeline_action_from_raw(raw_action)
            if action is not None:
                actions.append(action)

        source_path = self._timeline_source_path(resource, moment, frame)
        if source_path:
            actions.append({
                "kind": "gml",
                "source_path": source_path,
                "script_path": self._timeline_action_script_resource_path(
                    script_stem or generated_resource_stem(resource.name),
                    frame,
                ),
            })
        return actions

    def _timeline_discovered_source_actions(
        self,
        resource: _ProjectResource,
        *,
        script_stem: str | None = None,
    ) -> list[tuple[int, list[JsonDict]]]:
        resolved_script_stem = script_stem or generated_resource_stem(
            resource.name
        )
        discovered: list[tuple[int, list[JsonDict]]] = []
        timeline_directory = self._resolve_discovered_project_source(
            os.path.dirname(resource.yy_path),
            owner_source_path=resource.source_path,
            resource=resource.name,
            resource_type="timeline",
            field="timeline source directory",
        )
        if timeline_directory is None:
            self._timeline_action_source_failures.add(
                (resource.name, resource.source_path)
            )
            return discovered
        try:
            filenames = sorted(os.listdir(timeline_directory.filesystem_path))
        except OSError:
            self._timeline_action_source_failures.add(
                (resource.name, resource.source_path)
            )
            return discovered

        for filename in filenames:
            if not filename.lower().endswith(".gml"):
                continue
            frame = self._timeline_frame_from_filename(filename)
            if frame is None:
                continue
            resolved_source = self._resolve_discovered_project_source(
                os.path.join(timeline_directory.filesystem_path, filename),
                owner_source_path=resource.source_path,
                resource=resource.name,
                resource_type="timeline",
                field="discovered timeline moment source",
            )
            if resolved_source is None:
                self._timeline_action_source_failures.add(
                    (resource.name, resource.source_path)
                )
                continue
            if not os.path.isfile(resolved_source.filesystem_path):
                self._timeline_action_source_failures.add(
                    (resource.name, resource.source_path)
                )
                continue
            discovered.append((
                frame,
                [{
                    "kind": "gml",
                    "source_path": resolved_source.source_path,
                    "script_path": self._timeline_action_script_resource_path(
                        resolved_script_stem,
                        frame,
                    ),
                }],
            ))
        return discovered

    def _timeline_source_path(
        self,
        resource: _ProjectResource,
        moment: JsonDict,
        frame: int,
    ) -> str:
        for key in ("gmlFile", "eventFile", "filename", "source", "sourceFile"):
            value = moment.get(key)
            if isinstance(value, str) and value:
                resolved_source = self._resolve_project_source(
                    value,
                    owner_source_path=resource.source_path,
                    resource=resource.name,
                    resource_type="timeline",
                    field=key,
                )
                if resolved_source is None:
                    self._timeline_action_source_failures.add(
                        (resource.name, resource.source_path)
                    )
                return resolved_source.source_path if resolved_source is not None else ""
        for candidate in (
            f"Moment_{frame}.gml",
            f"moment_{frame}.gml",
            f"Timeline_{frame}.gml",
            f"{frame}.gml",
        ):
            resolved_source = self._resolve_project_source(
                candidate,
                owner_source_path=resource.source_path,
                resource=resource.name,
                resource_type="timeline",
                field="implicit timeline moment source",
            )
            if (
                resolved_source is not None
                and os.path.isfile(resolved_source.filesystem_path)
            ):
                return resolved_source.source_path
        return ""

    def _raw_action_items(self, moment: JsonDict) -> list[object]:
        raw_actions = moment.get("actions")
        if not isinstance(raw_actions, list):
            raw_actions = moment.get("actionList")
        if isinstance(raw_actions, list):
            return list(cast(list[object], raw_actions))
        scripts = moment.get("scripts")
        if isinstance(scripts, list):
            return [{"script": script} for script in cast(list[object], scripts)]
        callable_name = moment.get("callable")
        if isinstance(callable_name, str) and callable_name:
            return [{"callable": callable_name}]
        return []

    def _timeline_action_from_raw(self, raw_action: object) -> JsonDict | None:
        if isinstance(raw_action, str) and raw_action:
            return {"kind": "script", "script": raw_action}
        if not isinstance(raw_action, dict):
            return None
        action = cast(JsonDict, raw_action)
        callable_name = action.get("callable")
        if isinstance(callable_name, str) and callable_name:
            return {"kind": "callable", "callable": callable_name}
        script = action.get("script") or action.get("scriptName") or action.get("name")
        if isinstance(script, str) and script:
            return {"kind": "script", "script": script}
        return {"kind": "metadata", "raw": action}

    def _sequence_event_metadata(self, raw_data: JsonDict, keys: tuple[str, ...]) -> list[JsonDict]:
        events: list[JsonDict] = []
        for key in keys:
            raw_events = raw_data.get(key)
            if not isinstance(raw_events, list):
                continue
            for index, raw_event in enumerate(cast(list[object], raw_events)):
                if not isinstance(raw_event, dict):
                    continue
                event = cast(JsonDict, raw_event)
                frame = self._metadata_float(
                    event.get("frame", event.get("moment", event.get("time", index))),
                    float(index),
                )
                normalized: JsonDict = {"frame": frame}
                for name in ("name", "message", "event", "callable", "script"):
                    value = event.get(name)
                    if isinstance(value, str) and value:
                        normalized[name] = value
                normalized["raw"] = event
                events.append(normalized)
        return sorted(events, key=lambda item: self._metadata_float(item.get("frame"), 0.0))

    def _particle_system_metadata(self, raw_data: JsonDict) -> JsonDict:
        return {
            "types": self._json_list(raw_data, ("particleTypes", "types")),
            "emitters": self._json_list(raw_data, ("emitters",)),
            "attractors": self._json_list(raw_data, ("attractors",)),
            "destroyers": self._json_list(raw_data, ("destroyers",)),
            "deflectors": self._json_list(raw_data, ("deflectors",)),
            "changers": self._json_list(raw_data, ("changers",)),
            "raw": raw_data,
        }

    def _write_timeline_action_scripts(
        self,
        entries: tuple[AssetRegistryEntry, ...],
    ) -> dict[tuple[str, str], bool]:
        """Write GML-backed moments and report each timeline's completeness."""
        asset_names = {entry.name for entry in entries}
        completeness: dict[tuple[str, str], bool] = {}
        for entry in entries:
            if entry.asset_type != "timeline":
                continue
            timeline_key = (entry.name, entry.source_path)
            timeline_complete = (
                timeline_key not in self._timeline_action_source_failures
            )
            metadata = entry.metadata or {}
            raw_moments = metadata.get("moments")
            if not isinstance(raw_moments, list):
                completeness[timeline_key] = (
                    completeness.get(timeline_key, True) and timeline_complete
                )
                continue
            for raw_moment in cast(list[object], raw_moments):
                if not isinstance(raw_moment, dict):
                    continue
                moment = cast(JsonDict, raw_moment)
                frame = self._metadata_int(moment.get("frame"), 0)
                raw_actions = moment.get("actions")
                if not isinstance(raw_actions, list):
                    continue
                for raw_action in cast(list[object], raw_actions):
                    if not isinstance(raw_action, dict):
                        continue
                    action = cast(JsonDict, raw_action)
                    if action.get("kind") != "gml":
                        continue
                    source_path = action.get("source_path")
                    script_path = action.get("script_path")
                    if isinstance(source_path, str) and isinstance(script_path, str):
                        action_complete = self._write_timeline_action_script(
                            entry.name,
                            frame,
                            entry.source_path,
                            source_path,
                            script_path,
                            asset_names,
                        )
                    else:
                        action_complete = False
                    if not action_complete:
                        action.pop("script_path", None)
                        timeline_complete = False
            completeness[timeline_key] = (
                completeness.get(timeline_key, True) and timeline_complete
            )
        return completeness

    def _write_timeline_action_script(
        self,
        timeline_name: str,
        frame: int,
        owner_source_path: str,
        source_path: str,
        script_path: str,
        asset_names: set[str],
    ) -> bool:
        if not script_path.startswith("res://"):
            return False
        resolved_source = self._resolve_project_source(
            source_path,
            owner_source_path=owner_source_path,
            resource=timeline_name,
            resource_type="timeline",
            field="timeline action source_path",
        )
        if resolved_source is None:
            return False
        gm_source_path = resolved_source.filesystem_path
        try:
            with open(gm_source_path, "r", encoding="utf-8") as source_file:
                source = source_file.read()
        except (OSError, ValueError):
            self._safe_log(
                "Warning: Could not read GameMaker timeline moment code for "
                f"{timeline_name} frame {frame}: {gm_source_path}"
            )
            return False

        try:
            body = transpile_gml_code(
                source,
                asset_names=asset_names,
                source_path=gm_source_path,
                event=f"timeline moment {frame}",
                preserve_source_comments=True,
                self_expression="_gm_instance",
                other_expression="GMRuntime.gml_instance_noone()",
                instance_target="_gm_instance",
            )
        except GMLTranspileError as exc:
            message = (
                "Warning: Could not transpile GameMaker timeline moment code for "
                f"{timeline_name} frame {frame}: {gm_source_path}: {exc}"
            )
            if self.diagnostics is not None:
                self.diagnostics.add_transpile_failure(
                    message,
                    source_path=gm_source_path,
                    line=exc.line,
                    column=exc.column,
                    resource=timeline_name,
                    resource_type="timeline",
                    event=f"moment {frame}",
                    workaround="Split or rewrite unsupported GML in this timeline moment.",
                )
            self._safe_log(message)
            return False

        if not body.strip():
            body = "\tpass"
        output_path = os.path.join(self.godot_project_path, *script_path[len("res://"):].split("/"))
        self._atomic_write_text(
            output_path,
            "\n".join([
                "extends RefCounted",
                "",
                'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")',
                "",
                "static func execute(_gm_instance):",
                body.rstrip(),
                "",
            ]),
            confinement_root=self.godot_project_path,
        )
        return True

    @staticmethod
    def _timeline_action_script_resource_path(script_stem: str, frame: int) -> str:
        return f"res://gm2godot/timelines/{script_stem}_{frame}.gd"

    @staticmethod
    def _timeline_frame_from_filename(filename: str) -> int | None:
        stem = os.path.splitext(filename)[0]
        digits = "".join(char for char in stem if char.isdigit())
        if not digits:
            return None
        return int(digits)

    @staticmethod
    def _json_list(raw_data: JsonDict, keys: tuple[str, ...]) -> list[object]:
        for key in keys:
            value = raw_data.get(key)
            if isinstance(value, list):
                return list(cast(list[object], value))
        return []

    def _room_order_indices(self, resources: Iterable[_ProjectResource]) -> dict[str, int]:
        rooms = {resource.name for resource in resources if resource.kind == "rooms"}
        if not rooms:
            return {}

        ordered: list[str] = []
        yyp_data = self.project_manifest.raw_data
        if "RoomOrderNodes" in yyp_data:
            for raw_node in cast(list[object], yyp_data.get("RoomOrderNodes", [])):
                if not isinstance(raw_node, dict):
                    continue
                node = cast(JsonDict, raw_node)
                room_id = node.get("roomId")
                if not isinstance(room_id, dict):
                    continue
                room_ref = cast(JsonDict, room_id)
                name = room_ref.get("name")
                if not isinstance(name, str) or not name:
                    path = room_ref.get("path")
                    name = self._name_from_path(path) if isinstance(path, str) else ""
                if name in rooms and name not in ordered:
                    ordered.append(name)

        for name in sorted(rooms):
            if name not in ordered:
                ordered.append(name)
        return {name: index for index, name in enumerate(ordered)}

    def _font_godot_path(self, resource: _ProjectResource, *, suffix: str = "") -> str:
        subfolder = self._get_subfolder_from_resource(resource)
        ttf_name = resource.raw_data.get("TTFName")
        include_ttf = bool(resource.raw_data.get("includeTTF", False))
        if include_ttf and isinstance(ttf_name, str) and ttf_name:
            source_ttf = self._resolve_project_source(
                ttf_name,
                owner_source_path=resource.source_path,
                resource=resource.name,
                resource_type="font",
                field="TTFName",
            )
            output_filename = bundled_font_output_filename(ttf_name)
            if (
                source_ttf is not None
                and output_filename is not None
                and os.path.isfile(source_ttf.filesystem_path)
            ):
                stem, extension = os.path.splitext(output_filename)
                return self._flat_resource_path(
                    "fonts",
                    subfolder,
                    stem,
                    extension,
                    suffix=suffix,
                )

        system_font_name = resource.raw_data.get("fontName")
        if isinstance(system_font_name, str) and system_font_name:
            system_path = self._system_font_path(system_font_name)
            if system_path is not None:
                extension = os.path.splitext(system_path)[1].lower()
                return self._flat_resource_path(
                    "fonts",
                    subfolder,
                    resource.name,
                    extension,
                    suffix=suffix,
                )
        return self._flat_resource_path("fonts", subfolder, resource.name, ".tres", suffix=suffix)

    def _system_font_path(self, font_name: str) -> str | None:
        cache_key = font_name.casefold()
        if cache_key not in self._system_font_paths:
            self._system_font_paths[cache_key] = resolve_system_font_source(font_name)
        return self._system_font_paths[cache_key]

    def _get_subfolder_from_resource(self, resource: _ProjectResource) -> str:
        if not resource.yy_path:
            return ""
        return self._get_subfolder_from_yy(resource.yy_path)

    @staticmethod
    def _nested_resource_path(
        kind: str,
        subfolder: str,
        name: str,
        extension: str,
        *,
        suffix: str = "",
    ) -> str:
        return generated_nested_resource_path(kind, subfolder, name, extension, suffix=suffix)

    @staticmethod
    def _flat_resource_path(
        kind: str,
        subfolder: str,
        name: str,
        extension: str,
        *,
        suffix: str = "",
    ) -> str:
        return generated_flat_resource_path(kind, subfolder, name, extension, suffix=suffix)

    def _legacy_id(self, resource: _ProjectResource) -> str:
        for key in ("id", "resourceId", "guid"):
            value = resource.raw_data.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, int):
                return str(value)
        return resource.source_path

    @classmethod
    def _stable_asset_id(cls, asset_type: str, name: str, used_ids: set[int]) -> int:
        asset_id = cls._fnv1a32(f"{asset_type}:{name}") & STATIC_ASSET_ID_MASK
        while asset_id in used_ids:
            asset_id = (asset_id + 1) & STATIC_ASSET_ID_MASK
        used_ids.add(asset_id)
        return asset_id

    @staticmethod
    def _fnv1a32(value: str) -> int:
        hash_value = 2166136261
        for char in value:
            hash_value = ((hash_value ^ ord(char)) * 16777619) & 0xFFFFFFFF
        return hash_value

    @staticmethod
    def _normalize_yyp_kind(yyp_path: str) -> str:
        kind = yyp_path.replace("\\", "/").split("/", 1)[0]
        return "included_files" if kind == "datafiles" else kind

    @staticmethod
    def _name_from_path(yyp_path: str) -> str:
        filename = os.path.basename(yyp_path.replace("\\", "/"))
        return os.path.splitext(filename)[0]

    @staticmethod
    def _reference_name(value: object) -> str:
        if not isinstance(value, dict):
            return ""
        reference = cast(JsonDict, value)
        name = reference.get("name")
        if isinstance(name, str):
            return name
        return ""

    @staticmethod
    def _extract_tags(data: JsonDict) -> tuple[str, ...]:
        tags: set[str] = set()
        for key in ("tags", "resourceTags", "tagList"):
            value = data.get(key)
            if isinstance(value, list):
                for item in cast(list[object], value):
                    if isinstance(item, str) and item:
                        tags.add(item)
                    elif isinstance(item, dict):
                        item_data = cast(JsonDict, item)
                        tag_name = item_data.get("name")
                        if isinstance(tag_name, str) and tag_name:
                            tags.add(tag_name)
        return tuple(sorted(tags))

    @staticmethod
    def _metadata_float(value: object, default: float) -> float:
        if not isinstance(value, (str, int, float)):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _metadata_int(value: object, default: int) -> int:
        if not isinstance(value, (str, int, float)):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _metadata_string(value: object, default: str) -> str:
        return value if isinstance(value, str) and value else default


def render_asset_registry_script(
    entries: tuple[AssetRegistryEntry, ...],
    *,
    texture_groups: tuple[JsonDict, ...] = (),
    audio_groups: tuple[JsonDict, ...] = (),
) -> str:
    payload = [entry.to_godot_dict() for entry in entries]
    assets_literal = json.dumps(payload, indent=2, sort_keys=True)
    texture_groups_literal = json.dumps(list(texture_groups), indent=2, sort_keys=True)
    audio_groups_literal = json.dumps(list(audio_groups), indent=2, sort_keys=True)
    return (
        "extends RefCounted\n\n"
        "const FORMAT_VERSION = 1\n"
        f"const ASSETS = {assets_literal}\n\n"
        f"const TEXTURE_GROUPS = {texture_groups_literal}\n\n"
        f"const AUDIO_GROUPS = {audio_groups_literal}\n\n"
        "static func gml_asset_registry_entries():\n"
        "\treturn ASSETS\n\n"
        "static func gml_texture_group_registry_entries():\n"
        "\treturn TEXTURE_GROUPS\n\n"
        "static func gml_audio_group_registry_entries():\n"
        "\treturn AUDIO_GROUPS\n"
    )


__all__ = [
    "ASSET_REGISTRY_RELATIVE_PATH",
    "ASSET_REGISTRY_RESOURCE_PATH",
    "GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH",
    "AssetRegistryConverter",
    "AssetRegistryEntry",
    "render_asset_registry_script",
]
