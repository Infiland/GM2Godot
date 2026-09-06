from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.font_model import FontModel, parse_font_model
from src.conversion.fonts import FontConverter
from src.conversion.json_values import JsonObject
from src.conversion.resource_models import parse_gamemaker_resource_models
from src.localization import get_localized
from tests.test_font_model import FONT_ERROR_ORDER, FONT_FIELD_CASES

FONT_READ_CASES: tuple[tuple[str, bytes | None, str | None, type[Exception] | None, ConversionCounts], ...] = (
    ("object_missing_both", b"{}", None, None, ConversionCounts(1, 1, 0, 0, 1)),
    ("root_null", b"null", None, None, ConversionCounts(1, 1, 0, 0, 1)),
    ("root_array", b"[]", None, None, ConversionCounts(1, 1, 0, 0, 1)),
    ("root_string", b'"font"', None, None, ConversionCounts(1, 1, 0, 0, 1)),
    ("root_number", b"1", None, None, ConversionCounts(1, 1, 0, 0, 1)),
    ("root_bool", b"false", None, None, ConversionCounts(1, 1, 0, 0, 1)),
    ("malformed_json", b"{ bad", None, None, ConversionCounts(1, 1, 0, 0, 1)),
    ("missing_file", None, None, None, ConversionCounts(1, 0, 0, 1)),
    ("invalid_utf8", b"\xff", None, UnicodeDecodeError, ConversionCounts(1, 1, 0, 0, 1)),
    ("directory", None, None, None, ConversionCounts(1, 0, 0, 1)),
    ("bom", b'\xef\xbb\xbf{"fontName":"Family","name":"fnt_contract"}', None, None, ConversionCounts(1, 1, 0, 0, 1)),
    ("trailing_comma", b'{"fontName":"Family","name":"fnt_contract",}', "Family", None, ConversionCounts(1, 1, 1)),
    ("comma_inside_string_quirk", b'{"fontName":"Family,}","name":"fnt_contract"}', "Family}", None,
     ConversionCounts(1, 1, 1)),
    ("digit_limit", b"1" * 4301, None, ValueError, ConversionCounts(1, 1, 0, 0, 1)),
    ("recursion_limit", b"[" * 10000 + b"null" + b"]" * 10000, None, RecursionError, ConversionCounts(1, 0, 0, 1)),
)


def _document(data: JsonObject) -> bytes:
    return json.dumps({"resourceType": "GMFont", **data}).encode("utf-8")


class TestFontModelConsumers(unittest.TestCase):
    def setUp(self) -> None:
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name).resolve()
        directories = patch("src.conversion.font_sources.system_font_directories", return_value=[])
        directories.start()
        self.addCleanup(directories.stop)

    def _fixture(self, documents: dict[str, bytes | None]) -> tuple[Path, Path]:
        case = Path(tempfile.mkdtemp(dir=self.root))
        source, output = case / "source", case / "output"
        source.mkdir()
        references: list[JsonObject] = []
        for name, payload in documents.items():
            relative = f"fonts/{name}/{name}.yy"
            references.append({"id": {"name": name, "path": relative}})
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if payload is not None:
                path.write_bytes(payload)
        (source / "FontContract.yyp").write_text(json.dumps({
            "resourceType": "GMProject", "resources": references, "RoomOrderNodes": [],
        }), encoding="utf-8")
        return source, output

    def test_reader_and_root_errors_keep_worker_outcomes(self) -> None:
        self.assertEqual(sys.get_int_max_str_digits(), 4300)
        self.assertEqual(sys.getrecursionlimit(), 1000)
        for case in FONT_READ_CASES:
            with self.subTest(case=case[0]):
                self._assert_font_read_case(case)

    def _assert_font_read_case(
        self,
        case: tuple[str, bytes | None, str | None, type[Exception] | None, ConversionCounts],
    ) -> None:
        label, payload, family, error, expected = case
        source, output = self._fixture({"fnt": payload})
        yy_path = source / "fonts/fnt/fnt.yy"
        if label == "directory":
            yy_path.mkdir()
        logs: list[str] = []
        converter = FontConverter(source, output, log_callback=logs.append, max_workers=1)
        if error is None:
            converter.convert_all()
        else:
            with self.assertRaises(error):
                converter.convert_all()
        if error is RecursionError:
            # This decoder error occurs in registry planning, before any worker can start.
            with self.assertRaises(ValueError):
                converter.conversion_step_result(finalize_unfinished_as=None)
            self.assertEqual(converter.conversion_step_result().resources, expected)
        else:
            self.assertEqual(converter.conversion_step_result(finalize_unfinished_as=None).resources, expected)
        paths = sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file())
        self.assertEqual(paths, ["fonts/fnt.tres"] if family is not None else [])
        if family is not None:
            self.assertIn(f'font_names = PackedStringArray("{family}")',
                          (output / "fonts/fnt.tres").read_text(encoding="utf-8"))
        parse_error = get_localized("Console_Convertor_Fonts_ParseError").format(yy_path=str(yy_path))
        self.assertEqual(logs.count(parse_error), int(expected.failed == 1 and error is None))

    def test_required_key_errors_are_worker_local(self) -> None:
        for missing in ("fontName", "name"):
            data: JsonObject = {"fontName": "Family", "name": "fnt"}
            del data[missing]
            source, output = self._fixture({"fnt": _document(data)})
            logs: list[str] = []
            registry = AssetRegistryConverter(source, output, log_callback=logs.append)
            self.assertEqual([(entry.name, entry.godot_path) for entry in registry.build_entries()],
                             [("fnt", "res://fonts/fnt.tres")])
            self.assertFalse(output.exists())
            converter = FontConverter(source, output, log_callback=logs.append, max_workers=1)
            converter.convert_all()
            self.assertEqual(converter.conversion_step_result(finalize_unfinished_as=None).resources, ConversionCounts(1, 1, 0, 0, 1))
            self.assertFalse((output / "fonts/fnt.tres").exists())
            self.assertEqual(logs.count(get_localized("Console_Convertor_Fonts_ParseError").format(
                yy_path=str(source / "fonts/fnt/fnt.yy"))), 1)

    def test_numeric_worker_error_waits_for_safe_sibling(self) -> None:
        for field, value, error in (("size", "bad", ValueError), ("AntiAlias", "bad", ValueError),
                                    ("size", 10 ** 400, OverflowError), ("AntiAlias", float("inf"), OverflowError)):
            with self.subTest(field=field, value=value):
                source, output = self._fixture({
                    "a_bad": _document({"fontName": "Family", "name": "a_bad", field: value}),
                    "z_safe": _document({"fontName": "Safe Family", "name": "z_safe"}),
                })
                logs: list[str] = []
                converter = FontConverter(source, output, log_callback=logs.append, max_workers=1)
                with self.assertRaises(error):
                    converter.convert_all()
                self.assertEqual(converter.conversion_step_result(finalize_unfinished_as=None).resources, ConversionCounts(2, 2, 1, 0, 1))
                self.assertFalse((output / "fonts/a_bad.tres").exists())
                self.assertIn('font_names = PackedStringArray("Safe Family")',
                              (output / "fonts/z_safe.tres").read_text(encoding="utf-8"))
                self.assertNotIn(get_localized("Console_Convertor_Fonts_Complete"), logs)
                self.assertNotIn(get_localized("Console_Convertor_Fonts_ParseError").format(
                    yy_path=str(source / "fonts/a_bad/a_bad.yy")), logs)

    def test_registry_ignores_worker_numeric_fields(self) -> None:
        records: tuple[JsonObject, ...] = (
            {"fontName": "Family", "size": "bad", "AntiAlias": None},
            {"fontName": "Family", "name": [], "size": 10 ** 400, "AntiAlias": "bad"},
            {"fontName": 123, "name": None, "size": [], "includeTTF": "false", "TTFName": ["Family.ttf"]},
            {"fontName": "Family", "size": "bad", "AntiAlias": None,
             "includeTTF": True, "TTFName": "Bundled.ttf"},
        )
        for data in records:
            source, output = self._fixture({"font-A": _document(data), "font_A": _document(data)})
            system_dir = source / "system"
            system_dir.mkdir()
            (system_dir / "Family.ttf").write_bytes(b"system-source")
            (system_dir / "123.ttf").write_bytes(b"numeric-family-source")
            for name in ("font-A", "font_A"):
                (source / "fonts" / name / "Bundled.ttf").write_bytes(b"bundled-source")
            with patch("src.conversion.font_sources.system_font_directories", return_value=[str(system_dir)]):
                entries = AssetRegistryConverter(source, output, log_callback=lambda _line: None).build_entries()
            paths = [entry.godot_path for entry in entries]
            self.assertEqual([entry.name for entry in entries], ["font-A", "font_A"])
            extension = ".ttf" if data["fontName"] == "Family" else ".tres"
            prefix = "res://fonts/bundled" if data.get("TTFName") == "Bundled.ttf" else "res://fonts/font_a"
            self.assertEqual(paths, [prefix + extension, prefix + "_2" + extension])
            self.assertFalse(output.exists())

    def test_aggregate_uses_canonical_font_model(self) -> None:
        source, _output = self._fixture({"reference_name": _document({
            "fontName": "Family", "name": "raw_name", "size": "16.5", "unknown": {"values": [1]},
        })})
        aggregate = parse_gamemaker_resource_models(str(source))
        self.assertEqual(len(aggregate.fonts), 1)
        self.assertEqual(aggregate.diagnostics, ())
        model = aggregate.fonts[0]
        self.assertIs(type(model), FontModel)
        self.assertEqual((model.name, model.size, model.antialiasing), ("raw_name", 16.5, 0))
        self.assertEqual(model.source_path, str(source / "fonts/reference_name/reference_name.yy"))
        nested = model.raw_data["unknown"]
        assert isinstance(nested, dict)
        nested["later"] = True
        model.raw_data["name"] = "changed"
        self.assertIs(model.raw_data["unknown"], nested)
        self.assertEqual(model.raw_data["unknown"], {"values": [1], "later": True})
        self.assertEqual(model.name, "raw_name")

    def test_aggregate_field_domains_and_first_error(self) -> None:
        base: JsonObject = {"fontName": "Family", "name": "fnt", "size": 16, "AntiAlias": 1,
                            "bold": False, "italic": False, "includeTTF": False, "TTFName": ""}
        for field in base:
            for present, value in FONT_FIELD_CASES:
                data = dict(base)
                if present:
                    data[field] = value
                else:
                    del data[field]
                self._assert_aggregate_matches_canonical(data)
        for data, error, message in FONT_ERROR_ORDER:
            source, _output = self._fixture({"fnt": _document(data)})
            with self.assertRaises(error) as caught:
                parse_gamemaker_resource_models(str(source))
            self.assertEqual(str(caught.exception), message)
        for label, payload, family, _worker_error, _counts in FONT_READ_CASES:
            source, _output = self._fixture({"fnt": payload})
            if label == "directory":
                (source / "fonts/fnt/fnt.yy").mkdir()
            with self.subTest(root=label):
                if label in ("object_missing_both", "recursion_limit"):
                    with self.assertRaises(KeyError if label == "object_missing_both" else RecursionError):
                        parse_gamemaker_resource_models(str(source))
                else:
                    aggregate = parse_gamemaker_resource_models(str(source))
                    if family is not None:
                        self.assertEqual([model.font_name for model in aggregate.fonts], [family])
                        self.assertEqual(aggregate.diagnostics, ())
                    else:
                        self.assertEqual(aggregate.fonts, ())
                        self.assertEqual([diagnostic.code for diagnostic in aggregate.diagnostics],
                                         ["GM2GD-RESOURCE-YY-MISSING"])

    def _assert_aggregate_matches_canonical(self, data: JsonObject) -> None:
        source, _output = self._fixture({"fnt": _document(data)})
        path = str(source / "fonts/fnt/fnt.yy")
        document: JsonObject = {"resourceType": "GMFont", **data}
        try:
            expected = parse_font_model(document, source_path=path)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            with self.assertRaises(type(error)) as actual:
                parse_gamemaker_resource_models(str(source))
            self.assertEqual(str(actual.exception), str(error))
            return
        aggregate = parse_gamemaker_resource_models(str(source))
        self.assertEqual(len(aggregate.fonts), 1)
        self.assertEqual(aggregate.diagnostics, ())
        actual = aggregate.fonts[0]
        self.assertIs(type(actual), FontModel)
        # NaN is preserved by both JSON parsing and the canonical constructor, but is unequal to itself.
        if math.isnan(expected.size):
            self.assertTrue(math.isnan(actual.size))
        else:
            self.assertEqual(actual.size, expected.size)
        self.assertEqual((actual.font_name, actual.name, actual.bold, actual.italic, actual.antialiasing,
                          actual.include_ttf, actual.ttf_name, actual.source_path),
                         (expected.font_name, expected.name, expected.bold, expected.italic, expected.antialiasing,
                          expected.include_ttf, expected.ttf_name, expected.source_path))
        self.assertEqual(list(actual.raw_data), list(document))
