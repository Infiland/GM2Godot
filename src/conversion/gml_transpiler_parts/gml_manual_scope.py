from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, TypeAlias

from src.conversion.gml_transpiler_parts.gml_api_manifest import (
    GMLAPISupportStatus,
    category_issue_numbers,
)

GMLManualDiagnosticPolicy: TypeAlias = Literal[
    "none",
    "compatibility_report",
    "source_diagnostic",
    "explicit_unsupported",
    "out_of_scope",
]


@dataclass(frozen=True)
class GMLManualScopeEntry:
    key: str
    title: str
    section: str
    status: GMLAPISupportStatus
    issue_number: int
    owner_area: str
    diagnostic_policy: GMLManualDiagnosticPolicy
    docs_url: str
    manifest_categories: tuple[str, ...]
    test_paths: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class GMLManualScopeCategoryReport:
    section: str
    implemented: int
    partial: int
    planned: int
    unsupported: int
    out_of_scope: int

    @property
    def total(self) -> int:
        return (
            self.implemented
            + self.partial
            + self.planned
            + self.unsupported
            + self.out_of_scope
        )


_GM_DOCS = "https://manual.gamemaker.io/monthly/en"


def _gm_docs(path: str) -> str:
    return f"{_GM_DOCS}/{path}"


def _entry(
    key: str,
    title: str,
    section: str,
    status: GMLAPISupportStatus,
    issue_number: int,
    owner_area: str,
    diagnostic_policy: GMLManualDiagnosticPolicy,
    docs_path: str,
    manifest_categories: tuple[str, ...],
    test_paths: tuple[str, ...] = (),
    notes: str = "",
) -> GMLManualScopeEntry:
    return GMLManualScopeEntry(
        key=key,
        title=title,
        section=section,
        status=status,
        issue_number=issue_number,
        owner_area=owner_area,
        diagnostic_policy=diagnostic_policy,
        docs_url=_gm_docs(docs_path),
        manifest_categories=manifest_categories,
        test_paths=test_paths,
        notes=notes,
    )


_OVERVIEW_DOCS = "GameMaker_Language/GML_Overview/GML_Overview.htm"

_MANUAL_SCOPE_ENTRIES: tuple[GMLManualScopeEntry, ...] = (
    _entry(
        "overview_basic_code_structure",
        "Basic Code Structure",
        "GML Code Overview",
        "partial",
        579,
        "compiler frontend",
        "source_diagnostic",
        _OVERVIEW_DOCS,
        ("Foundation", "Runtime Function Dispatch"),
        ("tests/test_gml_transpiler.py",),
        "Parsing and emission exist, but full source mapping is tracked by #579.",
    ),
    _entry(
        "overview_runtime_functions",
        "Runtime Functions",
        "GML Code Overview",
        "partial",
        578,
        "API manifest and function dispatch",
        "compatibility_report",
        _OVERVIEW_DOCS,
        ("Runtime Function Dispatch",),
        ("tests/test_gml_api_manifest.py",),
        "Runtime dispatch is broad but still split from the manifest source of truth.",
    ),
    _entry(
        "overview_variables_scope",
        "Variables And Variable Scope",
        "GML Code Overview",
        "partial",
        582,
        "scope analysis and runtime variables",
        "source_diagnostic",
        _OVERVIEW_DOCS,
        ("Foundation", "Cross-Instance Addressing"),
        ("tests/test_gml_transpiler.py",),
        "Lookup precedence is encoded for locals, globals, assets, builtins, statics, and scoped instance targets; unresolved dynamic lookup edge cases remain partial.",
    ),
    _entry(
        "overview_data_types",
        "Data Types",
        "GML Code Overview",
        "partial",
        581,
        "runtime value model",
        "compatibility_report",
        _OVERVIEW_DOCS,
        ("Foundation", "Maths and Numbers", "Strings"),
        ("tests/test_gml_runtime.py",),
        "Runtime helpers centralize truthiness, equality, ordering, NaN, infinity, undefined, and string conversion semantics; exact string and handle edge cases remain partial.",
    ),
    _entry(
        "overview_conditionals",
        "if / else and Conditional Operators",
        "GML Code Overview",
        "partial",
        581,
        "expression parser and runtime value model",
        "source_diagnostic",
        _OVERVIEW_DOCS,
        ("Foundation",),
        ("tests/test_gml_transpiler.py",),
        "Conditional expression output routes through runtime truthiness helpers; uncovered expression contexts remain partial.",
    ),
    _entry(
        "overview_cross_instance_addressing",
        "Addressing Variables In Other Instances",
        "GML Code Overview",
        "partial",
        582,
        "cross-instance addressing",
        "source_diagnostic",
        _OVERVIEW_DOCS,
        ("Cross-Instance Addressing", "Instances"),
        ("tests/test_gml_transpiler.py", "tests/test_instance_registry_godot.py"),
        "Selectors exist, but parent targeting and nested self/other parity remain open.",
    ),
    _entry(
        "overview_expressions_operators",
        "Expressions And Operators",
        "GML Code Overview",
        "partial",
        580,
        "expression parser and emitter",
        "source_diagnostic",
        _OVERVIEW_DOCS,
        ("Foundation", "Arrays", "Accessors"),
        ("tests/test_gml_transpiler.py",),
        "Mutation expressions and assignment result semantics are tracked by #580.",
    ),
    _entry(
        "overview_script_functions",
        "Script Functions And Variables",
        "GML Code Overview",
        "partial",
        584,
        "script/function lowering",
        "compatibility_report",
        _OVERVIEW_DOCS,
        ("Script Functions",),
        ("tests/test_scripts.py", "tests/test_script_runtime_godot.py"),
        "Script wrappers preserve callable identity for registry/global lookups; unsupported multi-function current-script assets emit migration diagnostics.",
    ),
    _entry(
        "overview_methods",
        "Method Variables",
        "GML Code Overview",
        "partial",
        584,
        "method binding runtime",
        "compatibility_report",
        _OVERVIEW_DOCS,
        ("Script Functions", "Foundation"),
        ("tests/test_gml_transpiler.py",),
        "Bound methods expose self/index helpers and compare identity by bound self plus method index.",
    ),
    _entry(
        "overview_statics_constructors",
        "Static Variables, Structs, Constructors, Arrays, Accessors",
        "GML Code Overview",
        "partial",
        584,
        "structs, constructors, statics, arrays, and accessors",
        "compatibility_report",
        _OVERVIEW_DOCS,
        ("Arrays", "Accessors", "Foundation", "Script Functions"),
        ("tests/test_gml_transpiler.py", "tests/test_gml_runtime.py"),
        "Constructor static chains, inherited statics, closure-backed function literals, and accessor edge cases have focused runtime coverage.",
    ),
    _entry(
        "language_control_flow",
        "Control Flow Statements",
        "GML Language Features",
        "partial",
        585,
        "statement parser and event inheritance",
        "source_diagnostic",
        "GameMaker_Language/GML_Overview/Language_Features.htm",
        ("Foundation",),
        ("tests/test_gml_transpiler.py", "tests/test_objects.py"),
        "Finally preserves abrupt control flow, switch continue targets outer loops, delete covers member/accessor targets, and event inheritance has generated callback coverage.",
    ),
    _entry(
        "language_preprocessor_macros",
        "Preprocessor, Macros, And Directives",
        "GML Language Features",
        "partial",
        586,
        "preprocessor",
        "source_diagnostic",
        "GameMaker_Language/GML_Overview/Preprocessor.htm",
        ("Preprocessor",),
        ("tests/test_gml_transpiler.py",),
        "Directive policy and full preprocessor expressions are tracked by #586.",
    ),
    _entry(
        "reference_variable_functions",
        "Variable Functions",
        "GML Reference: Variable And Array Functions",
        "partial",
        582,
        "runtime variable helpers",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Variable_Functions/Variable_Functions.htm",
        ("Foundation", "Cross-Instance Addressing"),
        ("tests/test_gml_runtime.py",),
        "Dynamic variable helpers are partial and should be cross-checked with manifest coverage.",
    ),
    _entry(
        "reference_array_functions",
        "Array Functions",
        "GML Reference: Variable And Array Functions",
        "partial",
        583,
        "array/accessor runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Variable_Functions/Array_Functions/Array_Functions.htm",
        ("Arrays", "Accessors"),
        ("tests/test_gml_runtime.py",),
        "Array helpers and nested accessor mutation caching exist; exact copy/reference behavior remains partial.",
    ),
    _entry(
        "reference_asset_management",
        "General Asset Management",
        "GML Reference: Asset Management",
        "partial",
        587,
        "project graph and asset registry",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Asset_Management.htm",
        ("Asset Management",),
        ("tests/test_asset_registry.py",),
        "Asset registry exists; full project graph, tags, configs, groups, and dynamic assets remain open.",
    ),
    _entry(
        "reference_animation_curves",
        "Animation Curves",
        "GML Reference: Asset Management",
        "planned",
        591,
        "animation curve converter",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Animation_Curves/Animation_Curves.htm",
        ("Asset Management", "Sequences and Timelines"),
        (),
        "Animation curve conversion is planned with paths, tilesets, tilemaps, and curves.",
    ),
    _entry(
        "reference_audio",
        "Audio And Sounds",
        "GML Reference: Asset Management",
        "partial",
        601,
        "audio converter and runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Audio/Audio.htm",
        ("Audio",),
        ("tests/test_audio_runtime_godot.py", "tests/test_sounds.py"),
        "Playback subset exists; emitters, listeners, groups, recording, sync groups, and async payloads remain open.",
    ),
    _entry(
        "reference_extensions",
        "Extensions",
        "GML Reference: Asset Management",
        "partial",
        593,
        "extension import and mappings",
        "explicit_unsupported",
        "GameMaker_Language/GML_Reference/Asset_Management/Extensions/Extensions.htm",
        ("Extensions", "Platform Services"),
        ("tests/test_gml_transpiler.py",),
        "Extension functions require mappings today; metadata and native/plugin stubs are tracked by #593.",
    ),
    _entry(
        "reference_fonts",
        "Fonts",
        "GML Reference: Asset Management",
        "partial",
        602,
        "font converter and text runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Fonts/Fonts.htm",
        ("Asset Management", "Drawing Sprites Text Fonts"),
        ("tests/test_fonts.py", "tests/test_draw_sprite_text_godot.py"),
        "Basic font conversion exists; glyph ranges, sprite fonts, SDF/MSDF, and exact text rendering remain open.",
    ),
    _entry(
        "reference_instances_objects",
        "Instances And Objects",
        "GML Reference: Asset Management",
        "partial",
        604,
        "object converter and instance runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Instances/Instances.htm",
        ("Instances", "Cross-Instance Addressing"),
        ("tests/test_objects.py", "tests/test_instance_registry_godot.py"),
        "Object and instance basics exist; lifecycle, activation, parent targeting, and dynamic APIs remain open.",
    ),
    _entry(
        "reference_particles",
        "Particle Systems",
        "GML Reference: Asset Management",
        "partial",
        592,
        "particle asset converter and runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Particle_Systems/Particle_Systems.htm",
        ("Particles GPU Effects",),
        ("tests/test_particles_runtime_godot.py",),
        "Runtime subset exists; authored particle assets and layer elements remain open.",
    ),
    _entry(
        "reference_paths",
        "Paths",
        "GML Reference: Asset Management",
        "partial",
        591,
        "path converter and runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Paths/Paths.htm",
        ("Paths and Motion Planning", "Motion Helpers"),
        ("tests/test_path_registry.py", "tests/test_paths_motion_godot.py"),
        "Registry and path-follow subset exist; real Path2D/Curve2D and exact interpolation remain open.",
    ),
    _entry(
        "reference_rooms_layers",
        "Rooms, Layers, Tilesets, And Tilemaps",
        "GML Reference: Asset Management",
        "partial",
        590,
        "room/layer/tilemap converters",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Rooms/Rooms.htm",
        ("Rooms and Layers", "Cameras and Display", "Asset Management"),
        ("tests/test_rooms.py", "tests/test_layers_runtime_godot.py", "tests/test_tilesets.py"),
        "Room/layer basics exist; dynamic elements, inheritance, views, filters, and full tile data remain open.",
    ),
    _entry(
        "reference_sequences_timelines",
        "Sequences And Timelines",
        "GML Reference: Asset Management",
        "partial",
        592,
        "sequence/timeline converter and runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Sequences/Sequences.htm",
        ("Sequences and Timelines",),
        ("tests/test_sequences_timelines_godot.py",),
        "Runtime compatibility subset exists; authored conversion and scheduler integration remain open.",
    ),
    _entry(
        "reference_shaders",
        "Shaders",
        "GML Reference: Asset Management",
        "partial",
        602,
        "shader converter and runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Shaders/Shaders.htm",
        ("Shaders",),
        ("tests/test_shaders.py", "tests/test_shader_runtime_godot.py"),
        "Basic source conversion exists; full GLSL ES to Godot shader translation remains open.",
    ),
    _entry(
        "reference_sprites_textures",
        "Sprites, Textures, And Texture Groups",
        "GML Reference: Asset Management",
        "partial",
        602,
        "sprite converter and texture runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asset_Management/Sprites/Sprites.htm",
        ("Sprites and Textures", "Drawing Sprites Text Fonts", "Particles GPU Effects"),
        ("tests/test_sprites.py", "tests/test_draw_sprite_text_godot.py"),
        "Sprite conversion is broad; dynamic sprite/texture APIs, skeletal, masks, and texture groups remain open.",
    ),
    _entry(
        "reference_game_control",
        "General Game Control",
        "GML Reference: General Game Control",
        "partial",
        604,
        "room/game flow runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/General_Game_Control/General_Game_Control.htm",
        ("General Game Control", "Time"),
        ("tests/test_room_game_flow_godot.py", "tests/test_time_alarms_godot.py"),
        "Room flow subset exists; lifecycle ordering, persistence, and full timing are tracked by #604/#595.",
    ),
    _entry(
        "reference_movement_collisions",
        "Movement, Collisions, And Motion Planning",
        "GML Reference: Movement And Collisions",
        "partial",
        605,
        "movement, collision, path, and physics runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Movement_And_Collisions/Movement_And_Collisions.htm",
        ("Movement and Collisions", "Motion Helpers", "Paths and Motion Planning"),
        ("tests/test_motion_helpers_godot.py", "tests/test_collision_queries_godot.py"),
        "Movement and query subsets exist; exact masks, parent matching, MP grids, and physics integration remain open.",
    ),
    _entry(
        "reference_drawing",
        "Drawing, GPU, Surfaces, Text, Particles, Textures, And Video",
        "GML Reference: Drawing",
        "partial",
        602,
        "draw, GPU, surface, sprite, and video runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Drawing/Drawing.htm",
        (
            "Drawing Basic Forms",
            "Drawing Sprites Text Fonts",
            "Drawing Surfaces",
            "Particles GPU Effects",
            "Shaders",
            "Sprites and Textures",
        ),
        ("tests/test_draw_basic_godot.py", "tests/test_draw_surfaces_godot.py", "tests/test_gpu_draw_state_godot.py"),
        "Many draw subsets exist; advanced GPU state, primitives, video, surfaces, and texture fidelity remain open.",
    ),
    _entry(
        "reference_cameras_display",
        "Cameras, Display, Window, Views, And GUI",
        "GML Reference: Cameras And Display",
        "partial",
        603,
        "camera/display runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Cameras_And_Display/Cameras_And_Display.htm",
        ("Cameras and Display",),
        ("tests/test_cameras_display_godot.py",),
        "Camera/display subset exists; multi-view, view surfaces, window APIs, and GUI edge cases remain open.",
    ),
    _entry(
        "reference_game_input",
        "Device, Gamepad, Gesture, Keyboard, Mouse, And Virtual Input",
        "GML Reference: Game Input",
        "partial",
        596,
        "input runtime and event dispatch",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Game_Input/Game_Input.htm",
        ("Game Input",),
        ("tests/test_game_input_godot.py", "tests/conversion/events/test_keyboard_events.py"),
        "Polling subset exists; event dispatch, gestures, touch, IME, and exact pressed/released timing remain open.",
    ),
    _entry(
        "reference_data_structures",
        "Data Structures",
        "GML Reference: Data Structures",
        "partial",
        600,
        "data structure runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Data_Structures/Data_Structures.htm",
        ("Data Structures Sequential", "Data Structures Maps", "Data Structures Grids", "Accessors"),
        ("tests/test_ds_collections_godot.py",),
        "Core DS operations exist; accessor reads/writes return undefined for missing or destroyed handles, while serialization, sorting, and handle reuse remain partial.",
    ),
    _entry(
        "reference_strings",
        "Strings",
        "GML Reference: Strings",
        "partial",
        581,
        "string runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Strings/Strings.htm",
        ("Strings",),
        ("tests/test_gml_runtime.py",),
        "String helpers use Godot Unicode codepoint operations; byte length, formatting, locale case mapping, and template interpolation remain partial.",
    ),
    _entry(
        "reference_maths_numbers",
        "Maths, Numbers, Date, Time, And Matrices",
        "GML Reference: Maths And Numbers",
        "partial",
        581,
        "maths and number runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Maths_And_Numbers/Maths_And_Numbers.htm",
        ("Maths and Numbers", "Time"),
        ("tests/test_math_random_godot.py", "tests/test_time_alarms_godot.py"),
        "Math/random subsets exist; determinism, date/time encoding, matrix APIs, and edge values remain open.",
    ),
    _entry(
        "reference_flex_time_sources",
        "Flex Panels And Time Sources",
        "GML Reference: Flex Panels And Time Sources",
        "partial",
        594,
        "flex panel and time source runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Flex_Panels/Flex_Panels.htm",
        ("Flex Panels", "Time"),
        ("tests/test_flex_panels_godot.py", "tests/test_time_alarms_godot.py"),
        "Runtime subsets exist; full Yoga-equivalent layout and time-source lifecycle remain open.",
    ),
    _entry(
        "reference_physics",
        "Physics",
        "GML Reference: Physics",
        "partial",
        605,
        "physics runtime and object fixture import",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Physics/Physics.htm",
        ("Physics", "Movement and Collisions"),
        ("tests/test_physics_runtime_godot.py",),
        "Physics subset exists; fixture import, world scale, collision filters, joints, particles, and callbacks remain open.",
    ),
    _entry(
        "reference_async_network_files_buffers",
        "Async, Networking, Web, Files, And Buffers",
        "GML Reference: Async, Networking, Web, Files, Buffers",
        "partial",
        600,
        "async, networking, files, and buffer runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/Asynchronous_Functions/Asynchronous_Functions.htm",
        ("Asynchronous Functions", "Networking", "Files INI JSON", "Buffers"),
        (
            "tests/test_async_http_godot.py",
            "tests/test_networking_godot.py",
            "tests/test_files_ini_json_godot.py",
            "tests/test_buffers_godot.py",
        ),
        "Core subsets exist; async payload lifecycles, web, binary fidelity, and full file/network APIs remain open.",
    ),
    _entry(
        "reference_platform_os_debug_gc",
        "Platform, OS, Debug, GC, Media, And Services",
        "GML Reference: Platform, OS, Debug, GC",
        "partial",
        606,
        "platform hooks and OS/debug runtime",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/OS_And_Compiler/OS_And_Compiler.htm",
        ("OS Compiler Debug GC", "OS and Device Media", "Platform Services"),
        ("tests/test_os_debug_gc_godot.py", "tests/test_platform_services_godot.py"),
        "Hook-backed subset exists; media/device APIs and SDK integrations remain open.",
    ),
    _entry(
        "generated_godot_architecture",
        "Generated Godot Architecture And Validation",
        "Generated Godot Architecture",
        "partial",
        607,
        "Godot project generation",
        "compatibility_report",
        "GameMaker_Language/GML_Reference/GML_Reference.htm",
        ("Full-Game Fixtures",),
        ("tests/test_project_godot.py", "tests/test_simple_topdown_conversion.py"),
        "Generated projects exist; deterministic paths/resources and headless validation are tracked by #607/#609.",
    ),
)

_MANUAL_SCOPE_ENTRY_BY_KEY = {entry.key: entry for entry in _MANUAL_SCOPE_ENTRIES}


def iter_gml_manual_scope_entries() -> Iterable[GMLManualScopeEntry]:
    return _MANUAL_SCOPE_ENTRIES


def get_gml_manual_scope_entry(key: str) -> GMLManualScopeEntry | None:
    return _MANUAL_SCOPE_ENTRY_BY_KEY.get(key)


def generate_gml_manual_scope_report() -> tuple[GMLManualScopeCategoryReport, ...]:
    section_order: list[str] = []
    entries_by_section: dict[str, list[GMLManualScopeEntry]] = {}
    for entry in _MANUAL_SCOPE_ENTRIES:
        if entry.section not in entries_by_section:
            section_order.append(entry.section)
            entries_by_section[entry.section] = []
        entries_by_section[entry.section].append(entry)

    reports: list[GMLManualScopeCategoryReport] = []
    for section in section_order:
        counts = _status_counts(entries_by_section[section])
        reports.append(
            GMLManualScopeCategoryReport(
                section=section,
                implemented=counts["implemented"],
                partial=counts["partial"],
                planned=counts["planned"],
                unsupported=counts["unsupported"],
                out_of_scope=counts["out_of_scope"],
            )
        )
    return tuple(reports)


def render_gml_manual_scope_markdown() -> str:
    lines = [
        "# GML Manual Scope Coverage",
        "",
        "| Manual category | Implemented | Partial | Planned | Unsupported | Out of scope | Total |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in generate_gml_manual_scope_report():
        lines.append(
            f"| {row.section} | {row.implemented} | {row.partial} | "
            f"{row.planned} | {row.unsupported} | {row.out_of_scope} | {row.total} |"
        )

    lines.extend(["", "## Entries"])
    current_section = ""
    for entry in _MANUAL_SCOPE_ENTRIES:
        if entry.section != current_section:
            current_section = entry.section
            lines.extend(["", f"### {current_section}"])
        tests = ", ".join(f"`{path}`" for path in entry.test_paths) or "No direct test path yet"
        manifest_categories = ", ".join(f"`{category}`" for category in entry.manifest_categories)
        lines.append(
            f"- **{entry.title}**: `{entry.status}`, issue #{entry.issue_number}, "
            f"owner `{entry.owner_area}`, diagnostics `{entry.diagnostic_policy}`, "
            f"manifest {manifest_categories}, tests {tests}. {entry.docs_url}"
        )
    return "\n".join(lines)


def validate_gml_manual_scope_against_manifest() -> tuple[str, ...]:
    problems: list[str] = []
    seen_keys: set[str] = set()
    manifest_categories = set(category_issue_numbers())
    covered_manifest_categories: set[str] = set()

    for entry in _MANUAL_SCOPE_ENTRIES:
        if entry.key in seen_keys:
            problems.append(f"Duplicate manual scope key: {entry.key}")
        seen_keys.add(entry.key)

        if not entry.docs_url.startswith(_GM_DOCS):
            problems.append(f"Manual scope entry {entry.key} has non-GameMaker docs URL")
        if not entry.owner_area:
            problems.append(f"Manual scope entry {entry.key} has no owner area")
        if not entry.manifest_categories:
            problems.append(f"Manual scope entry {entry.key} has no manifest categories")

        for category in entry.manifest_categories:
            if category not in manifest_categories:
                problems.append(
                    f"Manual scope entry {entry.key} references unknown manifest category {category}"
                )
            else:
                covered_manifest_categories.add(category)

    for category in sorted(manifest_categories - covered_manifest_categories):
        problems.append(f"Manifest category {category} has no manual scope entry")

    return tuple(problems)


def _status_counts(
    entries: Iterable[GMLManualScopeEntry],
) -> dict[GMLAPISupportStatus, int]:
    counts: dict[GMLAPISupportStatus, int] = {
        "implemented": 0,
        "partial": 0,
        "planned": 0,
        "unsupported": 0,
        "out_of_scope": 0,
    }
    for entry in entries:
        counts[entry.status] += 1
    return counts
