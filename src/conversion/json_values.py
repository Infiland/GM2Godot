"""Recursive JSON values with an exhaustive, identity-preserving boundary."""

from typing import Literal, TypeGuard, cast

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | JsonArray | JsonObject
type JsonArray = list[JsonValue]
type JsonObject = dict[str, JsonValue]
type JsonPath = tuple[str | int, ...]
type JsonValueProblem = Literal["unsupported-type", "non-string-key", "cycle"]


class JsonValueError(ValueError):
    """A non-JSON value at a structural path in a source document."""

    source_path: str
    field_path: JsonPath
    expected: str
    actual: str
    reason: JsonValueProblem

    def __init__(
        self,
        *,
        source_path: str,
        field_path: JsonPath,
        expected: str,
        actual: str,
        reason: JsonValueProblem,
    ) -> None:
        self.source_path = source_path
        self.field_path = field_path
        self.expected = expected
        self.actual = actual
        self.reason = reason
        super().__init__(
            f"{source_path} at {field_path!r}: expected {expected}, got {actual} ({reason})"
        )


def _is_native_array(value: object) -> TypeGuard[list[object]]:
    # Every native list member is an object; this makes no claim about JSON.
    return type(value) is list


def _is_native_object(value: object) -> TypeGuard[dict[object, object]]:
    # Keys and values still require exhaustive validation below.
    return type(value) is dict


def _is_native_string(value: object) -> TypeGuard[str]:
    return type(value) is str


def validate_json_value(
    value: object,
    *,
    source_path: str,
    field_path: JsonPath = (),
) -> JsonValue:
    """Prove native JSON types without copying, recursion or a depth limit.

    Active ancestors detect cycles separately from completed subtrees, so a
    shared acyclic child is legal. Numeric finiteness is a separate policy;
    this boundary preserves the standard decoder's nonfinite float values.
    """
    pending: list[tuple[object, JsonPath, bool]] = [(value, field_path, False)]
    active: set[int] = set()
    completed: set[int] = set()

    while pending:
        current, current_path, leaving = pending.pop()
        if leaving:
            current_id = id(current)
            active.remove(current_id)
            completed.add(current_id)
            continue

        if current is None or type(current) in (str, int, float, bool):
            continue

        if _is_native_array(current):
            current_id = id(current)
            if current_id in active:
                raise JsonValueError(
                    source_path=source_path,
                    field_path=current_path,
                    expected="acyclic array or object",
                    actual="array",
                    reason="cycle",
                )
            if current_id in completed:
                continue
            active.add(current_id)
            pending.append((current, current_path, True))
            for index in range(len(current) - 1, -1, -1):
                pending.append((current[index], current_path + (index,), False))
            continue

        if _is_native_object(current):
            current_id = id(current)
            if current_id in active:
                raise JsonValueError(
                    source_path=source_path,
                    field_path=current_path,
                    expected="acyclic array or object",
                    actual="object",
                    reason="cycle",
                )
            if current_id in completed:
                continue
            entries: list[tuple[str, object]] = []
            for key, child in current.items():
                if not _is_native_string(key):
                    raise JsonValueError(
                        source_path=source_path,
                        field_path=current_path,
                        expected="string key",
                        actual=type(key).__name__,
                        reason="non-string-key",
                    )
                entries.append((key, child))
            active.add(current_id)
            pending.append((current, current_path, True))
            for key, child in reversed(entries):
                pending.append((child, current_path + (key,), False))
            continue

        raise JsonValueError(
            source_path=source_path,
            field_path=current_path,
            expected="JSON scalar, array, or object",
            actual=type(current).__name__,
            reason="unsupported-type",
        )

    # Every reachable native key and value is now proven. This is the sole
    # narrowing cast at the object-to-recursive-JSON boundary.
    return cast(JsonValue, value)
