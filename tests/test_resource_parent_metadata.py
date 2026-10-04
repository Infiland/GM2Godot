import dataclasses
import json
import sys
import unittest
from collections.abc import Iterator
from typing import overload

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonArray, JsonObject, JsonValue
from src.conversion.resource_parent_metadata import (
    GameMakerResourceParentMetadata,
    parse_gamemaker_resource_parent_metadata,
)


class _ObservedObject(dict[str, JsonValue]):
    def __init__(
        self,
        values: JsonObject,
        *,
        label: str,
        trace: list[tuple[str, str, int]],
        error: BaseException | None = None,
    ) -> None:
        super().__init__(values)
        self.label = label
        self.trace = trace
        self.error = error

    @overload
    def get(self, key: str, default: None = None, /) -> JsonValue: ...

    @overload
    def get(self, key: str, default: JsonValue, /) -> JsonValue: ...

    @overload
    def get[T](self, key: str, default: T, /) -> JsonValue | T: ...

    def get[T](self, key: str, /, *defaults: T) -> JsonValue | T:
        self.trace.append((self.label, key, len(defaults)))
        if self.error is not None:
            raise self.error
        if defaults:
            return super().get(key, defaults[0])
        return super().get(key)

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("parent projection must not traverse objects")

    def __bool__(self) -> bool:
        raise AssertionError("parent projection must not test object truthiness")


class _ObservedString(str):
    def __bool__(self) -> bool:
        raise AssertionError("parent projection must not test string truthiness")

    def __str__(self) -> str:
        raise AssertionError("parent projection must not coerce strings")


class TestResourceParentMetadata(unittest.TestCase):
    def test_frozen_field_order_defaults_and_fresh_raw_objects(self) -> None:
        self.assertEqual(
            [field.name for field in dataclasses.fields(GameMakerResourceParentMetadata)],
            ["parent_path", "raw_data", "has_parent_path"],
        )
        first = GameMakerResourceParentMetadata()
        second = GameMakerResourceParentMetadata()
        self.assertEqual(first.parent_path, "")
        self.assertIs(first.has_parent_path, False)
        self.assertEqual(first.raw_data, {})
        self.assertIsNot(first.raw_data, second.raw_data)
        first.raw_data["unknown"] = 7
        self.assertEqual(second.raw_data, {})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(first, "parent_path", "new")

    def test_actual_decoder_preserves_raw_root_parent_and_child_identity(self) -> None:
        document = decode_gamemaker_json(
            '{"unknown":{"last":[null,4],"first":1},'
            '"parent":{"path":"folders/Sprites/Enemy.yy","extra":[3]},}',
            source_path="sprites/enemy/enemy.yy",
        )
        assert isinstance(document.value, dict)
        data = document.value
        parent = data["parent"]
        assert isinstance(parent, dict)
        metadata = parse_gamemaker_resource_parent_metadata(data)
        self.assertEqual(metadata.parent_path, "folders/Sprites/Enemy.yy")
        self.assertIs(metadata.has_parent_path, True)
        self.assertIs(metadata.parent_path, parent["path"])
        self.assertIs(metadata.raw_data, data)
        self.assertIs(metadata.raw_data["parent"], parent)
        self.assertIs(metadata.raw_data["unknown"], data["unknown"])
        self.assertEqual(list(metadata.raw_data), ["unknown", "parent"])

    def test_missing_null_and_nonobject_parent_are_silent_empty_defaults(self) -> None:
        values: tuple[JsonValue, ...] = (None, False, True, 0, 1.25, "path", [], ["path"])
        missing: JsonObject = {}
        self.assertEqual(parse_gamemaker_resource_parent_metadata(missing).parent_path, "")
        for value in values:
            with self.subTest(kind=type(value).__name__):
                data: JsonObject = {"parent": value}
                metadata = parse_gamemaker_resource_parent_metadata(data)
                self.assertEqual(metadata.parent_path, "")
                self.assertIs(metadata.has_parent_path, False)
                self.assertIs(metadata.raw_data, data)
                self.assertIs(metadata.raw_data["parent"], value)

    def test_missing_null_and_nonstring_path_are_silent_empty_defaults(self) -> None:
        values: tuple[JsonValue, ...] = (None, False, True, 0, 1.25, [], {}, ["path"])
        self.assertEqual(parse_gamemaker_resource_parent_metadata({"parent": {}}).parent_path, "")
        for value in values:
            with self.subTest(kind=type(value).__name__):
                parent: JsonObject = {"path": value}
                data: JsonObject = {"parent": parent}
                metadata = parse_gamemaker_resource_parent_metadata(data)
                self.assertEqual(metadata.parent_path, "")
                self.assertIs(metadata.has_parent_path, False)
                self.assertIs(metadata.raw_data["parent"], parent)
                self.assertIs(parent["path"], value)

    def test_path_spelling_is_captured_without_folder_formatting(self) -> None:
        for path in (
            "", "folders/Sprites/AI.yy", "Folders/Sprites/AI.YY", "folders\\Sprites\\AI.yy",
            "folders//Sprites///AI.yy", " folders/Sprites/Ångström !.yy ",
        ):
            with self.subTest(path=path):
                metadata = parse_gamemaker_resource_parent_metadata({"parent": {"path": path}})
                self.assertIs(metadata.parent_path, path)
                self.assertIs(metadata.has_parent_path, True)

    def test_virtual_dictionary_and_string_subclasses_keep_identity_and_lookup_order(self) -> None:
        trace: list[tuple[str, str, int]] = []
        path = _ObservedString("folders/Sprites/Enemy.yy")
        parent = _ObservedObject({"path": path}, label="parent", trace=trace)
        data = _ObservedObject({"parent": parent}, label="root", trace=trace)
        metadata = parse_gamemaker_resource_parent_metadata(data)
        self.assertEqual(trace, [("root", "parent", 0), ("parent", "path", 0)])
        self.assertIs(metadata.parent_path, path)
        self.assertIs(metadata.has_parent_path, True)
        self.assertIs(metadata.raw_data, data)
        self.assertIs(metadata.raw_data["parent"], parent)

    def test_parent_lookup_is_not_repeated_and_path_lookup_needs_an_object(self) -> None:
        parents: tuple[JsonValue, ...] = (None, False, 7, "path", [], ["path"])
        for parent in parents:
            trace: list[tuple[str, str, int]] = []
            data = _ObservedObject({"parent": parent}, label="root", trace=trace)
            metadata = parse_gamemaker_resource_parent_metadata(data)
            self.assertEqual(metadata.parent_path, "")
            self.assertEqual(trace, [("root", "parent", 0)])

    def test_empty_parent_subclass_still_gets_path_without_truthiness(self) -> None:
        trace: list[tuple[str, str, int]] = []
        parent = _ObservedObject({}, label="parent", trace=trace)
        metadata = parse_gamemaker_resource_parent_metadata({"parent": parent})
        self.assertEqual(metadata.parent_path, "")
        self.assertIs(metadata.has_parent_path, False)
        self.assertEqual(trace, [("parent", "path", 0)])

    def test_empty_string_subclass_is_retained_without_truthiness(self) -> None:
        path = _ObservedString("")
        metadata = parse_gamemaker_resource_parent_metadata({"parent": {"path": path}})
        self.assertIs(metadata.parent_path, path)
        self.assertIs(metadata.has_parent_path, True)

    def test_valid_empty_path_is_distinct_from_missing_null_or_wrong_kind(self) -> None:
        valid = parse_gamemaker_resource_parent_metadata({"parent": {"path": ""}})
        self.assertEqual(valid.parent_path, "")
        self.assertIs(valid.has_parent_path, True)
        invalid: tuple[JsonObject, ...] = ({}, {"parent": None}, {"parent": {}},
                                         {"parent": {"path": None}}, {"parent": {"path": 0}})
        for data in invalid:
            with self.subTest(data=data):
                captured = parse_gamemaker_resource_parent_metadata(data)
                self.assertEqual(captured.parent_path, valid.parent_path)
                self.assertIs(captured.has_parent_path, False)

    def test_captured_path_stays_authoritative_while_raw_root_remains_live(self) -> None:
        parent: JsonObject = {"path": "folders/Sprites/Original.yy"}
        data: JsonObject = {"parent": parent}
        original = parse_gamemaker_resource_parent_metadata(data)
        parent["path"] = "folders/Sprites/Changed.yy"
        changed = parse_gamemaker_resource_parent_metadata(data)
        replacement: JsonObject = {"path": "folders/Sprites/Replaced.yy"}
        data["parent"] = replacement
        replaced = parse_gamemaker_resource_parent_metadata(data)
        self.assertEqual(original.parent_path, "folders/Sprites/Original.yy")
        self.assertEqual(changed.parent_path, "folders/Sprites/Changed.yy")
        self.assertEqual(replaced.parent_path, "folders/Sprites/Replaced.yy")
        self.assertIs(original.raw_data["parent"], replacement)
        self.assertIs(changed.raw_data, data)

    def test_unknown_deep_shared_and_cyclic_virtual_data_is_not_traversed(self) -> None:
        limit = sys.getrecursionlimit()
        deep: JsonValue = None
        for _ in range(1500):
            deep = [deep]
        shared: JsonObject = {"extra": [3, 2, 1]}
        cycle: JsonArray = []
        cycle.append(cycle)
        data: JsonObject = {
            "deep": deep, "shared_first": shared, "shared_second": shared,
            "cycle": cycle, "parent": {"path": "folders/Sprites/AI.yy"},
        }
        metadata = parse_gamemaker_resource_parent_metadata(data)
        self.assertEqual(metadata.parent_path, "folders/Sprites/AI.yy")
        self.assertIs(metadata.raw_data, data)
        self.assertIs(metadata.raw_data["deep"], deep)
        self.assertIs(metadata.raw_data["shared_first"], metadata.raw_data["shared_second"])
        self.assertIs(metadata.raw_data["cycle"], cycle)
        self.assertIs(cycle[0], cycle)
        self.assertEqual(list(data), ["deep", "shared_first", "shared_second", "cycle", "parent"])
        self.assertEqual(sys.getrecursionlimit(), limit)

    def test_overridden_get_exceptions_escape_with_exact_instance_and_position(self) -> None:
        errors = (
            KeyError("get-key"), TypeError("get-type"), AttributeError("get-attribute"),
            ValueError("get-value"), OverflowError("get-overflow"), RuntimeError("get-runtime"),
            MemoryError("get-memory"), KeyboardInterrupt("get-control"), SystemExit("get-exit"),
        )
        for stage in ("root", "parent"):
            for error in errors:
                with self.subTest(stage=stage, error_type=type(error).__name__):
                    trace: list[tuple[str, str, int]] = []
                    parent = _ObservedObject(
                        {"path": "ignored"}, label="parent", trace=trace,
                        error=error if stage == "parent" else None,
                    )
                    data = _ObservedObject(
                        {"parent": parent}, label="root", trace=trace,
                        error=error if stage == "root" else None,
                    )
                    with self.assertRaises(type(error)) as raised:
                        parse_gamemaker_resource_parent_metadata(data)
                    self.assertIs(raised.exception, error)
                    self.assertEqual(
                        trace,
                        [("root", "parent", 0)] if stage == "root"
                        else [("root", "parent", 0), ("parent", "path", 0)],
                    )

    def test_shallow_dataclass_reflection_contains_only_the_public_json_state(self) -> None:
        data: JsonObject = {"parent": {"path": "folders/Sprites/AI.yy"}, "extra": [None, 7]}
        metadata = parse_gamemaker_resource_parent_metadata(data)
        self.assertEqual(dataclasses.asdict(metadata),
                         {"parent_path": metadata.parent_path, "raw_data": data, "has_parent_path": True})
        self.assertEqual(json.loads(json.dumps(dataclasses.asdict(metadata)))["raw_data"], data)


if __name__ == "__main__":
    unittest.main()
