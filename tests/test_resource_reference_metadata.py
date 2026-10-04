import unittest
from typing import TypeVar, overload

from src.conversion.json_values import JsonArray, JsonObject, JsonValue, validate_json_value
from src.conversion.resource_reference_metadata import (
    capture_asset_name_declaration,
    capture_registry_resource_declaration,
    capture_sprite_resource_declaration,
    capture_tileset_resource_declaration,
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


class _ObservedObject(dict[str, JsonValue]):
    def __init__(self, values: JsonObject, trace: list[str], label: str) -> None:
        super().__init__(values)
        self.trace = trace
        self.label = label

    @overload
    def get(self, key: str, default: None = None) -> JsonValue: ...

    @overload
    def get(self, key: str, default: JsonValue) -> JsonValue: ...

    @overload
    def get(self, key: str, default: _T) -> JsonValue | _T: ...

    def get(self, key: str, default: JsonValue | _T = None) -> JsonValue | _T:
        self.trace.append(f"{self.label}.{key}")
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

    def test_tileset_path_hint_normalizes_backslashes_and_case_before_name_fallback(self) -> None:
        resource_id: JsonObject = {"path": "TiLeSeTs\\Rock\\Rock.yy", "name": None}
        resource: JsonObject = {"id": resource_id, "resourceType": "GMObject"}
        declaration = capture_tileset_resource_declaration(resource)
        assert declaration is not None
        self.assertEqual(declaration.name, "Rock")
        self.assertEqual(declaration.path, "TiLeSeTs/Rock/Rock.yy")
        self.assertEqual(declaration.path_value, "TiLeSeTs\\Rock\\Rock.yy")
        self.assertIs(declaration.raw_id, resource_id)
        self.assertIs(declaration.raw_resource, resource)

    def test_tileset_type_hints_retain_unusable_path_values_without_coercion(self) -> None:
        paths: JsonArray = [None, False, 0, [], {"future": [None, True]}]
        for outer_hint in (True, False):
            for path in paths:
                with self.subTest(outer_hint=outer_hint, path=path):
                    resource_id: JsonObject = {"path": path, "name": "declared"}
                    resource: JsonObject = {"id": resource_id}
                    (resource if outer_hint else resource_id)["resourceType"] = "GMTileSet"
                    declaration = capture_tileset_resource_declaration(resource)
                    assert declaration is not None
                    self.assertEqual(declaration.name, "declared")
                    self.assertEqual(declaration.path, "")
                    self.assertIs(declaration.path_value, path)
                    self.assertIs(declaration.raw_id, resource_id)

    def test_tileset_malformed_id_and_name_kinds_keep_filter_and_path_fallback(self) -> None:
        values: JsonArray = [None, False, 0, "", [], {}]
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(capture_tileset_resource_declaration({"resourceType": "GMTileSet", "id": value}))
                self.assertIsNone(capture_tileset_resource_declaration({
                    "resourceType": "GMTileSet", "id": {"path": None, "name": value},
                }))
                declaration = capture_tileset_resource_declaration({
                    "id": {"path": "tilesets/Fallback/Fallback.yy", "name": value},
                })
                assert declaration is not None
                self.assertEqual(declaration.name, "Fallback")
        self.assertIsNone(capture_tileset_resource_declaration({"resourceType": "GMTileSet"}))
        whitespace = capture_tileset_resource_declaration({"resourceType": "GMTileSet", "id": {"name": " "}})
        assert whitespace is not None
        self.assertEqual(whitespace.name, " ")

    def test_tileset_nonqualifying_entry_does_not_observe_guarded_name(self) -> None:
        paths: JsonArray = [None, [], "sounds/one/one.yy", "nested/tilesets/one.yy", "tilesets_extra/one.yy"]
        for path in paths:
            with self.subTest(path=path):
                resource: JsonObject = {
                    "id": _GuardedId(path=path, resourceType="gmtileSet"),
                    "resourceType": {"future": "GMTileSet"},
                }
                self.assertIsNone(capture_tileset_resource_declaration(resource))

    def test_tileset_capture_keeps_per_entry_getter_order_and_fresh_observation(self) -> None:
        trace: list[str] = []
        resource_id = _ObservedObject({"path": "tilesets/one/one.yy", "name": "before"}, trace, "id")
        resource = _ObservedObject({"id": resource_id}, trace, "resource")
        first = capture_tileset_resource_declaration(resource)
        assert first is not None
        self.assertEqual(trace, ["resource.id", "id.path", "resource.resourceType", "id.resourceType", "id.name"])
        resource_id["name"] = "after"
        resource_id["path"] = "tilesets/two/two.yy"
        trace.clear()
        second = capture_tileset_resource_declaration(resource)
        assert second is not None
        self.assertEqual((first.name, second.name), ("before", "after"))
        self.assertEqual((first.path, second.path), ("tilesets/one/one.yy", "tilesets/two/two.yy"))
        self.assertIs(first.raw_id, second.raw_id)
        self.assertEqual(trace, ["resource.id", "id.path", "resource.resourceType", "id.resourceType", "id.name"])

    def test_tileset_deep_unknown_shared_members_and_native_key_order_remain_identical(self) -> None:
        shared: JsonArray = [None, False, {"future": "value"}]
        nested: JsonObject = {"shared": shared}
        for _ in range(1600):
            nested = {"next": nested}
        resource_id: JsonObject = {"unknown": shared, "name": "deep", "path": "tilesets/deep/deep.yy"}
        resource: JsonObject = {"future": nested, "id": resource_id, "shared": shared}
        self.assertIs(validate_json_value(resource, source_path="Project.yyp"), resource)
        resource_keys = tuple(resource)
        id_keys = tuple(resource_id)
        declaration = capture_tileset_resource_declaration(resource)
        assert declaration is not None
        self.assertIs(declaration.raw_resource, resource)
        self.assertIs(declaration.raw_id, resource_id)
        self.assertIs(declaration.raw_resource["future"], nested)
        self.assertIs(declaration.raw_resource["shared"], shared)
        self.assertIs(declaration.raw_id["unknown"], shared)
        self.assertEqual(tuple(resource), resource_keys)
        self.assertEqual(tuple(resource_id), id_keys)


if __name__ == "__main__":
    unittest.main()
