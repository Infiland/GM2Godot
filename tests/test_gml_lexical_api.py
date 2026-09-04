from __future__ import annotations

import ast
from collections.abc import Callable
import inspect
from pathlib import Path
from typing import Iterable, get_type_hints
import unittest
from src.conversion.gml_transpiler import (
    preprocess_gml_source as facade_preprocess_gml_source,
)
from src.conversion.gml_transpiler_parts.lexical_api import (
    decode_gml_string_literal,
    decode_gml_verbatim_string_literal,
    is_plain_identifier,
    is_verbatim_string_start,
    preprocess_gml_source,
    preprocess_gml_source_preserving_layout,
    read_ordinary_string,
    read_template_string,
    read_verbatim_string,
    reject_asset_identifier_name,
    sanitize_gdscript_identifier,
    split_template_string,
    tokenize_gml_expression,
    tokenize_gml_source,
    validate_gml_identifier,
)
from src.conversion.gml_transpiler_parts.result_models import GMLPreprocessResult
from src.conversion.gml_transpiler_parts.shared_models import (
    GMLTranspileError,
    ScopeContext,
    Token,
)
from src.conversion.gml_transpiler_parts.utils import split_assignment, split_top_level, strip_comments
from tests.gml_facade_contract_support import static_all_exports


PUBLIC_NAMES = (
    "decode_gml_string_literal",
    "decode_gml_verbatim_string_literal",
    "is_plain_identifier",
    "is_verbatim_string_start",
    "preprocess_gml_source",
    "preprocess_gml_source_preserving_layout",
    "read_ordinary_string",
    "read_template_string",
    "read_verbatim_string",
    "reject_asset_identifier_name",
    "sanitize_gdscript_identifier",
    "split_template_string",
    "tokenize_gml_expression",
    "tokenize_gml_source",
    "validate_gml_identifier",
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEXICAL_API_PATH = (
    PROJECT_ROOT / "src" / "conversion" / "gml_transpiler_parts" / "lexical_api.py"
)
FACADE_PATH = PROJECT_ROOT / "src" / "conversion" / "gml_transpiler.py"
LEXICAL_API_FUNCTIONS = {
    "decode_gml_string_literal": decode_gml_string_literal,
    "decode_gml_verbatim_string_literal": decode_gml_verbatim_string_literal,
    "is_plain_identifier": is_plain_identifier,
    "is_verbatim_string_start": is_verbatim_string_start,
    "preprocess_gml_source": preprocess_gml_source,
    "preprocess_gml_source_preserving_layout": preprocess_gml_source_preserving_layout,
    "read_ordinary_string": read_ordinary_string,
    "read_template_string": read_template_string,
    "read_verbatim_string": read_verbatim_string,
    "reject_asset_identifier_name": reject_asset_identifier_name,
    "sanitize_gdscript_identifier": sanitize_gdscript_identifier,
    "split_template_string": split_template_string,
    "tokenize_gml_expression": tokenize_gml_expression,
    "tokenize_gml_source": tokenize_gml_source,
    "validate_gml_identifier": validate_gml_identifier,
}


def _token_fields(tokens: list[Token]) -> list[tuple[str, str, int, int, int]]:
    return [
        (token.kind, token.value, token.index, token.line, token.column)
        for token in tokens
    ]


def _parameter_shape(
    function: Callable[..., object],
) -> tuple[tuple[str, str, object], ...]:
    signature = inspect.signature(function)
    return tuple(
        (
            parameter.name,
            parameter.kind.name,
            parameter.default,
        )
        for parameter in signature.parameters.values()
    )


class GMLLexicalAPISurfaceTests(unittest.TestCase):
    def test_exact_static_alphabetized_public_surface(self) -> None:
        public_exports = static_all_exports(LEXICAL_API_PATH.read_text(encoding="utf-8"))
        self.assertEqual(public_exports, PUBLIC_NAMES)
        self.assertEqual(len(public_exports), 15)
        self.assertEqual(tuple(sorted(public_exports)), PUBLIC_NAMES)
        self.assertTrue(all(not name.startswith("_") for name in public_exports))
        self.assertNotIn("is_float_like_number", public_exports)

        tree = ast.parse(LEXICAL_API_PATH.read_text(encoding="utf-8"), filename=str(LEXICAL_API_PATH))
        declarations = [
            node
            for node in tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
        ]
        self.assertEqual(len(declarations), 1)
        declaration = declarations[0]
        value = declaration.value
        self.assertIsInstance(value, ast.Tuple)
        assert isinstance(value, ast.Tuple)
        self.assertEqual(
            tuple(
                element.value
                for element in value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ),
            PUBLIC_NAMES,
        )
        self.assertEqual(len(value.elts), len(PUBLIC_NAMES))
        self.assertEqual(ast.unparse(declaration.annotation), "Final[tuple[str, ...]]")
    def test_resolved_signatures_and_model_types_are_exact(self) -> None:
        one_argument = {
            "decode_gml_string_literal": "source",
            "decode_gml_verbatim_string_literal": "source",
            "is_plain_identifier": "name",
            "sanitize_gdscript_identifier": "name",
            "split_template_string": "source",
            "tokenize_gml_expression": "source",
            "tokenize_gml_source": "source",
            "validate_gml_identifier": "name",
        }
        for name, parameter_name in one_argument.items():
            with self.subTest(name=name):
                self.assertEqual(
                    _parameter_shape(LEXICAL_API_FUNCTIONS[name]),
                    (
                        (
                            parameter_name,
                            "POSITIONAL_OR_KEYWORD",
                            inspect.Parameter.empty,
                        ),
                    ),
                )

        for name in (
            "is_verbatim_string_start",
            "read_ordinary_string",
            "read_template_string",
            "read_verbatim_string",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    _parameter_shape(LEXICAL_API_FUNCTIONS[name]),
                    (
                        ("source", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
                        (
                            "index" if name == "is_verbatim_string_start" else "start",
                            "POSITIONAL_OR_KEYWORD",
                            inspect.Parameter.empty,
                        ),
                    ),
                )

        self.assertEqual(
            _parameter_shape(reject_asset_identifier_name),
            (
                ("name", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
                ("scope_context", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ),
        )
        preprocess_shape = (
            ("source", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("macro_configuration", "KEYWORD_ONLY", None),
            ("active_symbols", "KEYWORD_ONLY", None),
        )
        self.assertEqual(
            _parameter_shape(preprocess_gml_source),
            preprocess_shape,
        )
        self.assertEqual(
            _parameter_shape(preprocess_gml_source_preserving_layout),
            preprocess_shape,
        )

        expected_returns: dict[str, object] = {
            "decode_gml_string_literal": str,
            "decode_gml_verbatim_string_literal": str,
            "is_plain_identifier": bool,
            "is_verbatim_string_start": bool,
            "preprocess_gml_source": GMLPreprocessResult,
            "preprocess_gml_source_preserving_layout": GMLPreprocessResult,
            "read_ordinary_string": str,
            "read_template_string": str,
            "read_verbatim_string": str,
            "reject_asset_identifier_name": type(None),
            "sanitize_gdscript_identifier": str,
            "split_template_string": tuple[tuple[str, str], ...],
            "tokenize_gml_expression": list[Token],
            "tokenize_gml_source": list[Token],
            "validate_gml_identifier": type(None),
        }
        expected_parameters: dict[str, dict[str, object]] = {
            "decode_gml_string_literal": {"source": str},
            "decode_gml_verbatim_string_literal": {"source": str},
            "is_plain_identifier": {"name": str},
            "is_verbatim_string_start": {"source": str, "index": int},
            "preprocess_gml_source": {
                "source": str,
                "macro_configuration": str | None,
                "active_symbols": Iterable[str] | None,
            },
            "preprocess_gml_source_preserving_layout": {
                "source": str,
                "macro_configuration": str | None,
                "active_symbols": Iterable[str] | None,
            },
            "read_ordinary_string": {"source": str, "start": int},
            "read_template_string": {"source": str, "start": int},
            "read_verbatim_string": {"source": str, "start": int},
            "reject_asset_identifier_name": {
                "name": str,
                "scope_context": ScopeContext,
            },
            "sanitize_gdscript_identifier": {"name": str},
            "split_template_string": {"source": str},
            "tokenize_gml_expression": {"source": str},
            "tokenize_gml_source": {"source": str},
            "validate_gml_identifier": {"name": str},
        }
        self.assertEqual(set(expected_parameters), set(PUBLIC_NAMES))
        for name, expected_return in expected_returns.items():
            with self.subTest(return_type=name):
                hints = get_type_hints(LEXICAL_API_FUNCTIONS[name])
                self.assertEqual(hints["return"], expected_return)
                self.assertEqual(
                    {key: value for key, value in hints.items() if key != "return"},
                    expected_parameters[name],
                )
    def test_facade_exposes_only_the_supported_lexical_entry_point(self) -> None:
        self.assertIs(facade_preprocess_gml_source, preprocess_gml_source)
        facade_exports = static_all_exports(FACADE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(facade_exports), 44)
        self.assertEqual(sum(not name.startswith("_") for name in facade_exports), 44)
        self.assertEqual(sum(name.startswith("_") for name in facade_exports), 0)
        newly_internal = set(PUBLIC_NAMES) - {"preprocess_gml_source"}
        self.assertTrue(newly_internal.isdisjoint(facade_exports))

class GMLLexicalAPIBehaviorTests(unittest.TestCase):
    def test_source_and_expression_tokens_differ_only_by_newline_filtering(self) -> None:
        source = "alpha\r\n+\nbeta"

        source_tokens = tokenize_gml_source(source)
        expression_tokens = tokenize_gml_expression(source)

        self.assertTrue(all(type(token) is Token for token in source_tokens))
        self.assertTrue(all(type(token) is Token for token in expression_tokens))
        self.assertEqual(
            _token_fields(source_tokens),
            [
                ("IDENT", "alpha", 0, 1, 1),
                ("NEWLINE", "\n", 6, 1, 6),
                ("OP", "+", 7, 2, 1),
                ("NEWLINE", "\n", 8, 2, 2),
                ("IDENT", "beta", 9, 3, 1),
                ("EOF", "", 13, 3, 5),
            ],
        )
        self.assertEqual(
            expression_tokens,
            [token for token in source_tokens if token.kind != "NEWLINE"],
        )
        self.assertEqual(expression_tokens[-1].kind, "EOF")

    def test_ordinary_string_read_decode_and_failures(self) -> None:
        self.assertEqual(
            read_ordinary_string('xx"a\\"b"tail', 2),
            '"a\\"b"',
        )
        self.assertEqual(
            decode_gml_string_literal('"line\\n\\u0041\\x42\\101"'),
            "line\nABA",
        )
        self.assertEqual(
            decode_gml_string_literal("'single\\tquote'"),
            "single\tquote",
        )

        failure_cases = (
            (
                lambda: read_ordinary_string("plain", 0),
                "String literal must start with a quote",
            ),
            (
                lambda: read_ordinary_string('"unterminated', 0),
                "Unterminated string literal",
            ),
            (
                lambda: decode_gml_string_literal('"mismatch\''),
                "Invalid string literal",
            ),
        )
        for operation, message in failure_cases:
            with self.subTest(message=message):
                with self.assertRaises(GMLTranspileError) as raised:
                    operation()
                self.assertIs(type(raised.exception), GMLTranspileError)
                self.assertEqual(str(raised.exception), message)

    def test_verbatim_string_read_decode_predicate_and_failures(self) -> None:
        source = 'xx@"first\\\r\nsecond"tail'
        self.assertTrue(is_verbatim_string_start(source, 2))
        self.assertFalse(is_verbatim_string_start(source, -1))
        self.assertFalse(is_verbatim_string_start(source, len(source)))
        self.assertFalse(is_verbatim_string_start("@ x", 0))
        self.assertEqual(
            read_verbatim_string(source, 2),
            '@"first\\\r\nsecond"',
        )
        self.assertEqual(
            decode_gml_verbatim_string_literal('@"first\\\r\nsecond"'),
            "first\\\r\nsecond",
        )
        self.assertEqual(
            read_verbatim_string(r'@"a\" + suffix', 0),
            r'@"a\"',
        )

        failure_cases = (
            (
                lambda: read_verbatim_string('"plain"', 0),
                "Verbatim string literal must start with @ followed by a quote",
            ),
            (
                lambda: read_verbatim_string('@"unterminated', 0),
                "Unterminated verbatim string literal",
            ),
            (
                lambda: decode_gml_verbatim_string_literal('@"ok"tail'),
                "Unexpected text after verbatim string literal",
            ),
        )
        for operation, message in failure_cases:
            with self.subTest(message=message):
                with self.assertRaises(GMLTranspileError) as raised:
                    operation()
                self.assertIs(type(raised.exception), GMLTranspileError)
                self.assertEqual(str(raised.exception), message)

    def test_template_string_read_split_and_failures(self) -> None:
        self.assertEqual(
            read_template_string('xx$"hello {name}"tail', 2),
            '$"hello {name}"',
        )
        self.assertEqual(
            split_template_string('$"a\\n{name + " + "1}b"'),
            (
                ("text", "a\n"),
                ("expression", 'name + " + "1'),
                ("text", "b"),
            ),
        )
        self.assertEqual(
            split_template_string('$"{ {x: 1} }"'),
            (("expression", " {x: 1} "),),
        )

        failure_cases = (
            (
                lambda: read_template_string('"plain"', 0),
                'Template string literal must start with $"',
            ),
            (
                lambda: split_template_string('$"{   }"'),
                "Template string interpolation cannot be empty",
            ),
            (
                lambda: split_template_string('$"line\nbreak"'),
                "Template string literal text cannot contain a newline",
            ),
            (
                lambda: split_template_string('$"unterminated'),
                "Unterminated template string literal",
            ),
            (
                lambda: split_template_string('$"ok"tail'),
                "Unexpected text after template string literal",
            ),
        )
        for operation, message in failure_cases:
            with self.subTest(message=message):
                with self.assertRaises(GMLTranspileError) as raised:
                    operation()
                self.assertIs(type(raised.exception), GMLTranspileError)
                self.assertEqual(str(raised.exception), message)

    def test_identifier_validation_sanitization_and_asset_rejection(self) -> None:
        valid_64 = "a" * 64
        self.assertIsNone(validate_gml_identifier(valid_64))
        self.assertTrue(is_plain_identifier(valid_64))
        self.assertTrue(is_plain_identifier("naïve_2"))
        self.assertFalse(is_plain_identifier(""))
        self.assertFalse(is_plain_identifier("2bad"))
        self.assertFalse(is_plain_identifier("bad-name"))

        invalid_identifiers = (
            ("", "Expected identifier name"),
            ("a" * 65, "GML identifier exceeds 64 characters"),
            ("2bad", "GML identifier must start with a letter or underscore"),
            (
                "bad-name",
                "GML identifier can only contain letters, numbers, and underscores",
            ),
        )
        for name, message in invalid_identifiers:
            with self.subTest(name=name):
                with self.assertRaises(GMLTranspileError) as raised:
                    validate_gml_identifier(name)
                self.assertEqual(str(raised.exception), message)

        self.assertEqual(sanitize_gdscript_identifier("class"), "class_")
        self.assertEqual(
            sanitize_gdscript_identifier("_gml_internal"),
            "gml_user_gml_internal",
        )
        self.assertEqual(
            sanitize_gdscript_identifier("bad-name"),
            "bad-name",
        )
        self.assertEqual(sanitize_gdscript_identifier("player"), "player")

        scope_context = ScopeContext(asset_names=frozenset({"spr_player"}))
        self.assertIsNone(
            reject_asset_identifier_name("ordinary", scope_context)
        )
        with self.assertRaises(GMLTranspileError) as raised:
            reject_asset_identifier_name("spr_player", scope_context)
        self.assertEqual(
            str(raised.exception),
            "Unscoped identifier 'spr_player' collides with an asset name",
        )

        with self.assertRaises(GMLTranspileError) as raised:
            tokenize_gml_source("ok\n" + "b" * 65)
        self.assertEqual(raised.exception.line, 2)
        self.assertEqual(raised.exception.column, 1)
        self.assertEqual(
            str(raised.exception),
            "GML identifier exceeds 64 characters at line 2, column 1",
        )

    def test_preprocessing_models_layout_bytes_positions_and_failures(self) -> None:
        ordinary = preprocess_gml_source(
            "#ifdef FEATURE\nactive = 1;\n#else\ninactive = 2;\n#endif\n",
            active_symbols={"FEATURE"},
        )
        self.assertIs(type(ordinary), GMLPreprocessResult)
        self.assertEqual(ordinary.source, "\nactive = 1;\n\n\n")
        self.assertEqual(ordinary.diagnostics, ())

        source = (
            "#if FEATURE\r\n"
            "active = 1;\r\n"
            "#else\r"
            "inactive = 2;\n"
            "#endif\r\n"
            "tail = 3;"
        )
        result = preprocess_gml_source_preserving_layout(
            source,
            active_symbols={"FEATURE"},
        )
        expected = (
            "           \r\n"
            "active = 1;\r\n"
            "     \r"
            "             \n"
            "      \r\n"
            "tail = 3;"
        )
        self.assertIs(type(result), GMLPreprocessResult)
        self.assertEqual(result.source, expected)
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(len(result.source), len(source))
        self.assertEqual(result.source.index("active"), source.index("active"))
        self.assertEqual(result.source.index("tail"), source.index("tail"))
        self.assertNotIn("inactive", result.source)
        self.assertEqual(
            [
                (index, char)
                for index, char in enumerate(result.source)
                if char in "\r\n"
            ],
            [
                (index, char)
                for index, char in enumerate(source)
                if char in "\r\n"
            ],
        )

        for operation in (
            preprocess_gml_source,
            preprocess_gml_source_preserving_layout,
        ):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(GMLTranspileError) as raised:
                    operation("#else\nx = 1;")
                self.assertIs(type(raised.exception), GMLTranspileError)
                self.assertEqual(
                    str(raised.exception),
                    "Unmatched preprocessor directive #else at line 1: #else",
                )


class GMLUtilityLexicalParityTests(unittest.TestCase):
    def test_comments_preserve_quoted_delimiters_and_newlines(self) -> None:
        cases = (
            ("label = 'don\\'t // strip'; // comment\r\nnext = 2;",
             "label = 'don\\'t // strip'; \r\nnext = 2;"),
            ('var s = @"//verbatim"; /* block */ tail;', 'var s = @"//verbatim";  tail;'),
            ('var t = $"value {fn(1, 2)}"; // tail\n', 'var t = $"value {fn(1, 2)}"; \n'),
            ("unterminated /* block", "unterminated "),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(strip_comments(source), expected)

    def test_assignment_operators_ignore_comparisons_strings_and_nested_expressions(self) -> None:
        cases = (
            ("a == b", None),
            ("a != b", None),
            ("a <= b", None),
            ('"x=y"', None),
            ("a =", None),
            ("= value", None),
            ('a ??= fn("=", [1, 2])', ("a", "??=", 'fn("=", [1, 2])')),
            ('nested[fn("=")] += value', ('nested[fn("=")]', "+=", "value")),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(split_assignment(source), expected)

    def test_top_level_separators_preserve_escaped_quotes_and_empty_parts(self) -> None:
        cases = (
            ('one, "a,\\\"b", fn(2, 3), [4,5]', ['one', ' "a,\\\"b"', ' fn(2, 3)', ' [4,5]']),
            ('@"one,two", $"{fn(1,2)}", three', ['@"one,two"', ' $"{fn(1,2)}"', ' three']),
            ('head,,tail,', ['head', '', 'tail', '']),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(split_top_level(source, ","), expected)


if __name__ == "__main__":
    unittest.main()
