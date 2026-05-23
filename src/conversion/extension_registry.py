from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable, cast

from src.conversion.gml_transpiler_parts.extension_functions import (
    EXTENSION_FUNCTION_MAPPING_FILENAME,
    load_gml_extension_function_mappings,
)
from src.conversion.type_defs import JsonDict

EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH = os.path.join(
    "gm2godot", "extension_compatibility_report.json"
)
EXTENSION_STUBS_RELATIVE_DIR = os.path.join("addons", "gm2godot_extensions")


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


def build_extension_entries(gm_project_path: str) -> tuple[ExtensionEntry, ...]:
    extensions_dir = os.path.join(gm_project_path, "extensions")
    if not os.path.isdir(extensions_dir):
        return ()

    entries: list[ExtensionEntry] = []
    for name in sorted(os.listdir(extensions_dir)):
        yy_path = os.path.join(extensions_dir, name, name + ".yy")
        if not os.path.isfile(yy_path):
            continue
        data = _read_json_lenient(yy_path)
        if data is None:
            continue
        entries.append(extension_entry_from_yy(gm_project_path, yy_path, data))
    return tuple(entries)


def write_extension_compatibility_outputs(
    gm_project_path: str,
    godot_project_path: str,
) -> str:
    entries = build_extension_entries(gm_project_path)
    mappings = _load_extension_mapping_names(gm_project_path)
    report_path = os.path.join(godot_project_path, EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as report_file:
        json.dump(
            render_extension_compatibility_report(entries, mappings),
            report_file,
            indent=2,
            sort_keys=True,
        )
        report_file.write("\n")
    for entry in entries:
        _write_extension_stub(godot_project_path, entry)
    return report_path


def render_extension_compatibility_report(
    entries: Iterable[ExtensionEntry],
    mapped_functions: Iterable[str] = (),
) -> JsonDict:
    extension_entries = tuple(entries)
    mapped = set(mapped_functions)
    diagnostics: list[JsonDict] = []
    function_bindings: list[JsonDict] = []
    stubs: list[JsonDict] = []
    for entry in extension_entries:
        stubs.append({
            "extension": entry.name,
            "path": extension_stub_resource_path(entry.name),
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
                    "stub_path": extension_stub_resource_path(entry.name),
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


def extension_entry_metadata(entry: ExtensionEntry) -> JsonDict:
    return {
        "name": entry.name,
        "source_path": entry.source_path,
        "version": entry.version,
        "platforms": list(entry.platforms),
        "stub_path": extension_stub_resource_path(entry.name),
        "options": list(entry.options),
        "constants": list(entry.constants),
        "macros": list(entry.macros),
        "files": [_extension_file_metadata(file_entry) for file_entry in entry.files],
    }


def extension_stub_relative_dir(extension_name: str) -> str:
    return os.path.join(EXTENSION_STUBS_RELATIVE_DIR, _safe_identifier(extension_name))


def extension_stub_relative_script_path(extension_name: str) -> str:
    safe_name = _safe_identifier(extension_name)
    return os.path.join(extension_stub_relative_dir(extension_name), f"{safe_name}_extension.gd")


def extension_stub_resource_path(extension_name: str) -> str:
    return "res://" + extension_stub_relative_script_path(extension_name).replace(os.sep, "/")


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


def _write_extension_stub(godot_project_path: str, entry: ExtensionEntry) -> None:
    safe_name = _safe_identifier(entry.name)
    output_dir = os.path.join(godot_project_path, extension_stub_relative_dir(entry.name))
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "plugin.cfg"), "w", encoding="utf-8") as plugin_file:
        plugin_file.write(
            "\n".join([
                "[plugin]",
                f'name="GM2Godot Extension Stub - {entry.name}"',
                'description="Generated binding stub for GameMaker extension metadata."',
                'author="GM2Godot"',
                'version="1.0"',
                f'script="{safe_name}_extension.gd"',
                "",
            ])
        )
    with open(os.path.join(output_dir, f"{safe_name}_extension.gd"), "w", encoding="utf-8") as script_file:
        script_file.write(render_extension_stub_script(entry))


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


def _load_extension_mapping_names(gm_project_path: str) -> set[str]:
    mapping_path = os.path.join(gm_project_path, EXTENSION_FUNCTION_MAPPING_FILENAME)
    if not os.path.isfile(mapping_path):
        return set()
    try:
        return set(load_gml_extension_function_mappings(mapping_path))
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


def _read_json_lenient(path: str) -> JsonDict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None
    try:
        data = json.loads(re.sub(r",\s*([}\]])", r"\1", content))
    except json.JSONDecodeError:
        return None
    return cast(JsonDict, data) if isinstance(data, dict) else None
