"""Characterize the shared GameMaker decoding boundary and its legacy callers."""

from __future__ import annotations

import ast
import json
import math
import re
import tempfile
import unittest
from itertools import product
from pathlib import Path
from unittest.mock import patch

from scripts.maintainability_imports import build_graphs, elementary_cycles, module_edges
from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.base_converter import BaseConverter
from src.conversion.gamemaker_json import parse_gamemaker_json, read_gamemaker_json
from src.conversion.json_values import JsonValueError
from src.conversion.objects import ObjectConverter
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.project_source_discovery import project_gml_source_paths
from src.conversion.resource_models import parse_gamemaker_resource_models


class _MetadataReader(BaseConverter):
    def convert_all(self) -> None:
        pass

    def read_metadata(self, path: Path) -> object:
        return self._read_yy_file(path)


class _ObjectMetadataReader(ObjectConverter):
    def read_metadata(self) -> object:
        return self._parse_object_yy("o_test")

    def asset_names(self) -> set[str]:
        return self._get_project_asset_names()


class TestGameMakerJson(unittest.TestCase):
    def test_document_retains_original_source_and_successful_null(self) -> None:
        source = '{"unknown":[null,true,],"text":", }",}'
        document = parse_gamemaker_json(source, source_path="rooms/r.yy")
        self.assertEqual(document.source, source)
        self.assertEqual(document.source_path, "rooms/r.yy")
        self.assertEqual(document.value, {"unknown": [None, True], "text": "}"})
        self.assertIsNone(parse_gamemaker_json("null").value)
        self.assertEqual(parse_gamemaker_json("null").source_path, "")

    def test_read_retains_path_and_utf8_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.yy"
            source = '{"name":"čarobnjak","unknown":{}}\n'
            path.write_text(source, encoding="utf-8")
            document = read_gamemaker_json(path)
            self.assertEqual(document.source_path, str(path))
            self.assertEqual(document.source, source)
            self.assertEqual(document.value, {"name": "čarobnjak", "unknown": {}})

    def test_parse_preserves_stdlib_errors_and_nonfinite_values(self) -> None:
        for source in ('{"x":', '\ufeff{"x":1}', ""):
            with self.subTest(source=source):
                with self.assertRaises(json.JSONDecodeError):
                    parse_gamemaker_json(source)
        for source, expected in (("Infinity", math.inf), ("-Infinity", -math.inf)):
            with self.subTest(source=source):
                self.assertEqual(parse_gamemaker_json(source).value, expected)
        value = parse_gamemaker_json("NaN").value
        self.assertIsInstance(value, float)
        self.assertNotEqual(value, value)
        self.assertEqual(parse_gamemaker_json('{"x":1,"x":2}').value, {"x": 2})

    def test_read_propagates_io_and_encoding_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.yy"
            with self.assertRaises(FileNotFoundError):
                read_gamemaker_json(path)
            path.write_bytes(b"\xff")
            with self.assertRaises(UnicodeDecodeError):
                read_gamemaker_json(path)
            with self.assertRaises(OSError):
                read_gamemaker_json(directory)

    def test_validation_is_applied_to_decoded_values(self) -> None:
        with patch("src.conversion.gamemaker_json.json.loads", return_value={"extra": [b"invalid"]}):
            with self.assertRaises(JsonValueError) as raised:
                parse_gamemaker_json("{}")
        self.assertEqual(raised.exception.field_path, ("extra", 0))
        self.assertEqual(raised.exception.actual_type, "bytes")

    def test_decoder_depth_boundary_retains_native_recursion_policy(self) -> None:
        for depth, (opening, closing) in product((100, 700, 1500, 10000), (("[", "]"), ('{"x":', "}"))):
            source = opening * depth + "null" + closing * depth
            with self.subTest(depth=depth, opening=opening):
                try:
                    json.loads(re.sub(r",\s*([}\]])", r"\1", source))
                except RecursionError:
                    with self.assertRaises(RecursionError):
                        parse_gamemaker_json(source)
                else:
                    document = parse_gamemaker_json(source)
                    self.assertEqual(document.source, source)


class TestGameMakerJsonOwnership(unittest.TestCase):
    def test_source_discovery_dependency_direction_is_acyclic(self) -> None:
        root = Path(__file__).resolve().parents[1]
        names = ("json_values", "gamemaker_json", "project_source_paths", "project_manifest", "project_source_discovery")
        trees = {
            f"src/conversion/{name}.py": ast.parse((root / "src" / "conversion" / f"{name}.py").read_text())
            for name in names
        }
        static, eager = build_graphs(trees)
        self.assertEqual(elementary_cycles(static), [])
        self.assertEqual(elementary_cycles(eager), [])
        for name in ("json_values", "gamemaker_json", "project_source_paths"):
            path = f"src/conversion/{name}.py"
            targets = {target for target, _eager in module_edges(path, trees[path])}
            self.assertNotIn("src.conversion.project_manifest", targets)
            self.assertNotIn("src.conversion.project_source_discovery", targets)
        resolver = trees["src/conversion/project_source_paths.py"]
        self.assertNotIn("project_gml_source_paths", {node.name for node in resolver.body if isinstance(node, ast.FunctionDef)})

    def test_canonical_modules_do_not_import_legacy_json_types(self) -> None:
        conversion = Path(__file__).resolve().parents[1] / "src" / "conversion"
        for name in ("json_values", "gamemaker_json", "project_source_discovery"):
            with self.subTest(module=name):
                tree = ast.parse((conversion / f"{name}.py").read_text())
                imported = {
                    alias.name
                    for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                    and node.module in {"src.conversion.type_defs", "typing"}
                    for alias in node.names
                }
                self.assertTrue(imported.isdisjoint({"Any", "JsonDict", "JsonList", "JsonValue"}))


class TestLegacyResourceDecoding(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.yy_path = self.root / "objects" / "o_test" / "o_test.yy"
        self.yy_path.parent.mkdir(parents=True)
        (self.yy_path.parent / "Create_0.gml").write_text("x = 1;", encoding="utf-8")
        (self.root / "project.yyp").write_text(
            '{"resources":[{"id":{"name":"o_test","path":"objects/o_test/o_test.yy"}}]}',
            encoding="utf-8",
        )

    def test_resource_readers_preserve_unknown_data_and_trailing_comma_quirks(self) -> None:
        self.yy_path.write_text(
            '{"eventList":[{"eventType":0,"eventNum":0,},],"unknown":[null,{"text":", }"}],}',
            encoding="utf-8",
        )
        models = parse_gamemaker_resource_models(str(self.root))
        self.assertEqual(models.objects[0].raw_data["unknown"], [None, {"text": "}"}])
        self.assertEqual(models.diagnostics, ())
        self.assertEqual(
            [source.source_path for source in project_gml_source_paths(self.root)],
            ["objects/o_test/Create_0.gml"],
        )

    def test_resource_readers_keep_nonobject_and_malformed_fallbacks(self) -> None:
        for content in (b"null", b"[]", b"42", b'{"x":', b"\xff"):
            with self.subTest(content=content):
                self.yy_path.write_bytes(content)
                self.assertEqual(project_gml_source_paths(self.root), ())
                models = parse_gamemaker_resource_models(str(self.root))
                self.assertEqual(models.objects, ())
                self.assertEqual(len(models.diagnostics), 1)
                diagnostic = models.diagnostics[0]
                self.assertEqual(diagnostic.code, "GM2GD-RESOURCE-YY-MISSING")
                self.assertEqual(diagnostic.source_path, str(self.yy_path))
                self.assertEqual(diagnostic.resource_name, "o_test")
                self.assertEqual(diagnostic.resource_kind, "objects")

    def test_event_mapping_exceptions_are_outside_discovery_decode_policy(self) -> None:
        self.yy_path.write_text('{"eventList":[{"eventType":[]}]}', encoding="utf-8")
        with self.assertRaises(TypeError):
            project_gml_source_paths(self.root)

    def test_legacy_resource_readers_propagate_decoder_recursion_errors(self) -> None:
        self.yy_path.write_text("[" * 10000 + "null" + "]" * 10000, encoding="utf-8")
        with self.assertRaises(RecursionError):
            project_gml_source_paths(self.root)
        with self.assertRaises(RecursionError):
            parse_gamemaker_resource_models(str(self.root))
        with self.assertRaises(RecursionError):
            _MetadataReader(self.root, self.root).read_metadata(self.yy_path)
        with self.assertRaises(RecursionError):
            _ObjectMetadataReader(self.root, self.root).read_metadata()

    def test_manifest_and_object_project_reader_propagate_decoder_recursion_errors(self) -> None:
        (self.root / "project.yyp").write_text("[" * 10000 + "null" + "]" * 10000, encoding="utf-8")
        with self.assertRaises(RecursionError):
            load_gamemaker_project_manifest(str(self.root))
        with (
            patch.object(AssetRegistryConverter, "build_entries", side_effect=ValueError("fallback")),
            self.assertRaises(RecursionError),
        ):
            _ObjectMetadataReader(self.root, self.root).asset_names()


class TestLegacyGameMakerDecoding(unittest.TestCase):
    def test_shared_readers_preserve_values_and_normalizer_quirks(self) -> None:
        cases: tuple[tuple[str, object], ...] = (
            ('{"known":null,"unknown":{"deep":[1,true,"x"]}}',
             {"known": None, "unknown": {"deep": [1, True, "x"]}}),
            ('{"items":[1,2,],}', {"items": [1, 2]}),
            ('{"text":", }"}', {"text": "}"}),
            ('{"x":1,"x":2}', {"x": 2}),
            ("null", None),
            ("[1]", None),
            ("42", None),
            ('{"x":', None),
            ('\ufeff{"x":1}', None),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.yyp"
            reader = _MetadataReader(directory, directory)
            for source, expected in cases:
                with self.subTest(source=source):
                    path.write_text(source, encoding="utf-8")
                    self.assertEqual(reader.read_metadata(path), expected)
                    manifest = load_gamemaker_project_manifest(directory)
                    self.assertEqual(manifest.raw_data, expected if expected is not None else {})
                    malformed = [d for d in manifest.diagnostics if d.code == "GM2GD-PROJECT-YYP-MALFORMED"]
                    self.assertEqual(bool(malformed), expected is None)

    def test_nonfinite_numbers_remain_supported_by_legacy_readers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.yyp"
            path.write_text('{"n":NaN,"p":Infinity,"m":-Infinity}', encoding="utf-8")
            manifest = load_gamemaker_project_manifest(directory)
            self.assertTrue(math.isnan(manifest.raw_data["n"]))
            self.assertEqual(manifest.raw_data["p"], math.inf)
            self.assertEqual(manifest.raw_data["m"], -math.inf)

    def test_object_decoders_preserve_nonobject_root_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            object_path = root / "objects" / "o_test" / "o_test.yy"
            object_path.parent.mkdir(parents=True)
            project_path = root / "project.yyp"
            for source in ("null", "[]", "42", '"text"'):
                with self.subTest(source=source):
                    object_path.write_text(source, encoding="utf-8")
                    project_path.write_text(source, encoding="utf-8")
                    reader = _ObjectMetadataReader(directory, directory, log_callback=lambda _message: None)
                    with self.assertRaises(AttributeError):
                        reader.read_metadata()
                    with (
                        patch.object(AssetRegistryConverter, "build_entries", side_effect=ValueError("fallback")),
                        self.assertRaises(AttributeError),
                    ):
                        reader.asset_names()

    def test_object_decoders_keep_existing_malformed_input_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            object_path = root / "objects" / "o_test" / "o_test.yy"
            object_path.parent.mkdir(parents=True)
            project_path = root / "project.yyp"
            for content in (b'{"x":', b"\xff"):
                with self.subTest(content=content):
                    object_path.write_bytes(content)
                    project_path.write_bytes(content)
                    messages: list[str] = []
                    reader = _ObjectMetadataReader(directory, directory, log_callback=messages.append)
                    self.assertIsNone(reader.read_metadata())
                    self.assertEqual(len(messages), 1)
                    with patch.object(AssetRegistryConverter, "build_entries", side_effect=ValueError("fallback")):
                        self.assertEqual(reader.asset_names(), {"o_test"})


if __name__ == "__main__":
    unittest.main()
