import ast
import dataclasses
import json
import math
import pathlib
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.conversion.gamemaker_json import decode_gamemaker_json, read_gamemaker_json
from src.conversion.json_values import JsonValueError


def _legacy_decode(source: str) -> object:
    return json.loads(re.sub(r",\s*([}\]])", r"\1", source))


class TestGameMakerJson(unittest.TestCase):
    def test_trailing_commas_preserve_original_source_and_path(self) -> None:
        source = '{\n  "name": "Café",\n  "resources": [{"id": "one",},],\n}\n'
        source_path = "relative/../source project/Example.yyp"

        document = decode_gamemaker_json(source, source_path=source_path)

        self.assertEqual(document.source_path, source_path)
        self.assertEqual(document.source_text, source)
        self.assertEqual(document.value, {"name": "Café", "resources": [{"id": "one"}]})

    def test_frozen_document_retains_mutable_raw_containers(self) -> None:
        document = decode_gamemaker_json('{"items": [1]}', source_path="mutable.yy")
        assert isinstance(document.value, dict)
        items = document.value["items"]
        assert isinstance(items, list)

        items.append(2)
        document.value["extra"] = True

        self.assertIs(document.value["items"], items)
        self.assertEqual(document.value, {"items": [1, 2], "extra": True})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(document, "source_text", "replacement")

    def test_existing_decoder_behavior_for_scalar_and_nested_documents(self) -> None:
        sources = (
            '"text"', "123", "1.5", "true", "false", "null", "[]", "{}",
            '[false, 0, null, {"name": "a",},]',
            '{"duplicate": 1, "duplicate": 2, "after": 3,}',
            '{"escaped": "\\u2603", "text": ", }",}',
        )
        for source in sources:
            with self.subTest(source=source):
                expected = _legacy_decode(source)
                document = decode_gamemaker_json(source, source_path="parity.yy")
                self.assertEqual(document.value, expected)
                self.assertEqual(document.source_text, source)

    def test_quoted_string_regex_quirk_and_duplicate_key_order_are_preserved(self) -> None:
        document = decode_gamemaker_json(
            '{"first": 1, "text": ", }", "first": 2, "last": 3,}',
            source_path="quirk.yy",
        )
        assert isinstance(document.value, dict)
        self.assertEqual(document.value["text"], "}")
        self.assertEqual(document.value["first"], 2)
        self.assertEqual(list(document.value), ["first", "text", "last"])

    def test_stdlib_nonfinite_float_policy_is_preserved(self) -> None:
        document = decode_gamemaker_json(
            '{"nan": NaN, "positive": Infinity, "negative": -Infinity}',
            source_path="nonfinite.yy",
        )
        assert isinstance(document.value, dict)
        nan = document.value["nan"]
        positive = document.value["positive"]
        negative = document.value["negative"]
        assert isinstance(nan, float)
        assert isinstance(positive, float)
        assert isinstance(negative, float)
        self.assertTrue(math.isnan(nan))
        self.assertEqual(positive, math.inf)
        self.assertEqual(negative, -math.inf)

    def test_bom_comments_and_bad_syntax_match_original_decode_diagnostics(self) -> None:
        sources = ('\ufeff{"name": "bom"}', '{// comment\n "name": 1}', '{"bad": }', '{"x": 1} trailing')
        for source in sources:
            with self.subTest(source=source):
                with self.assertRaises(json.JSONDecodeError) as baseline:
                    _legacy_decode(source)
                with self.assertRaises(json.JSONDecodeError) as actual:
                    decode_gamemaker_json(source, source_path="bad.yy")
                self.assertEqual(actual.exception.msg, baseline.exception.msg)
                self.assertEqual(actual.exception.doc, baseline.exception.doc)
                self.assertEqual(actual.exception.pos, baseline.exception.pos)
                self.assertEqual(actual.exception.lineno, baseline.exception.lineno)
                self.assertEqual(actual.exception.colno, baseline.exception.colno)

    def test_decoder_rejects_an_injected_nested_non_json_value(self) -> None:
        raw: dict[str, object] = {"resources": [{"extra": b"invalid"}]}
        source = '{"resources": []}'
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            with self.assertRaises(JsonValueError) as raised:
                decode_gamemaker_json(source, source_path="injected.yy")
        self.assertEqual(raised.exception.source_path, "injected.yy")
        self.assertEqual(raised.exception.field_path, ("resources", 0, "extra"))
        self.assertEqual(raised.exception.reason, "unsupported-type")

    def test_decoder_retains_an_injected_valid_raw_root_by_identity(self) -> None:
        nested: list[object] = [1, {"enabled": True}]
        raw: dict[str, object] = {"values": nested}
        source = '{"values": []}'
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw) as decoder:
            document = decode_gamemaker_json(source, source_path="identity.yy")
        self.assertIs(document.value, raw)
        assert isinstance(document.value, dict)
        self.assertIs(document.value["values"], nested)
        decoder.assert_called_once_with(source)

    def test_decoder_does_not_wrap_failures_or_control_exceptions(self) -> None:
        errors: tuple[BaseException, ...] = (
            json.JSONDecodeError("bad", "{", 1), TypeError("type"), ValueError("integer limit"),
            RecursionError("decoder depth"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"),
            KeyboardInterrupt(), SystemExit(23),
        )
        for error in errors:
            with self.subTest(kind=type(error).__name__):
                with patch("src.conversion.gamemaker_json.json.loads", side_effect=error):
                    with self.assertRaises(type(error)) as raised:
                        decode_gamemaker_json("{}", source_path="errors.yy")
                self.assertIs(raised.exception, error)

    def test_integer_limit_behavior_matches_the_current_interpreter(self) -> None:
        maximum_digits = sys.get_int_max_str_digits()
        digit_count = maximum_digits + 1 if maximum_digits else 5000
        source = "9" * digit_count
        if maximum_digits:
            with self.assertRaises(ValueError) as baseline:
                _legacy_decode(source)
            with self.assertRaises(ValueError) as actual:
                decode_gamemaker_json(source, source_path="integer.yy")
            self.assertEqual(str(actual.exception), str(baseline.exception))
        else:
            self.assertEqual(decode_gamemaker_json(source, source_path="integer.yy").value, _legacy_decode(source))
        self.assertEqual(sys.get_int_max_str_digits(), maximum_digits)

    def test_decoder_depth_behavior_matches_the_current_interpreter(self) -> None:
        recursion_limit = sys.getrecursionlimit()
        depth = recursion_limit + 100
        source = "[" * depth + "0" + "]" * depth
        try:
            _legacy_decode(source)
        except RecursionError as baseline:
            with self.assertRaises(RecursionError) as actual:
                decode_gamemaker_json(source, source_path="decoder-depth.yy")
            self.assertEqual(str(actual.exception), str(baseline))
        else:
            document = decode_gamemaker_json(source, source_path="decoder-depth.yy")
            actual_value = document.value
            for _ in range(depth):
                assert isinstance(actual_value, list)
                self.assertEqual(len(actual_value), 1)
                actual_value = actual_value[0]
            self.assertEqual(actual_value, 0)
        self.assertEqual(sys.getrecursionlimit(), recursion_limit)

    def test_read_uses_utf8_and_keeps_original_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "source project.yy"
            source = '{"name": "Živeli ☃",}\n'
            path.write_bytes(source.encode("utf-8"))

            document = read_gamemaker_json(str(path))

            self.assertEqual(document.source_path, str(path))
            self.assertEqual(document.source_text, source)
            self.assertEqual(document.value, {"name": "Živeli ☃"})

    def test_invalid_utf8_propagates_before_decoding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "invalid.yy"
            path.write_bytes(b'{"name": "\xff"}')
            with patch("src.conversion.gamemaker_json.json.loads") as decoder:
                with self.assertRaises(UnicodeDecodeError):
                    read_gamemaker_json(str(path))
            decoder.assert_not_called()

    def test_missing_file_and_open_failures_propagate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "missing.yy"
            with self.assertRaises(FileNotFoundError) as raised:
                read_gamemaker_json(str(path))
            self.assertEqual(raised.exception.filename, str(path))
        error = OSError("read denied")
        with patch("src.conversion.gamemaker_json.open", side_effect=error, create=True):
            with self.assertRaises(OSError) as raised_error:
                read_gamemaker_json("source.yy")
        self.assertIs(raised_error.exception, error)

    def test_decoder_leaf_imports_only_stdlib_and_json_values(self) -> None:
        source_path = pathlib.Path(__file__).resolve().parents[1] / "src/conversion/gamemaker_json.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "Decoder leaf must not import relative project owners")
                assert node.module is not None
                imported_modules.add(node.module)
        for module in imported_modules:
            with self.subTest(module=module):
                if module != "src.conversion.json_values":
                    self.assertIn(module.split(".")[0], sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()
