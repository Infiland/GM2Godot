"""Strict JSON field access with distinct missing, null and wrong-kind states."""

from enum import Enum
from typing import Final, Literal, NoReturn

from src.conversion.json_values import JsonArray, JsonObject, JsonPath, JsonValue


class JsonMissing(Enum):
    MISSING = "missing"


MISSING: Final = JsonMissing.MISSING

type JsonFieldKind = Literal["string", "number", "boolean", "array", "object"]
type JsonFieldState = Literal["missing", "null", "string", "number", "boolean", "array", "object"]


class JsonFieldError(ValueError):
    source_path: str
    field_path: JsonPath
    expected: JsonFieldKind
    actual: JsonFieldState

    def __init__(
        self,
        *,
        source_path: str,
        field_path: JsonPath,
        expected: JsonFieldKind,
        actual: JsonFieldState,
    ) -> None:
        self.source_path = source_path
        self.field_path = field_path
        self.expected = expected
        self.actual = actual
        super().__init__(f"{source_path} at {field_path!r}: expected {expected}, got {actual}")


def field_value(data: JsonObject, key: str) -> JsonValue | JsonMissing:
    return data.get(key, MISSING)


def _field_state(value: JsonValue | JsonMissing) -> JsonFieldState:
    if isinstance(value, JsonMissing):
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    return "object"


def _wrong_kind(
    value: JsonValue | JsonMissing,
    key: str,
    *,
    source_path: str,
    field_path: JsonPath,
    expected: JsonFieldKind,
) -> NoReturn:
    raise JsonFieldError(
        source_path=source_path,
        field_path=field_path + (key,),
        expected=expected,
        actual=_field_state(value),
    )


def _optional_value(
    data: JsonObject,
    key: str,
    default: JsonValue | JsonMissing,
    *,
    source_path: str,
    field_path: JsonPath,
    expected: JsonFieldKind,
) -> JsonValue | JsonMissing:
    value = field_value(data, key)
    if not isinstance(value, JsonMissing):
        return value
    if default is None:
        _wrong_kind(default, key, source_path=source_path, field_path=field_path, expected=expected)
    return default


def required_string(data: JsonObject, key: str, *, source_path: str, field_path: JsonPath = ()) -> str:
    value = field_value(data, key)
    if isinstance(value, str):
        return value
    _wrong_kind(value, key, source_path=source_path, field_path=field_path, expected="string")


def required_number(data: JsonObject, key: str, *, source_path: str, field_path: JsonPath = ()) -> int | float:
    value = field_value(data, key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    _wrong_kind(value, key, source_path=source_path, field_path=field_path, expected="number")


def required_boolean(data: JsonObject, key: str, *, source_path: str, field_path: JsonPath = ()) -> bool:
    value = field_value(data, key)
    if isinstance(value, bool):
        return value
    _wrong_kind(value, key, source_path=source_path, field_path=field_path, expected="boolean")


def required_array(data: JsonObject, key: str, *, source_path: str, field_path: JsonPath = ()) -> JsonArray:
    value = field_value(data, key)
    if isinstance(value, list):
        return value
    _wrong_kind(value, key, source_path=source_path, field_path=field_path, expected="array")


def required_object(data: JsonObject, key: str, *, source_path: str, field_path: JsonPath = ()) -> JsonObject:
    value = field_value(data, key)
    if isinstance(value, dict):
        return value
    _wrong_kind(value, key, source_path=source_path, field_path=field_path, expected="object")


def optional_string(
    data: JsonObject,
    key: str,
    *,
    source_path: str,
    field_path: JsonPath = (),
    default: JsonValue | JsonMissing = MISSING,
) -> str | None | JsonMissing:
    value = _optional_value(
        data, key, default, source_path=source_path, field_path=field_path, expected="string"
    )
    if isinstance(value, JsonMissing) or value is None or isinstance(value, str):
        return value
    _wrong_kind(value, key, source_path=source_path, field_path=field_path, expected="string")


def optional_number(
    data: JsonObject,
    key: str,
    *,
    source_path: str,
    field_path: JsonPath = (),
    default: JsonValue | JsonMissing = MISSING,
) -> int | float | None | JsonMissing:
    value = _optional_value(
        data, key, default, source_path=source_path, field_path=field_path, expected="number"
    )
    if isinstance(value, JsonMissing) or value is None:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    _wrong_kind(value, key, source_path=source_path, field_path=field_path, expected="number")


def optional_boolean(
    data: JsonObject,
    key: str,
    *,
    source_path: str,
    field_path: JsonPath = (),
    default: JsonValue | JsonMissing = MISSING,
) -> bool | None | JsonMissing:
    value = _optional_value(
        data, key, default, source_path=source_path, field_path=field_path, expected="boolean"
    )
    if isinstance(value, JsonMissing) or value is None or isinstance(value, bool):
        return value
    _wrong_kind(value, key, source_path=source_path, field_path=field_path, expected="boolean")


def optional_array(
    data: JsonObject,
    key: str,
    *,
    source_path: str,
    field_path: JsonPath = (),
    default: JsonValue | JsonMissing = MISSING,
) -> JsonArray | None | JsonMissing:
    value = _optional_value(
        data, key, default, source_path=source_path, field_path=field_path, expected="array"
    )
    if isinstance(value, JsonMissing) or value is None or isinstance(value, list):
        return value
    _wrong_kind(value, key, source_path=source_path, field_path=field_path, expected="array")


def optional_object(
    data: JsonObject,
    key: str,
    *,
    source_path: str,
    field_path: JsonPath = (),
    default: JsonValue | JsonMissing = MISSING,
) -> JsonObject | None | JsonMissing:
    value = _optional_value(
        data, key, default, source_path=source_path, field_path=field_path, expected="object"
    )
    if isinstance(value, JsonMissing) or value is None or isinstance(value, dict):
        return value
    _wrong_kind(value, key, source_path=source_path, field_path=field_path, expected="object")
