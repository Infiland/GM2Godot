"""Staged timeline input captures and consumed normalized moment/action fields."""

from __future__ import annotations

from dataclasses import dataclass

from src.conversion.json_values import JsonArray, JsonObject, JsonValue


@dataclass(frozen=True, slots=True)
class TimelineActionFields:
    kind: str
    script: str = ""
    callable_name: str = ""
    raw_data: JsonObject | None = None

    def to_json(self) -> JsonObject:
        if self.kind == "script":
            return {"kind": self.kind, "script": self.script}
        if self.kind == "callable":
            return {"kind": self.kind, "callable": self.callable_name}
        return {"kind": self.kind, "raw": self.raw_data}


@dataclass(frozen=True, slots=True)
class TimelineMomentFields:
    frame: int
    order: int
    actions: list[JsonObject]
    source_path: str

    def to_json(self) -> JsonObject:
        return {
            "frame": self.frame,
            "order": self.order,
            "actions": [action for action in self.actions],
            "source_path": self.source_path,
        }


def timeline_moment_count(data: JsonObject) -> int:
    """Keep aggregate momentList counting distinct from registry fallbacks."""
    moments = data.get("momentList")
    return sum(isinstance(moment, dict) for moment in moments) if isinstance(moments, list) else 0


def capture_timeline_moment_list(data: JsonObject) -> JsonArray:
    moments = data.get("momentList")
    if not isinstance(moments, list):
        moments = data.get("moments")
    return moments if isinstance(moments, list) else []


def capture_timeline_moment_frame(moment: JsonObject, index: int) -> JsonValue:
    # dict.get defaults are eagerly evaluated, in time -> frame -> moment order.
    return moment.get("moment", moment.get("frame", moment.get("time", index)))


def capture_timeline_action_fields(value: JsonValue) -> TimelineActionFields | None:
    if isinstance(value, str) and value:
        return TimelineActionFields("script", script=value)
    if not isinstance(value, dict):
        return None
    callable_name = value.get("callable")
    if isinstance(callable_name, str) and callable_name:
        return TimelineActionFields("callable", callable_name=callable_name)
    script = value.get("script") or value.get("scriptName") or value.get("name")
    if isinstance(script, str) and script:
        return TimelineActionFields("script", script=script)
    return TimelineActionFields("metadata", raw_data=value)
