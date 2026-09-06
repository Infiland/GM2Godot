"""Canonical script schema, identity and aggregate consumption."""

from __future__ import annotations

from dataclasses import MISSING, FrozenInstanceError, fields
from unittest.mock import patch

from src.conversion.gamemaker_json import GameMakerJsonDocument
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.project_source_paths import ProjectSourcePathError
from src.conversion.resource_models import ResourceModel, ScriptModel, parse_gamemaker_resource_models
from src.conversion.script_model import ScriptModel as CanonicalScriptModel, dependency_script_names
from tests.script_source_support import ScriptFixture


class TestScriptModel(ScriptFixture):
    def test_nine_fields_defaults_and_raw_identity(self) -> None:
        first = ScriptModel("manifest", "scripts", "GMScript", "/owner.yy", "scripts/owner.yy", 4)
        second = ScriptModel("other", "scripts", "GMScript", "/other.yy", "scripts/other.yy", 5)
        self.assertEqual(tuple(item.name for item in fields(first)), (
            "name", "kind", "resource_type", "yy_path", "yyp_path", "order",
            "subfolder", "raw_data", "gml_path",
        ))
        self.assertTrue(all(item.default is MISSING and item.default_factory is MISSING for item in fields(first)[:6]))
        self.assertEqual((first.subfolder, first.raw_data, first.gml_path), ("", {}, None))
        self.assertIsNot(first.raw_data, second.raw_data)
        first.raw_data["new"] = 1
        self.assertEqual(second.raw_data, {})
        nested: JsonObject = {"items": [1, {"unknown": True}]}
        raw: JsonObject = {"%Name": "conflict", "unknown": nested}
        supplied = ScriptModel(
            "manifest", "scripts", "GMScript", "/owner.yy", "scripts/owner.yy", 4,
            "Tools", raw, "/owner.gml",
        )
        self.assertIs(supplied.raw_data, raw)
        self.assertIs(supplied.raw_data["unknown"], nested)
        nested["later"] = "visible"
        self.assertEqual(supplied.raw_data["unknown"], nested)
        with self.assertRaises(FrozenInstanceError):
            supplied.__setattr__("name", "changed")
        self.assertEqual(supplied.name, "manifest")

    def assert_parent_metadata(self, parent: JsonValue, expected: str) -> None:
        raw: JsonObject = {
            "%Name": "percent-conflict", "name": "raw-conflict",
            "resourceType": "GMSound", "parent": parent,
            "unknown": {"nested": [1, 2]},
        }
        self.write_json(self.root / self.owner, raw)
        self.write_json(self.root / "project.yyp", {
            "resourceType": "GMProject", "RoomOrderNodes": [], "resources": [{
                "id": {"name": "manifest", "path": self.owner}, "order": 17, "resourceType": "GMScript",
            }],
        })
        document = GameMakerJsonDocument(str(self.root / self.owner), "preserved source", raw)
        with patch("src.conversion.resource_models.read_gamemaker_json", return_value=document) as reader:
            models = parse_gamemaker_resource_models(str(self.root))
        reader.assert_called_once_with(str(self.root / self.owner))
        self.assertEqual(len(models.scripts), 1)
        model = models.scripts[0]
        self.assertEqual((model.name, model.kind, model.resource_type, model.yy_path, model.yyp_path, model.order), (
            "manifest", "scripts", "GMScript", str(self.root / self.owner), self.owner, 17,
        ))
        self.assertEqual(model.subfolder, expected)
        self.assertIs(model.raw_data, raw)
        self.assertIs(model.raw_data["unknown"], raw["unknown"])
        self.assertIsNone(model.gml_path)

    def test_manifest_metadata_and_subfolder_defaults(self) -> None:
        cases: tuple[tuple[JsonValue, str], ...] = (
            (None, ""), ("folder", ""), ({}, ""), ({"path": None}, ""),
            ({"path": 7}, ""), ({"path": "folders/Scripts.yy"}, ""),
            ({"path": "folders/Scripts/Tools.yy"}, "tools"),
            ({"path": "folders/Scripts/A/B.yy"}, "a/b"),
        )
        for parent, expected in cases:
            with self.subTest(parent=parent):
                self.assert_parent_metadata(parent, expected)
        # Missing parent is a separate actual reader case, not a None alias.
        self.raw.pop("parent", None)
        self.write_project()
        model = parse_gamemaker_resource_models(str(self.root)).scripts[0]
        self.assertEqual(model.subfolder, "")
        self.assertNotIn("parent", model.raw_data)

    def assert_dependency_names(self, raw: JsonObject, expected: tuple[str, ...]) -> None:
        model = CanonicalScriptModel("manifest", "scripts", "GMScript", str(self.root / self.owner), self.owner, 0,
                                     raw_data=raw)
        self.assertEqual(dependency_script_names(model), tuple(name[:-4] for name in expected))
        self.assertIs(model.raw_data, raw)
        self.raw = raw
        self.write_project()
        candidates: list[str] = []

        def reject(root: str, owner: str, candidate: str) -> None:
            self.assertEqual(root, str(self.root))
            self.assertEqual(owner, self.owner)
            candidates.append(candidate)
            raise ProjectSourcePathError("R14 record each ordered candidate")

        with patch("src.conversion.script_sources.resolve_project_sidecar_source_path", side_effect=reject):
            self.assertEqual(self.dependency_sources(), ())
        self.assertEqual(tuple(candidates), expected)

    def test_dependency_name_order_preserves_duplicates(self) -> None:
        self.assert_dependency_names(
            {"resourceType": "GMScript", "%Name": "percent", "name": "raw"},
            ("manifest.gml", "percent.gml", "raw.gml", "owner.gml"),
        )
        self.assert_dependency_names(
            {"resourceType": "GMScript", "%Name": "manifest", "name": "manifest"},
            ("manifest.gml", "manifest.gml", "manifest.gml", "owner.gml"),
        )
        for value in (None, 7, ""):
            with self.subTest(value=value):
                self.assert_dependency_names(
                    {"resourceType": "GMScript", "%Name": value, "name": value},
                    ("manifest.gml", "owner.gml"),
                )
        self.assert_dependency_names({"resourceType": "GMScript"}, ("manifest.gml", "owner.gml"))
        model = CanonicalScriptModel("manifest", "scripts", "GMScript", str(self.root / self.owner), self.owner, 0,
                                     raw_data=self.raw)
        self.raw["%Name"] = "changed"
        self.assertEqual(dependency_script_names(model), ("manifest", "changed", "owner"))

    def test_aggregate_uses_canonical_model_with_original_metadata(self) -> None:
        self.assertIs(ScriptModel, CanonicalScriptModel)
        self.assertFalse(issubclass(CanonicalScriptModel, ResourceModel))
        nested: JsonObject = {"unknown": [1, 2]}
        raw: JsonObject = {"%Name": "conflict", "name": "other", "resourceType": "GMSound", "nested": nested}
        source = self.write_gml("owner.gml")
        document = GameMakerJsonDocument(str(self.root / self.owner), "original source", raw)
        with patch("src.conversion.resource_models.read_gamemaker_json", return_value=document) as reader:
            models = parse_gamemaker_resource_models(str(self.root))
        reader.assert_called_once_with(str(self.root / self.owner))
        self.assertEqual(len(models.scripts), 1)
        model = models.scripts[0]
        self.assertIs(type(model), CanonicalScriptModel)
        self.assertEqual((model.name, model.kind, model.resource_type, model.yy_path, model.yyp_path, model.order,
                          model.subfolder, model.raw_data, model.gml_path), (
            "manifest", "scripts", "GMScript", str(self.root / self.owner), self.owner, 0, "", raw, str(source),
        ))
        self.assertIs(model.raw_data, document.value)
        self.assertIs(model.raw_data["nested"], nested)
        nested["after"] = True
        self.assertIs(model.raw_data["nested"], nested)
        self.assertEqual(model.raw_data["nested"], {"unknown": [1, 2], "after": True})
