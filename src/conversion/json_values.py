"""Recursive JSON values with validation that preserves the supplied tree."""

from __future__ import annotations

import json
from typing import TypeAlias, TypeGuard, cast

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
JsonArray: TypeAlias = list[JsonValue]
JsonFieldPath: TypeAlias = tuple[str | int, ...]

_NO_INVALID_KEY = object()


class JsonValueError(ValueError):
    """A non-JSON native value at a precise structural location."""

    def __init__(
        self,
        field_path: JsonFieldPath,
        expected: str,
        actual_type: str,
        *,
        invalid_key: object = _NO_INVALID_KEY,
    ) -> None:
        self.field_path = field_path
        self.expected = expected
        self.actual_type = actual_type
        self.invalid_key = invalid_key
        message = f"{format_json_field_path(field_path)}: expected {expected}, got {actual_type}"
        if invalid_key is not _NO_INVALID_KEY:
            message += f" (key {invalid_key!r})"
        super().__init__(message)


def format_json_field_path(path: JsonFieldPath) -> str:
    """Render keys and array indexes without treating dotted keys as nesting."""
    result = ""
    for component in path:
        if isinstance(component, int):
            result += f"[{component}]"
        elif component.isidentifier():
            result += ("." if result else "") + component
        else:
            result += f"[{json.dumps(component, ensure_ascii=False)}]"
    return result or "$"


def _is_container(value: object) -> TypeGuard[dict[object, object] | list[object]]:
    """Narrow only the container; its contents still require validation."""
    return isinstance(value, (dict, list))


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def validate_json_value(value: object, *, field_path: JsonFieldPath = ()) -> JsonValue:
    """Validate every value without copying or adding a recursive call limit.

    Only active ancestors indicate a cycle; shared acyclic children remain valid.
    Python's existing nonfinite float support is intentionally retained.
    """
    pending: list[tuple[object, JsonFieldPath, bool]] = [(value, field_path, False)]
    ancestors: set[int] = set()
    while pending:
        current, path, leaving = pending.pop()
        if leaving:
            ancestors.remove(id(current))
            continue
        if _is_scalar(current):
            continue
        if not _is_container(current):
            raise JsonValueError(path, "JSON value", type(current).__name__)
        identity = id(current)
        if identity in ancestors:
            raise JsonValueError(path, "acyclic JSON value", type(current).__name__)
        ancestors.add(identity)
        pending.append((current, (), True))
        if isinstance(current, dict):
            for key, child in reversed(current.items()):
                if not isinstance(key, str):
                    raise JsonValueError(
                        path, "string dictionary key", type(key).__name__, invalid_key=key,
                    )
                if not _is_scalar(child):
                    pending.append((child, (*path, key), False))
        else:
            for index in range(len(current) - 1, -1, -1):
                child = current[index]
                if not _is_scalar(child):
                    pending.append((child, (*path, index), False))
    return cast(JsonValue, value)
