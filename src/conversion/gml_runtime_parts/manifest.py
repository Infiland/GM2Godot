from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Pattern, TypeAlias

RuntimeSymbolKind: TypeAlias = Literal["class", "const", "static_func", "static_var"]

RUNTIME_SEGMENT_DIR = Path(__file__).with_name("segments")
RUNTIME_SEGMENT_MODULE_PREFIX = "src.conversion.gml_runtime_parts.segments."


@dataclass(frozen=True)
class RuntimeSegmentDefinition:
    file_name: str
    description: str
    depends_on: tuple[str, ...] = ()
    test_modules: tuple[str, ...] = ()

    @property
    def module_name(self) -> str:
        return f"{RUNTIME_SEGMENT_MODULE_PREFIX}{self.file_name.removesuffix('.gd')}"

    @property
    def path(self) -> Path:
        return RUNTIME_SEGMENT_DIR / self.file_name


@dataclass(frozen=True)
class RuntimeProvidedSymbol:
    name: str
    kind: RuntimeSymbolKind
    segment_name: str
    line: int


@dataclass(frozen=True)
class RuntimeAPIIndexEntry:
    api_name: str
    category: str
    status: str
    runtime_support: str
    smoke_coverage: str
    docs_url: str
    issue_number: int
    owner_module: str
    segment_name: str | None
    segment_path: str | None
    runtime_symbol: str | None
    test_modules: tuple[str, ...]


def _segment(
    file_name: str,
    description: str,
    *,
    depends_on: tuple[str, ...] = (),
    tests: tuple[str, ...] = (),
) -> RuntimeSegmentDefinition:
    return RuntimeSegmentDefinition(
        file_name=file_name,
        description=description,
        depends_on=depends_on,
        test_modules=tests,
    )


RUNTIME_SEGMENTS: tuple[RuntimeSegmentDefinition, ...] = (
    _segment(
        "00_prelude.gd",
        "Core GML value classes, constants, and primitive type predicates.",
        tests=("tests/test_gml_runtime.py",),
    ),
    _segment(
        "15_asset_registry.gd",
        "Asset lookup, legacy ids, dynamic asset registration, and asset tags.",
        depends_on=("00_prelude.gd",),
        tests=("tests/test_asset_registry.py", "tests/test_gml_runtime.py"),
    ),
    _segment(
        "10_handles_and_instances.gd",
        "Generic handles, instance registry, selectors, and built-in globals.",
        depends_on=("00_prelude.gd",),
        tests=("tests/test_gml_runtime.py", "tests/test_instance_registry_godot.py"),
    ),
    _segment(
        "11_layers.gd",
        "Layer and layer-element handles backed by Godot scene nodes.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd"),
        tests=("tests/test_layers_runtime_godot.py",),
    ),
    _segment(
        "20_methods_and_exceptions.gd",
        "Method binding, script calling, exceptions, and unsupported-call helpers.",
        depends_on=("00_prelude.gd",),
        tests=("tests/test_gml_runtime.py",),
    ),
    _segment(
        "30_numeric_arithmetic.gd",
        "GML arithmetic, comparison, nullish, and boolean operators.",
        depends_on=("00_prelude.gd",),
        tests=("tests/test_gml_runtime.py",),
    ),
    _segment(
        "35_maths_numbers.gd",
        "Math, number conversion, random, and geometry helpers.",
        depends_on=("00_prelude.gd", "30_numeric_arithmetic.gd"),
        tests=("tests/test_gml_runtime.py", "tests/test_math_random_godot.py"),
    ),
    _segment(
        "40_arrays_structs_variables.gd",
        "Array, struct, static, dynamic variable, and selector access helpers.",
        depends_on=(
            "00_prelude.gd",
            "10_handles_and_instances.gd",
            "20_methods_and_exceptions.gd",
            "30_numeric_arithmetic.gd",
        ),
        tests=("tests/test_gml_runtime.py", "tests/test_objects.py"),
    ),
    _segment(
        "45_collision_queries.gd",
        "Instance collision query helpers and DS-list collision result writers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "40_arrays_structs_variables.gd"),
        tests=("tests/test_collision_queries_godot.py",),
    ),
    _segment(
        "46_motion_helpers.gd",
        "Motion, direction, friction, and wrapping helpers.",
        depends_on=("00_prelude.gd", "30_numeric_arithmetic.gd", "35_maths_numbers.gd"),
        tests=("tests/test_motion_helpers_godot.py",),
    ),
    _segment(
        "47_paths_motion_planning.gd",
        "Path asset state, path following, and route planning helpers.",
        depends_on=("00_prelude.gd", "35_maths_numbers.gd", "46_motion_helpers.gd"),
        tests=("tests/test_paths_motion_godot.py",),
    ),
    _segment(
        "48_drawing_basic_forms.gd",
        "Draw state, primitive drawing, sprite, text, texture, and video helpers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "15_asset_registry.gd"),
        tests=("tests/test_draw_basic_godot.py", "tests/test_draw_sprite_text_godot.py"),
    ),
    _segment(
        "49_drawing_surfaces.gd",
        "Surface handles, application surface state, and surface draw targets.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "48_drawing_basic_forms.gd"),
        tests=("tests/test_draw_surfaces_godot.py",),
    ),
    _segment(
        "51_particles.gd",
        "Particle system, type, emitter, and built-in effect helpers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "48_drawing_basic_forms.gd"),
        tests=("tests/test_particles_runtime_godot.py",),
    ),
    _segment(
        "52_cameras_display.gd",
        "Camera, view, window, display, cursor, and GUI metric helpers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd"),
        tests=("tests/test_cameras_display_godot.py",),
    ),
    _segment(
        "53_game_input.gd",
        "Keyboard, mouse, gamepad, gesture, and virtual-keyboard helpers.",
        depends_on=("00_prelude.gd",),
        tests=("tests/test_game_input_godot.py",),
    ),
    _segment(
        "54_audio_runtime.gd",
        "Audio bus, emitter, listener, sync-group, and playback helpers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "15_asset_registry.gd"),
        tests=("tests/test_audio_runtime_godot.py",),
    ),
    _segment(
        "55_room_game_flow.gd",
        "Room order, game flow, transitions, and restart/end behavior.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "11_layers.gd", "15_asset_registry.gd"),
        tests=("tests/test_room_game_flow_godot.py",),
    ),
    _segment(
        "56_time_alarms.gd",
        "Date, time, delta-time, and alarm helpers.",
        depends_on=("00_prelude.gd", "30_numeric_arithmetic.gd"),
        tests=("tests/test_time_alarms_godot.py",),
    ),
    _segment(
        "57_ds_lists_stacks_queues.gd",
        "List, stack, queue, and priority data structure handles with destroyed-handle guards.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd"),
        tests=("tests/test_ds_collections_godot.py",),
    ),
    _segment(
        "58_ds_maps.gd",
        "Map data structure handles, accessors, destroyed-handle guards, JSON bridges, and persistence.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "57_ds_lists_stacks_queues.gd"),
        tests=("tests/test_ds_collections_godot.py",),
    ),
    _segment(
        "59_ds_grids.gd",
        "Grid data structure handles, accessors, regions, math operations, and destroyed-handle guards.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd"),
        tests=("tests/test_ds_collections_godot.py",),
    ),
    _segment(
        "50_static_types_and_clone.gd",
        "Deep clone helpers, equality and ordering value semantics, and static type metadata.",
        depends_on=("00_prelude.gd", "20_methods_and_exceptions.gd", "40_arrays_structs_variables.gd"),
        tests=("tests/test_gml_runtime.py",),
    ),
    _segment(
        "60_conversion_helpers.gd",
        "String, real, integer, boolean, and cross-type conversion helpers.",
        depends_on=("00_prelude.gd", "50_static_types_and_clone.gd"),
        tests=("tests/test_gml_runtime.py",),
    ),
    _segment(
        "61_sequences_timelines.gd",
        "Sequence and timeline asset/runtime lifecycle helpers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "15_asset_registry.gd", "56_time_alarms.gd"),
        tests=("tests/test_sequences_timelines_godot.py",),
    ),
    _segment(
        "65_files_ini_json.gd",
        "Filesystem, text file, binary file, INI, and JSON helpers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "60_conversion_helpers.gd"),
        tests=("tests/test_files_ini_json_godot.py",),
    ),
    _segment(
        "66_buffers.gd",
        "Buffer handles, binary read/write, compression, hashing, and checksums.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "60_conversion_helpers.gd"),
        tests=("tests/test_buffers_godot.py",),
    ),
    _segment(
        "67_async_runtime.gd",
        "Async queue, async_load payload, HTTP request, and dispatch helpers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "66_buffers.gd"),
        tests=("tests/test_async_http_godot.py",),
    ),
    _segment(
        "68_networking.gd",
        "TCP/UDP socket handles and async networking payload helpers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "66_buffers.gd", "67_async_runtime.gd"),
        tests=("tests/test_networking_godot.py",),
    ),
    _segment(
        "69_physics.gd",
        "Physics world/body/fixture/joint compatibility helpers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd"),
        tests=("tests/test_physics_runtime_godot.py",),
    ),
    _segment(
        "70_handle_string_helpers.gd",
        "Handle parsing, Unicode codepoint string helpers, hashing, and value serialization helpers.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd", "60_conversion_helpers.gd"),
        tests=("tests/test_gml_runtime.py",),
    ),
    _segment(
        "71_flex_panels.gd",
        "Flex panel node registry, layout properties, and compatibility diagnostics.",
        depends_on=("00_prelude.gd", "10_handles_and_instances.gd"),
        tests=("tests/test_flex_panels_godot.py",),
    ),
    _segment(
        "72_os_debug_gc.gd",
        "OS, environment, clipboard, debug, weak-reference, and GC helpers.",
        depends_on=("00_prelude.gd", "20_methods_and_exceptions.gd", "60_conversion_helpers.gd"),
        tests=("tests/test_os_debug_gc_godot.py",),
    ),
    _segment(
        "73_platform_services.gd",
        "Platform service bridge hooks for Steam, achievements, media, and OS services.",
        depends_on=("00_prelude.gd", "67_async_runtime.gd", "72_os_debug_gc.gd"),
        tests=("tests/test_platform_services_godot.py",),
    ),
    _segment(
        "80_static_hash_clone_error.gd",
        "Late compatibility wrappers for static, hash, clone, and error helpers.",
        depends_on=("00_prelude.gd", "20_methods_and_exceptions.gd", "50_static_types_and_clone.gd", "60_conversion_helpers.gd"),
        tests=("tests/test_gml_runtime.py",),
    ),
)

_SEGMENT_BY_NAME = {segment.file_name: segment for segment in RUNTIME_SEGMENTS}
_SYMBOL_PATTERNS: tuple[tuple[RuntimeSymbolKind, Pattern[str]], ...] = (
    ("class", re.compile(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
    ("const", re.compile(r"^const\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
    ("static_var", re.compile(r"^static\s+var\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
    ("static_func", re.compile(r"^static\s+func\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
)


def runtime_segment_names() -> tuple[str, ...]:
    return tuple(segment.file_name for segment in RUNTIME_SEGMENTS)


def runtime_segment_for_owner_module(owner_module: str) -> RuntimeSegmentDefinition | None:
    if not owner_module.startswith(RUNTIME_SEGMENT_MODULE_PREFIX):
        return None
    segment_name = f"{owner_module.removeprefix(RUNTIME_SEGMENT_MODULE_PREFIX)}.gd"
    return _SEGMENT_BY_NAME.get(segment_name)


def iter_runtime_segment_symbols(
    segments: tuple[RuntimeSegmentDefinition, ...] = RUNTIME_SEGMENTS,
) -> tuple[RuntimeProvidedSymbol, ...]:
    symbols: list[RuntimeProvidedSymbol] = []
    for segment in segments:
        if not segment.path.is_file():
            continue
        for line_number, line in enumerate(segment.path.read_text(encoding="utf-8").splitlines(), start=1):
            for kind, pattern in _SYMBOL_PATTERNS:
                match = pattern.match(line)
                if match is not None:
                    symbols.append(
                        RuntimeProvidedSymbol(
                            name=match.group(1),
                            kind=kind,
                            segment_name=segment.file_name,
                            line=line_number,
                        )
                    )
                    break
    return tuple(symbols)


def runtime_symbol_index() -> dict[str, RuntimeProvidedSymbol]:
    return {symbol.name: symbol for symbol in iter_runtime_segment_symbols()}


def duplicate_runtime_symbols() -> dict[str, tuple[RuntimeProvidedSymbol, ...]]:
    symbols_by_name: dict[str, list[RuntimeProvidedSymbol]] = {}
    for symbol in iter_runtime_segment_symbols():
        symbols_by_name.setdefault(symbol.name, []).append(symbol)
    return {
        name: tuple(symbols)
        for name, symbols in sorted(symbols_by_name.items())
        if len(symbols) > 1
    }


def runtime_api_index() -> dict[str, RuntimeAPIIndexEntry]:
    from src.conversion.gml_transpiler_parts.gml_api_manifest import iter_gml_api_entries

    symbol_index = runtime_symbol_index()
    entries: dict[str, RuntimeAPIIndexEntry] = {}
    for api_entry in iter_gml_api_entries():
        segment = runtime_segment_for_owner_module(api_entry.owner_module)
        runtime_symbol = _runtime_symbol_for_api(api_entry.name, symbol_index)
        if segment is None and runtime_symbol is not None:
            segment = _SEGMENT_BY_NAME.get(runtime_symbol.segment_name)
        entries[api_entry.name] = RuntimeAPIIndexEntry(
            api_name=api_entry.name,
            category=api_entry.category,
            status=api_entry.status,
            runtime_support=api_entry.runtime_support,
            smoke_coverage=api_entry.smoke_coverage,
            docs_url=api_entry.docs_url,
            issue_number=api_entry.issue_number,
            owner_module=api_entry.owner_module,
            segment_name=segment.file_name if segment is not None else None,
            segment_path=str(segment.path) if segment is not None else None,
            runtime_symbol=runtime_symbol.name if runtime_symbol is not None else None,
            test_modules=segment.test_modules if segment is not None else (),
        )
    return entries


def validate_runtime_segment_files(
    segments: tuple[RuntimeSegmentDefinition, ...] = RUNTIME_SEGMENTS,
) -> tuple[str, ...]:
    declared_names = {segment.file_name for segment in segments}
    disk_names = {path.name for path in RUNTIME_SEGMENT_DIR.glob("*.gd")}
    errors: list[str] = []
    for file_name in sorted(declared_names - disk_names):
        errors.append(f"Runtime segment is declared but missing on disk: {file_name}")
    for file_name in sorted(disk_names - declared_names):
        errors.append(f"Runtime segment exists on disk but is not declared: {file_name}")
    return tuple(errors)


def validate_runtime_segment_dependencies(
    segments: tuple[RuntimeSegmentDefinition, ...] = RUNTIME_SEGMENTS,
) -> tuple[str, ...]:
    declared_names = [segment.file_name for segment in segments]
    declared_set = set(declared_names)
    seen: set[str] = set()
    errors: list[str] = []
    for segment in segments:
        if declared_names.count(segment.file_name) > 1:
            errors.append(f"Runtime segment is declared more than once: {segment.file_name}")
        for dependency in segment.depends_on:
            if dependency not in declared_set:
                errors.append(f"{segment.file_name} depends on unknown runtime segment {dependency}")
            elif dependency not in seen:
                errors.append(f"{segment.file_name} depends on {dependency}, which is ordered after it")
        seen.add(segment.file_name)
    return tuple(errors)


def validate_runtime_segments() -> tuple[str, ...]:
    errors: list[str] = []
    errors.extend(validate_runtime_segment_files())
    errors.extend(validate_runtime_segment_dependencies())
    for name, symbols in duplicate_runtime_symbols().items():
        locations = ", ".join(f"{symbol.segment_name}:{symbol.line}" for symbol in symbols)
        errors.append(f"Runtime symbol {name} is provided more than once: {locations}")
    return tuple(errors)


def assert_runtime_segments_valid() -> None:
    errors = validate_runtime_segments()
    if errors:
        raise RuntimeError("Invalid GML runtime segment manifest:\n" + "\n".join(errors))


def _runtime_symbol_for_api(
    api_name: str, symbol_index: dict[str, RuntimeProvidedSymbol]
) -> RuntimeProvidedSymbol | None:
    for candidate in (f"gml_{api_name}", api_name):
        symbol = symbol_index.get(candidate)
        if symbol is not None:
            return symbol
    return None
