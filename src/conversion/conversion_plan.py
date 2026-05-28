from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Sequence


ConversionGroup = Literal["project", "assets", "wip"]


@dataclass(frozen=True)
class ConversionStep:
    """One conversion action and its dependency metadata."""

    key: str
    group: ConversionGroup
    log_key: str
    dependencies: tuple[str, ...] = field(default_factory=tuple)


CONVERSION_STEPS: tuple[ConversionStep, ...] = (
    ConversionStep("game_icon", "project", "Console_Convertor_Icon"),
    ConversionStep("project_name", "project", "Console_Convertor_Name"),
    ConversionStep("project_settings", "project", "Console_Convertor_Settings", ("project_name",)),
    ConversionStep("audio_buses", "project", "Console_Convertor_AudioBus", ("project_settings",)),
    ConversionStep("sprites", "assets", "Console_Convertor_Sprites"),
    ConversionStep("fonts", "assets", "Console_Convertor_Fonts"),
    ConversionStep("tilesets", "wip", "Console_Convertor_Tilesets", ("sprites",)),
    ConversionStep("sounds", "assets", "Console_Convertor_Sounds"),
    ConversionStep("notes", "project", "Console_Convertor_Notes"),
    ConversionStep("shaders", "wip", "Console_Convertor_Shaders"),
    ConversionStep("included_files", "assets", "Console_Convertor_IncludedFiles"),
    ConversionStep("scripts", "assets", "Console_Convertor_Scripts", ("included_files",)),
    ConversionStep("objects", "assets", "Console_Convertor_Objects", ("sprites", "scripts")),
    ConversionStep("rooms", "assets", "Console_Convertor_Rooms", ("objects", "tilesets", "scripts")),
    ConversionStep(
        "asset_registry",
        "assets",
        "Console_Convertor_AssetRegistry",
        (
            "sprites",
            "fonts",
            "tilesets",
            "sounds",
            "shaders",
            "included_files",
            "scripts",
            "objects",
            "rooms",
        ),
    ),
)


def conversion_step_map(
    steps: Sequence[ConversionStep] = CONVERSION_STEPS,
) -> dict[str, ConversionStep]:
    return {step.key: step for step in steps}


def validate_conversion_step_graph(
    steps: Sequence[ConversionStep] = CONVERSION_STEPS,
) -> tuple[str, ...]:
    """Return dependency graph validation errors without raising."""
    step_by_key = conversion_step_map(steps)
    errors: list[str] = []
    if len(step_by_key) != len(steps):
        errors.append("Conversion step keys must be unique.")
    for step in steps:
        for dependency in step.dependencies:
            if dependency not in step_by_key:
                errors.append(f"Conversion step {step.key!r} depends on unknown step {dependency!r}.")
    try:
        build_conversion_plan((step.key for step in steps), steps=steps)
    except ValueError as exc:
        errors.append(str(exc))
    return tuple(errors)


def build_conversion_plan(
    enabled_keys: Iterable[str],
    *,
    steps: Sequence[ConversionStep] = CONVERSION_STEPS,
) -> tuple[ConversionStep, ...]:
    """Return enabled conversion steps in dependency order.

    Dependencies only order steps that are already enabled. The planner does not
    auto-enable dependencies because UI settings still control the conversion
    surface.
    """
    step_by_key = conversion_step_map(steps)
    enabled = {key for key in enabled_keys if key in step_by_key}
    ordered: list[ConversionStep] = []
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(key: str) -> None:
        if key in permanent:
            return
        if key in temporary:
            cycle = " -> ".join([*temporary, key])
            raise ValueError(f"Conversion dependency cycle detected: {cycle}")
        temporary.add(key)
        step = step_by_key[key]
        for dependency in step.dependencies:
            if dependency in enabled:
                visit(dependency)
        temporary.remove(key)
        permanent.add(key)
        ordered.append(step)

    for step in steps:
        if step.key in enabled:
            visit(step.key)

    return tuple(ordered)


def group_conversion_plan(plan: Iterable[ConversionStep]) -> dict[ConversionGroup, tuple[ConversionStep, ...]]:
    grouped: dict[ConversionGroup, list[ConversionStep]] = {
        "project": [],
        "assets": [],
        "wip": [],
    }
    for step in plan:
        grouped[step.group].append(step)
    return {
        group: tuple(group_steps)
        for group, group_steps in grouped.items()
        if group_steps
    }
