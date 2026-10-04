"""Pure views of GameMaker objects and event fields.

Acquisition validates JSON graphs. These views capture only the fields used at
an owner's current stage; source resolution and event sanitation stay there.
"""

from dataclasses import dataclass, field

from src.conversion.json_values import JsonObject, JsonScalar, JsonValue


def _empty_object() -> JsonObject:
    return {}


@dataclass(frozen=True)
class GameMakerObjectMetadata:
    sprite_name: str | None = None
    parent_object_name: str | None = None
    event_count: int = 0
    persistent: bool = False
    solid: bool = False
    raw_data: JsonObject = field(default_factory=_empty_object)
    source_context: str = field(default="", compare=False, repr=False)


def _reference_name(value: JsonValue) -> str | None:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    return name if isinstance(name, str) and name else None


def parse_gamemaker_object_metadata(
    data: JsonObject, *, source_context: str
) -> GameMakerObjectMetadata:
    sprite_name = _reference_name(data.get("spriteId"))
    parent_name = _reference_name(data.get("parentObjectId"))
    events = data.get("eventList")
    event_count = sum(isinstance(event, dict) for event in events) if isinstance(events, list) else 0
    return GameMakerObjectMetadata(
        sprite_name=sprite_name,
        parent_object_name=parent_name,
        event_count=event_count,
        persistent=bool(data.get("persistent", False)),
        solid=bool(data.get("solid", False)),
        raw_data=data,
        source_context=source_context,
    )


@dataclass(frozen=True)
class GameMakerObjectResourceReference:
    raw_value: JsonValue
    path_value: JsonValue = None
    name_value: JsonValue = None
    path_present: bool = False
    source_context: str = field(default="", compare=False, repr=False)

    @property
    def is_object(self) -> bool:
        return isinstance(self.raw_value, dict)


def capture_gamemaker_object_resource_reference(
    value: JsonValue, *, source_context: str
) -> GameMakerObjectResourceReference:
    if not isinstance(value, dict):
        return GameMakerObjectResourceReference(value, source_context=source_context)
    path = value.get("path")
    name = value.get("name")
    present = "path" in value
    return GameMakerObjectResourceReference(value, path, name, present, source_context)


def _event_hash_key(value: JsonValue) -> JsonScalar:
    if isinstance(value, (list, dict)):
        raise TypeError(f"unhashable type: '{type(value).__name__}'")
    return value


@dataclass(frozen=True)
class GameMakerEventMappingInputs:
    event_type: JsonValue
    event_num: JsonValue

    def type_key(self) -> JsonScalar:
        return _event_hash_key(self.event_type)

    def event_key(self) -> tuple[JsonScalar, JsonScalar]:
        return self.type_key(), _event_hash_key(self.event_num)


def capture_gamemaker_event_mapping_inputs(event: JsonObject) -> GameMakerEventMappingInputs:
    return GameMakerEventMappingInputs(event.get("eventType", -1), event.get("eventNum", 0))


def capture_gamemaker_event_type(event: JsonObject) -> JsonScalar:
    return _event_hash_key(event.get("eventType", -1))


def gamemaker_event_integer(value: JsonValue) -> int:
    """Apply the existing input/script integer coercion, without inventing one."""
    if isinstance(value, (str, int, float)):
        return int(value)
    raise TypeError(
        "int() argument must be a string, a bytes-like object or a real number, "
        f"not '{type(value).__name__}'"
    )


@dataclass(frozen=True)
class GameMakerInputEventFields:
    event_type: int
    event_num: int


def project_gamemaker_input_event_fields(event: JsonObject) -> GameMakerInputEventFields:
    event_type = gamemaker_event_integer(event.get("eventType", -1))
    event_num = gamemaker_event_integer(event.get("eventNum", 0))
    return GameMakerInputEventFields(event_type, event_num)
