from __future__ import annotations

import json
import math
from collections.abc import Sized
from typing import cast

from src.conversion.type_defs import JsonDict


PARTICLE_DESCRIPTOR_FORMAT_VERSION = 1

PARTICLE_SHAPES = (
    "pixel",
    "disk",
    "square",
    "line",
    "star",
    "circle",
    "ring",
    "sphere",
    "flare",
    "spark",
    "explosion",
    "cloud",
    "smoke",
    "snow",
)
EMITTER_SHAPES = ("rectangle", "ellipse", "diamond", "line")
EMITTER_DISTRIBUTIONS = ("linear", "gaussian", "invgaussian")
UNSUPPORTED_PARTICLE_MODIFIERS = (
    "attractors",
    "destroyers",
    "deflectors",
    "changers",
)


def normalize_particle_system_asset(raw_data: JsonDict) -> JsonDict:
    """Return one deterministic runtime descriptor for a GameMaker asset."""

    raw_emitters = _dict_list(raw_data.get("emitters"))
    raw_types = _dict_list(
        raw_data.get("particleTypes")
        if isinstance(raw_data.get("particleTypes"), list)
        else raw_data.get("types")
    )

    types = [
        _normalize_particle_type(item, index, embedded_emitter=False)
        for index, item in enumerate(raw_types)
    ]
    emitters: list[JsonDict] = []
    modern_embedded_types = not raw_types
    for index, emitter in enumerate(raw_emitters):
        if modern_embedded_types:
            type_index = len(types)
            types.append(
                _normalize_particle_type(
                    emitter,
                    type_index,
                    embedded_emitter=True,
                )
            )
        else:
            type_index = _particle_type_index(emitter, index, len(types))
        emitters.append(_normalize_emitter(emitter, index, type_index))

    draw_order_value = _integer(raw_data.get("drawOrder"), 0)
    return {
        "descriptor_format_version": PARTICLE_DESCRIPTOR_FORMAT_VERSION,
        "name": _string(raw_data.get("name") or raw_data.get("%Name"), ""),
        "xorigin": _number(raw_data.get("xorigin"), 0.0),
        "yorigin": _number(raw_data.get("yorigin"), 0.0),
        "draw_order": "old_to_new" if draw_order_value == 0 else "new_to_old",
        "draw_order_value": draw_order_value,
        "types": types,
        "emitters": emitters,
        "unsupported_modifiers": list(
            particle_system_unsupported_modifier_fields(raw_data)
        ),
    }


def particle_system_unsupported_modifier_fields(raw_data: JsonDict) -> tuple[str, ...]:
    """Return authored legacy modifier categories that contain behavior."""

    return tuple(
        field
        for field in UNSUPPORTED_PARTICLE_MODIFIERS
        if _contains_authored_value(raw_data.get(field))
    )


def render_particle_system_resource(
    name: str,
    source_path: str,
    descriptor: JsonDict,
) -> str:
    """Render a loadable Godot Resource carrying the stable descriptor."""

    descriptor_literal = json.dumps(
        descriptor,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    return (
        "[gd_resource type=\"Resource\" format=3]\n\n"
        "[resource]\n"
        f"resource_name = {json.dumps(name)}\n"
        "metadata/gamemaker_resource_type = \"GMParticleSystem\"\n"
        f"metadata/gamemaker_source_path = {json.dumps(source_path)}\n"
        "metadata/gamemaker_particle_descriptor = "
        f"{descriptor_literal}\n"
    )


def _normalize_particle_type(
    raw_type: JsonDict,
    index: int,
    *,
    embedded_emitter: bool,
) -> JsonDict:
    name = _string(
        raw_type.get("name") or raw_type.get("%Name"),
        f"particle_type_{index}",
    )
    sprite_name = _reference_name(
        raw_type.get("spriteId")
        if raw_type.get("spriteId") is not None
        else raw_type.get("sprite")
    )
    texture_index = _integer(raw_type.get("texture"), 0)
    shape_value = None if embedded_emitter else raw_type.get("shape")
    if sprite_name:
        shape = _shape_name(shape_value, "pixel")
    elif shape_value is not None:
        shape = _shape_name(shape_value, "pixel")
    else:
        shape = _shape_name(texture_index, "pixel")

    colours, alphas = _particle_colours(raw_type)
    size_min = _number_alias(raw_type, ("sizeMin", "size_min", "size_xmin"), 1.0)
    size_max = _number_alias(raw_type, ("sizeMax", "size_max", "size_xmax"), size_min)
    size_increase = _number_alias(
        raw_type,
        ("sizeIncrease", "sizeIncr", "size_incr", "size_xincr"),
        0.0,
    )
    size_wiggle = _number_alias(
        raw_type,
        ("sizeWiggle", "size_wiggle", "size_xwiggle"),
        0.0,
    )
    life_min = max(
        1.0,
        _number_alias(
            raw_type,
            ("lifetimeMin", "lifeMin", "life_min"),
            1.0,
        ),
    )
    life_max = max(
        1.0,
        _number_alias(
            raw_type,
            ("lifetimeMax", "lifeMax", "life_max"),
            life_min,
        ),
    )
    return {
        "name": name,
        "shape": shape,
        "texture_index": texture_index,
        "sprite": sprite_name or None,
        "sprite_frame": _number_alias(
            raw_type,
            ("spriteFrame", "frame", "headPosition"),
            0.0,
        ),
        "sprite_animate": _boolean_alias(
            raw_type,
            ("spriteAnimate", "sprite_animate", "animate"),
            False,
        ),
        "sprite_stretch": _boolean_alias(
            raw_type,
            ("spriteStretch", "sprite_stretch", "stretch"),
            False,
        ),
        "sprite_random": _boolean_alias(
            raw_type,
            ("spriteRandom", "sprite_random", "random"),
            False,
        ),
        "size_min": size_min,
        "size_max": size_max,
        "size_increase": size_increase,
        "size_wiggle": size_wiggle,
        "scale_x": _number_alias(raw_type, ("scaleX", "scale_x", "xscale"), 1.0),
        "scale_y": _number_alias(raw_type, ("scaleY", "scale_y", "yscale"), 1.0),
        "life_min": life_min,
        "life_max": life_max,
        "speed_min": _number_alias(raw_type, ("speedMin", "speed_min"), 0.0),
        "speed_max": _number_alias(raw_type, ("speedMax", "speed_max"), 0.0),
        "speed_increase": _number_alias(
            raw_type,
            ("speedIncrease", "speedIncr", "speed_incr"),
            0.0,
        ),
        "speed_wiggle": _number_alias(
            raw_type,
            ("speedWiggle", "speed_wiggle"),
            0.0,
        ),
        "direction_min": _number_alias(
            raw_type,
            ("directionMin", "dirMin", "direction_min", "dir_min"),
            0.0,
        ),
        "direction_max": _number_alias(
            raw_type,
            ("directionMax", "dirMax", "direction_max", "dir_max"),
            0.0,
        ),
        "direction_increase": _number_alias(
            raw_type,
            ("directionIncrease", "dirIncr", "direction_incr", "dir_incr"),
            0.0,
        ),
        "direction_wiggle": _number_alias(
            raw_type,
            ("directionWiggle", "dirWiggle", "direction_wiggle", "dir_wiggle"),
            0.0,
        ),
        "gravity_amount": _number_alias(
            raw_type,
            ("gravityForce", "gravityAmount", "gravity_amount", "grav_amount"),
            0.0,
        ),
        "gravity_direction": _number_alias(
            raw_type,
            ("gravityDirection", "gravity_direction", "grav_dir"),
            270.0,
        ),
        "orientation_min": _number_alias(
            raw_type,
            ("orientationMin", "orientation_min", "ang_min"),
            0.0,
        ),
        "orientation_max": _number_alias(
            raw_type,
            ("orientationMax", "orientation_max", "ang_max"),
            0.0,
        ),
        "orientation_increase": _number_alias(
            raw_type,
            ("orientationIncrease", "orientation_incr", "ang_incr"),
            0.0,
        ),
        "orientation_wiggle": _number_alias(
            raw_type,
            ("orientationWiggle", "orientation_wiggle", "ang_wiggle"),
            0.0,
        ),
        "orientation_relative": _boolean_alias(
            raw_type,
            ("orientationRelative", "orientation_relative", "ang_relative"),
            False,
        ),
        "colours": colours,
        "alphas": alphas,
        "blend_additive": _boolean_alias(
            raw_type,
            ("additiveBlend", "blendAdditive", "blend_additive", "additive"),
            False,
        ),
        "spawn_on_death": _spawn_descriptor(raw_type, "Death"),
        "spawn_on_update": _spawn_descriptor(raw_type, "Update"),
    }


def _normalize_emitter(
    emitter: JsonDict,
    index: int,
    type_index: int,
) -> JsonDict:
    center_x = _number_alias(emitter, ("regionX",), 0.0)
    center_y = _number_alias(emitter, ("regionY",), 0.0)
    width = abs(_number_alias(emitter, ("regionW",), 0.0))
    height = abs(_number_alias(emitter, ("regionH",), 0.0))
    xmin = _number_alias(emitter, ("xmin",), center_x - width / 2.0)
    xmax = _number_alias(emitter, ("xmax",), center_x + width / 2.0)
    ymin = _number_alias(emitter, ("ymin",), center_y - height / 2.0)
    ymax = _number_alias(emitter, ("ymax",), center_y + height / 2.0)

    raw_mode = emitter.get("mode")
    mode = _emitter_mode(raw_mode)
    number = _number_alias(
        emitter,
        ("emitCount", "streamNumber", "burstNumber", "number"),
        0.0,
    )
    return {
        "name": _string(
            emitter.get("name") or emitter.get("%Name"),
            f"emitter_{index}",
        ),
        "type_index": type_index,
        "enabled": _boolean(emitter.get("enabled"), True),
        "mode": mode,
        "mode_value": _integer(raw_mode, 0 if mode == "stream" else 1),
        "number": number,
        "relative": _boolean(emitter.get("relative"), False),
        "region": {
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
            "shape": _emitter_shape_name(emitter.get("shape")),
            "distribution": _distribution_name(emitter.get("distribution")),
        },
        "delay_min": _number_alias(
            emitter,
            ("emitDelayMin", "delayMin", "delay_min"),
            0.0,
        ),
        "delay_max": _number_alias(
            emitter,
            ("emitDelayMax", "delayMax", "delay_max"),
            0.0,
        ),
        "delay_unit": _integer_alias(
            emitter,
            ("emitDelayUnits", "delayUnits", "delay_unit"),
            0,
        ),
        "interval_min": _number_alias(
            emitter,
            ("emitIntervalMin", "intervalMin", "interval_min"),
            0.0,
        ),
        "interval_max": _number_alias(
            emitter,
            ("emitIntervalMax", "intervalMax", "interval_max"),
            0.0,
        ),
        "interval_unit": _integer_alias(
            emitter,
            ("emitIntervalUnits", "intervalUnits", "interval_unit"),
            0,
        ),
    }


def _particle_colours(raw_type: JsonDict) -> tuple[list[int], list[float]]:
    modern_keys = ("startColour", "midColour", "endColour")
    if any(key in raw_type for key in modern_keys):
        packed_values = [_packed_colour(raw_type.get(key)) for key in modern_keys]
        return (
            [value & 0xFFFFFF for value in packed_values],
            [((value >> 24) & 0xFF) / 255.0 for value in packed_values],
        )

    raw_colours = raw_type.get("colours")
    colours = (
        [_integer(value, 0xFFFFFF) & 0xFFFFFF for value in cast(list[object], raw_colours)]
        if isinstance(raw_colours, list)
        else [
            _integer_alias(raw_type, ("colour1", "color1"), 0xFFFFFF)
            & 0xFFFFFF
        ]
    )
    raw_alphas = raw_type.get("alphas")
    alphas = (
        [
            min(1.0, max(0.0, _number(value, 1.0)))
            for value in cast(list[object], raw_alphas)
        ]
        if isinstance(raw_alphas, list)
        else [
            min(
                1.0,
                max(0.0, _number_alias(raw_type, ("alpha1",), 1.0)),
            )
        ]
    )
    return colours or [0xFFFFFF], alphas or [1.0]


def _spawn_descriptor(raw_type: JsonDict, suffix: str) -> JsonDict:
    prefix = f"spawnOn{suffix}"
    return {
        "count": _number(raw_type.get(f"{prefix}Count"), 0.0),
        "id": raw_type.get(f"{prefix}Id"),
        "preset": raw_type.get(f"{prefix}GMPreset"),
    }


def _particle_type_index(
    emitter: JsonDict,
    fallback: int,
    type_count: int,
) -> int:
    for key in ("typeIndex", "particleTypeIndex", "partTypeIndex"):
        if key in emitter:
            index = _integer(emitter.get(key), -1)
            return index if 0 <= index < type_count else -1
    return fallback if fallback < type_count else -1


def _shape_name(value: object, default: str) -> str:
    if isinstance(value, str):
        normalized = value.casefold().removeprefix("pt_shape_")
        return normalized if normalized in PARTICLE_SHAPES else default
    index = _integer(value, -1)
    return PARTICLE_SHAPES[index] if 0 <= index < len(PARTICLE_SHAPES) else default


def _emitter_shape_name(value: object) -> str:
    if isinstance(value, str):
        normalized = value.casefold().removeprefix("ps_shape_")
        if normalized in EMITTER_SHAPES:
            return normalized
    index = _integer(value, 0)
    return EMITTER_SHAPES[index] if 0 <= index < len(EMITTER_SHAPES) else "rectangle"


def _distribution_name(value: object) -> str:
    if isinstance(value, str):
        normalized = value.casefold().removeprefix("ps_distr_")
        if normalized in EMITTER_DISTRIBUTIONS:
            return normalized
    index = _integer(value, 0)
    if 0 <= index < len(EMITTER_DISTRIBUTIONS):
        return EMITTER_DISTRIBUTIONS[index]
    return "linear"


def _emitter_mode(value: object) -> str:
    if isinstance(value, str):
        normalized = value.casefold().removeprefix("ps_mode_")
        if normalized in {"stream", "burst"}:
            return normalized
    return "burst" if _integer(value, 0) == 1 else "stream"


def _reference_name(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    name = cast(dict[object, object], value).get("name")
    return name if isinstance(name, str) else ""


def _dict_list(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    return [
        cast(JsonDict, item)
        for item in cast(list[object], value)
        if isinstance(item, dict)
    ]


def _number_alias(
    data: JsonDict,
    keys: tuple[str, ...],
    default: float,
) -> float:
    for key in keys:
        if key in data:
            return _number(data.get(key), default)
    return default


def _integer_alias(
    data: JsonDict,
    keys: tuple[str, ...],
    default: int,
) -> int:
    for key in keys:
        if key in data:
            return _integer(data.get(key), default)
    return default


def _boolean_alias(
    data: JsonDict,
    keys: tuple[str, ...],
    default: bool,
) -> bool:
    for key in keys:
        if key in data:
            return _boolean(data.get(key), default)
    return default


def _number(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return default
    try:
        number = float(value)
    except ValueError:
        return default
    return number if math.isfinite(number) else default


def _integer(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return default
    try:
        return int(value)
    except (OverflowError, ValueError):
        return default


def _boolean(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return default


def _string(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _packed_colour(value: object) -> int:
    return _integer(value, 0xFFFFFFFF) & 0xFFFFFFFF


def _contains_authored_value(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value != ""
    if isinstance(value, Sized):
        return len(value) > 0
    return True


__all__ = [
    "EMITTER_DISTRIBUTIONS",
    "EMITTER_SHAPES",
    "PARTICLE_DESCRIPTOR_FORMAT_VERSION",
    "PARTICLE_SHAPES",
    "UNSUPPORTED_PARTICLE_MODIFIERS",
    "normalize_particle_system_asset",
    "particle_system_unsupported_modifier_fields",
    "render_particle_system_resource",
]
