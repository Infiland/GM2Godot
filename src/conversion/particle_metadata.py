"""Typed, consumed normalized particle fields; coercion remains at its original owner seam."""

from __future__ import annotations

from dataclasses import dataclass

from src.conversion.json_values import JsonObject, JsonValue


@dataclass(frozen=True, slots=True)
class ParticleSystemDescriptor:
    descriptor_format_version: int
    name: str
    xorigin: float
    yorigin: float
    draw_order: str
    draw_order_value: int
    types: list[JsonObject]
    emitters: list[JsonObject]
    unsupported_modifiers: list[str]

    def to_json(self) -> JsonObject:
        return {
            "descriptor_format_version": self.descriptor_format_version,
            "name": self.name,
            "xorigin": self.xorigin,
            "yorigin": self.yorigin,
            "draw_order": self.draw_order,
            "draw_order_value": self.draw_order_value,
            "types": [item for item in self.types],
            "emitters": [item for item in self.emitters],
            "unsupported_modifiers": [item for item in self.unsupported_modifiers],
        }


@dataclass(frozen=True, slots=True)
class ParticleTypeDescriptor:
    name: str
    shape: str
    texture_index: int
    sprite: str | None
    sprite_frame: float
    sprite_animate: bool
    sprite_stretch: bool
    sprite_random: bool
    size_min: float
    size_max: float
    size_increase: float
    size_wiggle: float
    scale_x: float
    scale_y: float
    life_min: float
    life_max: float
    speed_min: float
    speed_max: float
    speed_increase: float
    speed_wiggle: float
    direction_min: float
    direction_max: float
    direction_increase: float
    direction_wiggle: float
    gravity_amount: float
    gravity_direction: float
    orientation_min: float
    orientation_max: float
    orientation_increase: float
    orientation_wiggle: float
    orientation_relative: bool
    colours: list[int]
    alphas: list[float]
    blend_additive: bool
    spawn_on_death: JsonObject
    spawn_on_update: JsonObject

    def to_json(self) -> JsonObject:
        return {
            "name": self.name,
            "shape": self.shape,
            "texture_index": self.texture_index,
            "sprite": self.sprite,
            "sprite_frame": self.sprite_frame,
            "sprite_animate": self.sprite_animate,
            "sprite_stretch": self.sprite_stretch,
            "sprite_random": self.sprite_random,
            "size_min": self.size_min,
            "size_max": self.size_max,
            "size_increase": self.size_increase,
            "size_wiggle": self.size_wiggle,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "life_min": self.life_min,
            "life_max": self.life_max,
            "speed_min": self.speed_min,
            "speed_max": self.speed_max,
            "speed_increase": self.speed_increase,
            "speed_wiggle": self.speed_wiggle,
            "direction_min": self.direction_min,
            "direction_max": self.direction_max,
            "direction_increase": self.direction_increase,
            "direction_wiggle": self.direction_wiggle,
            "gravity_amount": self.gravity_amount,
            "gravity_direction": self.gravity_direction,
            "orientation_min": self.orientation_min,
            "orientation_max": self.orientation_max,
            "orientation_increase": self.orientation_increase,
            "orientation_wiggle": self.orientation_wiggle,
            "orientation_relative": self.orientation_relative,
            "colours": [item for item in self.colours],
            "alphas": [item for item in self.alphas],
            "blend_additive": self.blend_additive,
            "spawn_on_death": self.spawn_on_death,
            "spawn_on_update": self.spawn_on_update,
        }


@dataclass(frozen=True, slots=True)
class ParticleEmitterDescriptor:
    name: str
    type_index: int
    enabled: bool
    mode: str
    mode_value: int
    number: float
    relative: bool
    region: JsonObject
    delay_min: float
    delay_max: float
    delay_unit: int
    interval_min: float
    interval_max: float
    interval_unit: int

    def to_json(self) -> JsonObject:
        return {
            "name": self.name,
            "type_index": self.type_index,
            "enabled": self.enabled,
            "mode": self.mode,
            "mode_value": self.mode_value,
            "number": self.number,
            "relative": self.relative,
            "region": self.region,
            "delay_min": self.delay_min,
            "delay_max": self.delay_max,
            "delay_unit": self.delay_unit,
            "interval_min": self.interval_min,
            "interval_max": self.interval_max,
            "interval_unit": self.interval_unit,
        }


@dataclass(frozen=True, slots=True)
class ParticleSpawnDescriptor:
    count: float
    id: JsonValue
    preset: JsonValue

    def to_json(self) -> JsonObject:
        return {
            "count": self.count,
            "id": self.id,
            "preset": self.preset,
        }


@dataclass(frozen=True, slots=True)
class ParticleRegionDescriptor:
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    shape: str
    distribution: str

    def to_json(self) -> JsonObject:
        return {
            "xmin": self.xmin,
            "xmax": self.xmax,
            "ymin": self.ymin,
            "ymax": self.ymax,
            "shape": self.shape,
            "distribution": self.distribution,
        }
