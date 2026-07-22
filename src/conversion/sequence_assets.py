from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import cast

from src.conversion.type_defs import JsonDict


SEQUENCE_DESCRIPTOR_FORMAT_VERSION = 1

_ASSET_TRACK_TYPES = {
    "gmgraphictrack": "sprite",
    "gminstancetrack": "instance",
    "gmaudiotrack": "audio",
    "gmtexttrack": "text",
    "gmsequencetrack": "sequence",
}
_NUMERIC_ASSET_TRACK_TYPES = {
    1: "sprite",
    2: "audio",
    7: "sequence",
    14: "instance",
    17: "text",
}
_PARAMETER_TRACK_TYPES = {
    "gmrealtrack": "real",
    "gmcolourtrack": "colour",
    "gmcolortrack": "colour",
}
_SUPPORTED_PARAMETER_NAMES = {
    "position",
    "rotation",
    "origin",
    "scale",
    "image_index",
    "image_speed",
    "gain",
    "volume",
    "pitch",
    "frameSize",
    "characterSpacing",
    "lineSpacing",
    "paragraphSpacing",
    "coreColour",
    "coreColor",
    "outlineColour",
    "outlineColor",
    "outlineDist",
    "shadowColour",
    "shadowColor",
    "shadowSoftness",
    "shadowOffsetX",
    "shadowOffsetY",
}
_PARAMETER_NAME_ALIASES = {
    "imageindex": "image_index",
    "imagespeed": "image_speed",
    "frame_size": "frameSize",
    "framesize": "frameSize",
    "characterspacing": "characterSpacing",
    "character_spacing": "characterSpacing",
    "linespacing": "lineSpacing",
    "line_spacing": "lineSpacing",
    "paragraphspacing": "paragraphSpacing",
    "paragraph_spacing": "paragraphSpacing",
    "blend_multiply": "blend_multiply",
    "image_blend": "blend_multiply",
}
_SUPPORTED_AUDIO_EFFECT_TYPES = {
    "delay",
    "gain",
    "hishelf",
    "hpf2",
    "loshelf",
    "lpf2",
    "reverb1",
}
_SUPPORTED_AUDIO_EFFECT_PROPERTIES = {
    "delay": {"bypass", "feedback", "mix", "time"},
    "gain": {"bypass", "gain"},
    "hishelf": {"bypass", "freq", "gain"},
    "hpf2": {"bypass", "cutoff"},
    "loshelf": {"bypass", "freq", "gain"},
    "lpf2": {"bypass", "cutoff"},
    "reverb1": {"bypass", "damp", "mix", "size"},
}
_AUDIO_EFFECT_TYPE_ALIASES = {
    "reverb": "reverb1",
    "reverb1": "reverb1",
    "lowpass": "lpf2",
    "lpf": "lpf2",
    "lpf2": "lpf2",
    "highpass": "hpf2",
    "hpf": "hpf2",
    "hpf2": "hpf2",
    "highshelf": "hishelf",
    "hishelf": "hishelf",
    "lowshelf": "loshelf",
    "loshelf": "loshelf",
}
_ASSET_KEY_TYPES = {
    "sprite": {"assetspritekeyframe"},
    "instance": {"assetinstancekeyframe"},
    "audio": {"audiokeyframe"},
    "text": {"assettextkeyframe"},
    "sequence": {"assetsequencekeyframe"},
}
_NON_PAYLOAD_FIELDS = {
    "%Name",
    "builtinName",
    "events",
    "enabled",
    "disabled",
    "effectType",
    "inheritsTrackColour",
    "interpolation",
    "isCreationTrack",
    "keyframes",
    "modifiers",
    "name",
    "resourceType",
    "resourceVersion",
    "trackColour",
    "tracks",
    "traits",
    "type",
    "visible",
}


@dataclass(frozen=True, slots=True)
class SequenceCompatibilityIssue:
    code: str
    message: str
    manifest_entry: str
    track_type: str = ""
    key_type: str = ""
    workaround: str = ""


def normalize_sequence_asset(
    raw_data: JsonDict,
) -> tuple[JsonDict, tuple[SequenceCompatibilityIssue, ...]]:
    """Normalize one authored GameMaker sequence into a runtime descriptor."""

    issues: list[SequenceCompatibilityIssue] = []
    tracks: list[JsonDict] = []
    raw_tracks = _dict_list(raw_data.get("tracks"))
    for index, raw_track in enumerate(raw_tracks):
        normalized = _normalize_asset_track(
            raw_track,
            path=f"tracks[{index}]",
            order=index,
            issues=issues,
        )
        if normalized is not None:
            tracks.append(normalized)

    moments = _normalize_sequence_actions(
        raw_data,
        source_key="moments",
        legacy_keys=("momentEvents",),
        kind="moment",
        issues=issues,
    )
    broadcasts = _normalize_sequence_actions(
        raw_data,
        source_key="events",
        legacy_keys=("broadcastMessages", "broadcasts"),
        kind="broadcast",
        issues=issues,
    )

    event_to_function = raw_data.get("eventToFunction")
    if (
        isinstance(event_to_function, dict)
        and any(
            _contains_authored_event_binding(value)
            for value in cast(dict[object, object], event_to_function).values()
        )
    ):
        issues.append(
            SequenceCompatibilityIssue(
                code="GM2GD-SEQUENCE-EVENT-UNSUPPORTED",
                message=(
                    "Authored sequence lifecycle event bindings are not part of "
                    "the supported moment/broadcast conversion surface."
                ),
                manifest_entry="eventToFunction",
                track_type="sequence_event",
                workaround=(
                    "Move required behavior to a supported sequence moment or "
                    "project-specific converted object event."
                ),
            )
        )

    descriptor: JsonDict = {
        "descriptor_format_version": SEQUENCE_DESCRIPTOR_FORMAT_VERSION,
        "name": _string(raw_data.get("name") or raw_data.get("%Name"), ""),
        "length": max(_number(raw_data.get("length", raw_data.get("duration")), 0.0), 0.0),
        "playback_speed": max(_number(raw_data.get("playbackSpeed"), 1.0), 0.0),
        "playback_speed_type": _integer(raw_data.get("playbackSpeedType"), 0),
        "loopmode": _integer(
            raw_data.get("playback", raw_data.get("loopmode")),
            0,
        ),
        "time_units": _integer(raw_data.get("timeUnits"), 1),
        "xorigin": _number(raw_data.get("xorigin"), 0.0),
        "yorigin": _number(raw_data.get("yorigin"), 0.0),
        "volume": min(
            1.0,
            max(_number(raw_data.get("volume"), 1.0), 0.0),
        ),
        "tracks": tracks,
        "moments": moments,
        "broadcasts": broadcasts,
        "complete": not issues,
    }
    return descriptor, tuple(issues)


def render_sequence_resource(
    name: str,
    source_path: str,
    descriptor: JsonDict,
) -> str:
    """Render a loadable Godot Resource carrying a sequence descriptor."""

    descriptor_literal = json.dumps(
        descriptor,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    return (
        '[gd_resource type="Resource" format=3]\n\n'
        "[resource]\n"
        f"resource_name = {json.dumps(name)}\n"
        'metadata/gamemaker_resource_type = "GMSequence"\n'
        f"metadata/gamemaker_source_path = {json.dumps(source_path)}\n"
        "metadata/gamemaker_sequence_descriptor = "
        f"{descriptor_literal}\n"
    )


def _normalize_asset_track(
    raw_track: JsonDict,
    *,
    path: str,
    order: int,
    issues: list[SequenceCompatibilityIssue],
) -> JsonDict | None:
    resource_type = _resource_type(raw_track)
    track_kind = _asset_track_kind(raw_track, resource_type)
    if track_kind is None:
        issues.append(
            SequenceCompatibilityIssue(
                code="GM2GD-SEQUENCE-TRACK-UNSUPPORTED",
                message=(
                    "Unsupported authored GameMaker sequence track type "
                    f"{resource_type or '<missing>'!r}."
                ),
                manifest_entry=path,
                track_type=resource_type or "<missing>",
                workaround=(
                    "Replace this track with a supported sprite, instance, audio, "
                    "text, or nested-sequence track."
                ),
            )
        )
        return None

    raw_interpolation = _integer(raw_track.get("interpolation"), 1)
    if raw_interpolation not in {0, 1}:
        issues.append(
            SequenceCompatibilityIssue(
                code="GM2GD-SEQUENCE-TRACK-UNSUPPORTED",
                message=(
                    f"Sequence track {path} uses unsupported interpolation "
                    f"value {raw_interpolation}."
                ),
                manifest_entry=f"{path}.interpolation",
                track_type=resource_type,
                workaround="Use assign (0) or linear (1) interpolation.",
            )
        )

    keyframes = _normalize_asset_keyframes(
        raw_track,
        track_kind=track_kind,
        path=f"{path}.keyframes",
        issues=issues,
    )
    parameters: list[JsonDict] = []
    children: list[JsonDict] = []
    for child_index, child in enumerate(_dict_list(raw_track.get("tracks"))):
        child_path = f"{path}.tracks[{child_index}]"
        child_type = _resource_type(child)
        if _is_audio_effect_track(child, child_type):
            effect = _normalize_audio_effect_track(
                child,
                path=child_path,
                order=child_index,
                issues=issues,
            )
            if effect is not None:
                parameters.append(effect)
            continue
        if child_type.casefold() in _PARAMETER_TRACK_TYPES:
            parameter = _normalize_parameter_track(
                child,
                path=child_path,
                order=child_index,
                issues=issues,
            )
            if parameter is not None:
                parameters.append(parameter)
            continue
        if _asset_track_kind(child, child_type) is not None:
            normalized_child = _normalize_asset_track(
                child,
                path=child_path,
                order=child_index,
                issues=issues,
            )
            if normalized_child is not None:
                children.append(normalized_child)
            continue
        issues.append(
            SequenceCompatibilityIssue(
                code="GM2GD-SEQUENCE-TRACK-UNSUPPORTED",
                message=(
                    "Unsupported authored GameMaker sequence child track type "
                    f"{child_type or '<missing>'!r}."
                ),
                manifest_entry=child_path,
                track_type=child_type or "<missing>",
                workaround=(
                    "Replace this child with a supported parameter or asset track."
                ),
            )
        )

    return {
        "kind": track_kind,
        "name": _string(
            raw_track.get("name") or raw_track.get("%Name"),
            f"{track_kind}_{order}",
        ),
        "path": path,
        "order": order,
        "resource_type": resource_type,
        "enabled": _track_enabled(raw_track),
        "visible": _track_visible(raw_track),
        "interpolation": raw_interpolation if raw_interpolation in {0, 1} else 0,
        "keyframes": keyframes,
        "parameters": parameters,
        "children": children,
    }


def _normalize_asset_keyframes(
    raw_track: JsonDict,
    *,
    track_kind: str,
    path: str,
    issues: list[SequenceCompatibilityIssue],
) -> list[JsonDict]:
    keyframes: list[JsonDict] = []
    for index, raw_keyframe in enumerate(_keyframes(raw_track.get("keyframes"))):
        key_path = f"{path}.Keyframes[{index}]"
        channels = _channels(raw_keyframe)
        if not channels:
            issues.append(
                SequenceCompatibilityIssue(
                    code="GM2GD-SEQUENCE-KEY-UNSUPPORTED",
                    message=f"Sequence {track_kind} keyframe has no channel data.",
                    manifest_entry=key_path,
                    track_type=track_kind,
                    key_type="<missing>",
                    workaround="Recreate the asset key in the GameMaker Sequence Editor.",
                )
            )
            continue
        channel, raw_channel = channels[0]
        channel_type = _resource_type(raw_channel)
        if channel != 0 or (
            channel_type.casefold() not in _ASSET_KEY_TYPES[track_kind]
        ):
            issues.append(
                SequenceCompatibilityIssue(
                    code="GM2GD-SEQUENCE-KEY-UNSUPPORTED",
                    message=(
                        f"Unsupported {track_kind} key channel/type "
                        f"{channel}/{channel_type or '<missing>'}."
                    ),
                    manifest_entry=f"{key_path}.Channels[{channel}]",
                    track_type=track_kind,
                    key_type=channel_type or "<missing>",
                    workaround=(
                        "Use channel 0 with the GameMaker key type generated for "
                        f"a {track_kind} asset track."
                    ),
                )
            )
            continue

        normalized = _keyframe_base(raw_keyframe, index)
        normalized["channel"] = 0
        normalized["key_type"] = channel_type
        if track_kind == "text":
            normalized.update(_normalize_text_key(raw_channel))
            if normalized["glow_enabled"]:
                issues.append(
                    SequenceCompatibilityIssue(
                        code="GM2GD-SEQUENCE-EFFECT-UNSUPPORTED",
                        message=(
                            "GameMaker text-track glow cannot be represented "
                            "exactly by a Godot 4.7.1 Label."
                        ),
                        manifest_entry=f"{key_path}.Channels[0].EnableGlow",
                        track_type=track_kind,
                        key_type=channel_type,
                        workaround=(
                            "Use outline/shadow text effects or a project-specific "
                            "Godot SDF material."
                        ),
                    )
                )
        else:
            asset = _reference_name(
                raw_channel.get("Id")
                if raw_channel.get("Id") is not None
                else raw_channel.get("id")
            )
            if not asset:
                issues.append(
                    SequenceCompatibilityIssue(
                        code="GM2GD-SEQUENCE-KEY-UNSUPPORTED",
                        message=f"Sequence {track_kind} keyframe has no asset reference.",
                        manifest_entry=f"{key_path}.Channels[0].Id",
                        track_type=track_kind,
                        key_type=channel_type,
                        workaround=(
                            "Assign a valid GameMaker asset to this keyframe or "
                            "remove the empty key."
                        ),
                    )
                )
                continue
            normalized["asset"] = asset
            if track_kind == "audio":
                normalized["playback_mode"] = _integer(
                    raw_channel.get("Mode", raw_channel.get("playbackMode")),
                    1,
                )
        keyframes.append(normalized)
        for extra_channel, extra_data in channels[1:]:
            issues.append(
                SequenceCompatibilityIssue(
                    code="GM2GD-SEQUENCE-KEY-UNSUPPORTED",
                    message=(
                        f"Sequence {track_kind} asset key uses unsupported "
                        f"additional channel {extra_channel}."
                    ),
                    manifest_entry=f"{key_path}.Channels[{extra_channel}]",
                    track_type=track_kind,
                    key_type=_resource_type(extra_data) or "<missing>",
                    workaround="Keep asset key data on channel 0.",
                )
            )
    return sorted(
        keyframes,
        key=lambda item: (_number(item.get("frame"), 0.0), _integer(item.get("order"), 0)),
    )


def _normalize_text_key(raw_channel: JsonDict) -> JsonDict:
    alignment = _integer(
        raw_channel.get("Alignment", raw_channel.get("alignment")),
        0,
    )
    return {
        "asset": _reference_name(
            raw_channel.get("Id")
            if raw_channel.get("Id") is not None
            else raw_channel.get("fontIndex")
        ),
        "text": _string(
            raw_channel.get("Text", raw_channel.get("text")),
            "",
            allow_empty=True,
        ),
        "wrap": _boolean(raw_channel.get("Wrap", raw_channel.get("wrap")), False),
        "alignment_h": alignment & 0xFF,
        "alignment_v": (alignment >> 8) & 0xFF,
        "effects_enabled": _boolean(
            raw_channel.get(
                "EnableEffects",
                raw_channel.get("effectsEnabled"),
            ),
            False,
        ),
        "glow_enabled": _boolean(
            raw_channel.get("EnableGlow", raw_channel.get("glowEnabled")),
            False,
        ),
        "outline_enabled": _boolean(
            raw_channel.get(
                "EnableOutline",
                raw_channel.get("outlineEnabled"),
            ),
            False,
        ),
        "shadow_enabled": _boolean(
            raw_channel.get(
                "EnableShadow",
                raw_channel.get("dropShadowEnabled"),
            ),
            False,
        ),
    }


def _normalize_parameter_track(
    raw_track: JsonDict,
    *,
    path: str,
    order: int,
    issues: list[SequenceCompatibilityIssue],
    effect_parameter: bool = False,
) -> JsonDict | None:
    resource_type = _resource_type(raw_track)
    parameter_kind = _PARAMETER_TRACK_TYPES.get(resource_type.casefold())
    name = _parameter_name(raw_track)
    if parameter_kind is None:
        issues.append(
            SequenceCompatibilityIssue(
                code="GM2GD-SEQUENCE-TRACK-UNSUPPORTED",
                message=f"Unsupported sequence parameter track type {resource_type!r}.",
                manifest_entry=path,
                track_type=resource_type or "<missing>",
                workaround="Use a real or colour parameter track.",
            )
        )
        return None
    if not effect_parameter and name not in _SUPPORTED_PARAMETER_NAMES | {"blend_multiply"}:
        issues.append(
            SequenceCompatibilityIssue(
                code="GM2GD-SEQUENCE-TRACK-UNSUPPORTED",
                message=f"Unsupported sequence parameter track {name!r}.",
                manifest_entry=path,
                track_type=resource_type,
                workaround=(
                    "Use a documented GameMaker transform, visual, audio, or text "
                    "parameter track."
                ),
            )
        )
        return None

    interpolation = _integer(raw_track.get("interpolation"), 1)
    if interpolation not in {0, 1}:
        issues.append(
            SequenceCompatibilityIssue(
                code="GM2GD-SEQUENCE-TRACK-UNSUPPORTED",
                message=(
                    f"Sequence parameter {name!r} uses unsupported interpolation "
                    f"value {interpolation}."
                ),
                manifest_entry=f"{path}.interpolation",
                track_type=resource_type,
                workaround="Use assign (0) or linear (1) interpolation.",
            )
        )
        return None

    keyframes: list[JsonDict] = []
    for key_index, raw_keyframe in enumerate(
        _keyframes(raw_track.get("keyframes"))
    ):
        key_path = f"{path}.keyframes.Keyframes[{key_index}]"
        channels = _channels(raw_keyframe)
        if not channels:
            issues.append(
                SequenceCompatibilityIssue(
                    code="GM2GD-SEQUENCE-KEY-UNSUPPORTED",
                    message=f"Sequence parameter {name!r} key has no channels.",
                    manifest_entry=key_path,
                    track_type=resource_type,
                    key_type="<missing>",
                    workaround="Recreate this parameter key in GameMaker.",
                )
            )
            continue
        values: list[object] = []
        unsupported_curve = False
        for channel, raw_channel in channels:
            embedded_curve = raw_channel.get("EmbeddedAnimCurve")
            curve_reference = raw_channel.get("AnimCurveId")
            if embedded_curve is not None or curve_reference is not None:
                issues.append(
                    SequenceCompatibilityIssue(
                        code="GM2GD-SEQUENCE-KEY-UNSUPPORTED",
                        message=(
                            f"Sequence parameter {name!r} uses an animation-curve "
                            "key that cannot be represented by assign/linear playback."
                        ),
                        manifest_entry=(
                            f"{key_path}.Channels[{channel}]."
                            + (
                                "EmbeddedAnimCurve"
                                if embedded_curve is not None
                                else "AnimCurveId"
                            )
                        ),
                        track_type=resource_type,
                        key_type="animation_curve",
                        workaround=(
                            "Convert this curve to linear keys in GameMaker or "
                            "replace it with project-specific Godot animation."
                        ),
                    )
                )
                unsupported_curve = True
                break
            while len(values) <= channel:
                values.append(0.0)
            values[channel] = _parameter_channel_value(
                raw_channel,
                parameter_kind=parameter_kind,
            )
        if unsupported_curve:
            continue
        key = _keyframe_base(raw_keyframe, key_index)
        key["values"] = values
        keyframes.append(key)

    return {
        "kind": parameter_kind,
        "name": name,
        "path": path,
        "order": order,
        "resource_type": resource_type,
        "enabled": _track_enabled(raw_track),
        "interpolation": interpolation,
        "keyframes": sorted(
            keyframes,
            key=lambda item: (
                _number(item.get("frame"), 0.0),
                _integer(item.get("order"), 0),
            ),
        ),
    }


def _normalize_audio_effect_track(
    raw_track: JsonDict,
    *,
    path: str,
    order: int,
    issues: list[SequenceCompatibilityIssue],
) -> JsonDict | None:
    resource_type = _resource_type(raw_track)
    effect_type = _audio_effect_type(raw_track)
    if effect_type not in _SUPPORTED_AUDIO_EFFECT_TYPES:
        issues.append(
            SequenceCompatibilityIssue(
                code="GM2GD-SEQUENCE-EFFECT-UNSUPPORTED",
                message=(
                    "Unsupported authored GameMaker sequence audio effect "
                    f"{effect_type or resource_type or '<missing>'!r}."
                ),
                manifest_entry=path,
                track_type=resource_type or "audio_effect",
                workaround=(
                    "Use gain, reverb, delay, LPF, HPF, high-shelf, "
                    "or low-shelf, or recreate this effect on a Godot audio bus."
                ),
            )
        )
        return None

    parameter_tracks: list[JsonDict] = []
    supported_properties = _SUPPORTED_AUDIO_EFFECT_PROPERTIES[effect_type]
    for child_index, child in enumerate(_dict_list(raw_track.get("tracks"))):
        child_name = _parameter_name(child)
        if child_name not in supported_properties:
            issues.append(
                SequenceCompatibilityIssue(
                    code="GM2GD-SEQUENCE-EFFECT-UNSUPPORTED",
                    message=(
                        f"Audio effect {effect_type!r} property "
                        f"{child_name or '<missing>'!r} has no exact Godot 4.7.1 mapping."
                    ),
                    manifest_entry=f"{path}.tracks[{child_index}]",
                    track_type=resource_type or "audio_effect",
                    key_type=child_name or "<missing>",
                    workaround=(
                        "Remove this property animation or recreate the effect "
                        "with project-specific Godot audio code."
                    ),
                )
            )
            continue
        parameter = _normalize_parameter_track(
            child,
            path=f"{path}.tracks[{child_index}]",
            order=child_index,
            issues=issues,
            effect_parameter=True,
        )
        if parameter is not None:
            parameter_tracks.append(parameter)

    raw_defaults = _effect_defaults(raw_track)
    defaults: JsonDict = {}
    for property_name, value in raw_defaults.items():
        if property_name in supported_properties:
            defaults[property_name] = value
            continue
        issues.append(
            SequenceCompatibilityIssue(
                code="GM2GD-SEQUENCE-EFFECT-UNSUPPORTED",
                message=(
                    f"Audio effect {effect_type!r} property "
                    f"{property_name!r} has no exact Godot 4.7.1 mapping."
                ),
                manifest_entry=f"{path}.{property_name}",
                track_type=resource_type or "audio_effect",
                key_type=property_name,
                workaround=(
                    "Remove this property or recreate the effect with "
                    "project-specific Godot audio code."
                ),
            )
        )
    return {
        "kind": "audio_effect",
        "name": _string(
            raw_track.get("name") or raw_track.get("%Name"),
            effect_type,
        ),
        "path": path,
        "order": order,
        "resource_type": resource_type,
        "effect_type": effect_type,
        "enabled": _track_enabled(raw_track),
        "defaults": defaults,
        "parameters": parameter_tracks,
    }


def _normalize_sequence_actions(
    raw_data: JsonDict,
    *,
    source_key: str,
    legacy_keys: tuple[str, ...],
    kind: str,
    issues: list[SequenceCompatibilityIssue],
) -> list[JsonDict]:
    actions: list[JsonDict] = []
    raw_store = raw_data.get(source_key)
    if isinstance(raw_store, dict):
        raw_keyframes = _keyframes(cast(JsonDict, raw_store))
        for key_index, raw_keyframe in enumerate(raw_keyframes):
            key_path = f"{source_key}.Keyframes[{key_index}]"
            frame = _number(
                raw_keyframe.get(
                    "Key",
                    raw_keyframe.get("frame", raw_keyframe.get("moment")),
                ),
                float(key_index),
            )
            channels = _channels(raw_keyframe)
            if not channels:
                issues.append(
                    SequenceCompatibilityIssue(
                        code="GM2GD-SEQUENCE-KEY-UNSUPPORTED",
                        message=f"Sequence {kind} keyframe has no channel data.",
                        manifest_entry=key_path,
                        track_type=kind,
                        key_type="<missing>",
                        workaround=f"Recreate the {kind} key in GameMaker.",
                    )
                )
                continue
            channel, channel_data = channels[0]
            channel_type = _resource_type(channel_data)
            expected = (
                "momentseventkeyframe"
                if kind == "moment"
                else "messageeventkeyframe"
            )
            if channel != 0 or channel_type.casefold() != expected:
                issues.append(
                    SequenceCompatibilityIssue(
                        code="GM2GD-SEQUENCE-KEY-UNSUPPORTED",
                        message=(
                            f"Unsupported sequence {kind} channel/type "
                            f"{channel}/{channel_type or '<missing>'}."
                        ),
                        manifest_entry=f"{key_path}.Channels[{channel}]",
                        track_type=kind,
                        key_type=channel_type or "<missing>",
                        workaround=(
                            f"Use channel 0 with a GameMaker {expected} key."
                        ),
                    )
                )
                continue
            event_values = _event_strings(channel_data)
            if not event_values:
                issues.append(
                    SequenceCompatibilityIssue(
                        code="GM2GD-SEQUENCE-KEY-UNSUPPORTED",
                        message=f"Sequence {kind} keyframe has no action value.",
                        manifest_entry=f"{key_path}.Channels[0].Events",
                        track_type=kind,
                        key_type=channel_type,
                        workaround=f"Assign a valid {kind} value or remove the key.",
                    )
                )
                continue
            for event_index, value in enumerate(event_values):
                action: JsonDict = {
                    "frame": frame,
                    "order": len(actions),
                    "source_order": key_index,
                    "channel_order": event_index,
                }
                if kind == "moment":
                    action["script"] = value
                else:
                    action["message"] = value
                actions.append(action)
    elif isinstance(raw_store, list):
        actions.extend(
            _normalize_legacy_actions(
                cast(list[object], raw_store),
                kind=kind,
            )
        )

    for legacy_key in legacy_keys:
        raw_legacy = raw_data.get(legacy_key)
        if isinstance(raw_legacy, list):
            actions.extend(
                _normalize_legacy_actions(
                    cast(list[object], raw_legacy),
                    kind=kind,
                    order_offset=len(actions),
                )
            )
    return sorted(
        actions,
        key=lambda item: (
            _number(item.get("frame"), 0.0),
            _integer(item.get("order"), 0),
        ),
    )


def _normalize_legacy_actions(
    raw_actions: list[object],
    *,
    kind: str,
    order_offset: int = 0,
) -> list[JsonDict]:
    actions: list[JsonDict] = []
    for index, raw_action in enumerate(raw_actions):
        if not isinstance(raw_action, dict):
            continue
        action_data = cast(JsonDict, raw_action)
        normalized: JsonDict = {
            "frame": _number(
                action_data.get(
                    "frame",
                    action_data.get("moment", action_data.get("time")),
                ),
                float(index),
            ),
            "order": order_offset + index,
        }
        for name in ("name", "event", "callable", "script"):
            value = action_data.get(name)
            if isinstance(value, str) and value:
                normalized[name] = value
        if kind == "broadcast":
            message = action_data.get("message")
            if isinstance(message, str):
                normalized["message"] = message
        normalized["raw"] = action_data
        actions.append(normalized)
    return actions


def _parameter_channel_value(
    raw_channel: JsonDict,
    *,
    parameter_kind: str,
) -> object:
    if parameter_kind == "colour":
        colour_value = raw_channel.get(
            "Colour",
            raw_channel.get("Color", raw_channel.get("colour")),
        )
        if isinstance(colour_value, list):
            return [
                min(1.0, max(0.0, _number(component, 0.0)))
                for component in cast(list[object], colour_value)[:4]
            ]
        packed = _integer(colour_value, 0xFFFFFFFF) & 0xFFFFFFFF
        return [
            ((packed >> 24) & 0xFF) / 255.0,
            (packed & 0xFF) / 255.0,
            ((packed >> 8) & 0xFF) / 255.0,
            ((packed >> 16) & 0xFF) / 255.0,
        ]
    return _number(
        raw_channel.get(
            "RealValue",
            raw_channel.get("value", raw_channel.get("Value")),
        ),
        0.0,
    )


def _effect_defaults(raw_track: JsonDict) -> JsonDict:
    defaults: JsonDict = {}
    candidate = raw_track.get("effect")
    if not isinstance(candidate, dict):
        candidate = raw_track.get("params")
    sources = [cast(JsonDict, candidate)] if isinstance(candidate, dict) else []
    sources.append(raw_track)
    for source in sources:
        for key, value in source.items():
            if key in _NON_PAYLOAD_FIELDS or key.startswith("$"):
                continue
            if isinstance(value, bool | int | float | str) or value is None:
                defaults[key] = value
    return defaults


def _audio_effect_type(raw_track: JsonDict) -> str:
    candidates = (
        raw_track.get("effectType"),
        raw_track.get("type"),
        raw_track.get("name"),
        raw_track.get("%Name"),
    )
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        normalized = candidate.strip().casefold()
        normalized = normalized.removeprefix("audioeffect_")
        normalized = normalized.removesuffix("-fx")
        normalized = normalized.replace("_", "").replace("-", "")
        if normalized in _AUDIO_EFFECT_TYPE_ALIASES:
            return _AUDIO_EFFECT_TYPE_ALIASES[normalized]
        if normalized:
            return normalized
    return ""


def _is_audio_effect_track(raw_track: JsonDict, resource_type: str) -> bool:
    normalized_type = resource_type.casefold()
    if "audioeffect" in normalized_type:
        return True
    name = _string(raw_track.get("name") or raw_track.get("%Name"), "")
    normalized_name = name.casefold()
    if normalized_name.startswith("audioeffect_") or normalized_name.endswith("-fx"):
        return True
    return normalized_type == "gmbasetrack" and _integer(
        raw_track.get("builtinName"),
        -1,
    ) >= 32


def _asset_track_kind(raw_track: JsonDict, resource_type: str) -> str | None:
    normalized = resource_type.casefold()
    if normalized in _ASSET_TRACK_TYPES:
        return _ASSET_TRACK_TYPES[normalized]
    numeric_type = raw_track.get("type")
    if isinstance(numeric_type, int) and not isinstance(numeric_type, bool):
        return _NUMERIC_ASSET_TRACK_TYPES.get(numeric_type)
    return None


def _parameter_name(raw_track: JsonDict) -> str:
    name = _string(raw_track.get("name") or raw_track.get("%Name"), "")
    alias = _PARAMETER_NAME_ALIASES.get(name.casefold())
    if alias is not None:
        return alias
    if name.startswith("textEffect_"):
        return name.removeprefix("textEffect_")
    return name


def _track_enabled(raw_track: JsonDict) -> bool:
    if not _boolean(raw_track.get("enabled"), True):
        return False
    if _boolean(raw_track.get("disabled"), False):
        return False
    return not _has_modifier(raw_track, "disabled")


def _track_visible(raw_track: JsonDict) -> bool:
    if not _boolean(raw_track.get("visible"), True):
        return False
    return not _has_modifier(raw_track, "invisible")


def _has_modifier(raw_track: JsonDict, marker: str) -> bool:
    for modifier in _dict_list(raw_track.get("modifiers")):
        if marker in _resource_type(modifier).casefold():
            return True
    return False


def _keyframe_base(raw_keyframe: JsonDict, order: int) -> JsonDict:
    return {
        "frame": _number(
            raw_keyframe.get(
                "Key",
                raw_keyframe.get("frame", raw_keyframe.get("Frame")),
            ),
            float(order),
        ),
        "length": max(
            _number(
                raw_keyframe.get("Length", raw_keyframe.get("length")),
                1.0,
            ),
            0.0,
        ),
        "stretch": _boolean(
            raw_keyframe.get("Stretch", raw_keyframe.get("stretch")),
            False,
        ),
        "disabled": _boolean(
            raw_keyframe.get("Disabled", raw_keyframe.get("disabled")),
            False,
        ),
        "creation": _boolean(
            raw_keyframe.get(
                "IsCreationKey",
                raw_keyframe.get("isCreationKey"),
            ),
            False,
        ),
        "order": order,
    }


def _event_strings(channel_data: JsonDict) -> list[str]:
    raw_events = channel_data.get("Events", channel_data.get("events"))
    if isinstance(raw_events, list):
        return [
            value
            for value in cast(list[object], raw_events)
            if isinstance(value, str) and value
        ]
    event = channel_data.get("Event", channel_data.get("event"))
    return [event] if isinstance(event, str) and event else []


def _contains_authored_event_binding(value: object) -> bool:
    if value is None or value is False or value == "":
        return False
    if isinstance(value, dict):
        return any(
            _contains_authored_event_binding(item)
            for item in cast(dict[object, object], value).values()
        )
    if isinstance(value, list):
        return any(
            _contains_authored_event_binding(item)
            for item in cast(list[object], value)
        )
    return True


def _resource_type(data: JsonDict) -> str:
    explicit = data.get("resourceType")
    if isinstance(explicit, str) and explicit:
        return explicit
    for key in data:
        if key.startswith("$") and len(key) > 1:
            return key[1:]
    return ""


def _keyframes(value: object) -> list[JsonDict]:
    if isinstance(value, list):
        return _dict_list(cast(list[object], value))
    if not isinstance(value, dict):
        return []
    store = cast(JsonDict, value)
    return _dict_list(store.get("Keyframes", store.get("keyframes")))


def _channels(keyframe: JsonDict) -> list[tuple[int, JsonDict]]:
    raw_channels = keyframe.get("Channels", keyframe.get("channels"))
    channels: list[tuple[int, JsonDict]] = []
    if isinstance(raw_channels, dict):
        for fallback, (raw_channel, data) in enumerate(
            cast(dict[object, object], raw_channels).items()
        ):
            if not isinstance(data, dict):
                continue
            channel = _integer(raw_channel, fallback)
            channels.append((max(channel, 0), cast(JsonDict, data)))
    elif isinstance(raw_channels, list):
        for fallback, data in enumerate(cast(list[object], raw_channels)):
            if not isinstance(data, dict):
                continue
            channel_data = cast(JsonDict, data)
            channel = _integer(channel_data.get("channel"), fallback)
            channels.append((max(channel, 0), channel_data))
    return sorted(channels, key=lambda item: item[0])


def _dict_list(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    return [
        cast(JsonDict, item)
        for item in cast(list[object], value)
        if isinstance(item, dict)
    ]


def _reference_name(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    reference = cast(JsonDict, value)
    name = reference.get("name")
    return name if isinstance(name, str) else ""


def _number(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return default
    try:
        number = float(value)
    except (OverflowError, ValueError):
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
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return default


def _string(
    value: object,
    default: str,
    *,
    allow_empty: bool = False,
) -> str:
    if isinstance(value, str) and (value or allow_empty):
        return value
    return default


__all__ = [
    "SEQUENCE_DESCRIPTOR_FORMAT_VERSION",
    "SequenceCompatibilityIssue",
    "normalize_sequence_asset",
    "render_sequence_resource",
]
