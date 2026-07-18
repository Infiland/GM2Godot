from __future__ import annotations

import json
import os
import re
import secrets
import stat
import tempfile
from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol, cast

from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.gml_transpiler_parts.extension_functions import (
    EXTENSION_FUNCTION_MAPPING_FILENAME,
    load_gml_extension_function_mappings,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    resolve_project_filesystem_source_path,
    resolve_project_source_path,
    validate_project_resource_source_path,
)
from src.conversion.type_defs import JsonDict, LogCallback

EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH = os.path.join(
    "gm2godot", "extension_compatibility_report.json"
)
EXTENSION_STUBS_RELATIVE_DIR = os.path.join("addons", "gm2godot_extensions")


@dataclass(frozen=True)
class _OutputFileState:
    identity: tuple[int, int] | None
    mode: int | None


@dataclass(frozen=True)
class ExtensionFunctionEntry:
    name: str
    external_name: str
    arg_count: int | None
    return_type: str
    help_text: str
    raw_data: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "external_name": self.external_name,
            "arg_count": self.arg_count,
            "return_type": self.return_type,
            "help": self.help_text,
            "raw": self.raw_data,
        }


@dataclass(frozen=True)
class ExtensionFileEntry:
    filename: str
    platform: str
    functions: tuple[ExtensionFunctionEntry, ...]
    constants: tuple[JsonDict, ...]
    macros: tuple[JsonDict, ...]
    options: tuple[JsonDict, ...]
    raw_data: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "filename": self.filename,
            "platform": self.platform,
            "functions": [function.to_dict() for function in self.functions],
            "constants": list(self.constants),
            "macros": list(self.macros),
            "options": list(self.options),
            "raw": self.raw_data,
        }


@dataclass(frozen=True)
class ExtensionEntry:
    name: str
    source_path: str
    files: tuple[ExtensionFileEntry, ...]
    options: tuple[JsonDict, ...]
    constants: tuple[JsonDict, ...]
    macros: tuple[JsonDict, ...]
    platforms: tuple[str, ...]
    version: str
    raw_data: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "source_path": self.source_path,
            "version": self.version,
            "platforms": list(self.platforms),
            "files": [file.to_dict() for file in self.files],
            "options": list(self.options),
            "constants": list(self.constants),
            "macros": list(self.macros),
            "raw": self.raw_data,
        }


@dataclass(frozen=True)
class _SourceContext:
    diagnostics: DiagnosticCollector | None
    log_callback: LogCallback | None
    owner_source_path: str
    resource: str
    field: str


class _ExtensionAssetEntry(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def source_path(self) -> str: ...

    @property
    def godot_path(self) -> str: ...


def build_extension_entries(
    gm_project_path: str,
    *,
    diagnostics: DiagnosticCollector | None = None,
    log_callback: LogCallback | None = None,
) -> tuple[ExtensionEntry, ...]:
    extensions_context = _SourceContext(
        diagnostics, log_callback, "extensions", "extensions", "extensions directory"
    )
    extensions_dir = _resolve_source(gm_project_path, "extensions", extensions_context)
    if extensions_dir is None:
        return ()

    extension_names = _list_confined_directory(
        gm_project_path, extensions_dir, extensions_context
    )
    if extension_names is None:
        return ()

    entries: list[ExtensionEntry] = []
    for name in extension_names:
        extension_context = _SourceContext(
            diagnostics,
            log_callback,
            f"extensions/{name}",
            name,
            "extension directory",
        )
        extension_dir = _resolve_source(
            gm_project_path,
            os.path.join(extensions_dir.filesystem_path, name),
            extension_context,
            discovered=True,
        )
        if extension_dir is None or not os.path.isdir(extension_dir.filesystem_path):
            continue

        yy_source_path = f"{extension_dir.source_path}/{name}.yy"
        metadata_context = _SourceContext(
            diagnostics, log_callback, yy_source_path, name, "extension metadata"
        )
        yy_path = _resolve_source(
            gm_project_path,
            os.path.join(extension_dir.filesystem_path, name + ".yy"),
            metadata_context,
            discovered=True,
        )
        if yy_path is None:
            continue
        try:
            validate_project_resource_source_path(yy_path, "extensions")
        except ProjectSourcePathError as error:
            _report_source_path_rejection(
                yy_source_path,
                error,
                metadata_context,
            )
            continue
        data = _read_json_lenient(gm_project_path, yy_path, metadata_context)
        if data is None:
            continue
        entries.append(
            extension_entry_from_yy(
                gm_project_path,
                yy_path.filesystem_path,
                data,
            )
        )
    return tuple(entries)


def write_extension_compatibility_outputs(
    gm_project_path: str,
    godot_project_path: str,
    *,
    diagnostics: DiagnosticCollector | None = None,
    log_callback: LogCallback | None = None,
    asset_entries: Iterable[_ExtensionAssetEntry] | None = None,
) -> str:
    entries = build_extension_entries(
        gm_project_path,
        diagnostics=diagnostics,
        log_callback=log_callback,
    )
    selected_stub_paths: dict[str, str] | None = None
    if asset_entries is not None:
        selected_by_source: dict[str, _ExtensionAssetEntry] = {}
        selected_candidates = sorted(
            (
                asset_entry
                for asset_entry in asset_entries
                if asset_entry.kind == "extensions"
            ),
            key=lambda asset_entry: (
                _extension_source_key(asset_entry.source_path),
                asset_entry.name.casefold(),
                asset_entry.name,
                asset_entry.source_path,
                asset_entry.godot_path.casefold(),
                asset_entry.godot_path,
            ),
        )
        for asset_entry in selected_candidates:
            selected_by_source.setdefault(
                _extension_source_key(asset_entry.source_path),
                asset_entry,
            )
        selected_entries: list[ExtensionEntry] = []
        selected_stub_paths = {}
        for entry in entries:
            asset_entry = selected_by_source.get(
                _extension_source_key(entry.source_path)
            )
            if asset_entry is None:
                same_file_candidates = [
                    candidate
                    for candidate in selected_candidates
                    if _extension_sources_are_same_file(
                        gm_project_path,
                        entry.source_path,
                        candidate.source_path,
                    )
                ]
                if len(same_file_candidates) == 1:
                    asset_entry = same_file_candidates[0]
            if asset_entry is None:
                continue
            selected_entries.append(entry)
            selected_stub_paths[entry.source_path] = asset_entry.godot_path
        entries = tuple(selected_entries)
    default_stub_paths = collision_safe_extension_stub_resource_paths(
        (entry.name, entry.source_path)
        for entry in entries
    )
    output_stub_paths = {
        entry.source_path: (
            selected_stub_paths.get(entry.source_path, "")
            if selected_stub_paths is not None
            else ""
        )
        or default_stub_paths[(entry.name, entry.source_path)]
        for entry in entries
    }
    mappings = _load_extension_mapping_names(
        gm_project_path,
        diagnostics=diagnostics,
        log_callback=log_callback,
    )
    report_path = os.path.join(godot_project_path, EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH)
    report_content = json.dumps(
        render_extension_compatibility_report(
            entries,
            mappings,
            stub_paths_by_source=output_stub_paths,
        ),
        indent=2,
        sort_keys=True,
    ) + "\n"
    report_directory = os.path.dirname(report_path) or os.curdir
    report_directory_identity = _ensure_extension_report_directory(
        report_directory
    )
    previous_report_mode = _invalidate_extension_report(
        report_path,
        report_directory,
        report_directory_identity,
    )
    try:
        for entry in entries:
            _write_extension_stub(
                godot_project_path,
                entry,
                stub_resource_path=output_stub_paths[entry.source_path],
            )
        _atomic_write_extension_report(
            report_path,
            report_content,
            report_directory=report_directory,
            report_directory_identity=report_directory_identity,
            output_mode=previous_report_mode,
        )
    except BaseException as publish_error:
        try:
            _invalidate_extension_report(
                report_path,
                report_directory,
                report_directory_identity,
            )
        except OSError as invalidation_error:
            publish_error.add_note(
                "Extension compatibility report invalidation failed: "
                f"{invalidation_error}"
            )
        raise
    return report_path


def _ensure_extension_report_directory(
    report_directory: str,
) -> tuple[int, int]:
    os.makedirs(report_directory, exist_ok=True)
    report_directory_stat = os.lstat(report_directory)
    if (
        _is_redirecting_extension_path(
            report_directory,
            report_directory_stat,
        )
        or not stat.S_ISDIR(report_directory_stat.st_mode)
    ):
        raise OSError(
            "Refusing redirected extension-report output directory: "
            f"{report_directory}"
        )
    return (
        report_directory_stat.st_dev,
        report_directory_stat.st_ino,
    )


def _invalidate_extension_report(
    report_path: str,
    report_directory: str,
    report_directory_identity: tuple[int, int],
) -> int | None:
    """Remove the report entry itself without following its referent."""
    _verify_extension_report_directory(
        report_directory,
        report_directory_identity,
    )
    try:
        report_stat = os.lstat(report_path)
    except FileNotFoundError:
        return None
    if not (
        stat.S_ISREG(report_stat.st_mode)
        or stat.S_ISLNK(report_stat.st_mode)
    ):
        raise OSError(
            "Refusing non-regular extension compatibility report: "
            f"{report_path}"
        )
    output_mode = (
        stat.S_IMODE(report_stat.st_mode)
        if stat.S_ISREG(report_stat.st_mode)
        else None
    )
    os.unlink(report_path)
    return output_mode


def _atomic_write_extension_report(
    report_path: str,
    content: str,
    *,
    report_directory: str,
    report_directory_identity: tuple[int, int],
    output_mode: int | None,
) -> None:
    """Publish the compatibility report without following its final entry."""
    _verify_extension_report_directory(
        report_directory,
        report_directory_identity,
    )
    target_state = _OutputFileState(identity=None, mode=None)
    _verify_output_file_state(
        report_path,
        target_state,
        description="extension compatibility report",
    )
    file_descriptor, staged_path = tempfile.mkstemp(
        dir=report_directory,
        prefix=f".{os.path.basename(report_path)}.",
        suffix=".tmp",
    )
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
        _verify_extension_report_directory(
            report_directory,
            report_directory_identity,
        )
        _verify_output_file_state(
            report_path,
            target_state,
            description="extension compatibility report",
        )
        os.replace(staged_path, report_path)
        staged_pending = False
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if staged_pending:
            try:
                _verify_extension_report_directory(
                    report_directory,
                    report_directory_identity,
                )
                os.unlink(staged_path)
            except OSError:
                pass


def _verify_extension_report_directory(
    path: str,
    expected_identity: tuple[int, int],
) -> None:
    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise OSError(
            f"Extension-report output directory changed: {path}"
        ) from error
    if (
        _is_redirecting_extension_path(path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Extension-report output directory changed: {path}")


def _output_file_state(path: str, *, description: str) -> _OutputFileState:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return _OutputFileState(identity=None, mode=None)
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(f"Refusing non-regular {description}: {path}")
    return _OutputFileState(
        identity=(path_stat.st_dev, path_stat.st_ino),
        mode=stat.S_IMODE(path_stat.st_mode),
    )


def _verify_output_file_state(
    path: str,
    expected: _OutputFileState,
    *,
    description: str,
) -> None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        if expected.identity is None:
            return
        raise OSError(f"{description.capitalize()} changed during publication: {path}")
    if (
        expected.identity is None
        or not stat.S_ISREG(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected.identity
    ):
        raise OSError(f"{description.capitalize()} changed during publication: {path}")


def render_extension_compatibility_report(
    entries: Iterable[ExtensionEntry],
    mapped_functions: Iterable[str] = (),
    *,
    stub_paths_by_source: Mapping[str, str] | None = None,
) -> JsonDict:
    extension_entries = tuple(entries)
    default_stub_paths = collision_safe_extension_stub_resource_paths(
        (entry.name, entry.source_path)
        for entry in extension_entries
    )

    def stub_path(entry: ExtensionEntry) -> str:
        if stub_paths_by_source is not None:
            selected_path = stub_paths_by_source.get(entry.source_path)
            if selected_path:
                return selected_path
        return default_stub_paths[(entry.name, entry.source_path)]

    mapped = set(mapped_functions)
    diagnostics: list[JsonDict] = []
    function_bindings: list[JsonDict] = []
    stubs: list[JsonDict] = []
    for entry in extension_entries:
        entry_stub_path = stub_path(entry)
        stubs.append({
            "extension": entry.name,
            "path": entry_stub_path,
        })
        for file_entry in entry.files:
            if _is_native_extension_file(file_entry.filename):
                diagnostics.append({
                    "code": "extension_native_binding_required",
                    "severity": "warning",
                    "extension": entry.name,
                    "file": file_entry.filename,
                    "source_path": entry.source_path,
                    "message": (
                        "Native GameMaker extension file requires an explicit Godot "
                        "plugin or GDExtension implementation before calls can run."
                    ),
                })
            for function in file_entry.functions:
                function_bindings.append({
                    "extension": entry.name,
                    "function": function.name,
                    "external_name": function.external_name,
                    "arg_count": function.arg_count,
                    "return_type": function.return_type,
                    "file": file_entry.filename,
                    "platform": file_entry.platform,
                    "mapped": function.name in mapped,
                    "stub_path": entry_stub_path,
                })
                if function.name not in mapped:
                    diagnostics.append({
                        "code": "extension_function_mapping_required",
                        "severity": "warning",
                        "extension": entry.name,
                        "function": function.name,
                        "external_name": function.external_name,
                        "file": file_entry.filename,
                        "source_path": entry.source_path,
                        "message": (
                            "Extension function has no gm2godot_extension_functions.json "
                            "mapping or generated Godot plugin implementation."
                        ),
                    })
    return {
        "format_version": 1,
        "extensions": [entry.to_dict() for entry in extension_entries],
        "function_bindings": function_bindings,
        "mapped_functions": sorted(mapped),
        "stubs": stubs,
        "diagnostics": diagnostics,
    }


def extension_entry_from_yy(
    gm_project_path: str,
    yy_path: str,
    data: JsonDict,
) -> ExtensionEntry:
    extension_name = str(data.get("name") or data.get("%Name") or os.path.splitext(os.path.basename(yy_path))[0])
    files: list[ExtensionFileEntry] = []
    raw_files = data.get("files")
    if isinstance(raw_files, list):
        for raw_file in cast(list[object], raw_files):
            if isinstance(raw_file, dict):
                files.append(_extension_file_from_yy(cast(JsonDict, raw_file)))
    source_path = os.path.relpath(yy_path, gm_project_path).replace(os.sep, "/")
    return ExtensionEntry(
        name=extension_name,
        source_path=source_path,
        files=tuple(files),
        options=tuple(_json_dict_list(data.get("options"))),
        constants=tuple(_json_dict_list(data.get("constants"))),
        macros=tuple(_json_dict_list(data.get("macros"))),
        platforms=_extension_platforms(data, files),
        version=str(data.get("version") or data.get("packageVersion") or ""),
        raw_data=data,
    )


def extension_entry_metadata(
    entry: ExtensionEntry,
    *,
    stub_path: str | None = None,
) -> JsonDict:
    return {
        "name": entry.name,
        "source_path": entry.source_path,
        "version": entry.version,
        "platforms": list(entry.platforms),
        "stub_path": stub_path or extension_stub_resource_path(entry.name),
        "options": list(entry.options),
        "constants": list(entry.constants),
        "macros": list(entry.macros),
        "files": [_extension_file_metadata(file_entry) for file_entry in entry.files],
    }


def extension_stub_relative_dir(
    extension_name: str,
    *,
    suffix: str = "",
) -> str:
    return os.path.join(
        EXTENSION_STUBS_RELATIVE_DIR,
        _safe_identifier(extension_name) + suffix,
    )


def extension_stub_relative_script_path(
    extension_name: str,
    *,
    suffix: str = "",
) -> str:
    safe_name = _safe_identifier(extension_name) + suffix
    return os.path.join(
        extension_stub_relative_dir(extension_name, suffix=suffix),
        f"{safe_name}_extension.gd",
    )


def extension_stub_resource_path(
    extension_name: str,
    *,
    suffix: str = "",
) -> str:
    return "res://" + extension_stub_relative_script_path(
        extension_name,
        suffix=suffix,
    ).replace(os.sep, "/")


def collision_safe_extension_stub_resource_paths(
    identities: Iterable[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    """Return stable, case-insensitively unique extension stub paths."""
    ordered_identities = sorted(
        set(identities),
        key=lambda identity: (
            _safe_identifier(identity[0]).casefold(),
            identity[0].casefold(),
            identity[0],
            identity[1].casefold(),
            identity[1],
        ),
    )
    paths: dict[tuple[str, str], str] = {}
    used_paths: set[str] = set()
    for identity in ordered_identities:
        extension_name, _source_path = identity
        suffix_index = 0
        while True:
            suffix = "" if suffix_index == 0 else f"_{suffix_index + 1}"
            path = extension_stub_resource_path(
                extension_name,
                suffix=suffix,
            )
            if path.casefold() not in used_paths:
                break
            suffix_index += 1
        used_paths.add(path.casefold())
        paths[identity] = path
    return paths


def _extension_file_from_yy(data: JsonDict) -> ExtensionFileEntry:
    functions: list[ExtensionFunctionEntry] = []
    raw_functions = data.get("functions")
    if isinstance(raw_functions, list):
        for raw_function in cast(list[object], raw_functions):
            if isinstance(raw_function, dict):
                function = _extension_function_from_yy(cast(JsonDict, raw_function))
                if function is not None:
                    functions.append(function)
    filename = str(data.get("filename") or data.get("name") or "")
    return ExtensionFileEntry(
        filename=filename,
        platform=_extension_platform(data, filename),
        functions=tuple(functions),
        constants=tuple(_json_dict_list(data.get("constants"))),
        macros=tuple(_json_dict_list(data.get("macros"))),
        options=tuple(_json_dict_list(data.get("options"))),
        raw_data=data,
    )


def _extension_function_from_yy(data: JsonDict) -> ExtensionFunctionEntry | None:
    name = data.get("name") or data.get("functionName")
    external_name = data.get("externalName") or data.get("external_name")
    if not name and external_name:
        name = external_name
    if not name:
        return None
    return ExtensionFunctionEntry(
        name=str(name),
        external_name=str(external_name or ""),
        arg_count=_extension_arg_count(data),
        return_type=str(data.get("returnType") or data.get("return_type") or ""),
        help_text=str(data.get("help") or data.get("helpText") or ""),
        raw_data=data,
    )


def _write_extension_stub(
    godot_project_path: str,
    entry: ExtensionEntry,
    *,
    stub_resource_path: str | None = None,
) -> None:
    resolved_stub_path = stub_resource_path or extension_stub_resource_path(
        entry.name
    )
    if not resolved_stub_path.startswith("res://"):
        raise ValueError(
            "Generated extension stub path must use the res:// scheme: "
            f"{resolved_stub_path!r}"
        )
    relative_script_path = resolved_stub_path.removeprefix("res://").replace(
        "/",
        os.sep,
    )
    relative_dir = os.path.dirname(relative_script_path)
    script_filename = os.path.basename(relative_script_path)
    _atomic_write_extension_text(
        godot_project_path,
        os.path.join(relative_dir, "plugin.cfg"),
        "\n".join([
            "[plugin]",
            f'name="GM2Godot Extension Stub - {entry.name}"',
            'description="Generated binding stub for GameMaker extension metadata."',
            'author="GM2Godot"',
            'version="1.0"',
            f'script="{script_filename}"',
            "",
        ]),
    )
    _atomic_write_extension_text(
        godot_project_path,
        relative_script_path,
        render_extension_stub_script(entry),
    )


def _atomic_write_extension_text(
    godot_project_path: str,
    relative_path: str,
    content: str,
) -> None:
    """Atomically publish one stub without following replaceable output symlinks."""
    components = _extension_output_components(relative_path)
    if _confined_directory_fds_supported():
        _atomic_write_extension_text_at(
            os.path.abspath(godot_project_path),
            components,
            content,
        )
        return
    _atomic_write_extension_text_fallback(
        os.path.abspath(godot_project_path),
        components,
        content,
    )


def _extension_output_components(relative_path: str) -> tuple[str, ...]:
    normalized = relative_path.replace("\\", "/")
    components = tuple(normalized.split("/"))
    managed_root = ("addons", "gm2godot_extensions")
    if (
        os.path.isabs(relative_path)
        or any(component in {"", ".", ".."} for component in components)
        or components[: len(managed_root)] != managed_root
        or len(components) <= len(managed_root)
    ):
        raise ValueError(f"Unsafe generated extension output path: {relative_path!r}")
    return components


def _confined_directory_fds_supported() -> bool:
    return all(
        operation in os.supports_dir_fd
        for operation in (os.open, os.mkdir, os.stat, os.rename, os.unlink)
    )


def _atomic_write_extension_text_at(
    project_path: str,
    components: tuple[str, ...],
    content: str,
) -> None:
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    project_fd = os.open(project_path, directory_flags)
    current_fd = project_fd
    try:
        _verify_open_extension_directory(project_path, project_path, project_fd)
        for component in components[:-1]:
            child_fd = _open_or_create_extension_directory(
                current_fd,
                component,
                directory_flags,
            )
            if current_fd != project_fd:
                os.close(current_fd)
            current_fd = child_fd

        output_directory = os.path.join(project_path, *components[:-1])
        _verify_open_extension_directory(project_path, output_directory, current_fd)
        _atomic_write_text_at(current_fd, components[-1], content)
        _verify_open_extension_directory(project_path, output_directory, current_fd)
    finally:
        if current_fd != project_fd:
            os.close(current_fd)
        os.close(project_fd)


def _open_or_create_extension_directory(
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
            f"Refusing redirected generated extension output directory: {component}"
        ) from error


def _verify_open_extension_directory(
    project_path: str,
    directory_path: str,
    directory_fd: int,
) -> None:
    try:
        path_stat = os.lstat(directory_path)
        open_stat = os.fstat(directory_fd)
    except OSError as error:
        raise OSError(
            f"Generated extension output directory changed: {directory_path}"
        ) from error
    project_real = os.path.realpath(project_path)
    directory_real = os.path.realpath(directory_path)
    try:
        contained = os.path.commonpath((directory_real, project_real)) == project_real
    except ValueError:
        contained = False
    if (
        stat.S_ISLNK(path_stat.st_mode)
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino)
        != (open_stat.st_dev, open_stat.st_ino)
        or not contained
    ):
        raise OSError(
            f"Refusing redirected generated extension output directory: {directory_path}"
        )


def _atomic_write_text_at(directory_fd: int, filename: str, content: str) -> None:
    output_mode = 0o644
    existing_mode: int | None = None
    try:
        output_stat = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(output_stat.st_mode):
            raise OSError(f"Refusing non-regular generated extension output: {filename}")
        output_mode = stat.S_IMODE(output_stat.st_mode)
        existing_mode = output_mode

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
                output_mode,
                dir_fd=directory_fd,
            )
            break
        except FileExistsError:
            continue
    if file_descriptor < 0:
        raise OSError(f"Could not stage generated extension output: {filename}")

    temporary_pending = True
    try:
        if existing_mode is not None and os.name != "nt":
            os.fchmod(file_descriptor, existing_mode)
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
        os.rename(
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


def _atomic_write_extension_text_fallback(
    project_path: str,
    components: tuple[str, ...],
    content: str,
) -> None:
    """Best-effort no-follow fallback for platforms without directory handles."""
    project_real = _normalized_real_path(project_path)
    directory_path = project_path
    for component in components[:-1]:
        directory_path = os.path.join(directory_path, component)
        try:
            path_stat = os.lstat(directory_path)
        except FileNotFoundError:
            os.mkdir(directory_path)
            path_stat = os.lstat(directory_path)
        if (
            _is_redirecting_extension_path(directory_path, path_stat)
            or not stat.S_ISDIR(path_stat.st_mode)
        ):
            raise OSError(
                f"Refusing redirected generated extension output directory: {directory_path}"
            )
        directory_real = _normalized_real_path(directory_path)
        try:
            contained = (
                os.path.commonpath((directory_real, project_real))
                == project_real
            )
        except ValueError:
            contained = False
        if not contained:
            raise OSError(
                f"Refusing redirected generated extension output directory: {directory_path}"
            )

    directory_stat = os.lstat(directory_path)
    directory_identity = (directory_stat.st_dev, directory_stat.st_ino)
    output_path = os.path.join(directory_path, components[-1])
    output_state = _output_file_state(
        output_path,
        description="generated extension output",
    )
    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=directory_path,
        prefix=f".{components[-1]}.",
        suffix=".tmp",
    )
    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    temporary_pending = True
    try:
        if output_state.mode is not None:
            os.chmod(temporary_path, output_state.mode)
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
        _verify_fallback_extension_directory(
            project_real,
            directory_path,
            directory_identity,
        )
        _verify_output_file_state(
            output_path,
            output_state,
            description="generated extension output",
        )
        os.replace(temporary_path, output_path)
        temporary_pending = False
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                _verify_fallback_extension_directory(
                    project_real,
                    directory_path,
                    directory_identity,
                )
                current_temporary_stat = os.lstat(temporary_path)
                if (
                    current_temporary_stat.st_dev,
                    current_temporary_stat.st_ino,
                ) != temporary_identity:
                    raise OSError(
                        "Generated extension staging file changed: "
                        f"{temporary_path}"
                    )
                os.unlink(temporary_path)
            except OSError:
                pass


def _normalized_real_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.realpath(path)))


def _is_redirecting_extension_path(
    path: str,
    path_stat: os.stat_result,
) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return stat.S_ISLNK(path_stat.st_mode) or (
        is_junction is not None and is_junction(path)
    )


def _verify_fallback_extension_directory(
    project_real: str,
    directory_path: str,
    expected_identity: tuple[int, int],
) -> None:
    try:
        directory_stat = os.lstat(directory_path)
    except OSError as error:
        raise OSError(
            f"Generated extension output directory changed: {directory_path}"
        ) from error
    directory_real = _normalized_real_path(directory_path)
    try:
        contained = os.path.commonpath((directory_real, project_real)) == project_real
    except ValueError:
        contained = False
    if (
        _is_redirecting_extension_path(directory_path, directory_stat)
        or not stat.S_ISDIR(directory_stat.st_mode)
        or (directory_stat.st_dev, directory_stat.st_ino) != expected_identity
        or not contained
    ):
        raise OSError(
            f"Generated extension output directory changed: {directory_path}"
        )


def render_extension_stub_script(entry: ExtensionEntry) -> str:
    lines = [
        "@tool",
        "extends EditorPlugin",
        "",
        "# Generated by GM2Godot. Replace these stubs with reviewed Godot addon",
        "# or GDExtension calls before enabling native extension behavior.",
        f"# GameMaker extension: {entry.name}",
        f"# Source: {entry.source_path}",
        "",
        "func _enter_tree():",
        "\tpass",
        "",
    ]
    emitted_methods: set[str] = set()
    for file_entry in entry.files:
        lines.append(f"# Native file: {file_entry.filename or '<metadata-only>'} ({file_entry.platform})")
        for function in file_entry.functions:
            method_name = _safe_gdscript_identifier(function.name)
            if method_name in emitted_methods:
                lines.append(f"# Duplicate platform binding for {function.name} is covered by func {method_name}.")
                continue
            emitted_methods.add(method_name)
            args = ", ".join(f"arg{index}" for index in range(function.arg_count or 0))
            lines.extend([
                f"func {method_name}({args}):",
                (
                    "\tpush_error(\"GM2Godot extension stub {name}.{function} "
                    "needs a project-specific implementation\")"
                ).format(name=entry.name, function=function.name),
                "\treturn null",
                "",
            ])
    return "\n".join(lines)


def _extension_file_metadata(file_entry: ExtensionFileEntry) -> JsonDict:
    return {
        "filename": file_entry.filename,
        "platform": file_entry.platform,
        "native": _is_native_extension_file(file_entry.filename),
        "functions": [_extension_function_metadata(function) for function in file_entry.functions],
        "constants": list(file_entry.constants),
        "macros": list(file_entry.macros),
        "options": list(file_entry.options),
    }


def _extension_function_metadata(function: ExtensionFunctionEntry) -> JsonDict:
    return {
        "name": function.name,
        "external_name": function.external_name,
        "arg_count": function.arg_count,
        "return_type": function.return_type,
        "help": function.help_text,
    }


def _load_extension_mapping_names(
    gm_project_path: str,
    *,
    diagnostics: DiagnosticCollector | None,
    log_callback: LogCallback | None,
) -> set[str]:
    context = _SourceContext(
        diagnostics,
        log_callback,
        EXTENSION_FUNCTION_MAPPING_FILENAME,
        EXTENSION_FUNCTION_MAPPING_FILENAME,
        "extension function mapping",
    )
    mapping_path = _resolve_source(
        gm_project_path, EXTENSION_FUNCTION_MAPPING_FILENAME, context
    )
    if mapping_path is None:
        return set()
    refreshed = _resolve_source(
        gm_project_path,
        mapping_path.filesystem_path,
        context,
        discovered=True,
    )
    if refreshed is None or not os.path.isfile(refreshed.filesystem_path):
        return set()
    try:
        return set(load_gml_extension_function_mappings(refreshed.filesystem_path))
    except (OSError, ValueError, TypeError):
        return set()


def _extension_arg_count(data: JsonDict) -> int | None:
    raw_arg_count = data.get("argCount")
    if raw_arg_count is None:
        raw_arg_count = data.get("argc")
    if raw_arg_count is not None and not isinstance(raw_arg_count, bool):
        try:
            return int(raw_arg_count)
        except (TypeError, ValueError):
            return None
    args = data.get("args")
    if isinstance(args, list):
        return len(cast(list[object], args))
    return None


def _extension_platform(data: JsonDict, filename: str) -> str:
    for key in ("platform", "target", "copyToTargets"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    lower = filename.lower()
    if lower.endswith(".dll"):
        return "windows"
    if lower.endswith(".dylib") or lower.endswith(".framework"):
        return "macos"
    if lower.endswith(".so"):
        return "linux/android"
    if lower.endswith(".aar") or lower.endswith(".jar"):
        return "android"
    return ""


def _extension_platforms(data: JsonDict, files: list[ExtensionFileEntry]) -> tuple[str, ...]:
    platforms: set[str] = set()
    for key in ("platforms", "targets", "supportedTargets", "copyToTargets"):
        _collect_platform_names(platforms, data.get(key))
    for file_entry in files:
        if file_entry.platform:
            platforms.add(file_entry.platform)
    return tuple(sorted(platforms))


def _collect_platform_names(platforms: set[str], value: object) -> None:
    if isinstance(value, str) and value:
        platforms.add(value)
        return
    if isinstance(value, list):
        for item in cast(list[object], value):
            if isinstance(item, str) and item:
                platforms.add(item)
            elif isinstance(item, dict):
                name = cast(JsonDict, item).get("name")
                if isinstance(name, str) and name:
                    platforms.add(name)
        return
    if isinstance(value, dict):
        for key, enabled in cast(JsonDict, value).items():
            if key and enabled:
                platforms.add(key)


def _is_native_extension_file(filename: str) -> bool:
    return filename.lower().endswith((".dll", ".so", ".dylib", ".framework", ".aar", ".jar", ".a"))


def _extension_source_key(source_path: str) -> str:
    normalized = os.path.normpath(
        source_path.replace("\\", os.sep).replace("/", os.sep)
    )
    return os.path.normcase(normalized).replace("\\", "/")


def _extension_sources_are_same_file(
    gm_project_path: str,
    left_source_path: str,
    right_source_path: str,
) -> bool:
    def filesystem_path(source_path: str) -> str:
        normalized = source_path.replace("\\", "/")
        return os.path.join(gm_project_path, *normalized.split("/"))

    try:
        return os.path.samefile(
            filesystem_path(left_source_path),
            filesystem_path(right_source_path),
        )
    except OSError:
        return False


def _safe_identifier(value: str) -> str:
    identifier = re.sub(r"[^0-9A-Za-z_]", "_", value).strip("_").lower()
    if not identifier:
        return "extension"
    if identifier[0].isdigit():
        return "_" + identifier
    return identifier


def _safe_gdscript_identifier(value: str) -> str:
    identifier = re.sub(r"[^0-9A-Za-z_]", "_", value).strip("_")
    if not identifier:
        return "extension_function"
    if identifier[0].isdigit():
        return "_" + identifier
    return identifier


def _json_dict_list(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    items: list[JsonDict] = []
    for item in cast(list[object], value):
        if isinstance(item, dict):
            items.append(cast(JsonDict, item))
    return items


def _resolve_source(
    gm_project_path: str,
    source_path: str,
    context: _SourceContext,
    *,
    discovered: bool = False,
) -> ResolvedProjectSourcePath | None:
    try:
        return (
            resolve_project_filesystem_source_path(gm_project_path, source_path)
            if discovered
            else resolve_project_source_path(gm_project_path, source_path)
        )
    except ProjectSourcePathError as error:
        _report_source_path_rejection(source_path, error, context)
        return None


def _list_confined_directory(
    gm_project_path: str,
    directory: ResolvedProjectSourcePath,
    context: _SourceContext,
) -> tuple[str, ...] | None:
    refreshed = _resolve_source(
        gm_project_path,
        directory.filesystem_path,
        context,
        discovered=True,
    )
    if refreshed is None:
        return None
    try:
        if not os.path.isdir(refreshed.filesystem_path):
            return None
        return tuple(sorted(os.listdir(refreshed.filesystem_path)))
    except OSError:
        return None


def _read_json_lenient(
    gm_project_path: str,
    source: ResolvedProjectSourcePath,
    context: _SourceContext,
) -> JsonDict | None:
    refreshed = _resolve_source(
        gm_project_path,
        source.filesystem_path,
        context,
        discovered=True,
    )
    if refreshed is None:
        return None
    try:
        with open(refreshed.filesystem_path, "r", encoding="utf-8") as source_file:
            content = source_file.read()
        data = json.loads(re.sub(r",\s*([}\]])", r"\1", content))
    except OSError:
        return None
    except json.JSONDecodeError:
        return None
    return cast(JsonDict, data) if isinstance(data, dict) else None


def _report_source_path_rejection(
    rejected_path: str,
    error: ProjectSourcePathError,
    context: _SourceContext,
) -> None:
    message = (
        "Warning: Rejected GameMaker source path "
        f"{rejected_path!r} from {context.owner_source_path} "
        f"field {context.field}: {error}"
    )
    if context.diagnostics is not None:
        context.diagnostics.add(
            "warning",
            "GM2GD-SOURCE-PATH-REJECTED",
            message,
            source_path=context.owner_source_path,
            resource=context.resource,
            resource_type="extension",
            manifest_entry=context.field,
            workaround=(
                "Keep GameMaker extension metadata and mapping files inside "
                "the selected project root."
            ),
        )
    if context.log_callback is not None:
        context.log_callback(message)
