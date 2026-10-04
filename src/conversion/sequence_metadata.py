"""Typed, consumed normalized sequence fields; coercion remains at its original owner seam."""

from __future__ import annotations

from dataclasses import dataclass

from src.conversion.json_values import JsonObject


@dataclass(frozen=True, slots=True)
class SequenceDescriptor:
    descriptor_format_version: int
    name: str
    length: float
    playback_speed: float
    playback_speed_type: int
    loopmode: int
    time_units: int
    xorigin: float
    yorigin: float
    volume: float
    tracks: list[JsonObject]
    moments: list[JsonObject]
    broadcasts: list[JsonObject]
    complete: bool

    def to_json(self) -> JsonObject:
        return {
            "descriptor_format_version": self.descriptor_format_version,
            "name": self.name,
            "length": self.length,
            "playback_speed": self.playback_speed,
            "playback_speed_type": self.playback_speed_type,
            "loopmode": self.loopmode,
            "time_units": self.time_units,
            "xorigin": self.xorigin,
            "yorigin": self.yorigin,
            "volume": self.volume,
            "tracks": [item for item in self.tracks],
            "moments": [item for item in self.moments],
            "broadcasts": [item for item in self.broadcasts],
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class SequenceAssetTrack:
    kind: str
    name: str
    path: str
    order: int
    resource_type: str
    enabled: bool
    visible: bool
    interpolation: int
    keyframes: list[JsonObject]
    parameters: list[JsonObject]
    children: list[JsonObject]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "order": self.order,
            "resource_type": self.resource_type,
            "enabled": self.enabled,
            "visible": self.visible,
            "interpolation": self.interpolation,
            "keyframes": [item for item in self.keyframes],
            "parameters": [item for item in self.parameters],
            "children": [item for item in self.children],
        }


@dataclass(frozen=True, slots=True)
class SequenceTextKey:
    asset: str
    text: str
    wrap: bool
    alignment_h: int
    alignment_v: int
    effects_enabled: bool
    glow_enabled: bool
    outline_enabled: bool
    shadow_enabled: bool

    def to_json(self) -> JsonObject:
        return {
            "asset": self.asset,
            "text": self.text,
            "wrap": self.wrap,
            "alignment_h": self.alignment_h,
            "alignment_v": self.alignment_v,
            "effects_enabled": self.effects_enabled,
            "glow_enabled": self.glow_enabled,
            "outline_enabled": self.outline_enabled,
            "shadow_enabled": self.shadow_enabled,
        }


@dataclass(frozen=True, slots=True)
class SequenceParameterTrack:
    kind: str
    name: str
    path: str
    order: int
    resource_type: str
    enabled: bool
    interpolation: int
    keyframes: list[JsonObject]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "order": self.order,
            "resource_type": self.resource_type,
            "enabled": self.enabled,
            "interpolation": self.interpolation,
            "keyframes": [item for item in self.keyframes],
        }


@dataclass(frozen=True, slots=True)
class SequenceAudioEffectTrack:
    kind: str
    name: str
    path: str
    order: int
    resource_type: str
    effect_type: str
    enabled: bool
    defaults: JsonObject
    parameters: list[JsonObject]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "order": self.order,
            "resource_type": self.resource_type,
            "effect_type": self.effect_type,
            "enabled": self.enabled,
            "defaults": self.defaults,
            "parameters": [item for item in self.parameters],
        }


@dataclass(frozen=True, slots=True)
class SequenceActionBase:
    frame: float
    order: int

    def to_json(self) -> JsonObject:
        return {
            "frame": self.frame,
            "order": self.order,
        }


@dataclass(frozen=True, slots=True)
class SequenceKeyframeBase:
    frame: float
    length: float
    stretch: bool
    disabled: bool
    creation: bool
    order: int

    def to_json(self) -> JsonObject:
        return {
            "frame": self.frame,
            "length": self.length,
            "stretch": self.stretch,
            "disabled": self.disabled,
            "creation": self.creation,
            "order": self.order,
        }


def sequence_track_count(data: JsonObject) -> int:
    """Strict aggregate count; normalization and legacy fallbacks are separate."""
    tracks = data.get("tracks")
    return sum(isinstance(track, dict) for track in tracks) if isinstance(tracks, list) else 0


@dataclass(frozen=True, slots=True)
class SequenceChannel:
    index: int
    raw_data: JsonObject

    def as_pair(self) -> tuple[int, JsonObject]:
        return self.index, self.raw_data


@dataclass(frozen=True, slots=True)
class SequenceEventAction:
    frame: float
    order: int
    source_order: int
    channel_order: int

    def to_json(self) -> JsonObject:
        return {
            "frame": self.frame,
            "order": self.order,
            "source_order": self.source_order,
            "channel_order": self.channel_order,
        }
