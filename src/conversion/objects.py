# pyright: reportPrivateUsage=false
import json
import os
import posixpath
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from src.conversion.asset_output_paths import (
    build_asset_output_paths,
    resource_filesystem_path,
    resource_sibling_path,
)
from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.event_mapping import is_input_event, map_event, map_input_event
from src.conversion.events.base import EventMapping
from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.generated_paths import (
    generated_nested_resource_path,
)
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import (
    GMLSourceMap,
    GMLTranspileError,
    GMLTranspileResult,
    analyze_gml_source_identifiers,
    merge_gml_source_maps,
    transpile_gml_code_with_source_map,
    write_gml_source_map,
)
from src.conversion.gml_transpiler_parts.constants import (
    ASSIGNMENT_OPERATORS,
    BUILTIN_GLOBAL_VARIABLES,
    BUILTIN_INSTANCE_VARIABLES,
    GDSCRIPT_NATIVE_INSTANCE_MEMBER_IDENTIFIERS,
    GML_LITERAL_IDENTIFIERS,
)
from src.conversion.gml_transpiler_parts.function_declarations import event_function_names
from src.conversion.gml_transpiler_parts.lexical_api import (
    preprocess_gml_source,
    tokenize_gml_source,
)
from src.conversion.gml_transpiler_parts.shared_models import EventFunctionSplit, Token
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.object_metadata import capture_gamemaker_object_resource_reference
from src.conversion.object_variables import (
    VARIABLE_DEFINITIONS_FUNCTION,
    VariableDefinition,
    VariableOverride,
    object_pre_create_gml,
    parse_variable_definitions,
    parse_variable_overrides,
    variable_definition_identifiers,
)
from src.conversion.project_enums import collect_project_enum_values
from src.conversion.project_macros import collect_project_macro_values
from src.conversion.project_manifest import (
    ProjectManifestDiagnostic,
    load_gamemaker_project_manifest,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    is_safe_project_source_component,
    project_gml_source_paths,
    resolve_project_source_path,
    validate_project_resource_source_path,
)
from src.conversion.resource_reference_metadata import capture_asset_name_declaration
from src.conversion.script_generator import (
    EVENT_FUNCTIONS_KEY_PREFIX,
    ObjectRuntimeConfig,
    SpriteRuntimeConfig,
    _valid_instance_variables,
    generate_script_content,
)
from src.conversion.type_defs import (
    ConversionRunning,
    LogCallback,
    ProgressCallback,
    StrPath,
)
from src.localization import get_localized

_GML_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SCRIPT_ASSIGNMENT_OPERATORS = frozenset(ASSIGNMENT_OPERATORS) | frozenset({"++", "--"})
_SCRIPT_ASSIGNMENT_SKIP_IDENTIFIERS = (
    BUILTIN_GLOBAL_VARIABLES
    | BUILTIN_INSTANCE_VARIABLES
    | GML_LITERAL_IDENTIFIERS
    | frozenset(
        {
            "break",
            "case",
            "catch",
            "continue",
            "default",
            "delete",
            "do",
            "else",
            "enum",
            "exit",
            "finally",
            "for",
            "function",
            "global",
            "globalvar",
            "if",
            "new",
            "repeat",
            "return",
            "self",
            "static",
            "switch",
            "then",
            "throw",
            "try",
            "until",
            "var",
            "while",
            "with",
        }
    )
)


class ParsedObject(TypedDict):
    source_path: str
    sprite_name: str | None
    sprite_source_path: str | None
    mask_sprite_name: str | None
    parent_object_name: str | None
    parent_object_source_path: str | None
    event_list: list[JsonObject]
    solid: bool
    persistent: bool
    # The object's Variable Definitions and its overrides of inherited ones.
    variable_definitions: tuple[VariableDefinition, ...]
    variable_overrides: tuple[VariableOverride, ...]


class ObjectProcessResult(TypedDict):
    status: Literal["completed", "skipped", "failed"]
    name: str
    has_sprite: bool
    sprite_name: str | None
    event_count: int


class ObjectEventSource(TypedDict):
    mapping: EventMapping
    source_path: str
    source: str
    inherited_event_call: str | None


@dataclass(frozen=True)
class _EventTranspileScope:
    """What the events of one object share when they are transpiled."""

    instance_variables: set[str]
    asset_names: set[str] | None
    direct_names: set[str]
    dynamic_names: set[str]
    enum_values: Mapping[str, Mapping[str, int]] | None
    macro_values: Mapping[str, str] | None


@dataclass(frozen=True)
class _DeclaredObjectResource:
    name: str
    source_path: str | None
    owner_source_path: str | None
    manifest_field: str | None


@dataclass(frozen=True)
class _ManifestObjectPlan:
    requested_names: tuple[str, ...]
    available_subfolders: dict[str, str]
    skipped_names: tuple[str, ...]


@dataclass(frozen=True)
class _ObjectConversionContext:
    """What every object of one conversion run shares."""

    subfolders: Mapping[str, str]
    sprite_scene_paths: Mapping[str, str] | None
    asset_names: set[str] | None
    project_script_instance_variables: set[str] | None
    enum_values: Mapping[str, Mapping[str, int]] | None
    macro_values: Mapping[str, str] | None


@dataclass
class _ObjectRunState:
    total: int
    processed: int = 0
    cancelled: bool = False
    first_error: Exception | None = None
    completed: set[str] = field(default_factory=set[str])
    skipped: set[str] = field(default_factory=set[str])
    failed: set[str] = field(default_factory=set[str])


def _event_source_filenames(mapping: EventMapping) -> tuple[str, ...]:
    filenames: list[str] = []
    for filename in (mapping.gml_filename, *mapping.fallback_gml_filenames):
        if filename and filename not in filenames:
            filenames.append(filename)
    return tuple(filenames)


def _line_offset_for_block(script_content: str, block: str) -> int:
    script_lines = script_content.splitlines()
    block_lines = block.splitlines()
    if not block_lines:
        return 0
    for index in range(0, len(script_lines) - len(block_lines) + 1):
        if script_lines[index:index + len(block_lines)] == block_lines:
            return index
    first_line = block_lines[0]
    for index, line in enumerate(script_lines):
        if line == first_line:
            return index
    return 0


def _script_assigned_instance_variable_names(
    source: str,
    *,
    asset_names: set[str],
    macro_configuration: str | None = None,
) -> set[str]:
    try:
        tokens = tokenize_gml_source(
            preprocess_gml_source(
                source,
                macro_configuration=macro_configuration,
            ).source
        )
    except GMLTranspileError:
        return set()

    assigned_names: set[str] = set()
    local_names = _script_function_parameter_names(tokens)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "EOF":
            break
        if token.kind == "IDENT" and token.value == "var":
            local_names.update(_script_var_declaration_names(tokens, index + 1))
        if token.kind == "IDENT":
            name = token.value
            previous_token = tokens[index - 1] if index > 0 else None
            next_token = tokens[index + 1] if index + 1 < len(tokens) else None
            if (
                name not in local_names
                and name not in asset_names
                and name not in _SCRIPT_ASSIGNMENT_SKIP_IDENTIFIERS
                and (previous_token is None or previous_token.value != ".")
                and _script_identifier_is_assigned(previous_token, next_token)
            ):
                assigned_names.add(name)
        index += 1
    return assigned_names


def _script_identifier_is_assigned(previous_token: Token | None, next_token: Token | None) -> bool:
    previous_value = previous_token.value if previous_token is not None else None
    next_value = next_token.value if next_token is not None else None
    return (
        next_value in _SCRIPT_ASSIGNMENT_OPERATORS
        or previous_value in {"++", "--"}
    )


def _script_var_declaration_names(tokens: Sequence[Token], start: int) -> set[str]:
    names: set[str] = set()
    index = start
    depth = 0
    expect_name = True
    while index < len(tokens):
        token = tokens[index]
        value = token.value
        kind = token.kind
        if kind == "EOF":
            break
        if depth == 0 and value in {";", "\n"}:
            break
        if expect_name:
            if kind == "IDENT":
                names.add(str(value))
                expect_name = False
            index += 1
            continue
        if value in {"(", "[", "{"}:
            depth += 1
        elif value in {")", "]", "}"}:
            if depth <= 0:
                break
            depth -= 1
        elif depth == 0 and value == ",":
            expect_name = True
        index += 1
    return names


def _script_function_parameter_names(tokens: Sequence[Token]) -> set[str]:
    names: set[str] = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "EOF":
            break
        if token.kind == "IDENT" and token.value == "function":
            open_index = _next_token_value_index(tokens, index + 1, "(")
            if open_index is not None:
                close_index = _matching_token_index(tokens, open_index, "(", ")")
                for parameter_index in range(open_index + 1, close_index):
                    parameter = tokens[parameter_index]
                    if parameter.kind == "IDENT":
                        names.add(parameter.value)
                index = close_index
        index += 1
    return names


def _next_token_value_index(tokens: Sequence[Token], start: int, value: str) -> int | None:
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token.kind == "EOF":
            return None
        if token.value == value:
            return index
    return None


def _matching_token_index(tokens: Sequence[Token], open_index: int, open_value: str, close_value: str) -> int:
    depth = 0
    for index in range(open_index, len(tokens)):
        value = tokens[index].value
        if value == open_value:
            depth += 1
        elif value == close_value:
            depth -= 1
            if depth == 0:
                return index
    return max(open_index, len(tokens) - 1)


class ObjectConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath,
                 log_callback: LogCallback = print, progress_callback: ProgressCallback | None = None,
                 conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None,
                 macro_configuration: str | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)
        self.godot_objects_path = os.path.join(self.godot_project_path, 'objects')
        self.macro_configuration = macro_configuration
        self._project_asset_names_cache: set[str] | None = None
        self._project_script_instance_variables_cache: set[str] | None = None
        self._project_enum_values_cache: dict[str, dict[str, int]] | None = None
        self._project_macro_values_cache: dict[str, str] | None = None
        self._asset_output_paths: dict[str, dict[str, str]] = {}
        self._object_source_paths: dict[str, str] = {}
        # While a conversion runs: the objects that get no script (skipped,
        # failed or not part of the project). None outside one, when every
        # object counts as having a script.
        self._objects_without_script: set[str] | None = None
        self._project_resource_names_by_path: dict[tuple[str, str], str] | None = None

    def _get_valid_object_names(self) -> dict[str, str] | None:
        """Parse the .yyp project file and return a dict of object name -> subfolder.

        Returns None if the .yyp file cannot be found or parsed, allowing
        the caller to fall back to converting all objects on disk.
        """
        plan = self._plan_manifest_objects()
        if plan is None:
            return None
        return dict(plan.available_subfolders)

    def _declared_object_resources(
        self,
    ) -> tuple[_DeclaredObjectResource, ...] | None:
        """Return base objects selected by a valid YYP, including rejected paths."""
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="object",
            include_project_sources=True,
        )
        if manifest.yyp_path is None or any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in manifest.diagnostics
        ):
            if manifest.yyp_path is not None:
                self._safe_log(
                    get_localized("Console_Convertor_Objects_YYPFilterWarning")
                )
            return None

        declared: dict[str, _DeclaredObjectResource] = {}
        for resource in manifest.find_resources(kind="objects"):
            if not resource.name:
                continue
            field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            declared.setdefault(
                resource.name,
                _DeclaredObjectResource(
                    name=resource.name,
                    source_path=resource.path,
                    owner_source_path=manifest.yyp_path,
                    manifest_field=field,
                ),
            )

        for diagnostic in manifest.diagnostics:
            if (
                diagnostic.code != "GM2GD-SOURCE-PATH-REJECTED"
                or not diagnostic.resource
                or not self._manifest_diagnostic_is_object(diagnostic)
            ):
                continue
            declared.setdefault(
                diagnostic.resource,
                _DeclaredObjectResource(
                    name=diagnostic.resource,
                    source_path=None,
                    owner_source_path=(
                        diagnostic.source.path
                        if diagnostic.source is not None
                        else manifest.yyp_path
                    ),
                    manifest_field=(
                        diagnostic.source.field_path
                        if diagnostic.source is not None
                        else None
                    ),
                ),
            )

        return tuple(declared.values())

    @staticmethod
    def _manifest_diagnostic_is_object(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        resource_kind = diagnostic.resource_kind
        resource_type = diagnostic.resource_type
        return (
            isinstance(resource_kind, str)
            and resource_kind.casefold() == "objects"
        ) or (
            isinstance(resource_type, str)
            and resource_type.casefold() in {"object", "gmobject"}
        )

    def _plan_manifest_objects(self) -> _ManifestObjectPlan | None:
        """Resolve declared objects without dropping unavailable declarations."""
        declared_resources = self._declared_object_resources()
        if declared_resources is None:
            return None

        available_subfolders: dict[str, str] = {}
        skipped_names: list[str] = []
        for resource in declared_resources:
            if resource.source_path is None:
                self._report_unavailable_declared_object(
                    resource,
                    reason="its manifest source path was rejected",
                )
                skipped_names.append(resource.name)
                continue

            resolved = self._resolve_project_source(
                resource.source_path,
                owner_source_path=resource.owner_source_path,
                resource=resource.name,
                resource_type="object",
                field=resource.manifest_field,
            )
            if resolved is None or not self._source_has_resource_kind(
                resolved,
                "objects",
                rejected_path=resource.source_path,
                owner_source_path=resource.owner_source_path or self.gm_project_path,
                resource=resource.name,
                field=resource.manifest_field or "object.yy",
            ):
                self._report_unavailable_declared_object(
                    resource,
                    reason="its manifest source path is unavailable",
                )
                skipped_names.append(resource.name)
                continue
            if not os.path.isfile(resolved.filesystem_path):
                self._report_unavailable_declared_object(
                    resource,
                    reason=f"metadata is missing at {resolved.source_path!r}",
                )
                skipped_names.append(resource.name)
                continue

            self._object_source_paths[resource.name] = resolved.source_path
            available_subfolders[resource.name] = self._get_subfolder_from_yy(
                resolved.filesystem_path
            )

        return _ManifestObjectPlan(
            requested_names=tuple(resource.name for resource in declared_resources),
            available_subfolders=available_subfolders,
            skipped_names=tuple(skipped_names),
        )

    def _report_unavailable_declared_object(
        self,
        resource: _DeclaredObjectResource,
        *,
        reason: str,
    ) -> None:
        message = (
            "Warning: Skipping manifest-declared GameMaker object "
            f"{resource.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-OBJECT-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    resource.owner_source_path
                ),
                resource=resource.name,
                resource_type="object",
                manifest_entry=resource.manifest_field,
                workaround=(
                    "Restore the declared GameMaker object .yy metadata inside "
                    "the project root or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def _source_has_resource_kind(
        self,
        resolved: ResolvedProjectSourcePath,
        resource_kind: str,
        *,
        rejected_path: str,
        owner_source_path: StrPath,
        resource: str,
        field: str,
    ) -> bool:
        try:
            validate_project_resource_source_path(resolved, resource_kind)
            return True
        except ProjectSourcePathError as error:
            self._report_source_path_rejection(
                rejected_path,
                error,
                owner_source_path=owner_source_path,
                resource=resource,
                resource_type="object",
                field=field,
            )
            return False

    def _get_project_asset_names(self) -> set[str]:
        """Return GameMaker resource names that can collide with unscoped GML identifiers."""
        if self._project_asset_names_cache is not None:
            return set(self._project_asset_names_cache)

        try:
            registry_converter = AssetRegistryConverter(
                self.gm_project_path,
                self.godot_project_path,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=self.conversion_running,
                macro_configuration=self.macro_configuration,
                diagnostics=self.diagnostics,
            )
            asset_names = {entry.name for entry in registry_converter.build_entries()}
            self._project_asset_names_cache = asset_names
            return set(asset_names)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

        try:
            yyp_files = sorted(
                f for f in os.listdir(self.gm_project_path) if f.endswith('.yyp')
            )
            for yyp_filename in yyp_files:
                yyp_source = self._resolve_discovered_project_source(
                    os.path.join(self.gm_project_path, yyp_filename),
                    resource_type="project",
                    field="project asset-name discovery",
                )
                if yyp_source is None or not os.path.isfile(yyp_source.filesystem_path):
                    continue
                with open(yyp_source.filesystem_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                value = decode_gamemaker_json(
                    content, source_path=yyp_source.filesystem_path
                ).value
                if not isinstance(value, dict):
                    raise AttributeError(
                        f"'{type(value).__name__}' object has no attribute 'get'",
                        name="get", obj=value,
                    )
                data = value

                asset_names: set[str] = set()
                resources = data.get("resources", [])
                if not isinstance(resources, (list, dict, str)):
                    raise TypeError(f"'{type(resources).__name__}' object is not iterable")
                for resource in resources:
                    declaration = capture_asset_name_declaration(resource)
                    if declaration.name is not None:
                        asset_names.add(declaration.name)
                self._project_asset_names_cache = asset_names
                return set(asset_names)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

        asset_names = set()
        for resource_dir in ("objects", "sprites", "sounds", "rooms", "scripts"):
            resolved_root = self._resolve_discovered_project_source(
                os.path.join(self.gm_project_path, resource_dir),
                resource_type="project_resource",
                field="asset-name discovery directory",
            )
            if resolved_root is None or not os.path.isdir(resolved_root.filesystem_path):
                continue
            try:
                names = sorted(os.listdir(resolved_root.filesystem_path))
            except OSError:
                continue
            for name in names:
                resolved_resource = self._resolve_discovered_project_source(
                    os.path.join(resolved_root.filesystem_path, name),
                    owner_source_path=resolved_root.source_path,
                    resource=name,
                    resource_type="project_resource",
                    field="asset-name discovery resource",
                )
                if resolved_resource is not None and os.path.isdir(
                    resolved_resource.filesystem_path
                ):
                    asset_names.add(name)
        self._project_asset_names_cache = asset_names
        return set(asset_names)

    def _get_project_script_instance_variables(self, asset_names: set[str]) -> set[str]:
        """Return bare script-assigned names that execute in caller instance scope."""
        if self._project_script_instance_variables_cache is not None:
            return set(self._project_script_instance_variables_cache)

        script_instance_variables: set[str] = set()
        for source_path in project_gml_source_paths(self.gm_project_path):
            if not source_path.source_path.casefold().startswith("scripts/"):
                continue
            try:
                with open(
                    source_path.filesystem_path,
                    "r",
                    encoding="utf-8",
                ) as source_file:
                    source = source_file.read()
            except OSError:
                continue
            script_instance_variables.update(
                _script_assigned_instance_variable_names(
                    source,
                    asset_names=asset_names,
                    macro_configuration=self.macro_configuration,
                )
            )
        self._project_script_instance_variables_cache = script_instance_variables
        return set(script_instance_variables)

    def _get_project_enum_values(self) -> dict[str, dict[str, int]]:
        if self._project_enum_values_cache is None:
            self._project_enum_values_cache = collect_project_enum_values(
                self.gm_project_path,
                macro_configuration=self.macro_configuration,
            )
        return {
            name: dict(members)
            for name, members in self._project_enum_values_cache.items()
        }

    def _get_project_macro_values(self) -> dict[str, str]:
        if self._project_macro_values_cache is None:
            self._project_macro_values_cache = collect_project_macro_values(
                self.gm_project_path,
                macro_configuration=self.macro_configuration,
            )
        return dict(self._project_macro_values_cache)

    def _resolve_object_yy_source(
        self,
        object_name: str,
        source_path: str | None = None,
    ) -> ResolvedProjectSourcePath | None:
        if source_path is not None:
            resolved = self._resolve_project_source(
                source_path,
                resource=object_name,
                resource_type="object",
                field="object.yy",
            )
            owner_source_path: StrPath = os.path.dirname(source_path)
            rejected_path = source_path
        else:
            candidate = os.path.join(
                self.gm_project_path,
                "objects",
                object_name,
                object_name + ".yy",
            )
            resolved = self._resolve_discovered_project_source(
                candidate,
                owner_source_path=os.path.dirname(candidate),
                resource=object_name,
                resource_type="object",
                field="object.yy",
            )
            owner_source_path = os.path.dirname(candidate)
            rejected_path = candidate
        if resolved is None or not self._source_has_resource_kind(
            resolved,
            "objects",
            rejected_path=rejected_path,
            owner_source_path=owner_source_path,
            resource=object_name,
            field="object.yy",
        ):
            return None
        return resolved

    def _resolve_resource_reference(
        self,
        value: JsonValue,
        *,
        owner_source_path: str,
        owner_name: str,
        field: str,
        resource_kind: str,
    ) -> tuple[str, str] | None:
        reference = capture_gamemaker_object_resource_reference(
            value, source_context=owner_source_path
        )
        if not reference.is_object:
            return None

        raw_path = reference.path_value
        raw_name = reference.name_value
        reference_field = f"{field}.path"
        legacy_name_reference = not reference.path_present
        if legacy_name_reference:
            if not isinstance(raw_name, str) or not is_safe_project_source_component(
                raw_name
            ):
                rejected_name = (
                    raw_name if isinstance(raw_name, str) else repr(raw_name)
                )
                self._report_source_path_rejection(
                    rejected_name,
                    ProjectSourcePathError(
                        "Legacy GameMaker resource reference name must be one "
                        f"safe path component: {raw_name!r}"
                    ),
                    owner_source_path=owner_source_path,
                    resource=owner_name,
                    resource_type="object",
                    field=f"{field}.name",
                )
                return None
            raw_path = f"{resource_kind}/{raw_name}/{raw_name}.yy"
            reference_field = f"{field}.name"
        elif not isinstance(raw_path, str) or not raw_path:
            rejected_path = raw_path if isinstance(raw_path, str) else repr(raw_path)
            self._report_source_path_rejection(
                rejected_path,
                ProjectSourcePathError(
                    "GameMaker resource reference path must be a non-empty "
                    f"string: {raw_path!r}"
                ),
                owner_source_path=owner_source_path,
                resource=owner_name,
                resource_type="object",
                field=reference_field,
            )
            return None

        resolved = self._resolve_project_source(
            raw_path,
            owner_source_path=owner_source_path,
            resource=owner_name,
            resource_type="object",
            field=reference_field,
        )
        if resolved is None or not self._source_has_resource_kind(
            resolved,
            resource_kind,
            rejected_path=raw_path,
            owner_source_path=owner_source_path,
            resource=owner_name,
            field=reference_field,
        ):
            return None

        reference_name = (
            raw_name
            if legacy_name_reference and isinstance(raw_name, str)
            else self._logical_resource_name(resource_kind, resolved)
        )
        if not reference_name:
            return None
        return reference_name, resolved.source_path

    def _logical_resource_name(
        self,
        resource_kind: str,
        resolved: ResolvedProjectSourcePath,
    ) -> str:
        if self._project_resource_names_by_path is None:
            names_by_path: dict[tuple[str, str], str] = {}
            manifest = load_gamemaker_project_manifest(self.gm_project_path)
            for resource in manifest.resources:
                kind = resource.kind.casefold()
                if kind not in {"sprites", "objects"}:
                    continue
                try:
                    resource_source = resolve_project_source_path(
                        self.gm_project_path,
                        resource.path,
                    )
                    validate_project_resource_source_path(
                        resource_source,
                        kind,
                    )
                except ProjectSourcePathError:
                    continue
                if is_safe_project_source_component(resource.name):
                    names_by_path.setdefault(
                        (kind, resource_source.source_path),
                        resource.name,
                    )
            self._project_resource_names_by_path = names_by_path

        manifest_name = self._project_resource_names_by_path.get(
            (resource_kind.casefold(), resolved.source_path),
            "",
        )
        if manifest_name:
            return manifest_name

        referenced_data = self._read_yy_file(resolved.filesystem_path)
        if referenced_data is not None:
            for key in ("%Name", "name"):
                value = referenced_data.get(key)
                if isinstance(value, str) and is_safe_project_source_component(value):
                    return value

        fallback_name = posixpath.splitext(
            posixpath.basename(resolved.source_path)
        )[0]
        return (
            fallback_name
            if is_safe_project_source_component(fallback_name)
            else ""
        )

    def _sanitize_object_events(
        self,
        raw_event_list: JsonValue,
        *,
        owner_source_path: str,
        object_name: str,
    ) -> list[JsonObject]:
        if not isinstance(raw_event_list, list):
            return []

        events: list[JsonObject] = []
        for index, raw_event in enumerate(raw_event_list):
            if not isinstance(raw_event, dict):
                continue
            event: JsonObject = {
                key: value
                for key, value in raw_event.items()
            }
            if isinstance(event.get("collisionObjectId"), dict):
                collision_reference = self._resolve_resource_reference(
                    event["collisionObjectId"],
                    owner_source_path=owner_source_path,
                    owner_name=object_name,
                    field=f"eventList[{index}].collisionObjectId",
                    resource_kind="objects",
                )
                event["collisionObjectId"] = (
                    {
                        "name": collision_reference[0],
                        "path": collision_reference[1],
                    }
                    if collision_reference is not None
                    else None
                )

            mapping = map_input_event(event) if is_input_event(event) else map_event(event)
            if (
                event.get("isDnD") is True
                and mapping is not None
                and not self._event_mapping_paths_are_contained(
                    owner_source_path,
                    object_name,
                    mapping,
                    field=f"eventList[{index}].sourceFile",
                )
            ):
                # DnD events do not consume adjacent GML, but malformed event
                # metadata must not flow into generated function names.
                continue
            events.append(event)
        return events

    def _event_mapping_paths_are_contained(
        self,
        owner_source_path: str,
        object_name: str,
        mapping: EventMapping,
        *,
        field: str,
    ) -> bool:
        for filename in _event_source_filenames(mapping):
            if self._resolve_event_source(
                owner_source_path,
                object_name,
                filename,
                field=field,
            ) is None:
                return False
        return True

    def _resolve_event_source(
        self,
        owner_source_path: str,
        object_name: str,
        filename: str,
        *,
        field: str = "eventList[].sourceFile",
    ) -> ResolvedProjectSourcePath | None:
        if not is_safe_project_source_component(filename):
            self._report_source_path_rejection(
                filename,
                ProjectSourcePathError(
                    "GameMaker object event source must be one safe filename "
                    f"component: {filename!r}"
                ),
                owner_source_path=owner_source_path,
                resource=object_name,
                resource_type="object",
                field=field,
            )
            return None
        resolved = self._resolve_project_source(
            filename,
            owner_source_path=owner_source_path,
            resource=object_name,
            resource_type="object",
            field=field,
        )
        if resolved is None:
            return None
        owner_directory = posixpath.dirname(owner_source_path.replace("\\", "/"))
        if posixpath.dirname(resolved.source_path) == owner_directory:
            return resolved
        self._report_source_path_rejection(
            filename,
            ProjectSourcePathError(
                "GameMaker object event filenames must stay beside their "
                "declaring object .yy file"
            ),
            owner_source_path=owner_source_path,
            resource=object_name,
            resource_type="object",
            field=field,
        )
        return None

    def _parse_object_yy(
        self,
        object_name: str,
        object_source_path: str | None = None,
    ) -> ParsedObject | None:
        """Parse an object .yy file and extract the sprite reference and event list.

        Returns a dict with 'sprite_name' (str or None) and 'event_list' (list)
        or None if parsing fails.
        """
        resolved_object = self._resolve_object_yy_source(
            object_name,
            object_source_path or self._object_source_paths.get(object_name),
        )
        if resolved_object is None:
            return None
        yy_path = resolved_object.filesystem_path
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            value = decode_gamemaker_json(content, source_path=yy_path).value
            if not isinstance(value, dict):
                raise AttributeError(
                    f"'{type(value).__name__}' object has no attribute 'get'",
                    name="get", obj=value,
                )
            data = value

            sprite_reference = self._resolve_resource_reference(
                data.get("spriteId"),
                owner_source_path=resolved_object.source_path,
                owner_name=object_name,
                field="spriteId",
                resource_kind="sprites",
            )
            parent_reference = self._resolve_resource_reference(
                data.get("parentObjectId"),
                owner_source_path=resolved_object.source_path,
                owner_name=object_name,
                field="parentObjectId",
                resource_kind="objects",
            )
            event_list = self._sanitize_object_events(
                data.get("eventList", []),
                owner_source_path=resolved_object.source_path,
                object_name=object_name,
            )

            parsed_object = ParsedObject(
                source_path=resolved_object.source_path,
                sprite_name=sprite_reference[0] if sprite_reference is not None else None,
                sprite_source_path=sprite_reference[1] if sprite_reference is not None else None,
                mask_sprite_name=None,
                parent_object_name=parent_reference[0] if parent_reference is not None else None,
                parent_object_source_path=parent_reference[1] if parent_reference is not None else None,
                event_list=event_list,
                solid=bool(data.get("solid", False)),
                persistent=bool(data.get("persistent", False)),
                variable_definitions=parse_variable_definitions(data.get("properties")),
                variable_overrides=parse_variable_overrides(data.get("overriddenProperties")),
            )
            # The object's collision mask ("Collision Mask" in the object
            # editor) starts every instance's mask_index.
            mask_reference = self._resolve_resource_reference(
                data.get("spriteMaskId"),
                owner_source_path=resolved_object.source_path,
                owner_name=object_name,
                field="spriteMaskId",
                resource_kind="sprites",
            )
            if mask_reference is not None:
                parsed_object["mask_sprite_name"] = mask_reference[0]
            return parsed_object
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._safe_log(get_localized("Console_Convertor_Objects_ParseError").format(
                yy_path=yy_path, object_name=object_name))
            return None

    def _object_script_res_path(self, object_name: str, subfolder: str = "") -> str:
        return resource_sibling_path(
            self._object_scene_res_path(object_name, subfolder),
            ".gd",
        )

    def _object_scene_res_path(self, object_name: str, subfolder: str = "") -> str:
        return self._asset_output_paths.get("objects", {}).get(
            object_name,
            generated_nested_resource_path("objects", subfolder, object_name, ".tscn"),
        )

    def _get_object_subfolder(
        self,
        object_name: str,
        object_source_path: str | None = None,
    ) -> str:
        resolved = self._resolve_object_yy_source(
            object_name,
            object_source_path or self._object_source_paths.get(object_name),
        )
        return (
            self._get_subfolder_from_yy(resolved.filesystem_path)
            if resolved is not None
            else ""
        )

    def _get_sprite_subfolder(
        self,
        sprite_source_path: str,
        *,
        owner_source_path: str,
        object_name: str,
    ) -> str:
        """Resolve a sprite's subfolder from the object's contained reference."""
        resolved = self._resolve_project_source(
            sprite_source_path,
            owner_source_path=owner_source_path,
            resource=object_name,
            resource_type="object",
            field="spriteId.path",
        )
        return (
            self._get_subfolder_from_yy(resolved.filesystem_path)
            if resolved is not None
            else ""
        )

    def _sprite_scene_exists(self, sprite_name: str, sprite_subfolder: str = "") -> bool:
        """Check whether the converted sprite scene exists in the Godot project."""
        scene_path = self._asset_output_paths.get("sprites", {}).get(
            sprite_name,
            generated_nested_resource_path("sprites", sprite_subfolder, sprite_name, ".tscn"),
        )
        tscn_path = resource_filesystem_path(self.godot_project_path, scene_path)
        return os.path.isfile(tscn_path)

    def _get_available_sprite_scene_paths(self) -> dict[str, str]:
        """Return sprite resource names mapped to converted Godot scene paths."""
        indexed_paths = {
            name: scene_path
            for name, scene_path in self._asset_output_paths.get("sprites", {}).items()
            if os.path.isfile(resource_filesystem_path(self.godot_project_path, scene_path))
        }
        if indexed_paths:
            return indexed_paths

        sprites_root = os.path.join(self.godot_project_path, 'sprites')
        if not os.path.isdir(sprites_root):
            return {}

        scene_paths: dict[str, str] = {}
        for dirpath, _, filenames in os.walk(sprites_root):
            for filename in filenames:
                if not filename.endswith('.tscn'):
                    continue
                sprite_name = os.path.splitext(filename)[0]
                scene_path = os.path.join(dirpath, filename)
                relative_path = os.path.relpath(scene_path, self.godot_project_path).replace(os.sep, '/')
                scene_paths[sprite_name] = f"res://{relative_path}"
        return scene_paths

    def _generate_object_scene(
        self,
        object_name: str,
        sprite_name: str | None,
        sprite_scene_path: str | None = None,
        script_res_path: str | None = None,
    ) -> str:
        """Build the .tscn content string for an object scene.

        If sprite_name is not None, the scene instances the sprite's scene as a child.
        If script_res_path is not None, the scene attaches the script to the root node.
        """
        has_sprite = sprite_name is not None
        has_script = script_res_path is not None
        ext_resource_count = int(has_sprite) + int(has_script)
        load_steps = ext_resource_count + 1 if ext_resource_count > 0 else 0

        if load_steps > 0:
            parts = [f'[gd_scene format=3 load_steps={load_steps}]\n']
        else:
            parts = ['[gd_scene format=3]\n']

        next_id = 1
        sprite_id = None
        script_id = None

        if has_sprite:
            sprite_id = str(next_id)
            next_id += 1
            sprite_path = sprite_scene_path or generated_nested_resource_path(
                "sprites", "", sprite_name or "sprite", ".tscn"
            )
            parts.append(f'\n[ext_resource type="PackedScene" path="{sprite_path}" id="{sprite_id}"]\n')

        if has_script:
            script_id = str(next_id)
            parts.append(f'\n[ext_resource type="Script" path="{script_res_path}" id="{script_id}"]\n')

        if has_script:
            parts.append(f'\n[node name="{object_name}" type="Node2D"]\nscript = ExtResource("{script_id}")\n')
        else:
            parts.append(f'\n[node name="{object_name}" type="Node2D"]\n')

        if has_sprite:
            parts.append(f'\n[node name="{sprite_name}" parent="." instance=ExtResource("{sprite_id}")]\n')

        return ''.join(parts)

    def _load_event_code_bodies(
        self,
        object_name: str,
        object_source_path: str,
        event_list: list[JsonObject],
        inherited_event_functions: set[str] | None = None,
        asset_names: set[str] | None = None,
        project_script_instance_variables: set[str] | None = None,
        direct_instance_variables: set[str] | None = None,
        direct_reference_names: set[str] | None = None,
        enum_values: Mapping[str, Mapping[str, int]] | None = None,
        macro_values: Mapping[str, str] | None = None,
        inherited_member_names: frozenset[str] | None = None,
        variable_definitions: ObjectEventSource | None = None,
    ) -> tuple[dict[str, str], set[str], dict[str, GMLSourceMap], bool]:
        code_bodies: dict[str, str] = {}
        source_maps: dict[str, GMLSourceMap] = {}
        has_event_blocker = False
        instance_variables: set[str] = set(project_script_instance_variables or set())
        inherited_functions = inherited_event_functions or set()
        source_entries: list[ObjectEventSource] = []
        asset_name_set = set(asset_names or set())

        for event_index, event in enumerate(event_list or []):
            if event.get("isDnD") is True:
                continue
            mapping = map_input_event(event) if is_input_event(event) else map_event(event)
            if mapping is None or not mapping.gml_filename:
                continue

            manifest_entry = f"eventList[{event_index}].sourceFile"
            if not self._event_mapping_paths_are_contained(
                object_source_path,
                object_name,
                mapping,
                field=manifest_entry,
            ):
                has_event_blocker = True
                self._record_rejected_event_source(
                    object_name,
                    object_source_path,
                    mapping,
                    manifest_entry=manifest_entry,
                )
                continue

            source_path = self._event_source_path(
                object_source_path,
                object_name,
                mapping,
            )
            if source_path is None:
                self._record_missing_event_source(
                    object_name,
                    object_source_path,
                    mapping,
                    manifest_entry=manifest_entry,
                )
                has_event_blocker = True
                continue

            try:
                with open(source_path, 'r', encoding='utf-8') as f:
                    source = f.read()
            except OSError as exc:
                has_event_blocker = True
                self._record_unreadable_event_source(
                    object_name,
                    source_path,
                    mapping,
                    exc,
                    manifest_entry=manifest_entry,
                )
                continue

            if not source.strip():
                continue

            inherited_event_call = (
                self._inherited_event_call(mapping)
                if mapping.godot_func in inherited_functions
                else None
            )
            source_entries.append(
                {
                    "mapping": mapping,
                    "source_path": source_path,
                    "source": source,
                    "inherited_event_call": inherited_event_call,
                }
            )
            instance_variables.update(
                _script_assigned_instance_variable_names(
                    source,
                    asset_names=asset_name_set,
                    macro_configuration=self.macro_configuration,
                )
            )

        # The object's Pre-Create code (its Variable Definitions) converts
        # like an event.
        if variable_definitions is not None:
            source_entries.append(variable_definitions)
            instance_variables.update(
                _script_assigned_instance_variable_names(
                    variable_definitions["source"],
                    asset_names=asset_name_set,
                    macro_configuration=self.macro_configuration,
                )
            )

        # The functions an event declares are bound when the instance is
        # built, by code of their own rather than by the event.
        event_function_positions = {
            position
            for position, entry in enumerate(source_entries)
            if self._event_declares_functions(entry)
        }

        # A child object's script declares (and reads directly) only the
        # variables no ancestor script can declare already.
        own_variables = (
            instance_variables
            if inherited_member_names is None
            else instance_variables - inherited_member_names
        )
        direct_names = (
            set(_valid_instance_variables(own_variables))
            if direct_instance_variables is None
            else set(direct_instance_variables)
        )
        direct_names.update(direct_reference_names or set())
        dynamic_names = (
            set(instance_variables)
            | GDSCRIPT_NATIVE_INSTANCE_MEMBER_IDENTIFIERS
        ) - direct_names

        scope = _EventTranspileScope(
            instance_variables=instance_variables,
            asset_names=asset_names,
            direct_names=direct_names,
            dynamic_names=dynamic_names,
            enum_values=enum_values,
            macro_values=macro_values,
        )
        for position, entry in enumerate(source_entries):
            mapping = entry["mapping"]
            source_path = entry["source_path"]
            source = entry["source"]
            declares_functions = position in event_function_positions
            try:
                self._record_event_source_diagnostics(
                    source,
                    source_path,
                    object_name,
                    mapping.godot_func,
                )

                result = self._transpile_event_entry(
                    object_name,
                    entry,
                    scope,
                    EventFunctionSplit("body") if declares_functions else None,
                )
                code_bodies[mapping.godot_func] = result.code
                source_maps[mapping.godot_func] = result.source_map
                if declares_functions:
                    declarations = self._transpile_event_entry(
                        object_name,
                        entry,
                        scope,
                        EventFunctionSplit("declarations"),
                    )
                    key = f"{EVENT_FUNCTIONS_KEY_PREFIX}{mapping.godot_func}"
                    code_bodies[key] = declarations.code
                    source_maps[key] = declarations.source_map
            except GMLTranspileError as exc:
                has_event_blocker = True
                message = (
                    "Warning: Could not transpile GameMaker event code for "
                    f"{object_name}/{mapping.gml_filename}: {exc}"
                )
                if self.diagnostics is not None:
                    self.diagnostics.add_transpile_failure(
                        message,
                        source_path=source_path,
                        line=exc.line,
                        column=exc.column,
                        resource=object_name,
                        resource_type="object",
                        event=mapping.godot_func,
                        workaround="Split or rewrite unsupported GML for this event, or add the missing runtime/API support tracked by the linked issue.",
                    )
                self._safe_log(message)

        return code_bodies, instance_variables, source_maps, has_event_blocker

    def _transpile_event_entry(
        self,
        object_name: str,
        entry: ObjectEventSource,
        scope: _EventTranspileScope,
        event_functions: EventFunctionSplit | None,
    ) -> GMLTranspileResult:
        mapping = entry["mapping"]
        return transpile_gml_code_with_source_map(
            entry["source"],
            instance_variables=scope.instance_variables,
            inherited_event_call=entry["inherited_event_call"],
            macro_configuration=self.macro_configuration,
            asset_names=scope.asset_names,
            static_scope_prefix=f"{object_name}.{mapping.godot_func}",
            source_path=entry["source_path"],
            event=mapping.godot_func,
            preserve_source_comments=(
                event_functions is None or event_functions.part == "body"
            ),
            instance_target="self",
            direct_instance_names=scope.direct_names,
            dynamic_instance_names=scope.dynamic_names,
            enum_values=scope.enum_values,
            macro_values=scope.macro_values,
            event_functions=event_functions,
        )

    def _event_declares_functions(self, entry: ObjectEventSource) -> bool:
        try:
            return bool(
                event_function_names(
                    entry["source"],
                    macro_configuration=self.macro_configuration,
                )
            )
        except GMLTranspileError:
            # The transpile of the event reports the error.
            return False

    def _event_source_path(
        self,
        object_source_path: str,
        object_name: str,
        mapping: EventMapping,
    ) -> str | None:
        for filename in _event_source_filenames(mapping):
            resolved = self._resolve_event_source(
                object_source_path,
                object_name,
                filename,
            )
            if resolved is not None and os.path.isfile(resolved.filesystem_path):
                return resolved.filesystem_path
        return None

    def _record_missing_event_source(
        self,
        object_name: str,
        object_source_path: str,
        mapping: EventMapping,
        *,
        manifest_entry: str,
    ) -> None:
        filenames = _event_source_filenames(mapping)
        owner_directory = posixpath.dirname(object_source_path.replace("\\", "/"))
        message = (
            "Warning: Missing GameMaker event code file for "
            f"{object_name}/{mapping.godot_func}; looked for {', '.join(filenames)}"
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                (
                    "GM2GD-OBJECT-MISSING-COLLISION-EVENT-SOURCE"
                    if mapping.gml_filename.startswith("Collision_")
                    else "GM2GD-OBJECT-EVENT-SOURCE-MISSING"
                ),
                message,
                source_path=(
                    posixpath.join(owner_directory, filenames[0])
                    if filenames
                    else object_source_path
                ),
                resource=object_name,
                resource_type="object",
                event=mapping.godot_func,
                manifest_entry=manifest_entry,
                workaround=(
                    "Restore the declared GameMaker event GML file or remove "
                    "the stale event metadata. A deliberately empty event "
                    "should retain its readable zero-byte GML file."
                ),
            )
        self._safe_log(message)

    def _record_rejected_event_source(
        self,
        object_name: str,
        object_source_path: str,
        mapping: EventMapping,
        *,
        manifest_entry: str,
    ) -> None:
        filenames = _event_source_filenames(mapping)
        message = (
            "Warning: Rejected GameMaker event code source for "
            f"{object_name}/{mapping.godot_func}; looked for {', '.join(filenames)}"
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-OBJECT-EVENT-SOURCE-REJECTED",
                message,
                source_path=object_source_path,
                resource=object_name,
                resource_type="object",
                event=mapping.godot_func,
                manifest_entry=manifest_entry,
                workaround=(
                    "Use the canonical GameMaker event filename beside the "
                    "declaring object .yy file."
                ),
            )
        self._safe_log(message)

    def _record_unreadable_event_source(
        self,
        object_name: str,
        source_path: str,
        mapping: EventMapping,
        error: OSError,
        *,
        manifest_entry: str,
    ) -> None:
        message = (
            "Warning: Could not read GameMaker event code file for "
            f"{object_name}/{mapping.godot_func}: {source_path}: {error}"
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-OBJECT-EVENT-SOURCE-READ",
                message,
                source_path=self._diagnostic_source_path(source_path),
                resource=object_name,
                resource_type="object",
                event=mapping.godot_func,
                manifest_entry=manifest_entry,
                workaround=(
                    "Restore a readable GameMaker event GML file before "
                    "converting this object."
                ),
            )
        self._safe_log(message)

    def _record_event_source_diagnostics(
        self,
        source: str,
        source_path: str,
        object_name: str,
        event_name: str,
    ) -> None:
        if self.diagnostics is None:
            return
        for diagnostic in analyze_gml_source_identifiers(source):
            self.diagnostics.add(
                diagnostic.severity,
                diagnostic.code,
                diagnostic.message,
                source_path=source_path,
                line=diagnostic.line,
                column=diagnostic.column,
                resource=object_name,
                resource_type="object",
                event=event_name,
                workaround=(
                    f"Rename '{diagnostic.identifier}'"
                    + (
                        f" to '{diagnostic.suggested_name}'"
                        if diagnostic.suggested_name
                        else ""
                    )
                    + " before conversion."
                ),
            )

    def _object_variable_definitions(
        self,
        object_name: str,
        parsed: ParsedObject,
    ) -> tuple[ObjectEventSource | None, bool]:
        """Return an object's Pre-Create source and whether its instances run one.

        GameMaker compiles the Variable Definitions of an object with
        definitions or overrides of its own into its Pre-Create event, which
        starts with event_inherited(); an object without them runs its
        nearest ancestor's (the generated method is inherited).
        """
        inherited_definitions: dict[str, VariableDefinition] = {}
        ancestors_define = False
        seen = {object_name}
        ancestor_name = parsed["parent_object_name"]
        ancestor_source_path = parsed["parent_object_source_path"]
        while ancestor_name is not None and ancestor_name not in seen:
            seen.add(ancestor_name)
            ancestor = self._parse_object_yy(ancestor_name, ancestor_source_path)
            if ancestor is None:
                break
            # The definitions of an ancestor without a script do not reach the
            # instance: its Pre-Create method does not exist.
            if self._object_has_script(ancestor_name) and (
                ancestor["variable_definitions"] or ancestor["variable_overrides"]
            ):
                ancestors_define = True
                for definition in ancestor["variable_definitions"]:
                    inherited_definitions.setdefault(definition.name, definition)
            ancestor_name = ancestor["parent_object_name"]
            ancestor_source_path = ancestor["parent_object_source_path"]
        if not (parsed["variable_definitions"] or parsed["variable_overrides"]):
            return None, ancestors_define
        resolved = self._resolve_object_yy_source(object_name, parsed["source_path"])
        source: ObjectEventSource = {
            # Diagnostics name the source by its object-editor panel.
            "mapping": EventMapping(VARIABLE_DEFINITIONS_FUNCTION, "", 0, "Variable Definitions"),
            "source_path": resolved.filesystem_path if resolved is not None else parsed["source_path"],
            "source": object_pre_create_gml(
                parsed["variable_definitions"],
                parsed["variable_overrides"],
                inherited_definitions,
                inherited=ancestors_define,
            ),
            "inherited_event_call": (
                f"super.{VARIABLE_DEFINITIONS_FUNCTION}()" if ancestors_define else None
            ),
        }
        return source, True

    def _inherited_event_call(self, mapping: EventMapping) -> str:
        if not mapping.params:
            return f"super.{mapping.godot_func}()"
        return f"super.{mapping.godot_func}({mapping.params})"

    def _parent_event_function_names(
        self,
        parent_object_name: str | None,
        parent_object_source_path: str | None,
    ) -> set[str]:
        # The events of every ancestor: like GameMaker, an object without an
        # event runs its nearest ancestor's, and event_inherited() runs the
        # nearest one above the object, even past a parent without it.
        function_names: set[str] = set()
        seen: set[str] = set()
        object_name = parent_object_name
        source_path = parent_object_source_path
        while object_name is not None and object_name not in seen:
            seen.add(object_name)
            parsed = self._parse_object_yy(object_name, source_path)
            if parsed is None:
                break
            if self._object_has_script(object_name):
                for event in parsed["event_list"]:
                    mapping = map_input_event(event) if is_input_event(event) else map_event(event)
                    if mapping is not None:
                        function_names.add(mapping.godot_func)
            object_name = parsed["parent_object_name"]
            source_path = parsed["parent_object_source_path"]
        return function_names

    def _ancestors_declare_event_functions(
        self,
        parent_object_name: str | None,
        parent_object_source_path: str | None,
    ) -> bool:
        """Whether an ancestor's script binds functions its events declare."""
        seen: set[str] = set()
        object_name = parent_object_name
        source_path = parent_object_source_path
        while object_name is not None and object_name not in seen:
            seen.add(object_name)
            parsed = self._parse_object_yy(object_name, source_path)
            if parsed is None:
                return False
            if self._object_has_script(object_name) and self._object_declares_event_functions(
                object_name,
                parsed,
            ):
                return True
            object_name = parsed["parent_object_name"]
            source_path = parsed["parent_object_source_path"]
        return False

    def _object_declares_event_functions(self, object_name: str, parsed: ParsedObject) -> bool:
        for event in parsed["event_list"]:
            mapping = map_input_event(event) if is_input_event(event) else map_event(event)
            if event.get("isDnD") is True or mapping is None or not mapping.gml_filename:
                continue
            event_source_path = self._event_source_path(parsed["source_path"], object_name, mapping)
            if event_source_path is None:
                continue
            try:
                with open(event_source_path, "r", encoding="utf-8") as f:
                    declared = event_function_names(
                        f.read(),
                        macro_configuration=self.macro_configuration,
                    )
            except (OSError, UnicodeDecodeError, GMLTranspileError):
                continue
            if declared:
                return True
        return False

    def _inherited_input_functions(
        self,
        parent_object_name: str | None,
        parent_object_source_path: str | None,
    ) -> tuple[str, ...]:
        """Return the input event methods of an object's ancestors, nearest first."""
        function_names: list[str] = []
        seen: set[str] = set()
        object_name = parent_object_name
        source_path = parent_object_source_path
        while object_name is not None and object_name not in seen:
            seen.add(object_name)
            parsed = self._parse_object_yy(object_name, source_path)
            if parsed is None:
                break
            if self._object_has_script(object_name):
                for event in parsed["event_list"]:
                    mapping = map_input_event(event) if is_input_event(event) else None
                    if mapping is not None and mapping.godot_func not in function_names:
                        function_names.append(mapping.godot_func)
            object_name = parsed["parent_object_name"]
            source_path = parsed["parent_object_source_path"]
        return tuple(function_names)

    def _event_function_names(self, event_list: list[JsonObject]) -> set[str]:
        function_names: set[str] = set()
        for event in event_list:
            mapping = map_input_event(event) if is_input_event(event) else map_event(event)
            if mapping is not None:
                function_names.add(mapping.godot_func)
        return function_names

    def _object_has_script(self, object_name: str) -> bool:
        """Whether the object gets a script (every object does outside a conversion run)."""
        return self._objects_without_script is None or object_name not in self._objects_without_script

    def _script_parent(
        self,
        parent_name: str | None,
        parent_source_path: str | None,
    ) -> tuple[str | None, str | None, tuple[str, ...]]:
        """Return the nearest ancestor that has a script, and the ancestors passed over.

        The script of an object that was skipped, failed or is no project
        object does not exist, so its descendants extend the next ancestor
        with one (the name and source path are None when none has).
        """
        passed_over: list[str] = []
        seen: set[str] = set()
        name, source_path = parent_name, parent_source_path
        while name is not None and name not in seen:
            seen.add(name)
            if self._object_has_script(name):
                return name, source_path, tuple(passed_over)
            passed_over.append(name)
            parsed = self._parse_object_yy(name, source_path)
            if parsed is None:
                break
            name = parsed["parent_object_name"]
            source_path = parsed["parent_object_source_path"]
        return None, None, tuple(passed_over)

    def _report_unconverted_ancestors(
        self,
        object_name: str,
        object_source_path: str,
        script_parent_name: str | None,
        unconverted_ancestors: tuple[str, ...],
    ) -> None:
        names = ", ".join(repr(name) for name in unconverted_ancestors)
        extends = repr(script_parent_name) if script_parent_name is not None else "no object script"
        message = (
            f"Warning: GameMaker object {object_name!r} extends {extends} because its ancestor "
            f"{names} produced no script; the events and Variable Definitions of "
            f"{names} do not run for {object_name!r}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-OBJECT-PARENT-NOT-CONVERTED",
                message,
                source_path=self._diagnostic_source_path(object_source_path),
                resource=object_name,
                resource_type="object",
                workaround=(
                    f"Fix the conversion problem reported for {names}, then convert again."
                ),
            )
        self._safe_log(message)

    def _parent_object_chain(
        self,
        object_name: str,
        object_source_path: str | None = None,
        seen: set[str] | None = None,
        parsed_object: ParsedObject | None = None,
    ) -> tuple[str, ...]:
        seen = set(seen or set())
        if object_name in seen:
            return ()
        seen.add(object_name)

        parsed = parsed_object or self._parse_object_yy(object_name, object_source_path)
        if parsed is None or parsed["parent_object_name"] is None:
            return ()

        parent_name = parsed["parent_object_name"]
        return (
            parent_name,
            *self._parent_object_chain(
                parent_name,
                parsed["parent_object_source_path"],
                seen,
            ),
        )

    def _ancestor_member_names(
        self,
        parent_object_name: str,
        parent_object_source_path: str | None,
        project_script_instance_variables: set[str] | None,
        macro_values: Mapping[str, str] | None,
    ) -> frozenset[str] | None:
        """Return every name an object's ancestor scripts may declare as a member.

        An ancestor script declares the instance variables its events assign
        (the root object the project scripts' ones too), and each of them
        appears in the ancestor's event code, in a project macro or among the
        script variables: a name found in none of them is free for the
        object's own script. Returns None when an ancestor cannot be read.
        """
        names: set[str] = set(project_script_instance_variables or ())
        for macro_value in (macro_values or {}).values():
            names.update(_GML_IDENTIFIER_RE.findall(str(macro_value)))
        seen: set[str] = set()
        object_name: str | None = parent_object_name
        source_path = parent_object_source_path
        while object_name is not None:
            if object_name in seen:
                return None
            seen.add(object_name)
            parsed = self._parse_object_yy(object_name, source_path)
            if parsed is None:
                return None
            # An ancestor without a script declares nothing.
            if self._object_has_script(object_name) and not self._add_object_member_names(
                names,
                object_name,
                parsed,
            ):
                return None
            object_name = parsed["parent_object_name"]
            source_path = parsed["parent_object_source_path"]
        return frozenset(names)

    def _add_object_member_names(
        self,
        names: set[str],
        object_name: str,
        parsed: ParsedObject,
    ) -> bool:
        """Add the names one ancestor's script may declare; False if its code is unreadable."""
        names.update(
            variable_definition_identifiers(
                parsed["variable_definitions"],
                parsed["variable_overrides"],
            )
        )
        for event in parsed["event_list"]:
            mapping = map_input_event(event) if is_input_event(event) else map_event(event)
            if mapping is None or not mapping.gml_filename:
                continue
            event_source_path = self._event_source_path(
                parsed["source_path"],
                object_name,
                mapping,
            )
            if event_source_path is None:
                if event.get("isDnD") is True:
                    continue
                return False
            try:
                with open(event_source_path, "r", encoding="utf-8") as f:
                    names.update(_GML_IDENTIFIER_RE.findall(f.read()))
            except (OSError, UnicodeDecodeError):
                return False
        return True

    def _object_inherits_sprite_runtime(
        self,
        object_name: str | None,
        object_source_path: str | None = None,
    ) -> bool:
        # Every converted object script declares the sprite runtime (every
        # GameMaker instance has sprite_index and the image_* variables), so
        # a child inherits it from any parent that converts.
        if object_name is None:
            return False
        return self._parse_object_yy(object_name, object_source_path) is not None

    def _process_object(
        self,
        object_name: str,
        subfolder: str = "",
        sprite_scene_paths: Mapping[str, str] | None = None,
        asset_names: set[str] | None = None,
        project_script_instance_variables: set[str] | None = None,
        enum_values: Mapping[str, Mapping[str, int]] | None = None,
        macro_values: Mapping[str, str] | None = None,
        object_source_path: str | None = None,
    ) -> ObjectProcessResult | None:
        """Process a single object: parse .yy, generate scene and script, write files.

        Returns a result dict or None if conversion was stopped.
        """
        if not self.conversion_running():
            return None

        parsed = self._parse_object_yy(object_name, object_source_path)
        if parsed is None:
            return {
                "status": "failed",
                "name": object_name,
                "has_sprite": False,
                "sprite_name": None,
                "event_count": 0,
            }

        sprite_name = parsed["sprite_name"]
        sprite_source_path = parsed["sprite_source_path"]
        # The scripts extend the nearest ancestor that has one: a skipped
        # object leaves none, and its descendants must still load.
        (
            parent_object_name,
            parent_object_source_path,
            unconverted_ancestors,
        ) = self._script_parent(parsed["parent_object_name"], parsed["parent_object_source_path"])
        if unconverted_ancestors:
            self._report_unconverted_ancestors(
                object_name,
                parsed["source_path"],
                parent_object_name,
                unconverted_ancestors,
            )
        event_list = parsed["event_list"]
        solid = bool(parsed.get("solid", False))
        persistent = bool(parsed.get("persistent", False))
        sprite_scene_path: str | None = None
        parent_script_res_path = None
        inherited_event_functions: set[str] = set()

        if parent_object_name is not None and parent_object_name != object_name:
            parent_subfolder = self._get_object_subfolder(
                parent_object_name,
                parent_object_source_path,
            )
            parent_script_res_path = self._object_script_res_path(parent_object_name, parent_subfolder)
            inherited_event_functions = self._parent_event_function_names(
                parent_object_name,
                parent_object_source_path,
            )
        inherited_sprite_runtime = self._object_inherits_sprite_runtime(
            parent_object_name,
            parent_object_source_path,
        )
        local_event_functions = self._event_function_names(event_list)

        if sprite_name is not None and sprite_source_path is not None:
            sprite_scene_path = (sprite_scene_paths or {}).get(sprite_name)
            if sprite_scene_path is None:
                sprite_subfolder = self._get_sprite_subfolder(
                    sprite_source_path,
                    owner_source_path=parsed["source_path"],
                    object_name=object_name,
                )
                if self._sprite_scene_exists(sprite_name, sprite_subfolder):
                    sprite_scene_path = self._asset_output_paths.get("sprites", {}).get(
                        sprite_name,
                        generated_nested_resource_path(
                            "sprites", sprite_subfolder, sprite_name, ".tscn"
                        ),
                    )
            if sprite_scene_path is None:
                self._safe_log(get_localized("Console_Convertor_Objects_SpriteNotFound").format(
                    object_name=object_name, sprite_name=sprite_name))
                sprite_name = None

        scene_res_path = self._object_scene_res_path(object_name, subfolder)
        tscn_path = resource_filesystem_path(self.godot_project_path, scene_res_path)
        object_dir = os.path.dirname(tscn_path)
        script_res_path = self._object_script_res_path(object_name, subfolder)

        # Names a child object's ancestors may declare as members; null for a
        # root object, and for a child whose ancestors cannot all be read
        # (it then declares none of its own).
        inherited_member_names: frozenset[str] | None = None
        if parent_object_name is not None:
            ancestor_names = self._ancestor_member_names(
                parent_object_name,
                parent_object_source_path,
                project_script_instance_variables,
                macro_values,
            )
            if ancestor_names is not None:
                inherited_member_names = ancestor_names | frozenset(asset_names or ())
        variable_definitions, runs_variable_definitions = self._object_variable_definitions(
            object_name,
            parsed,
        )
        (
            code_bodies,
            instance_variables,
            event_source_maps,
            has_event_blocker,
        ) = self._load_event_code_bodies(
            object_name,
            parsed["source_path"],
            event_list,
            inherited_event_functions=inherited_event_functions,
            asset_names=asset_names,
            project_script_instance_variables=(
                project_script_instance_variables
                if parent_object_name is None
                else None
            ),
            direct_instance_variables=(
                set()
                if parent_object_name is not None and inherited_member_names is None
                else None
            ),
            direct_reference_names=set(sprite_scene_paths or {}),
            enum_values=enum_values,
            macro_values=macro_values,
            inherited_member_names=inherited_member_names,
            variable_definitions=variable_definitions,
        )
        binds_event_functions = any(
            key.startswith(EVENT_FUNCTIONS_KEY_PREFIX) for key in code_bodies
        )
        inherits_event_functions = parent_object_name is not None and (
            self._ancestors_declare_event_functions(
                parent_object_name,
                parent_object_source_path,
            )
        )
        if has_event_blocker:
            # An object is one logical resource. Publishing a script with only
            # the events with available, readable, supported GML would make the
            # generated scene look complete while silently dropping behavior.
            return {
                "status": "skipped",
                "name": object_name,
                "has_sprite": sprite_name is not None,
                "sprite_name": sprite_name,
                "event_count": len(event_list),
            }

        script_content = generate_script_content(
            event_list,
            code_bodies=code_bodies,
            instance_variables=(
                instance_variables
                if parent_object_name is None
                else set()
                if inherited_member_names is None
                else instance_variables - inherited_member_names
            ),
            sprite_runtime=SpriteRuntimeConfig(
                initial_sprite_name=sprite_name,
                sprite_scene_paths=sprite_scene_paths,
                inherit_runtime=inherited_sprite_runtime,
            ),
            object_runtime=ObjectRuntimeConfig(
                object_name=object_name,
                parent_object_names=self._parent_object_chain(
                    object_name,
                    parsed["source_path"],
                    parsed_object=parsed,
                ),
                solid=solid,
                persistent=persistent,
                mask_sprite_name=parsed["mask_sprite_name"],
                inherit_ready="_ready" in inherited_event_functions and "_ready" not in local_event_functions,
                inherited_input_functions=self._inherited_input_functions(
                    parent_object_name,
                    parent_object_source_path,
                ),
                runs_variable_definitions=runs_variable_definitions,
                binds_event_functions=binds_event_functions or inherits_event_functions,
                inherits_event_functions=inherits_event_functions,
            ),
            base_script_path=parent_script_res_path,
        )
        scene_content = self._generate_object_scene(
            object_name,
            sprite_name,
            sprite_scene_path,
            script_res_path,
        )

        os.makedirs(object_dir, exist_ok=True)

        with open(tscn_path, 'w', encoding='utf-8') as f:
            f.write(scene_content)

        gd_path = resource_filesystem_path(self.godot_project_path, script_res_path)
        with open(gd_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        self._write_object_source_map(gd_path, script_content, code_bodies, event_source_maps)

        return {
            "status": "completed",
            "name": object_name,
            "has_sprite": sprite_name is not None,
            "sprite_name": sprite_name,
            "event_count": len(event_list),
        }

    def _process_requested_object(
        self,
        object_name: str,
        subfolder: str = "",
        sprite_scene_paths: Mapping[str, str] | None = None,
        asset_names: set[str] | None = None,
        project_script_instance_variables: set[str] | None = None,
        enum_values: Mapping[str, Mapping[str, int]] | None = None,
        macro_values: Mapping[str, str] | None = None,
        object_source_path: str | None = None,
    ) -> ObjectProcessResult | None:
        """Process one requested object while preserving cancellation state."""
        if not self.conversion_running():
            return None
        self._resource_started(object_name)
        return self._process_object(
            object_name,
            subfolder,
            sprite_scene_paths,
            asset_names,
            project_script_instance_variables,
            enum_values,
            macro_values,
            object_source_path,
        )

    def _write_object_source_map(
        self,
        gd_path: str,
        script_content: str,
        code_bodies: Mapping[str, str],
        source_maps: Mapping[str, GMLSourceMap],
    ) -> None:
        offset_maps: list[GMLSourceMap] = []
        for event_name, source_map in source_maps.items():
            body = code_bodies.get(event_name)
            if not body:
                continue
            offset = _line_offset_for_block(script_content, body)
            offset_maps.append(source_map.with_generated_line_offset(offset))
        if offset_maps:
            write_gml_source_map(gd_path, merge_gml_source_maps(offset_maps))

    def _plan_object_waves(self, object_names: Sequence[str]) -> tuple[list[list[str]], set[str]]:
        """Group objects by ancestor depth; also return the parents that are no object.

        Every object follows its ancestors, so a wave only needs the results
        of the waves before it. Objects of one wave convert in parallel.
        """
        known = set(object_names)
        parent_of: dict[str, str | None] = {}
        unknown_parents: set[str] = set()
        for name in object_names:
            try:
                parsed = self._parse_object_yy(name, self._object_source_paths.get(name))
            except Exception:
                # Converting the object reports what is wrong with it.
                parsed = None
            parent = parsed["parent_object_name"] if parsed is not None else None
            if parent is not None and parent not in known:
                unknown_parents.add(parent)
                parent = None
            parent_of[name] = parent
        waves: dict[int, list[str]] = {}
        for name in object_names:
            depth = 0
            seen = {name}
            ancestor = parent_of[name]
            while ancestor is not None and ancestor not in seen:
                seen.add(ancestor)
                depth += 1
                ancestor = parent_of[ancestor]
            waves.setdefault(depth, []).append(name)
        return [waves[depth] for depth in sorted(waves)], unknown_parents

    def _run_object_wave(
        self,
        executor: ThreadPoolExecutor,
        names: Sequence[str],
        context: _ObjectConversionContext,
        state: _ObjectRunState,
    ) -> None:
        futures_map = {
            executor.submit(
                self._process_requested_object,
                name,
                context.subfolders.get(name, ""),
                context.sprite_scene_paths,
                context.asset_names,
                context.project_script_instance_variables,
                context.enum_values,
                context.macro_values,
                self._object_source_paths.get(name),
            ): name
            for name in names
        }
        for future in as_completed(futures_map):
            self._record_object_result(futures_map[future], future, state)

    def _record_object_result(
        self,
        object_name: str,
        future: Future[ObjectProcessResult | None],
        state: _ObjectRunState,
    ) -> None:
        try:
            result = future.result()
        except Exception as error:
            state.failed.add(object_name)
            if state.first_error is None:
                state.first_error = error
            return
        if result is None:
            state.cancelled = True
            return

        state.processed += 1
        if result["status"] == "completed":
            state.completed.add(object_name)
            self._log_converted_object(result, state)
        elif result["status"] == "skipped":
            state.skipped.add(object_name)
        else:
            state.failed.add(object_name)
        self._safe_progress(state.processed / state.total * 100)

    def _log_converted_object(self, result: ObjectProcessResult, state: _ObjectRunState) -> None:
        if self.compact_logging:
            self._safe_log_progress(result["name"], state.processed, state.total)
        elif result["has_sprite"]:
            self._safe_log(get_localized("Console_Convertor_Objects_ConvertedWithSprite").format(
                object_name=result["name"], sprite_name=result["sprite_name"],
                event_count=result["event_count"]))
        else:
            self._safe_log(get_localized("Console_Convertor_Objects_Converted").format(
                object_name=result["name"], event_count=result["event_count"]))

    def convert_objects(self) -> None:
        os.makedirs(self.godot_objects_path, exist_ok=True)

        manifest_plan = self._plan_manifest_objects()
        gm_objects_path = os.path.join(self.gm_project_path, 'objects')
        object_names: list[str] = []
        object_subfolders: dict[str, str] = {}
        requested_names: list[str] = []
        skipped_names: list[str] = []
        if manifest_plan is not None:
            requested_names.extend(manifest_plan.requested_names)
            skipped_names.extend(manifest_plan.skipped_names)
            object_names.extend(manifest_plan.available_subfolders)
            object_subfolders.update(manifest_plan.available_subfolders)
        else:
            resolved_objects_root = self._resolve_discovered_project_source(
                gm_objects_path,
                resource_type="object",
                field="objectsDirectory",
            )
            if (
                resolved_objects_root is None
                or not os.path.isdir(resolved_objects_root.filesystem_path)
            ):
                self.log_callback(
                    get_localized("Console_Convertor_Objects_Error_NotFound")
                )
                return
            for name in os.listdir(resolved_objects_root.filesystem_path):
                object_directory = self._resolve_discovered_project_source(
                    os.path.join(resolved_objects_root.filesystem_path, name),
                    resource=name,
                    resource_type="object",
                    field="objectDirectory",
                )
                if (
                    object_directory is None
                    or not os.path.isdir(object_directory.filesystem_path)
                ):
                    continue
                yy_source = self._resolve_discovered_project_source(
                    os.path.join(object_directory.filesystem_path, name + ".yy"),
                    owner_source_path=object_directory.source_path,
                    resource=name,
                    resource_type="object",
                    field="object.yy",
                )
                if (
                    yy_source is None
                    or not self._source_has_resource_kind(
                        yy_source,
                        "objects",
                        rejected_path=os.path.join(
                            object_directory.filesystem_path,
                            name + ".yy",
                        ),
                        owner_source_path=object_directory.source_path,
                        resource=name,
                        field="object.yy",
                    )
                    or not os.path.isfile(yy_source.filesystem_path)
                ):
                    continue
                self._object_source_paths[name] = yy_source.source_path
                object_names.append(name)
                object_subfolders[name] = self._get_subfolder_from_yy(
                    yy_source.filesystem_path
                )
            requested_names.extend(object_names)

        for object_name in requested_names:
            self._resource_requested(object_name)
        for object_name in skipped_names:
            self._resource_skipped(object_name)

        if not object_names:
            self.log_callback(get_localized("Console_Convertor_Objects_Complete"))
            return

        write_gml_runtime(self.godot_project_path)

        total = len(object_names)
        self._asset_output_paths = build_asset_output_paths(
            self.gm_project_path,
            self.godot_project_path,
            conversion_running=self.conversion_running,
        )
        sprite_scene_paths = self._get_available_sprite_scene_paths()
        asset_names = self._get_project_asset_names()
        context = _ObjectConversionContext(
            subfolders=object_subfolders,
            sprite_scene_paths=sprite_scene_paths,
            asset_names=asset_names,
            project_script_instance_variables=self._get_project_script_instance_variables(asset_names),
            enum_values=self._get_project_enum_values(),
            macro_values=self._get_project_macro_values(),
        )
        state = _ObjectRunState(total=total)

        # Whether an ancestor gets a script decides what a descendant's script
        # extends, so the objects convert in waves of equal ancestor depth.
        waves, unknown_parents = self._plan_object_waves(object_names)
        self._objects_without_script = set(unknown_parents)
        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                for wave in waves:
                    self._run_object_wave(executor, wave, context, state)
                    self._objects_without_script |= state.skipped | state.failed
        finally:
            self._objects_without_script = None

        completed_objects, skipped_objects, failed_objects = state.completed, state.skipped, state.failed
        cancelled, first_error = state.cancelled, state.first_error
        for object_name in sorted(completed_objects):
            self._resource_completed(object_name)
        for object_name in sorted(skipped_objects):
            self._resource_skipped(object_name)
        for object_name in sorted(failed_objects):
            self._resource_failed(object_name)

        if first_error is not None:
            raise first_error
        if cancelled:
            self.log_callback(get_localized("Console_Convertor_Objects_Stopped"))
            return

        self.log_callback(get_localized("Console_Convertor_Objects_Complete"))

    def convert_all(self) -> None:
        self._reset_resource_outcomes()
        self.convert_objects()
