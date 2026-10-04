import unittest
from typing import TypeVar, overload

from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.resource_reference_metadata import (
    capture_asset_name_declaration,
    capture_registry_resource_declaration,
    capture_sprite_resource_declaration,
)


_T = TypeVar("_T")


class _GuardedId(dict[str, JsonValue]):
    @overload
    def get(self, key: str, default: None = None) -> JsonValue: ...

    @overload
    def get(self, key: str, default: JsonValue) -> JsonValue: ...

    @overload
    def get(self, key: str, default: _T) -> JsonValue | _T: ...

    def get(self, key: str, default: JsonValue | _T = None) -> JsonValue | _T:
        if key == "name":
            raise AssertionError("unused declaration name was read")
        return super().get(key, default)


class TestResourceReferenceMetadata(unittest.TestCase):
    def test_registry_retains_name_provenance_and_raw_identity(self) -> None:
        name: JsonObject = {"future": [None, True]}
        resource_id: JsonObject = {"path": "sprites/spr_player/spr_player.yy", "name": name}
        declaration = capture_registry_resource_declaration(resource_id)
        assert declaration is not None
        self.assertEqual(declaration.path, "sprites/spr_player/spr_player.yy")
        self.assertIs(declaration.name_value, name)
        self.assertIs(declaration.raw_id, resource_id)

    def test_registry_rejects_path_before_reading_name(self) -> None:
        values: tuple[JsonValue, ...] = (None, False, 0, "", [], {})
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(capture_registry_resource_declaration(_GuardedId(path=value)))

    def test_sprite_non_sprite_does_not_read_name(self) -> None:
        resource: JsonObject = {"id": _GuardedId(path="sounds/snd_test/snd_test.yy")}
        self.assertIsNone(capture_sprite_resource_declaration(resource))

    def test_sprite_path_hint_and_path_derived_name(self) -> None:
        resource_id: JsonObject = {"path": "SPRITES/player/player.yy", "name": None}
        resource: JsonObject = {"id": resource_id, "unknown": resource_id}
        declaration = capture_sprite_resource_declaration(resource)
        assert declaration is not None
        self.assertEqual(declaration.name, "player")
        self.assertIs(declaration.raw_resource, resource)
        self.assertIs(declaration.raw_id, resource_id)

    def test_sprite_type_hints_retain_unusable_declared_path(self) -> None:
        for outer_hint in (True, False):
            path: JsonObject = {"unknown": None}
            resource_id: JsonObject = {"path": path, "name": "player"}
            resource: JsonObject = {"id": resource_id}
            (resource if outer_hint else resource_id)["resourceType"] = "GMSprite"
            declaration = capture_sprite_resource_declaration(resource)
            assert declaration is not None
            self.assertEqual(declaration.name, "player")
            self.assertIs(declaration.path_value, path)

    def test_sprite_empty_name_and_bad_id_are_filtered(self) -> None:
        resources: tuple[JsonObject, ...] = ({"id": None}, {"id": []}, {"resourceType": "GMSprite"})
        for resource in resources:
            with self.subTest(resource=resource):
                self.assertIsNone(capture_sprite_resource_declaration(resource))

    def test_asset_name_ignores_path_and_type_hints(self) -> None:
        resource_id: JsonObject = {"name": "obj_player", "path": None, "resourceType": []}
        resource: JsonObject = {"id": resource_id, "resourceType": {}}
        declaration = capture_asset_name_declaration(resource)
        self.assertEqual(declaration.name, "obj_player")
        self.assertIs(declaration.raw_id, resource_id)
        self.assertIs(declaration.raw_resource, resource)

    def test_asset_name_defaults_and_wrong_name_kinds(self) -> None:
        self.assertIsNone(capture_asset_name_declaration({}).name)
        names: tuple[JsonValue, ...] = (None, False, 2, "", [], {})
        for name in names:
            with self.subTest(name=name):
                self.assertIsNone(capture_asset_name_declaration({"id": {"name": name}}).name)

    def test_asset_name_nonobject_entry_or_id_keeps_attribute_failure(self) -> None:
        values: tuple[JsonValue, ...] = (None, False, 2, "not an object", [])
        for value in values:
            entries: tuple[JsonValue, ...] = (value, {"id": value})
            for entry in entries:
                with self.subTest(entry=entry):
                    with self.assertRaises(AttributeError) as caught:
                        capture_asset_name_declaration(entry)
                    self.assertEqual(caught.exception.name, "get")
                    self.assertIs(caught.exception.obj, value)

    def test_each_capture_observes_later_entry_mutations(self) -> None:
        resource: JsonObject = {"id": {"name": "before"}}
        first = capture_asset_name_declaration(resource)
        resource_id = resource["id"]
        assert isinstance(resource_id, dict)
        resource_id["name"] = "after"
        second = capture_asset_name_declaration(resource)
        self.assertEqual((first.name, second.name), ("before", "after"))
        self.assertIs(first.raw_id, second.raw_id)


if __name__ == "__main__":
    unittest.main()
