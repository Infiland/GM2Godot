import json
import os
import re
import tempfile
import unittest

from src.conversion.gml_transpiler import (
    GMLTranspileError,
    GMLTranspileResult,
    load_gml_extension_function_mappings,
    preprocess_gml_source,
    transpile_gml_code,
    transpile_gml_code_with_source_map,
    transpile_gml_expression,
)
from src.conversion.gml_transpiler_parts.constants import BUILTIN_VARIABLE_REGISTRY
from src.conversion.gml_transpiler_parts.expression_api import parse_gml_expression
from src.conversion.gml_transpiler_parts.expression_models import (
    ArrayLiteral,
    NumberLiteral,
    StringLiteral,
    StructLiteral,
    TemplateStringLiteral,
)
from src.conversion.gml_transpiler_parts.lexical_api import tokenize_gml_source


class TestGMLExpressionTranspiler(unittest.TestCase):
    def test_builtin_variable_registry_captures_scope_defaults_and_mutability(self):
        self.assertEqual(BUILTIN_VARIABLE_REGISTRY["x"].scope, "instance")
        self.assertEqual(BUILTIN_VARIABLE_REGISTRY["x"].default, "0")
        self.assertTrue(BUILTIN_VARIABLE_REGISTRY["x"].mutable)
        self.assertFalse(BUILTIN_VARIABLE_REGISTRY["x"].is_array)
        self.assertEqual(BUILTIN_VARIABLE_REGISTRY["x"].subsystem, "transform")
        self.assertEqual(BUILTIN_VARIABLE_REGISTRY["room"].scope, "global")
        self.assertEqual(BUILTIN_VARIABLE_REGISTRY["room"].default, "undefined")
        self.assertFalse(BUILTIN_VARIABLE_REGISTRY["room"].mutable)
        self.assertEqual(BUILTIN_VARIABLE_REGISTRY["view_xview"].scope, "global")
        self.assertTrue(BUILTIN_VARIABLE_REGISTRY["view_xview"].mutable)
        self.assertTrue(BUILTIN_VARIABLE_REGISTRY["view_xview"].is_array)
        self.assertEqual(BUILTIN_VARIABLE_REGISTRY["view_xview"].subsystem, "view")
        self.assertEqual(BUILTIN_VARIABLE_REGISTRY["argument"].default, "[]")
        self.assertEqual(BUILTIN_VARIABLE_REGISTRY["async_load"].subsystem, "async_event")

    def test_preserves_arithmetic_precedence(self):
        self.assertEqual(
            transpile_gml_expression("a + b * c"),
            "GMRuntime.gml_add(a, GMRuntime.gml_mul(b, c))",
        )
        self.assertEqual(
            transpile_gml_expression("(a + b) * c"),
            "GMRuntime.gml_mul((GMRuntime.gml_add(a, b)), c)",
        )

    def test_parses_numeric_real_literals(self):
        self.assertEqual(transpile_gml_expression("42"), "42")
        self.assertEqual(transpile_gml_expression("0.5"), "0.5")
        self.assertEqual(transpile_gml_expression(".5"), ".5")
        self.assertEqual(transpile_gml_expression("5."), "5.")
        self.assertEqual(
            transpile_gml_expression("1.5 / 2"),
            "GMRuntime.gml_div(1.5, 2)",
        )

    def test_strips_numeric_literal_separators(self):
        self.assertEqual(transpile_gml_expression("100_000_000"), "100000000")
        self.assertEqual(transpile_gml_expression("3_141.59"), "3141.59")
        self.assertEqual(transpile_gml_expression("3.141_59"), "3.14159")
        self.assertEqual(transpile_gml_expression("0xDEAD_BEEF"), "0xDEADBEEF")
        self.assertEqual(transpile_gml_expression("$DEAD_BEEF"), "0xDEADBEEF")
        self.assertEqual(
            transpile_gml_expression("0b01101000_01101001"),
            "0b0110100001101001",
        )

    def test_preserves_separated_numeric_literal_values_exactly(self):
        cases = (
            ("100_000_000", "100000000", "100000000 == 100000000"),
            ("3_141.59", "3141.59", "3141.59 == 3141.59"),
            ("0xDEAD_BEEF", "0xDEADBEEF", "0xDEADBEEF == 0xDEADBEEF"),
            (
                "0b01101000_01101001",
                "0b0110100001101001",
                "0b0110100001101001 == 0b0110100001101001",
            ),
        )

        for separated, plain, expected in cases:
            with self.subTest(separated=separated):
                self.assertEqual(
                    transpile_gml_expression(f"{separated} == {plain}"),
                    expected,
                )

    def test_preserves_numeric_literal_float_metadata(self):
        integer_literal = parse_gml_expression("42")
        decimal_literal = parse_gml_expression("3.5")

        self.assertIsInstance(integer_literal, NumberLiteral)
        self.assertIsInstance(decimal_literal, NumberLiteral)
        assert isinstance(integer_literal, NumberLiteral)
        assert isinstance(decimal_literal, NumberLiteral)
        self.assertFalse(integer_literal.is_float_like)
        self.assertTrue(decimal_literal.is_float_like)

    def test_rejects_malformed_numeric_literals(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_expression("1.2.3")

    def test_rejects_malformed_numeric_separator_placement(self):
        cases = (
            "1_",
            "1__000",
            "1_.0",
            "1._0",
            ".5_",
            "0x_DEAD",
            "0xDEAD_",
            "0xDEAD__BEEF",
            "$_DEAD",
            "$DEAD_",
            "$DEAD__BEEF",
            "0b_1010",
            "0b1010_",
            "0b10__10",
        )

        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(GMLTranspileError):
                    transpile_gml_expression(source)

    def test_parses_hexadecimal_literals(self):
        self.assertEqual(transpile_gml_expression("0x2c8e"), "0x2c8e")
        self.assertEqual(transpile_gml_expression("0XDEAD"), "0XDEAD")
        self.assertEqual(transpile_gml_expression("$2c8e"), "0x2c8e")
        self.assertEqual(
            transpile_gml_expression("$2c8e + 1"),
            "GMRuntime.gml_add(0x2c8e, 1)",
        )

    def test_rejects_malformed_hexadecimal_literals(self):
        for source in ("0x", "$", "0x2g", "$2g"):
            with self.subTest(source=source):
                with self.assertRaises(GMLTranspileError):
                    transpile_gml_expression(source)

    def test_parses_hash_color_literals_with_gml_byte_order(self):
        self.assertEqual(transpile_gml_expression("#dd8e2c"), "0x2c8edd")
        self.assertEqual(transpile_gml_expression("#DD8E2C"), "0x2c8edd")
        self.assertEqual(
            transpile_gml_expression("#2c8edd != $2c8edd"),
            "0xdd8e2c != 0x2c8edd",
        )

    def test_rejects_malformed_hash_color_literals(self):
        for source in ("#", "#12345", "#12345g", "#1234567"):
            with self.subTest(source=source):
                with self.assertRaises(GMLTranspileError):
                    transpile_gml_expression(source)

    def test_grey_and_gray_colour_constants_share_gamemaker_values(self):
        # GameMaker defines both spellings: c_grey = c_gray = 8421504,
        # c_dkgrey = c_dkgray = 4210752, c_ltgrey = c_ltgray = 12632256.
        cases = (
            ("c_grey", "c_gray", 8421504),
            ("c_dkgrey", "c_dkgray", 4210752),
            ("c_ltgrey", "c_ltgray", 12632256),
        )
        for british, american, value in cases:
            with self.subTest(constant=british):
                emitted = transpile_gml_expression(british)
                self.assertEqual(emitted, transpile_gml_expression(american))
                self.assertEqual(int(emitted, 16), value)

    def test_preserves_hex_literals_as_numeric_values(self):
        self.assertEqual(
            transpile_gml_expression("$2c8e + 10"),
            "GMRuntime.gml_add(0x2c8e, 10)",
        )
        self.assertEqual(
            transpile_gml_expression("#dd8e2c == $2c8edd"),
            "0x2c8edd == 0x2c8edd",
        )
        self.assertEqual(
            transpile_gml_expression("typeof(#dd8e2c)"),
            "GMRuntime.gml_typeof(0x2c8edd)",
        )
        self.assertEqual(
            transpile_gml_expression("real($2c8e)"),
            "GMRuntime.gml_real(0x2c8e)",
        )

    def test_writes_hex_literals_of_two_to_the_63_or_more_as_signed_int64(self):
        # GDScript clamps an integer literal beyond the int64 range to
        # INT64_MAX ("Cannot represent ... as a 64-bit signed integer"). In
        # GML a hex literal is an int64 with that bit pattern, so
        # 0xFFFFFFFFFFFFFFFF == -1.
        smallest = "(-9223372036854775807 - 1)"
        cases = (
            ("0x8000000000000000", smallest),
            ("$8000000000000000", smallest),
            ("0xFFFFFFFFFFFFFFFF", "(-1)"),
            ("$FFFFFFFFFFFFFFFF", "(-1)"),
            ("0xffff_ffff_ffff_ffff", "(-1)"),
            ("0x8000000000000001", "(-9223372036854775807)"),
            ("0xCBF29CE484222325", "(-3750763034362895579)"),
            ("0b" + "1" * 64, "(-1)"),
            ("0b1" + "0" * 63, smallest),
            ("0x7FFFFFFFFFFFFFFF", "0x7FFFFFFFFFFFFFFF"),
            ("$7FFFFFFFFFFFFFFF", "0x7FFFFFFFFFFFFFFF"),
            ("0xFFFFFFFF", "0xFFFFFFFF"),
            ("0b" + "1" * 63, "0b" + "1" * 63),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_expression(source), expected)

        self.assertEqual(
            transpile_gml_expression("x & $FFFFFFFFFFFFFFFF"),
            "GMRuntime.gml_bit_and(position.x, (-1))",
        )
        self.assertEqual(
            transpile_gml_expression("~0xFFFFFFFFFFFFFFFF"),
            "GMRuntime.gml_bit_not((-1))",
        )
        self.assertEqual(
            transpile_gml_code("var mask = 0x8000000000000000;", indent=""),
            f"var mask = {smallest}",
        )

    def test_writes_decimal_integer_literals_beyond_int64_as_reals(self):
        # GML reads a decimal literal beyond the int64 range as a real; as an
        # integer literal GDScript would clamp it to INT64_MAX.
        cases = (
            ("9223372036854775807", "9223372036854775807"),
            ("9223372036854775808", "9223372036854775808.0"),
            ("18446744073709551615", "18446744073709551615.0"),
            ("9_223_372_036_854_775_808", "9223372036854775808.0"),
            ("9223372036854775808.5", "9223372036854775808.5"),
            ("12345", "12345"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_expression(source), expected)

    def test_hash_color_literal_parity_examples(self):
        cases = (
            ("#dd8e2c == $2c8edd", "0x2c8edd == 0x2c8edd"),
            ("#2c8edd != $2c8edd", "0xdd8e2c != 0x2c8edd"),
            ("#0000ff == $ff0000", "0xff0000 == 0xff0000"),
            ("#ff0000 == $0000ff", "0x0000ff == 0x0000ff"),
        )

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_expression(source), expected)

    def test_parses_binary_literals(self):
        self.assertEqual(transpile_gml_expression("0b0010"), "0b0010")
        self.assertEqual(transpile_gml_expression("0B0100"), "0B0100")
        self.assertEqual(transpile_gml_expression("0b0110_1001"), "0b01101001")
        self.assertEqual(
            transpile_gml_expression("0b0010 | 0b0100"),
            "GMRuntime.gml_bit_or(0b0010, 0b0100)",
        )

    def test_rejects_malformed_binary_literals(self):
        for source in ("0b", "0b2", "0b102", "0b_1010", "0b1010_", "0b10__10"):
            with self.subTest(source=source):
                with self.assertRaises(GMLTranspileError):
                    transpile_gml_expression(source)

    def test_parses_string_literals(self):
        self.assertEqual(transpile_gml_expression('"hello"'), '"hello"')
        self.assertEqual(transpile_gml_expression("'hello'"), "'hello'")
        self.assertEqual(transpile_gml_expression(r'"Hello\"World\""'), r'"Hello\"World\""')
        self.assertEqual(transpile_gml_expression(r'"line\nnext"'), r'"line\nnext"')
        self.assertEqual(transpile_gml_expression(r'"C:\\tmp"'), r'"C:\\tmp"')

    def test_decodes_gamemaker_string_character_escapes(self):
        self.assertEqual(transpile_gml_expression(r'"\q"'), '"q"')
        self.assertEqual(transpile_gml_expression(r"'\q; quote=\''"), r"'q; quote=\''")
        self.assertEqual(transpile_gml_expression(r'"\u61a"'), r'"\u061a"')
        self.assertEqual(
            transpile_gml_expression(
                r'"unicode=\u61; emoji=\u1F600; hex=\x41; octal=\101; vertical=\v"'
            ),
            r'"unicode=a; emoji=\ud83d\ude00; hex=A; octal=A; vertical=\u000b"',
        )

    def test_rejects_invalid_gamemaker_string_escapes(self):
        for source, message in (
            (r'"\u"', "Unicode escape.*requires at least one hex digit"),
            (r'"\x"', "hexadecimal escape.*requires at least one hex digit"),
            (r'"\u110000"', "not a valid Unicode scalar value"),
            (r'"\uD800"', "not a valid Unicode scalar value"),
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, message):
                    transpile_gml_expression(source)

    def test_preserves_string_literal_metadata(self):
        literal = parse_gml_expression('"hello"')

        self.assertIsInstance(literal, StringLiteral)
        assert isinstance(literal, StringLiteral)
        self.assertEqual(literal.value, '"hello"')

    def test_rejects_unterminated_string_literals(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_expression('"unterminated')

    def test_transpiles_documented_verbatim_string_forms_without_escapes(self):
        self.assertEqual(transpile_gml_expression('@""'), '""')
        self.assertEqual(transpile_gml_expression("@''"), '""')
        self.assertEqual(
            transpile_gml_expression('@"first\nsecond\\n"'),
            '"first\\nsecond\\\\n"',
        )
        self.assertEqual(
            transpile_gml_expression("@'double \" quote'"),
            '"double \\" quote"',
        )
        self.assertEqual(
            transpile_gml_expression(r'@"a\"'),
            '"a\\\\"',
        )

    def test_verbatim_content_is_not_split_as_comments_or_statements(self):
        source = (
            'var text = @"line 1\n'
            '// literal comment; { nested }\\n\n'
            'line 3";\n'
            'value = 2;'
        )

        self.assertEqual(
            transpile_gml_code(source, indent=""),
            'var text = "line 1\\n// literal comment; { nested }\\\\n\\nline 3"\n'
            "value = 2",
        )

    def test_rejects_whitespace_and_missing_closer_in_verbatim_strings(self):
        with self.assertRaisesRegex(GMLTranspileError, "Expected expression, got: @"):
            transpile_gml_expression('@ "not contiguous"')
        with self.assertRaisesRegex(
            GMLTranspileError,
            "Unterminated verbatim string literal",
        ):
            transpile_gml_expression('@"unterminated')

    def test_nested_template_expression_skips_verbatim_braces_and_comments(self):
        self.assertEqual(
            transpile_gml_expression('$"wrapped={@\'literal { } // text\'}"'),
            'GMRuntime.gml_string_join(["wrapped=", "literal { } // text"], "")',
        )

    def test_tokenizes_template_string_as_one_literal(self):
        source = '$"Hello {name}!" + 1'
        tokens = tokenize_gml_source(source)

        self.assertEqual(tokens[0].kind, "TEMPLATE_STRING")
        self.assertEqual(tokens[0].value, '$"Hello {name}!"')
        self.assertEqual(tokens[0].line, 1)
        self.assertEqual(tokens[0].column, 1)
        self.assertEqual(tokens[1].value, "+")

        literal = parse_gml_expression('$"Hello {name}!"')
        self.assertIsInstance(literal, TemplateStringLiteral)
        assert isinstance(literal, TemplateStringLiteral)
        self.assertEqual(literal.parts[0], "Hello ")
        self.assertEqual(literal.parts[2], "!")

    def test_transpiles_template_strings_with_implicit_string_conversion(self):
        self.assertEqual(transpile_gml_expression('$""'), '""')
        self.assertEqual(transpile_gml_expression('$"plain text"'), '"plain text"')
        self.assertEqual(
            transpile_gml_expression('$"{score}"'),
            "GMRuntime.gml_string(score)",
        )
        self.assertEqual(
            transpile_gml_expression('$"Hello {name}!"'),
            'GMRuntime.gml_string_join(["Hello ", name, "!"], "")',
        )
        self.assertEqual(
            transpile_gml_expression('$"{score}/{true}/{undefined}"'),
            'GMRuntime.gml_string_join([score, "/", true, "/", '
            'GMRuntime.gml_undefined()], "")',
        )

    def test_transpiles_multiple_template_expressions_and_accessors(self):
        self.assertEqual(
            transpile_gml_expression(
                '$"Score {score + bonus}; first {_values[| 0]}"'
            ),
            'GMRuntime.gml_string_join(["Score ", '
            'GMRuntime.gml_add(score, bonus), "; first ", '
            'GMRuntime.gml_ds_list_find_value(_values, 0)], "")',
        )

    def test_transpiles_nested_template_and_struct_expressions(self):
        self.assertEqual(
            transpile_gml_expression('$"Outer {$"inner {value}"}"'),
            'GMRuntime.gml_string_join(["Outer ", '
            'GMRuntime.gml_string_join(["inner ", value], "")], "")',
        )
        self.assertEqual(
            transpile_gml_expression('$"Struct {({value: score}).value}"'),
            'GMRuntime.gml_string_join(["Struct ", '
            'GMRuntime.gml_selector_get((GMRuntime.gml_struct({"value": score})), '
            '"value")], "")',
        )

    def test_preserves_template_string_escapes(self):
        self.assertEqual(
            transpile_gml_expression(
                r'$"Use \{literal\} and \"quotes\": {value}\n"'
            ),
            r'GMRuntime.gml_string_join(["Use {literal} and \"quotes\": ", '
            r'value, "\n"], "")',
        )

    def test_decodes_gamemaker_template_string_character_escapes(self):
        self.assertEqual(
            transpile_gml_expression(
                r'$"unicode=\u61; emoji=\u1F600; hex=\x41; octal=\101; vertical=\v"'
            ),
            r'"unicode=a; emoji=\ud83d\ude00; hex=A; octal=A; vertical=\u000b"',
        )
        self.assertEqual(
            transpile_gml_expression(r'$"\u61a"'),
            r'"\u061a"',
        )
        self.assertEqual(
            transpile_gml_expression(r'$"\1234"'),
            '"S4"',
        )
        self.assertEqual(
            transpile_gml_expression(r'$"\q"'),
            '"q"',
        )

    def test_rejects_invalid_gamemaker_template_string_escapes(self):
        cases = (
            (r'$"\u"', "Unicode escape.*requires at least one hex digit"),
            (r'$"\x"', "hexadecimal escape.*requires at least one hex digit"),
            (r'$"\u110000"', "not a valid Unicode scalar value"),
            (r'$"\uD800"', "not a valid Unicode scalar value"),
        )

        for source, message in cases:
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, message):
                    transpile_gml_expression(source)

    def test_template_strings_preserve_parser_context(self):
        self.assertEqual(
            transpile_gml_expression(
                '$"Answer {ANSWER}"',
                macro_values={"ANSWER": "40 + 2"},
            ),
            'GMRuntime.gml_string_join(["Answer ", '
            'GMRuntime.gml_add(40, 2)], "")',
        )
        self.assertEqual(
            transpile_gml_expression(
                '$"Score {score}"',
                global_names={"score"},
            ),
            'GMRuntime.gml_string_join(["Score ", '
            'GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "score")], "")',
        )

    def test_template_strings_allow_newlines_only_inside_expressions(self):
        self.assertEqual(
            transpile_gml_code(
                'var message = $"Result {\nvalue + 1\n}";',
                indent="",
            ),
            'var message = GMRuntime.gml_string_join(["Result ", '
            'GMRuntime.gml_add(value, 1)], "")',
        )
        with self.assertRaisesRegex(
            GMLTranspileError,
            "Template string literal text cannot contain a newline",
        ):
            transpile_gml_expression('$"bad\ntext"')

    def test_template_string_expressions_support_comments_with_braces(self):
        self.assertEqual(
            transpile_gml_expression('$"Value {1 /* ignored } */ + 2}"'),
            'GMRuntime.gml_string_join(["Value ", '
            'GMRuntime.gml_add(1, 2)], "")',
        )
        self.assertEqual(
            transpile_gml_expression('$"Value {1 // ignored }\n + 2}"'),
            'GMRuntime.gml_string_join(["Value ", '
            'GMRuntime.gml_add(1, 2)], "")',
        )

    def test_template_strings_survive_preprocessing_and_declaration_splitting(self):
        source = (
            'var url = $"URL: {string("http://example.com")}";\n'
            'var csv = $"CSV: {string("a,b")}", other = 1;\n'
            'message = $"Equals: {string("a=b")}";'
        )

        self.assertEqual(
            transpile_gml_code(source, indent=""),
            'var url = GMRuntime.gml_string_join(["URL: ", '
            'GMRuntime.gml_string("http://example.com")], "")\n'
            'var csv = GMRuntime.gml_string_join(["CSV: ", '
            'GMRuntime.gml_string("a,b")], "")\n'
            'var other = 1\n'
            'message = GMRuntime.gml_string_join(["Equals: ", '
            'GMRuntime.gml_string("a=b")], "")',
        )

    def test_template_string_target_expressions_are_evaluated_once(self):
        self.assertEqual(
            transpile_gml_code(
                'inventory[? $"key {next_key()}"] += 1;',
                indent="",
            ),
            'var _gml_map_key_0 = GMRuntime.gml_string_join(["key ", '
            'GMRuntime.gml_call_named("next_key", [], self, other)], "")\n'
            'GMRuntime.gml_ds_map_set(inventory, _gml_map_key_0, '
            'GMRuntime.gml_add(GMRuntime.gml_ds_map_find_value('
            'inventory, _gml_map_key_0), 1))',
        )

    def test_rejects_malformed_template_strings(self):
        cases = (
            ('$"unterminated', "Unterminated template string literal"),
            ('$"value {name"', "Unterminated template string interpolation"),
            ('$"value {}"', "Template string interpolation cannot be empty"),
        )

        for source, message in cases:
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, message):
                    transpile_gml_expression(source)

        with self.assertRaises(GMLTranspileError):
            transpile_gml_expression('$"value {name +}"')

    def test_transpiles_logical_operators(self):
        self.assertEqual(
            transpile_gml_expression("a && !b || c"),
            "GMRuntime.gml_bool(a) and not GMRuntime.gml_bool(b) or GMRuntime.gml_bool(c)",
        )
        self.assertEqual(
            transpile_gml_expression("a and not b or c"),
            "GMRuntime.gml_bool(a) and not GMRuntime.gml_bool(b) or GMRuntime.gml_bool(c)",
        )
        self.assertEqual(
            transpile_gml_expression("a ^^ b"),
            "GMRuntime.gml_bool(a) != GMRuntime.gml_bool(b)",
        )

    def test_transpiles_div_and_mod(self):
        self.assertEqual(
            transpile_gml_expression("score div 10"),
            "GMRuntime.gml_int_div(score, 10)",
        )
        self.assertEqual(
            transpile_gml_expression("score mod 3"),
            "GMRuntime.gml_mod(score, 3)",
        )

    def test_transpiles_runtime_safe_real_division(self):
        self.assertEqual(
            transpile_gml_expression("5 / 2"),
            "GMRuntime.gml_div(5, 2)",
        )
        self.assertEqual(
            transpile_gml_expression("1 / 0"),
            "GMRuntime.gml_div(1, 0)",
        )
        self.assertEqual(
            transpile_gml_expression("a / b + c"),
            "GMRuntime.gml_add(GMRuntime.gml_div(a, b), c)",
        )

    def test_transpiles_invalid_numeric_results_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("0 / 0"),
            "GMRuntime.gml_div(0, 0)",
        )
        self.assertEqual(
            transpile_gml_expression("sqrt(-1)"),
            "GMRuntime.gml_sqrt(-1)",
        )

    def test_transpiles_integer_division_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("5 div 2"),
            "GMRuntime.gml_int_div(5, 2)",
        )
        self.assertEqual(
            transpile_gml_expression("int64(5) / int64(2)"),
            "GMRuntime.gml_div(GMRuntime.gml_int64(5), GMRuntime.gml_int64(2))",
        )
        self.assertEqual(
            transpile_gml_expression("int64(5) div int64(2)"),
            "GMRuntime.gml_int_div(GMRuntime.gml_int64(5), GMRuntime.gml_int64(2))",
        )
        self.assertEqual(
            transpile_gml_expression("a div b + c"),
            "GMRuntime.gml_add(GMRuntime.gml_int_div(a, b), c)",
        )

    def test_transpiles_dynamic_arithmetic_through_runtime(self):
        self.assertEqual(transpile_gml_expression("a + b"), "GMRuntime.gml_add(a, b)")
        self.assertEqual(transpile_gml_expression("a - b"), "GMRuntime.gml_sub(a, b)")
        self.assertEqual(transpile_gml_expression("a * b"), "GMRuntime.gml_mul(a, b)")
        self.assertEqual(transpile_gml_expression("a % b"), "GMRuntime.gml_mod(a, b)")

    def test_transpiles_string_concatenation_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression('"hello" + " world"'),
            'GMRuntime.gml_add("hello", " world")',
        )
        self.assertEqual(
            transpile_gml_expression('score + " pts"'),
            'GMRuntime.gml_add(score, " pts")',
        )
        self.assertEqual(
            transpile_gml_expression('"Score: " + string(score)'),
            'GMRuntime.gml_add("Score: ", GMRuntime.gml_string(score))',
        )

    def test_transpiles_infinity_and_nan_constants(self):
        self.assertEqual(transpile_gml_expression("infinity"), "INF")
        self.assertEqual(transpile_gml_expression("NaN"), "NAN")
        self.assertEqual(transpile_gml_expression("pi"), "PI")

    def test_transpiles_nan_as_numeric_runtime_value(self):
        self.assertEqual(transpile_gml_expression("nan"), "NAN")
        self.assertEqual(
            transpile_gml_expression("NaN + 1"),
            "GMRuntime.gml_add(NAN, 1)",
        )
        self.assertEqual(
            transpile_gml_expression("is_numeric(NaN)"),
            "GMRuntime.is_numeric(NAN)",
        )
        self.assertEqual(
            transpile_gml_expression("is_real(NaN)"),
            "GMRuntime.is_real(NAN)",
        )
        self.assertEqual(
            transpile_gml_expression("real(NaN)"),
            "GMRuntime.gml_real(NAN)",
        )

    def test_preserves_infinity_equality_cases(self):
        self.assertEqual(
            transpile_gml_expression("infinity == infinity"),
            "INF == INF",
        )
        self.assertEqual(
            transpile_gml_expression("infinity == NaN"),
            "GMRuntime.gml_eq(INF, NAN)",
        )
        self.assertEqual(
            transpile_gml_expression("infinity == undefined"),
            "GMRuntime.gml_eq(INF, GMRuntime.gml_undefined())",
        )

    def test_special_equality_table_cells(self):
        cases = (
            ("NaN == NaN", "GMRuntime.gml_eq(NAN, NAN)"),
            ("NaN == undefined", "GMRuntime.gml_eq(NAN, GMRuntime.gml_undefined())"),
            ("NaN == infinity", "GMRuntime.gml_eq(NAN, INF)"),
            ("undefined == NaN", "GMRuntime.gml_eq(GMRuntime.gml_undefined(), NAN)"),
            (
                "undefined == undefined",
                "GMRuntime.gml_eq(GMRuntime.gml_undefined(), GMRuntime.gml_undefined())",
            ),
            ("undefined == infinity", "GMRuntime.gml_eq(GMRuntime.gml_undefined(), INF)"),
            ("infinity == NaN", "GMRuntime.gml_eq(INF, NAN)"),
            ("infinity == undefined", "GMRuntime.gml_eq(INF, GMRuntime.gml_undefined())"),
            ("infinity == infinity", "INF == INF"),
        )

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_expression(source), expected)

    def test_nan_equality_uses_runtime_type_table(self):
        self.assertEqual(
            transpile_gml_expression("NaN == NaN"),
            "GMRuntime.gml_eq(NAN, NAN)",
        )
        self.assertEqual(
            transpile_gml_expression("NaN != NaN"),
            "GMRuntime.gml_ne(NAN, NAN)",
        )
        self.assertEqual(
            transpile_gml_expression("array_equals([NaN], [NaN])"),
            "GMRuntime.gml_array_equals([NAN], [NAN])",
        )
        self.assertEqual(
            transpile_gml_expression("array_push(items, 2, 3)"),
            "GMRuntime.gml_array_push(items, [2, 3])",
        )

    def test_undefined_equality_uses_runtime_type_table(self):
        self.assertEqual(
            transpile_gml_expression("undefined == undefined"),
            "GMRuntime.gml_eq(GMRuntime.gml_undefined(), GMRuntime.gml_undefined())",
        )
        self.assertEqual(
            transpile_gml_expression("undefined == NaN"),
            "GMRuntime.gml_eq(GMRuntime.gml_undefined(), NAN)",
        )
        self.assertEqual(
            transpile_gml_expression("undefined != infinity"),
            "GMRuntime.gml_ne(GMRuntime.gml_undefined(), INF)",
        )

    def test_transpiles_single_equals_as_expression_equality(self):
        self.assertEqual(
            transpile_gml_expression("faster = true"),
            "GMRuntime.gml_eq(faster, true)",
        )
        self.assertEqual(
            transpile_gml_expression("1 = 1"),
            "1 == 1",
        )

    def test_transpiles_reference_equality_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("items == other_items"),
            "GMRuntime.gml_eq(items, other_items)",
        )
        self.assertEqual(
            transpile_gml_expression("items != other_items"),
            "GMRuntime.gml_ne(items, other_items)",
        )
        self.assertEqual(
            transpile_gml_expression("{a: 1} == {a: 1}"),
            'GMRuntime.gml_eq(GMRuntime.gml_struct({"a": 1}), GMRuntime.gml_struct({"a": 1}))',
        )

    def test_transpiles_infinity_variable_functions(self):
        self.assertEqual(
            transpile_gml_expression("is_infinity(infinity)"),
            "GMRuntime.is_infinity(INF)",
        )
        self.assertEqual(
            transpile_gml_expression("is_infinity(-infinity)"),
            "GMRuntime.is_infinity(-INF)",
        )
        self.assertEqual(
            transpile_gml_expression("is_infinity(1)"),
            "GMRuntime.is_infinity(1)",
        )
        self.assertEqual(
            transpile_gml_expression("typeof(infinity)"),
            "GMRuntime.gml_typeof(INF)",
        )
        self.assertEqual(
            transpile_gml_expression("string(infinity)"),
            "GMRuntime.gml_string(INF)",
        )
        self.assertEqual(
            transpile_gml_expression("bool(infinity)"),
            "GMRuntime.gml_bool(INF)",
        )

    def test_transpiles_shared_value_helpers(self):
        self.assertEqual(
            transpile_gml_expression("undefined"),
            "GMRuntime.gml_undefined()",
        )
        self.assertEqual(
            transpile_gml_expression("is_undefined(undefined)"),
            "GMRuntime.is_undefined(GMRuntime.gml_undefined())",
        )
        self.assertEqual(
            transpile_gml_expression("is_nan(NaN)"),
            "GMRuntime.is_nan_value(NAN)",
        )

    def test_transpiles_pointer_values_and_helpers(self):
        self.assertEqual(
            transpile_gml_expression("noone"),
            "GMRuntime.gml_instance_noone()",
        )
        self.assertEqual(
            transpile_gml_expression("pointer_null"),
            "GMRuntime.gml_pointer_null()",
        )
        self.assertEqual(
            transpile_gml_expression("pointer_invalid"),
            "GMRuntime.gml_pointer_invalid()",
        )
        self.assertEqual(transpile_gml_expression("ptr(0)"), "GMRuntime.gml_ptr(0)")
        self.assertEqual(
            transpile_gml_expression("is_ptr(pointer_null)"),
            "GMRuntime.is_ptr(GMRuntime.gml_pointer_null())",
        )
        self.assertEqual(
            transpile_gml_expression("is_ptr(pointer_invalid)"),
            "GMRuntime.is_ptr(GMRuntime.gml_pointer_invalid())",
        )
        self.assertEqual(
            transpile_gml_expression('handle_parse("ref ds_list 1")'),
            'GMRuntime.gml_handle_parse("ref ds_list 1")',
        )
        self.assertEqual(
            transpile_gml_expression('is_handle(handle_parse("ref ds_list 1"))'),
            'GMRuntime.is_handle(GMRuntime.gml_handle_parse("ref ds_list 1"))',
        )
        self.assertEqual(
            transpile_gml_expression('ref_create(self, "text")'),
            'GMRuntime.gml_ref_create(self, "text")',
        )
        self.assertEqual(
            transpile_gml_expression('ref_create(self, "array", 2)'),
            'GMRuntime.gml_ref_create(self, "array", 2)',
        )
        self.assertEqual(
            transpile_gml_expression('handle_parse(string(ref_create(self, "text")))'),
            'GMRuntime.gml_handle_parse(GMRuntime.gml_string(GMRuntime.gml_ref_create(self, "text")))',
        )
        self.assertEqual(
            transpile_gml_expression("typeof(pointer_null)"),
            "GMRuntime.gml_typeof(GMRuntime.gml_pointer_null())",
        )

    def test_pointer_equality_uses_runtime_type_table(self):
        self.assertEqual(
            transpile_gml_expression("pointer_null == pointer_null"),
            "GMRuntime.gml_eq(GMRuntime.gml_pointer_null(), GMRuntime.gml_pointer_null())",
        )
        self.assertEqual(
            transpile_gml_expression("pointer_invalid != pointer_null"),
            "GMRuntime.gml_ne(GMRuntime.gml_pointer_invalid(), GMRuntime.gml_pointer_null())",
        )
        self.assertEqual(
            transpile_gml_expression("instance_id != noone"),
            "GMRuntime.gml_ne(instance_id, GMRuntime.gml_instance_noone())",
        )

    def test_pointer_operations_stay_on_runtime_checked_paths(self):
        self.assertEqual(
            transpile_gml_expression("pointer_null + 1"),
            "GMRuntime.gml_add(GMRuntime.gml_pointer_null(), 1)",
        )
        self.assertEqual(
            transpile_gml_expression("pointer_null & 1"),
            "GMRuntime.gml_bit_and(GMRuntime.gml_pointer_null(), 1)",
        )

    def test_undefined_conditions_use_gml_truthiness(self):
        self.assertEqual(
            transpile_gml_code("if undefined begin score = 1; end", indent=""),
            "if GMRuntime.gml_bool(GMRuntime.gml_undefined()):\n\tscore = 1",
        )

    def test_transpiles_nan_type_helpers(self):
        self.assertEqual(
            transpile_gml_expression("typeof(NaN)"),
            "GMRuntime.gml_typeof(NAN)",
        )
        self.assertEqual(
            transpile_gml_expression("is_nan(NaN)"),
            "GMRuntime.is_nan_value(NAN)",
        )
        self.assertEqual(
            transpile_gml_expression("is_nan(0)"),
            "GMRuntime.is_nan_value(0)",
        )
        self.assertEqual(
            transpile_gml_expression("is_nan(int64(0))"),
            "GMRuntime.is_nan_value(GMRuntime.gml_int64(0))",
        )

    def test_transpiles_boolean_value_helpers(self):
        self.assertEqual(transpile_gml_expression("true"), "true")
        self.assertEqual(transpile_gml_expression("false"), "false")
        self.assertEqual(
            transpile_gml_expression("bool(0.5)"),
            "GMRuntime.gml_bool(0.5)",
        )
        self.assertEqual(
            transpile_gml_expression('bool(handle_parse("ref ds_list 1"))'),
            'GMRuntime.gml_bool(GMRuntime.gml_handle_parse("ref ds_list 1"))',
        )
        self.assertEqual(
            transpile_gml_expression("is_bool(true)"),
            "GMRuntime.is_bool(true)",
        )

    def test_transpiles_real_number_conversion_helpers(self):
        self.assertEqual(transpile_gml_expression("real(score)"), "GMRuntime.gml_real(score)")
        self.assertEqual(transpile_gml_expression('real("0x00F")'), 'GMRuntime.gml_real("0x00F")')
        self.assertEqual(
            transpile_gml_expression('real(handle_parse("ref ds_list 1"))'),
            'GMRuntime.gml_real(GMRuntime.gml_handle_parse("ref ds_list 1"))',
        )
        self.assertEqual(transpile_gml_expression("int64(score)"), "GMRuntime.gml_int64(score)")
        self.assertEqual(transpile_gml_expression('int64("42")'), 'GMRuntime.gml_int64("42")')
        self.assertEqual(
            transpile_gml_expression("int64(pointer_null)"),
            "GMRuntime.gml_int64(GMRuntime.gml_pointer_null())",
        )
        self.assertEqual(transpile_gml_expression("is_real(score)"), "GMRuntime.is_real(score)")
        self.assertEqual(transpile_gml_expression("is_numeric(true)"), "GMRuntime.is_numeric(true)")
        self.assertEqual(transpile_gml_expression("is_int32(score)"), "GMRuntime.is_int32(score)")
        self.assertEqual(transpile_gml_expression("is_int32(2147483647)"), "GMRuntime.is_int32(2147483647)")
        self.assertEqual(transpile_gml_expression("is_int32(2147483648)"), "GMRuntime.is_int32(2147483648)")
        self.assertEqual(
            transpile_gml_expression("is_numeric(int64(score))"),
            "GMRuntime.is_numeric(GMRuntime.gml_int64(score))",
        )
        self.assertEqual(
            transpile_gml_expression("is_int64(int64(score))"),
            "GMRuntime.is_int64(GMRuntime.gml_int64(score))",
        )
        self.assertEqual(
            transpile_gml_expression("is_int64(int64(2147483648))"),
            "GMRuntime.is_int64(GMRuntime.gml_int64(2147483648))",
        )
        self.assertEqual(
            transpile_gml_expression("int64(score) + int64(delta)"),
            "GMRuntime.gml_add(GMRuntime.gml_int64(score), GMRuntime.gml_int64(delta))",
        )
        self.assertEqual(transpile_gml_expression('ptr("42")'), 'GMRuntime.gml_ptr("42")')
        self.assertEqual(
            transpile_gml_expression('ptr(int64("42"))'),
            'GMRuntime.gml_ptr(GMRuntime.gml_int64("42"))',
        )

    def test_transpiles_string_value_helpers(self):
        self.assertEqual(transpile_gml_expression('string("abc")'), 'GMRuntime.gml_string("abc")')
        self.assertEqual(transpile_gml_expression('typeof("abc")'), 'GMRuntime.gml_typeof("abc")')
        self.assertEqual(transpile_gml_expression('is_string("abc")'), 'GMRuntime.is_string("abc")')

    def test_transpiles_string_length(self):
        self.assertEqual(
            transpile_gml_expression("string_length(s)"),
            "GMRuntime.gml_string_length(s)",
        )

    def test_transpiles_string_byte_length(self):
        self.assertEqual(
            transpile_gml_expression("string_byte_length(s)"),
            "GMRuntime.gml_string_byte_length(s)",
        )

    def test_transpiles_string_char_at(self):
        self.assertEqual(
            transpile_gml_expression('string_char_at(s, 1)'),
            'GMRuntime.gml_string_char_at(s, 1)',
        )

    def test_transpiles_string_ord_at(self):
        self.assertEqual(
            transpile_gml_expression('string_ord_at(s, 1)'),
            'GMRuntime.gml_string_ord_at(s, 1)',
        )

    def test_transpiles_string_hash_to_newline(self):
        self.assertEqual(
            transpile_gml_expression('string_hash_to_newline("a#b")'),
            'GMRuntime.gml_string_hash_to_newline("a#b")',
        )

    def test_transpiles_string_copy(self):
        self.assertEqual(
            transpile_gml_expression('string_copy(s, 1, 3)'),
            'GMRuntime.gml_string_copy(s, 1, 3)',
        )

    def test_transpiles_string_pos(self):
        self.assertEqual(
            transpile_gml_expression('string_pos("x", s)'),
            'GMRuntime.gml_string_pos("x", s)',
        )

    def test_transpiles_string_replace(self):
        self.assertEqual(
            transpile_gml_expression('string_replace(s, "a", "b")'),
            'GMRuntime.gml_string_replace(s, "a", "b")',
        )

    def test_transpiles_string_replace_all(self):
        self.assertEqual(
            transpile_gml_expression('string_replace_all(s, "a", "b")'),
            'GMRuntime.gml_string_replace_all(s, "a", "b")',
        )

    def test_transpiles_string_delete(self):
        self.assertEqual(
            transpile_gml_expression('string_delete(s, 1, 3)'),
            'GMRuntime.gml_string_delete(s, 1, 3)',
        )

    def test_transpiles_string_insert(self):
        self.assertEqual(
            transpile_gml_expression('string_insert("x", s, 1)'),
            'GMRuntime.gml_string_insert("x", s, 1)',
        )

    def test_transpiles_string_lower(self):
        self.assertEqual(
            transpile_gml_expression('string_lower(s)'),
            'GMRuntime.gml_string_lower(s)',
        )

    def test_transpiles_string_upper(self):
        self.assertEqual(
            transpile_gml_expression('string_upper(s)'),
            'GMRuntime.gml_string_upper(s)',
        )

    def test_transpiles_string_trim(self):
        self.assertEqual(
            transpile_gml_expression('string_trim(s)'),
            'GMRuntime.gml_string_trim(s)',
        )

    def test_transpiles_string_repeat(self):
        self.assertEqual(
            transpile_gml_expression('string_repeat(s, 3)'),
            'GMRuntime.gml_string_repeat(s, 3)',
        )

    def test_transpiles_string_digits(self):
        self.assertEqual(
            transpile_gml_expression('string_digits(s)'),
            'GMRuntime.gml_string_digits(s)',
        )

    def test_transpiles_string_letters(self):
        self.assertEqual(
            transpile_gml_expression('string_letters(s)'),
            'GMRuntime.gml_string_letters(s)',
        )

    def test_transpiles_string_lettersdigits(self):
        self.assertEqual(
            transpile_gml_expression('string_lettersdigits(s)'),
            'GMRuntime.gml_string_lettersdigits(s)',
        )

    def test_transpiles_string_split(self):
        self.assertEqual(
            transpile_gml_expression('string_split(s, ",")'),
            'GMRuntime.gml_string_split(s, ",")',
        )

    def test_transpiles_string_join(self):
        # string_join(delimiter, value1, ...) joins the values after the
        # delimiter (Function_String.js string_join).
        self.assertEqual(
            transpile_gml_expression('string_join(",", a, 1, "b")'),
            'GMRuntime.gml_string_join_values(",", [a, 1, "b"])',
        )
        self.assertEqual(
            transpile_gml_expression('string_join(",", a)'),
            'GMRuntime.gml_string_join_values(",", [a])',
        )

    def test_transpiles_string_format(self):
        self.assertEqual(
            transpile_gml_expression("string_format(score, 6, 2)"),
            "GMRuntime.gml_string_format(score, 6, 2)",
        )

    def test_transpiles_string_count_point_in_rectangle_and_array_set(self):
        self.assertEqual(
            transpile_gml_expression('string_count("Easy", tags)'),
            'GMRuntime.gml_string_count("Easy", tags)',
        )
        self.assertEqual(
            transpile_gml_expression("point_in_rectangle(mx, my, 40, 720, 120, 760)"),
            "GMRuntime.gml_point_in_rectangle(mx, my, 40, 720, 120, 760)",
        )
        self.assertEqual(
            transpile_gml_expression("array_set(items, 2, 5)"),
            "GMRuntime.gml_array_set_function(items, 2, 5)",
        )

    def test_transpiles_device_mouse_buttons_and_mouse_wheel_calls(self):
        self.assertEqual(
            transpile_gml_expression("device_mouse_check_button_released(0, mb_left)"),
            "GMRuntime.gml_device_mouse_check_button_released(0, MOUSE_BUTTON_LEFT)",
        )
        self.assertEqual(transpile_gml_expression("mouse_wheel_up()"), "GMRuntime.gml_mouse_wheel_up()")
        self.assertEqual(transpile_gml_expression("mouse_wheel_down()"), "GMRuntime.gml_mouse_wheel_down()")

    def test_transpiles_object_get_name_and_sprite_exists(self):
        self.assertEqual(
            transpile_gml_expression("object_get_name(object_index)"),
            "GMRuntime.gml_object_get_name(object_index)",
        )
        self.assertEqual(transpile_gml_expression("sprite_exists(spr)"), "GMRuntime.gml_sprite_exists(spr)")

    def test_transpiles_room_set_width_and_height(self):
        self.assertEqual(
            transpile_gml_expression("room_set_width(level_room, blocks * 32)"),
            "GMRuntime.gml_room_set_width(level_room, GMRuntime.gml_mul(blocks, 32))",
        )
        self.assertEqual(
            transpile_gml_expression("room_set_height(level_room, 768)"),
            "GMRuntime.gml_room_set_height(level_room, 768)",
        )

    def test_transpiles_layer_draw_depth_forcing(self):
        self.assertEqual(
            transpile_gml_expression("layer_force_draw_depth(true, 0)"),
            "GMRuntime.gml_layer_force_draw_depth(true, 0)",
        )
        self.assertEqual(
            transpile_gml_expression("layer_is_draw_depth_forced()"),
            "GMRuntime.gml_layer_is_draw_depth_forced()",
        )
        self.assertEqual(transpile_gml_expression("layer_get_forced_depth()"), "GMRuntime.gml_layer_get_forced_depth()")

    def test_transpiles_date_functions_and_time_zone_constants(self):
        self.assertEqual(
            transpile_gml_expression("date_create_datetime(2024, 2, 29, 23, 59, 59)"),
            "GMRuntime.gml_date_create_datetime(2024, 2, 29, 23, 59, 59)",
        )
        self.assertEqual(
            transpile_gml_expression("date_day_span(date_current_datetime(), d)"),
            "GMRuntime.gml_date_day_span(GMRuntime.gml_date_current_datetime(), d)",
        )
        self.assertEqual(transpile_gml_expression("date_set_timezone(timezone_utc)"), "GMRuntime.gml_date_set_timezone(1)")
        self.assertEqual(transpile_gml_expression("timezone_local"), "0")
        with self.assertRaises(GMLTranspileError):
            transpile_gml_expression("date_inc_day(d)")

    def test_transpiles_chr(self):
        self.assertEqual(
            transpile_gml_expression('chr(65)'),
            'GMRuntime.gml_chr(65)',
        )

    def test_transpiles_ord(self):
        self.assertEqual(
            transpile_gml_expression('ord("A")'),
            'GMRuntime.gml_ord("A")',
        )

    def test_transpiles_ansi_char(self):
        self.assertEqual(
            transpile_gml_expression('ansi_char(65)'),
            'GMRuntime.gml_ansi_char(65)',
        )

    def test_transpiles_typeof_return_string_categories(self):
        cases = (
            ("typeof(undefined)", "GMRuntime.gml_typeof(GMRuntime.gml_undefined())"),
            ("typeof(null)", "GMRuntime.gml_typeof(null)"),
            ("typeof(true)", "GMRuntime.gml_typeof(true)"),
            ("typeof(1)", "GMRuntime.gml_typeof(1)"),
            ("typeof(1.5)", "GMRuntime.gml_typeof(1.5)"),
            ('typeof("abc")', 'GMRuntime.gml_typeof("abc")'),
            ("typeof([1])", "GMRuntime.gml_typeof([1])"),
            ("typeof({a: 1})", 'GMRuntime.gml_typeof(GMRuntime.gml_struct({"a": 1}))'),
            ("typeof(ptr(0))", "GMRuntime.gml_typeof(GMRuntime.gml_ptr(0))"),
            ("typeof(int64(score))", "GMRuntime.gml_typeof(GMRuntime.gml_int64(score))"),
            ("typeof(method(player, callback))", "GMRuntime.gml_typeof(GMRuntime.gml_method(player, callback))"),
            (
                'typeof(handle_parse("ref script 1"))',
                'GMRuntime.gml_typeof(GMRuntime.gml_handle_parse("ref script 1"))',
            ),
        )

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_expression(source), expected)

    def test_transpiles_nameof_function_call_syntax_without_emitting_call(self):
        self.assertEqual(transpile_gml_expression("nameof(ds_list_create)"), '"ds_list_create"')
        self.assertEqual(transpile_gml_expression("nameof(ds_list_create())"), '"ds_list_create"')
        self.assertEqual(
            transpile_gml_expression("nameof(ds_list_create(expensive()))"),
            '"ds_list_create"',
        )
        self.assertEqual(
            transpile_gml_code("name = nameof(ds_list_create(expensive()));", indent=""),
            'name = "ds_list_create"',
        )

    def test_transpiles_nameof_compile_time_identifiers(self):
        cases = (
            ("nameof(score)", '"score"'),
            ("nameof(obj_enemy)", '"obj_enemy"'),
            ("nameof(MY_MACRO)", '"MY_MACRO"'),
            ("nameof(pi)", '"pi"'),
            ("nameof(undefined)", '"undefined"'),
            ("nameof(RAINBOW.GREEN)", '"GREEN"'),
            ("nameof(global.factory)", '"factory"'),
        )

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_expression(source), expected)

    def test_transpiles_nameof_enum_member_after_declaration(self):
        self.assertEqual(
            transpile_gml_code("enum RAINBOW { GREEN }\nlabel = nameof(RAINBOW.GREEN)", indent=""),
            'var RAINBOW = GMRuntime.gml_enum({"GREEN": 0})\nlabel = "GREEN"',
        )

    def test_method_function_literals_resolve_fields_through_rebound_self(self):
        self.assertEqual(
            transpile_gml_expression(
                "method(scope, function() { return value; })"
            ),
            "GMRuntime.gml_method(scope, GMRuntime.gml_receiver_method(self, "
            "func(_gml_method_self = null, _gml_method_other = null): return "
            'GMRuntime.gml_variable_instance_get(_gml_method_self, "value")))',
        )

    def test_method_function_literals_receive_other_from_each_invocation(self):
        self.assertEqual(
            transpile_gml_expression(
                "function() { return [self, other]; }"
            ),
            "GMRuntime.gml_receiver_method(self, "
            "func(_gml_method_self = null, _gml_method_other = null): "
            "return [_gml_method_self, _gml_method_other])",
        )

    def test_method_locals_get_their_own_names_beside_enclosing_locals(self):
        # A method's locals are its own (manual: Local Variables); GDScript
        # rejects a lambda local that reuses an enclosing local or parameter.
        code = transpile_gml_code(
            "function outer(_name) {\n"
            "    var n = 1;\n"
            "    var f = function() {\n"
            "        var n = 2;\n"
            "        var _name = \"n\";\n"
            "        var g = function() { var n = 4; return n; };\n"
            "        for (var _i = 0; _i < 2; _i += 1) { n += _i; }\n"
            "        return n + other.n + _name;\n"
            "    };\n"
            "    return f() + n;\n"
            "}\n"
        )

        self.assertIn("\t\tvar n = 1\n", code)
        self.assertIn("\t\t\tvar _gml_local_n_2 = 2\n", code)
        self.assertIn('\t\t\tvar _gml_local__name = "n"\n', code)
        self.assertIn("\t\t\t\tvar _gml_local_n = 4\n\t\t\t\treturn _gml_local_n\n", code)
        self.assertIn("_gml_local_n_2 = GMRuntime.gml_add(_gml_local_n_2, _i)", code)
        self.assertIn(
            'return GMRuntime.gml_add(GMRuntime.gml_add(_gml_local_n_2, '
            'GMRuntime.gml_selector_get(_gml_method_other, "n")), _gml_local__name)',
            code,
        )
        self.assertIn('GMRuntime.gml_call_value(f, [], _gml_method_self, _gml_method_other, "f"), n)', code)
        # A local that reuses no enclosing name keeps its own name.
        self.assertIn("\t\t\tvar _i = 0\n", code)

    def test_method_temporaries_are_named_apart_from_the_enclosing_code(self):
        # switch, try, with and repeat declare temporaries. A method is a
        # GDScript lambda inside the enclosing code, where GDScript rejects
        # redeclaring a name already in scope, so a method (or a method in a
        # method) using the same constructs needs temporaries of its own.
        code = transpile_gml_code(
            "switch (a) { case 1: b = 1; break; }\n"
            "try { b = 2; } catch (_e) { b = 3; }\n"
            "repeat (2) { b += 1; }\n"
            "with (obj_thing) {\n"
            "    f = function(_k) {\n"
            "        switch (_k) { case 2: return 2; }\n"
            "        try { throw 1; } catch (_e) { _k = 0; }\n"
            "        repeat (2) { _k += 1; }\n"
            "        with (obj_thing) { y = 1; }\n"
            "        var g = function() { switch (a) { default: return 0; } };\n"
            "        return g();\n"
            "    };\n"
            "}\n"
        )

        declared = re.findall(r"\b(?:var|for)\s+(_gml_\w+)", code)
        for prefix in ("_gml_switch_value_", "_gml_try_control_", "_gml_repeat_index_", "_gml_with_target_"):
            self.assertGreaterEqual(sum(name.startswith(prefix) for name in declared), 2, code)
        self.assertEqual(len(declared), len(set(declared)), code)

    def test_increments_inside_methods_stay_in_the_method_body(self):
        # A method's ++ and -- run each time the method is called, not where
        # the method is declared.
        code = transpile_gml_code(
            "var f = function() {\n"
            "    var _n = 0;\n"
            "    for (var _i = 0; _i < 3; _i++) { _n++; }\n"
            "    return [_n--, ++_n];\n"
            "};\n"
            "var g = [function(a) { a--; return a; }, j++];\n"
        )

        self.assertEqual(
            code,
            "\tvar f = GMRuntime.gml_receiver_method(self, func(_gml_method_self = null, _gml_method_other = null):\n"
            "\t\tvar _n = 0\n"
            "\t\tvar _i = 0\n"
            "\t\twhile GMRuntime.gml_lt(_i, 3):\n"
            "\t\t\t_n = GMRuntime.gml_add(_n, 1)\n"
            "\t\t\t_i = GMRuntime.gml_add(_i, 1)\n"
            "\t\tvar _gm2gd_mutation_value_0 = _n\n"
            "\t\t_n = GMRuntime.gml_sub(_gm2gd_mutation_value_0, 1)\n"
            "\t\tvar _gm2gd_mutation_value_1 = GMRuntime.gml_add(_n, 1)\n"
            "\t\t_n = _gm2gd_mutation_value_1\n"
            "\t\treturn [_gm2gd_mutation_value_0, _gm2gd_mutation_value_1]\n"
            "\t)\n"
            "\tvar _gm2gd_mutation_value_2 = j\n"
            "\tj = GMRuntime.gml_add(_gm2gd_mutation_value_2, 1)\n"
            "\tvar g = [GMRuntime.gml_receiver_method(self, func(_gml_method_self = null, _gml_method_other = null, a = null):\n"
            "\t\tif a == null: a = GMRuntime.gml_undefined()\n"
            "\t\ta = GMRuntime.gml_sub(a, 1)\n"
            "\t\treturn a\n"
            "\t), _gm2gd_mutation_value_2]",
        )

    def test_struct_literals_may_repeat_a_variable_name(self):
        # Every value is evaluated in order and the last one wins; a GDScript
        # dictionary literal cannot repeat a key.
        self.assertEqual(
            transpile_gml_expression("{a: 1, b: f(), a: 3, c: 4, b: 5, a: 6}"),
            'GMRuntime.gml_struct_repeated_fields([{"a": 1, "b": GMRuntime.gml_call_named("f", [], self, other)}, '
            '{"a": 3, "c": 4, "b": 5}, {"a": 6}])',
        )
        self.assertEqual(
            transpile_gml_expression("{a: 1, b: 2}"),
            'GMRuntime.gml_struct({"a": 1, "b": 2})',
        )

    def test_method_rebinding_resolves_script_asset_callable_metadata(self):
        self.assertEqual(
            transpile_gml_expression(
                "method(target, scr_receiver)",
                asset_names={"scr_receiver"},
            ),
            "GMRuntime.gml_method(target, "
            "GMRuntime.gml_script_get_callable("
            'GMRuntime.gml_asset_get_index("scr_receiver")))',
        )
        self.assertEqual(
            transpile_gml_expression(
                "method(target, scr_receiver)",
                local_names={"scr_receiver"},
                asset_names={"scr_receiver"},
            ),
            "GMRuntime.gml_method(target, scr_receiver)",
        )

    def test_rejects_nameof_non_name_expressions(self):
        with self.assertRaisesRegex(GMLTranspileError, "identifier"):
            transpile_gml_expression("nameof([score])")
        with self.assertRaisesRegex(GMLTranspileError, "identifier, enum member"):
            transpile_gml_expression("nameof(score + 1)")
        with self.assertRaisesRegex(GMLTranspileError, "identifier, enum member"):
            transpile_gml_expression("nameof(factory()())")

    def test_transpiles_primitive_type_predicates(self):
        self.assertEqual(transpile_gml_expression("is_array(items)"), "GMRuntime.is_array(items)")
        self.assertEqual(transpile_gml_expression("is_struct(mystruct)"), "GMRuntime.is_struct(mystruct)")
        self.assertEqual(transpile_gml_expression("is_method(callback)"), "GMRuntime.is_method(callback)")
        self.assertEqual(transpile_gml_expression("is_callable(callback)"), "GMRuntime.is_callable(callback)")
        self.assertEqual(
            transpile_gml_expression("method(player, callback)"),
            "GMRuntime.gml_method(player, callback)",
        )
        self.assertEqual(
            transpile_gml_expression("method(undefined, callback)"),
            "GMRuntime.gml_method(self, callback)",
        )
        self.assertEqual(
            transpile_gml_expression("typeof(method(player, callback))"),
            "GMRuntime.gml_typeof(GMRuntime.gml_method(player, callback))",
        )
        self.assertEqual(
            transpile_gml_expression('typeof(handle_parse("ref script 1"))'),
            'GMRuntime.gml_typeof(GMRuntime.gml_handle_parse("ref script 1"))',
        )
        self.assertEqual(
            transpile_gml_expression("method_get_self(method(player, callback))"),
            "GMRuntime.gml_method_get_self(GMRuntime.gml_method(player, callback))",
        )
        self.assertEqual(
            transpile_gml_expression("method_get_index(method(player, callback))"),
            "GMRuntime.gml_method_get_index(GMRuntime.gml_method(player, callback))",
        )
        self.assertEqual(
            transpile_gml_expression("method_get_self(callback)"),
            "GMRuntime.gml_method_get_self(callback)",
        )
        self.assertEqual(
            transpile_gml_expression("method_get_index(callback)"),
            "GMRuntime.gml_method_get_index(callback)",
        )
        self.assertEqual(
            transpile_gml_expression("method(player, callback) == method(player, callback)"),
            "GMRuntime.gml_eq(GMRuntime.gml_method(player, callback), GMRuntime.gml_method(player, callback))",
        )
        self.assertEqual(
            transpile_gml_expression("method(player, callback) != method(enemy, callback)"),
            "GMRuntime.gml_ne(GMRuntime.gml_method(player, callback), GMRuntime.gml_method(enemy, callback))",
        )
        self.assertEqual(
            transpile_gml_expression("method_call(callback)"),
            "GMRuntime.gml_method_call(callback, null, 0, null, self, other)",
        )
        self.assertEqual(
            transpile_gml_expression("method_call(callback, [1, 2, 3], 1, 2)"),
            "GMRuntime.gml_method_call(callback, [1, 2, 3], 1, 2, self, other)",
        )
        self.assertEqual(
            transpile_gml_expression("method_call(callback, [1, 2, 3], -1, -2)"),
            "GMRuntime.gml_method_call(callback, [1, 2, 3], -1, -2, self, other)",
        )

    def test_transpiles_bitwise_operators(self):
        self.assertEqual(
            transpile_gml_expression("flags & mask | 4"),
            "GMRuntime.gml_bit_or(GMRuntime.gml_bit_and(flags, mask), 4)",
        )
        self.assertEqual(
            transpile_gml_expression("value ^ mask"),
            "GMRuntime.gml_bit_xor(value, mask)",
        )
        self.assertEqual(
            transpile_gml_expression("value << 2"),
            "GMRuntime.gml_shift_left(value, 2)",
        )
        self.assertEqual(
            transpile_gml_expression("value >> 1"),
            "GMRuntime.gml_shift_right(value, 1)",
        )
        self.assertEqual(
            transpile_gml_expression("~0b0011"),
            "GMRuntime.gml_bit_not(0b0011)",
        )

    def test_transpiles_enum_declarations_and_member_access(self):
        self.assertEqual(
            transpile_gml_code("enum RAINBOW { RED, ORANGE, GREEN }\ncolour = RAINBOW.GREEN", indent=""),
            'var RAINBOW = GMRuntime.gml_enum({"RED": 0, "ORANGE": 1, "GREEN": 2})\n'
            "colour = 2",
        )
        self.assertEqual(
            transpile_gml_code(
                "enum ENUM_TEST { VAL = 10 }\n"
                "enum RAINBOW { RED = 5, ORANGE = 5 * 2, VIOLET = 35 * ENUM_TEST.VAL }",
                indent="",
            ),
            'var ENUM_TEST = GMRuntime.gml_enum({"VAL": 10})\n'
            'var RAINBOW = GMRuntime.gml_enum({"RED": 5, "ORANGE": 10, "VIOLET": 350})',
        )
        self.assertEqual(
            transpile_gml_code(
                "#macro BASE 0x10\n"
                "enum FLAGS { A = BASE, B = int64(A << 1), C = bool(false) }",
                indent="",
            ),
            'var FLAGS = GMRuntime.gml_enum({"A": 16, "B": 32, "C": 0})',
        )

    def test_folds_enum_div_and_mod_with_gml_integer_semantics(self):
        # mod and div truncate toward zero (GML gives -5 mod 3 == -2, where
        # Python's floor modulo gives 1), and the folding is exact beyond
        # 2^53, where a float quotient is not. Results wrap around 2^64 like
        # an int64, and a shift count is taken modulo 64 like the runner's Long.
        source = (
            "enum FOLD {\n"
            "    NEG_MOD = -5 mod 3,\n"
            "    NEG_PERCENT = -5 % 3,\n"
            "    NEG_DIVISOR_MOD = 5 mod -3,\n"
            "    BOTH_NEG_MOD = -5 % -3,\n"
            "    EXACT_MOD = 6 mod 3,\n"
            "    NEG_DIV = -7 div 2,\n"
            "    NEG_DIVISOR_DIV = 7 div -2,\n"
            "    BOTH_NEG_DIV = -7 div -2,\n"
            "    SLASH = 7 / 2,\n"
            "    HUGE_DIV = 9007199254740993 div 1,\n"
            "    PRECISE_DIV = 9223372036854775807 div 3,\n"
            "    PRECISE_MOD = 18014398509481985 mod 10,\n"
            "    SMALLEST_DIV = 0x8000000000000000 div -1,\n"
            "    SHIFTED = 1 << 63,\n"
            "    SHIFT_WRAPS = 1 << 64,\n"
            "    SHIFT_RIGHT = -8 >> 1,\n"
            "    OVERFLOW = 0x7FFFFFFFFFFFFFFF + 1,\n"
            "    NEGATED = -0x8000000000000000,\n"
            "    AFTER_LARGEST = 0x7FFFFFFFFFFFFFFE,\n"
            "    NEXT,\n"
            "}\n"
        )
        expected_values = {
            "NEG_MOD": -2,
            "NEG_PERCENT": -2,
            "NEG_DIVISOR_MOD": 2,
            "BOTH_NEG_MOD": -2,
            "EXACT_MOD": 0,
            "NEG_DIV": -3,
            "NEG_DIVISOR_DIV": -3,
            "BOTH_NEG_DIV": 3,
            "SLASH": 3,
            "HUGE_DIV": 9007199254740993,
            "PRECISE_DIV": 3074457345618258602,
            "PRECISE_MOD": 5,
            "SMALLEST_DIV": -9223372036854775808,
            "SHIFTED": -9223372036854775808,
            "SHIFT_WRAPS": 1,
            "SHIFT_RIGHT": -4,
            "OVERFLOW": -9223372036854775808,
            "NEGATED": -9223372036854775808,
            "AFTER_LARGEST": 9223372036854775806,
            "NEXT": 9223372036854775807,
        }
        emitted = transpile_gml_code(source, indent="")
        fields = ", ".join(
            f'"{name}": ' + ("(-9223372036854775807 - 1)" if value == -9223372036854775808 else str(value))
            for name, value in expected_values.items()
        )
        self.assertEqual(emitted, f"var FOLD = GMRuntime.gml_enum({{{fields}}})")

    def test_rejects_enum_division_by_zero(self):
        for source in ("enum BAD { A = 5 div 0 }", "enum BAD { A = 5 mod 0 }", "enum BAD { A = 5 % 0 }"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, "integer compile-time constants"):
                    transpile_gml_code(source, indent="")

    def test_wraps_hex_enum_values_of_two_to_the_63_or_more_to_signed_int64(self):
        self.assertEqual(
            transpile_gml_code(
                "enum MASK { ALL = 0xFFFFFFFFFFFFFFFF, TOP = $8000000000000000, LOW = 0xFF }\n"
                "a = MASK.ALL;\n"
                "b = MASK.TOP;",
                indent="",
            ),
            'var MASK = GMRuntime.gml_enum({"ALL": -1, "TOP": (-9223372036854775807 - 1), "LOW": 255})\n'
            "a = -1\n"
            "b = (-9223372036854775807 - 1)",
        )
        self.assertEqual(
            transpile_gml_code(
                "result = MASK.TOP;",
                indent="",
                enum_values={"MASK": {"TOP": -9223372036854775808}},
            ),
            "result = (-9223372036854775807 - 1)",
        )

    def test_lowers_project_global_enum_members_to_integer_constants(self):
        enum_values = {
            "AddingOperator": {
                "equals": 0,
                "add": 7,
                "multiply": 11,
            }
        }

        self.assertEqual(
            transpile_gml_code(
                "result = AddingOperator.add;",
                indent="",
                enum_values=enum_values,
            ),
            "result = 7",
        )

    def test_transpiles_macro_declarations_and_configuration_overrides(self):
        self.assertEqual(
            transpile_gml_code(
                "#macro STEP 4\n"
                "#macro DOUBLE STEP * 2\n"
                "speed = DOUBLE + 1",
                indent="",
            ),
            "GMRuntime.gml_motion_set_speed(self, GMRuntime.gml_add(GMRuntime.gml_mul(4, 2), 1))",
        )
        self.assertEqual(
            transpile_gml_code(
                "#macro TOTAL 1 + \\\n"
                "2\n"
                "score = TOTAL",
                indent="",
            ),
            "score = GMRuntime.gml_add(1, 2)",
        )
        self.assertEqual(
            transpile_gml_code(
                '#macro AD_ID "default"\n'
                '#macro Android:AD_ID "android"\n'
                "value = AD_ID",
                indent="",
                macro_configuration="Android",
            ),
            'value = "android"',
        )
        self.assertEqual(
            transpile_gml_code(
                '#macro AD_ID "default"\n'
                '#macro Android:AD_ID "android"\n'
                "value = AD_ID",
                indent="",
            ),
            'value = "default"',
        )

    def test_preprocessor_strips_editor_only_directives(self):
        self.assertEqual(
            transpile_gml_code(
                "#region Movement\n"
                "speed = 4\n"
                "#endregion\n",
                indent="",
            ),
            "GMRuntime.gml_motion_set_speed(self, 4)",
        )

    def test_preprocessor_define_values_feed_macro_expansion(self):
        self.assertEqual(
            transpile_gml_code(
                "#define LIMIT 10\n"
                "score = LIMIT + 2",
                indent="",
            ),
            "score = GMRuntime.gml_add(10, 2)",
        )

    def test_preprocessor_conditionals_skip_disabled_code(self):
        self.assertEqual(
            transpile_gml_code(
                "#if Windows\n"
                "score = missing ?? ??\n"
                "#else\n"
                "score = 2\n"
                "#endif\n",
                indent="",
                macro_configuration="Android",
            ),
            "score = 2",
        )
        self.assertEqual(
            transpile_gml_code(
                "#define FEATURE_ENABLED\n"
                "#if defined(FEATURE_ENABLED)\n"
                "score = 1\n"
                "#elif Android\n"
                "score = 2\n"
                "#else\n"
                "score = 3\n"
                "#endif\n",
                indent="",
                macro_configuration="Android",
            ),
            "score = 1",
        )
        self.assertEqual(
            transpile_gml_code(
                "#define FEATURE_ENABLED\n"
                "#ifdef FEATURE_ENABLED\n"
                "score = 4\n"
                "#endif\n",
                indent="",
            ),
            "score = 4",
        )

    def test_preprocessor_evaluates_boolean_and_comparison_expressions(self):
        self.assertEqual(
            transpile_gml_code(
                "#define BUILD 2\n"
                "#if (BUILD >= 2 && defined(Android)) || false\n"
                "score = 7\n"
                "#else\n"
                "score = 0\n"
                "#endif\n",
                indent="",
                macro_configuration="Android",
            ),
            "score = 7",
        )
        self.assertEqual(
            transpile_gml_code(
                "#macro CHANNEL 'beta'\n"
                "#if CHANNEL == 'beta' && !defined(DISABLED)\n"
                "score = 3\n"
                "#else\n"
                "score = 0\n"
                "#endif\n",
                indent="",
            ),
            "score = 3",
        )
        self.assertEqual(
            transpile_gml_code(
                "#define BUILD 1\n"
                "#if BUILD > 1 || Windows\n"
                "score = 1\n"
                "#else\n"
                "score = 2\n"
                "#endif\n",
                indent="",
                macro_configuration="Android",
            ),
            "score = 2",
        )
        self.assertEqual(
            transpile_gml_code(
                "#define MASK $10\n"
                "#define OFFSET -1\n"
                "#if MASK == 0x10 && !OFFSET ^^ false\n"
                "score = 5\n"
                "#else\n"
                "score = 0\n"
                "#endif\n",
                indent="",
            ),
            "score = 5",
        )

    def test_preprocessor_reports_unsupported_directives_with_source_context(self):
        with self.assertRaisesRegex(
            GMLTranspileError,
            r"Unsupported preprocessor directive #import at line 1: #import \"native.gml\"",
        ):
            transpile_gml_code('#import "native.gml"\nscore = 1', indent="")
        with self.assertRaisesRegex(
            GMLTranspileError,
            r"Unsupported preprocessor directive #include at line 1: #include \"shared.gml\"",
        ):
            transpile_gml_code('#include "shared.gml"\nscore = 1', indent="")
        with self.assertRaisesRegex(
            GMLTranspileError,
            r"Unsupported preprocessor directive #gml_pragma at line 1: #gml_pragma global",
        ):
            transpile_gml_code("#gml_pragma global\nscore = 1", indent="")

        with self.assertRaisesRegex(
            GMLTranspileError,
            r"Unsupported preprocessor condition 'BUILD &&' at line 2: #if BUILD &&",
        ):
            transpile_gml_code("#define BUILD 1\n#if BUILD &&\nscore = 1\n#endif", indent="")
        with self.assertRaisesRegex(
            GMLTranspileError,
            r"Unsupported preprocessor condition 'BUILD == 2' at line 2: #if BUILD == 2",
        ):
            transpile_gml_code("#define BUILD 1 + 1\n#if BUILD == 2\nscore = 1\n#endif", indent="")

    def test_preprocessor_preserves_macro_lines_in_structured_result(self):
        result = preprocess_gml_source("#region R\n#macro VALUE 7\n#endregion\nscore = VALUE")

        self.assertEqual(result.diagnostics, ())
        self.assertIn("#macro VALUE 7", result.source)
        self.assertNotIn("#region", result.source)

    def test_macros_used_as_statements_run_their_statements(self):
        # A macro is text substitution (manual: Constants, Macros): its value
        # may be several statements, and it may be used on its own as a
        # statement.
        self.assertEqual(
            transpile_gml_code(
                "#macro SET_FONT var _data = load(_name);\\\n"
                "    _data.ready = true;\\\n"
                "    if (_data.missing) return false;\\\n"
                "    ++_count;\n"
                "function parse(_name) {\n"
                "    var _count = 0;\n"
                "    switch (_name) {\n"
                "        case \"a\": SET_FONT; break;\n"
                "        case \"b\": SET_FONT break;\n"
                "    }\n"
                "    return _data;\n"
                "}\n",
                indent="",
            ),
            transpile_gml_code(
                "function parse(_name) {\n"
                "    var _count = 0;\n"
                "    switch (_name) {\n"
                "        case \"a\": var _data = load(_name); _data.ready = true; "
                "if (_data.missing) return false; ++_count;; break;\n"
                "        case \"b\": var _data = load(_name); _data.ready = true; "
                "if (_data.missing) return false; ++_count; break;\n"
                "    }\n"
                "    return _data;\n"
                "}\n",
                indent="",
            ),
        )
        self.assertEqual(transpile_gml_code("#macro SET_X x = 5\nSET_X;", indent=""), "position.x = 5")
        self.assertEqual(
            transpile_gml_code("#macro LOG show_debug_message\nLOG(\"hi\");", indent=""),
            'GMRuntime.gml_show_debug_message("hi", [])',
        )

    def test_rejects_recursive_macros(self):
        with self.assertRaisesRegex(GMLTranspileError, "Recursive macro"):
            transpile_gml_code("#macro LOOP LOOP\nvalue = LOOP", indent="")

    def test_rejects_writes_to_builtin_and_macro_constants(self):
        for source in (
            "pi = 3",
            "NaN++",
            "delete pointer_null",
            "#macro LIMIT 10\nLIMIT = 11",
            "#macro LIMIT 10\nvar LIMIT = 11",
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, "constant"):
                    transpile_gml_code(source, indent="")

    def test_rejects_runtime_enum_value_expressions(self):
        with self.assertRaisesRegex(GMLTranspileError, "Enum values must be integer compile-time constants"):
            transpile_gml_code("enum BAD { VALUE = score + 1 }", indent="")

    def test_rejects_enum_member_mutation(self):
        mutation_sources = [
            "enum RAINBOW { GREEN }\nRAINBOW.GREEN = 2",
            "enum RAINBOW { GREEN }\nRAINBOW.GREEN += 1",
            'enum RAINBOW { GREEN }\nRAINBOW[$ "GREEN"] = 2',
            "enum RAINBOW { GREEN }\nRAINBOW.GREEN++",
            'enum RAINBOW { GREEN }\nstruct_set(RAINBOW, "GREEN", 2)',
            'enum RAINBOW { GREEN }\nvar text = $"{struct_set(RAINBOW, "GREEN", 2)}"',
            "enum RAINBOW { GREEN }\nvar mutate = function() { RAINBOW.GREEN = 2; }",
        ]

        for source in mutation_sources:
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, "enum"):
                    transpile_gml_code(source, indent="")

    def test_rejects_enum_reassignment(self):
        with self.assertRaisesRegex(GMLTranspileError, "Cannot assign to enum"):
            transpile_gml_code("enum RAINBOW { GREEN }\nRAINBOW = {}", indent="")

    def test_allows_enum_member_as_non_mutating_index(self):
        self.assertEqual(
            transpile_gml_code("enum RAINBOW { GREEN }\nitems[RAINBOW.GREEN] = 2", indent=""),
            'var RAINBOW = GMRuntime.gml_enum({"GREEN": 0})\n'
            "GMRuntime.gml_array_set(items, 0, 2)",
        )

    def test_transpiles_nullish_operator(self):
        self.assertEqual(
            transpile_gml_expression("value ?? fallback"),
            "value if not GMRuntime.gml_is_nullish(value) else fallback",
        )

    def test_transpiles_ternary_operator(self):
        self.assertEqual(
            transpile_gml_expression("alive ? speed : 0"),
            "speed if GMRuntime.gml_bool(alive) else 0",
        )

    def test_transpiles_calls_indexes_and_members(self):
        self.assertEqual(
            transpile_gml_expression("project_choose(items[index + 1], other.value)"),
            "GMRuntime.gml_call_named("
            '"project_choose", [GMRuntime.gml_array_get(items, GMRuntime.gml_add(index, 1)), '
            'GMRuntime.gml_selector_get(other, "value")], self, other)',
        )

    def test_parses_array_literals(self):
        self.assertEqual(transpile_gml_expression("[]"), "[]")
        self.assertEqual(
            transpile_gml_expression('[1, score + 1, "ready"]'),
            '[1, GMRuntime.gml_add(score, 1), "ready"]',
        )
        self.assertEqual(
            transpile_gml_expression("[[1, 2], [3, 4]]"),
            "[[1, 2], [3, 4]]",
        )

    def test_preserves_array_literal_metadata(self):
        literal = parse_gml_expression("[1, [2]]")

        self.assertIsInstance(literal, ArrayLiteral)
        assert isinstance(literal, ArrayLiteral)
        self.assertEqual(len(literal.elements), 2)

    def test_parses_struct_literals(self):
        self.assertEqual(transpile_gml_expression("{}"), "GMRuntime.gml_struct({})")
        self.assertEqual(
            transpile_gml_expression('{a: 10, b: "Hello World"}'),
            'GMRuntime.gml_struct({"a": 10, "b": "Hello World"})',
        )
        self.assertEqual(
            transpile_gml_expression("{d: _xx + 50, f: [10, 20], g: image_index}"),
            'GMRuntime.gml_struct({"d": GMRuntime.gml_add(_xx, 50), '
            '"f": [10, 20], "g": image_index})',
        )
        self.assertEqual(
            transpile_gml_expression("{child: {value: 1}, items: [[1], [2, 3]],}"),
            'GMRuntime.gml_struct({"child": GMRuntime.gml_struct({"value": 1}), '
            '"items": [[1], [2, 3]]})',
        )

    def test_parses_double_quoted_struct_field_names(self):
        self.assertEqual(
            transpile_gml_expression(
                r'{"display name": 1, "punctuation.!?": 2, '
                r'"Unicode 鍵": 3, "quote\" and slash\\": 4,}'
            ),
            'GMRuntime.gml_struct({"display name": 1, "punctuation.!?": 2, '
            '"Unicode \\u9375": 3, "quote\\\" and slash\\\\": 4})',
        )

        literal = parse_gml_expression(r'{"line\nname": 1, "Unicode 鍵": 2}')
        self.assertIsInstance(literal, StructLiteral)
        assert isinstance(literal, StructLiteral)
        self.assertEqual(
            [field_name for field_name, _field_value in literal.fields],
            ["line\nname", "Unicode 鍵"],
        )

    def test_parses_nested_and_function_values_for_quoted_struct_fields(self):
        self.assertEqual(
            transpile_gml_expression(
                '{"nested value": {"child-key": value}, '
                '"compute!": function(input) { return input + 1; }}'
            ),
            'GMRuntime.gml_struct({"nested value": '
            'GMRuntime.gml_struct({"child-key": value}), '
            '"compute!": GMRuntime.gml_receiver_method(GMRuntime.gml_undefined(), '
            "func(_gml_method_self = null, _gml_method_other = null, input = null):\n"
            '\tif input == null: input = GMRuntime.gml_undefined()\n'
            '\treturn GMRuntime.gml_add(input, 1)\n'
            ')})',
        )

    def test_quoted_struct_fields_require_nonempty_double_quoted_names_and_values(self):
        cases = (
            ('{"": value}', "cannot be empty"),
            ("{'Root': value}", "must use double quotes"),
            ('{"Root"}', "Expected ':'"),
            ('{"Root",}', "Expected ':'"),
        )
        for source, message in cases:
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, message):
                    transpile_gml_expression(source)

        self.assertEqual(
            transpile_gml_expression('{identifier_shorthand, "quoted": value,}'),
            'GMRuntime.gml_struct({"identifier_shorthand": '
            'identifier_shorthand, "quoted": value})',
        )

    def test_preserves_struct_literal_metadata(self):
        literal = parse_gml_expression("{a: 1, child: {b: 2}, shorthand}")

        self.assertIsInstance(literal, StructLiteral)
        assert isinstance(literal, StructLiteral)
        self.assertEqual([field_name for field_name, _ in literal.fields], ["a", "child", "shorthand"])

    def test_struct_literal_shorthand_uses_enclosing_scope(self):
        self.assertEqual(
            transpile_gml_expression("{x, y}", local_names={"x"}),
            'GMRuntime.gml_struct({"x": x, "y": position.y})',
        )

    def test_struct_literal_initializers_do_not_see_prior_fields(self):
        self.assertEqual(
            transpile_gml_expression("{a: 10, b: 10, c: a + b}"),
            'GMRuntime.gml_struct({"a": 10, "b": 10, "c": GMRuntime.gml_add(a, b)})',
        )

    def test_parses_function_literals_inside_structs(self):
        self.assertEqual(
            transpile_gml_expression("{apply: function(a, b) { return a + b; }}"),
            'GMRuntime.gml_struct({"apply": GMRuntime.gml_receiver_method('
            "GMRuntime.gml_undefined(), func(_gml_method_self = null, "
            "_gml_method_other = null, a = null, b = null):\n"
            "\tif a == null: a = GMRuntime.gml_undefined()\n"
            "\tif b == null: b = GMRuntime.gml_undefined()\n"
            "\treturn GMRuntime.gml_add(a, b)\n"
            ")})",
        )
        self.assertEqual(
            transpile_gml_expression('string({toString: function() { return "ok"; }})'),
            'GMRuntime.gml_string(GMRuntime.gml_struct({"toString": '
            "GMRuntime.gml_receiver_method(GMRuntime.gml_undefined(), "
            'func(_gml_method_self = null, _gml_method_other = null): return "ok")}))',
        )

    def test_function_literals_preserve_optional_defaults(self):
        self.assertEqual(
            transpile_gml_expression("function(a, b = 90) { return b; }"),
            "GMRuntime.gml_receiver_method(self, func(_gml_method_self = null, "
            "_gml_method_other = null, a = null, b = null):\n"
            "\tif a == null: a = GMRuntime.gml_undefined()\n"
            "\tif b == null or GMRuntime.is_undefined(b): b = 90\n"
            "\treturn b\n"
            ")",
        )
        self.assertEqual(
            transpile_gml_expression("function(a, b = a + 1) { return b; }"),
            "GMRuntime.gml_receiver_method(self, func(_gml_method_self = null, "
            "_gml_method_other = null, a = null, b = null):\n"
            "\tif a == null: a = GMRuntime.gml_undefined()\n"
            "\tif b == null or GMRuntime.is_undefined(b): b = GMRuntime.gml_add(a, 1)\n"
            "\treturn b\n"
            ")",
        )
        self.assertEqual(
            transpile_gml_expression("[function() { return 1; }]"),
            "[GMRuntime.gml_receiver_method(self, func(_gml_method_self = null, "
            "_gml_method_other = null): return 1)]",
        )

    def test_omitted_call_arguments_emit_gml_undefined(self):
        self.assertEqual(
            transpile_gml_expression("move(4,)"),
            'GMRuntime.gml_call_named("move", [4, GMRuntime.gml_undefined()], self, other)',
        )
        self.assertEqual(
            transpile_gml_expression("my_func(0,,,1)"),
            'GMRuntime.gml_call_named("my_func", [0, GMRuntime.gml_undefined(), '
            "GMRuntime.gml_undefined(), 1], self, other)",
        )

    def test_rejects_invalid_struct_field_names(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_expression("{6fish: value}")

    def test_transpiles_struct_member_access_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("mystruct.a"),
            'GMRuntime.gml_selector_get(mystruct, "a")',
        )
        self.assertEqual(
            transpile_gml_expression("{a: 1}.a"),
            'GMRuntime.gml_selector_get(GMRuntime.gml_struct({"a": 1}), "a")',
        )
        self.assertEqual(
            transpile_gml_expression('mystruct[$ "x"]'),
            'GMRuntime.gml_struct_get(mystruct, "x")',
        )
        self.assertEqual(
            transpile_gml_expression("mystruct[$ key_name]"),
            "GMRuntime.gml_struct_get(mystruct, key_name)",
        )
        self.assertEqual(
            transpile_gml_expression("other.value"),
            'GMRuntime.gml_selector_get(other, "value")',
        )

    def test_transpiles_struct_variable_functions_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression('struct_exists(mystruct, "x")'),
            'GMRuntime.gml_struct_exists(mystruct, "x")',
        )
        self.assertEqual(
            transpile_gml_expression('struct_get(mystruct, "x")'),
            'GMRuntime.gml_struct_get(mystruct, "x")',
        )
        self.assertEqual(
            transpile_gml_expression('struct_set(mystruct, "x", score + 1)'),
            'GMRuntime.gml_struct_set(mystruct, "x", GMRuntime.gml_add(score, 1))',
        )
        self.assertEqual(
            transpile_gml_expression('struct_remove(mystruct, "x")'),
            'GMRuntime.gml_struct_remove(mystruct, "x")',
        )
        self.assertEqual(
            transpile_gml_expression('variable_struct_get(mystruct, "x")'),
            'GMRuntime.gml_variable_struct_get(mystruct, "x")',
        )
        self.assertEqual(
            transpile_gml_expression('variable_struct_exists(mystruct, "x")'),
            'GMRuntime.gml_variable_struct_exists(mystruct, "x")',
        )
        self.assertEqual(
            transpile_gml_expression('variable_struct_set(mystruct, "x", score + 1)'),
            'GMRuntime.gml_variable_struct_set(mystruct, "x", GMRuntime.gml_add(score, 1))',
        )
        self.assertEqual(
            transpile_gml_expression('variable_struct_remove(mystruct, "x")'),
            'GMRuntime.gml_variable_struct_remove(mystruct, "x")',
        )
        self.assertEqual(
            transpile_gml_expression("variable_struct_get_names(mystruct)"),
            "GMRuntime.gml_variable_struct_get_names(mystruct)",
        )
        self.assertEqual(
            transpile_gml_expression("variable_struct_names_count(mystruct)"),
            "GMRuntime.gml_variable_struct_names_count(mystruct)",
        )
        self.assertEqual(
            transpile_gml_expression('variable_instance_get(enemy, "hp")'),
            'GMRuntime.gml_variable_instance_get(enemy, "hp")',
        )
        self.assertEqual(
            transpile_gml_expression('variable_instance_exists(enemy, "hp")'),
            'GMRuntime.gml_variable_instance_exists(enemy, "hp")',
        )
        self.assertEqual(
            transpile_gml_expression('variable_instance_set(enemy, "hp", score + 1)'),
            'GMRuntime.gml_variable_instance_set(enemy, "hp", GMRuntime.gml_add(score, 1))',
        )
        self.assertEqual(
            transpile_gml_expression('variable_instance_set(noone, "hp", 10)'),
            'GMRuntime.gml_variable_instance_set(GMRuntime.gml_instance_noone(), "hp", 10)',
        )

    def test_transpiles_legacy_numeric_instance_keywords(self):
        self.assertEqual(
            transpile_gml_expression('variable_instance_get(-1, "hp")'),
            'GMRuntime.gml_variable_instance_get(self, "hp")',
        )
        self.assertEqual(
            transpile_gml_expression('variable_instance_get(-2, "hp")'),
            'GMRuntime.gml_variable_instance_get(other, "hp")',
        )
        self.assertEqual(
            transpile_gml_expression("variable_instance_get_names(-3)"),
            "GMRuntime.gml_variable_instance_get_names(GMRuntime.gml_instance_all())",
        )
        self.assertEqual(
            transpile_gml_expression('variable_instance_get(-4, "hp")'),
            'GMRuntime.gml_variable_instance_get(GMRuntime.gml_instance_noone(), "hp")',
        )
        self.assertEqual(transpile_gml_expression("all"), "GMRuntime.gml_instance_all()")

    def test_transpiles_with_targets_instance_keywords(self):
        self.assertEqual(
            transpile_gml_expression("with_targets(self)"),
            "GMRuntime.gml_with_targets(self)",
        )
        self.assertEqual(
            transpile_gml_expression("with_targets(other)"),
            "GMRuntime.gml_with_targets(other)",
        )
        self.assertEqual(
            transpile_gml_expression("with_targets(all)"),
            "GMRuntime.gml_with_targets(GMRuntime.gml_instance_all())",
        )
        self.assertEqual(
            transpile_gml_expression("with_targets(noone)"),
            "GMRuntime.gml_with_targets(GMRuntime.gml_instance_noone())",
        )
        self.assertEqual(
            transpile_gml_expression("with_targets(-1)"),
            "GMRuntime.gml_with_targets(self)",
        )
        self.assertEqual(
            transpile_gml_expression("with_targets(-2)"),
            "GMRuntime.gml_with_targets(other)",
        )
        self.assertEqual(
            transpile_gml_expression("with_targets(-3)"),
            "GMRuntime.gml_with_targets(GMRuntime.gml_instance_all())",
        )
        self.assertEqual(
            transpile_gml_expression("with_targets(-4)"),
            "GMRuntime.gml_with_targets(GMRuntime.gml_instance_noone())",
        )

    def test_transpiles_global_keyword_to_shared_runtime_scope(self):
        self.assertEqual(transpile_gml_expression("global"), "GMRuntime.gml_global_scope()")
        self.assertEqual(
            transpile_gml_expression("global.score"),
            'GMRuntime.gml_selector_get(GMRuntime.gml_global_scope(), "score")',
        )
        self.assertEqual(
            transpile_gml_code("global.score = 10", indent=""),
            'GMRuntime.gml_selector_set(GMRuntime.gml_global_scope(), "score", 10)',
        )
        self.assertEqual(
            transpile_gml_expression('variable_instance_get(global, "score")'),
            'GMRuntime.gml_variable_instance_get(GMRuntime.gml_global_scope(), "score")',
        )
        self.assertEqual(
            transpile_gml_expression("variable_instance_get_names(global)"),
            "GMRuntime.gml_variable_instance_get_names(GMRuntime.gml_global_scope())",
        )
        self.assertEqual(
            transpile_gml_expression("variable_instance_names_count(global)"),
            "GMRuntime.gml_variable_instance_names_count(GMRuntime.gml_global_scope())",
        )
        self.assertEqual(
            transpile_gml_expression("variable_instance_get_names(enemy)"),
            "GMRuntime.gml_variable_instance_get_names(enemy)",
        )
        self.assertEqual(
            transpile_gml_expression("variable_instance_names_count(enemy)"),
            "GMRuntime.gml_variable_instance_names_count(enemy)",
        )
        self.assertEqual(
            transpile_gml_expression("variable_instance_get_names(noone)"),
            "GMRuntime.gml_variable_instance_get_names(GMRuntime.gml_instance_noone())",
        )
        self.assertEqual(
            transpile_gml_expression('variable_global_exists("score")'),
            'GMRuntime.gml_variable_global_exists("score")',
        )
        self.assertEqual(
            transpile_gml_expression('variable_global_get("score")'),
            'GMRuntime.gml_variable_global_get("score")',
        )
        self.assertEqual(
            transpile_gml_expression('variable_global_set("score", score + 1)'),
            'GMRuntime.gml_variable_global_set("score", GMRuntime.gml_add(score, 1))',
        )

    def test_transpiles_script_global_scope_and_globalvar(self):
        self.assertEqual(
            transpile_gml_code(
                "score = 10; total = score + 1; var local_score = score;",
                indent="",
                top_level_global_scope=True,
            ),
            'GMRuntime.gml_struct_set(GMRuntime.gml_global_scope(), "score", 10)\n'
            'GMRuntime.gml_struct_set(GMRuntime.gml_global_scope(), "total", '
            'GMRuntime.gml_add(GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "score"), 1))\n'
            'var local_score = GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "score")',
        )
        self.assertEqual(
            transpile_gml_code("globalvar score, health; score += health;", indent=""),
            'GMRuntime.gml_struct_set(GMRuntime.gml_global_scope(), "score", '
            'GMRuntime.gml_add(GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "score"), '
            'GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "health")))',
        )
        self.assertEqual(
            transpile_gml_code("score++; lives = score;", indent="", legacy_global_builtins=True),
            'GMRuntime.gml_struct_set(GMRuntime.gml_global_scope(), "score", '
            'GMRuntime.gml_add(GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "score"), 1))\n'
            'GMRuntime.gml_struct_set(GMRuntime.gml_global_scope(), "lives", '
            'GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "score"))',
        )

    def test_transpiles_ds_map_missing_value_apis_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression('ds_map_find_value(inventory, "food")'),
            'GMRuntime.gml_ds_map_find_value(inventory, "food")',
        )
        self.assertEqual(
            transpile_gml_expression('ds_map_exists(inventory, "food")'),
            'GMRuntime.gml_ds_map_exists(inventory, "food")',
        )
        self.assertEqual(
            transpile_gml_expression('inventory[? "food"]'),
            'GMRuntime.gml_ds_map_find_value(inventory, "food")',
        )
        self.assertEqual(
            transpile_gml_code('inventory[? "food"] = amount;', indent=""),
            'GMRuntime.gml_ds_map_set(inventory, "food", amount)',
        )

    def test_transpiles_ds_grid_mutation_targets_once(self):
        self.assertEqual(
            transpile_gml_code("grid[# next_x(), next_y()] += value;", indent=""),
            'var _gml_grid_x_0 = GMRuntime.gml_call_named("next_x", [], self, other)\n'
            'var _gml_grid_y_1 = GMRuntime.gml_call_named("next_y", [], self, other)\n'
            "GMRuntime.gml_ds_grid_set(grid, _gml_grid_x_0, _gml_grid_y_1, "
            "GMRuntime.gml_add(GMRuntime.gml_ds_grid_get(grid, _gml_grid_x_0, _gml_grid_y_1), value))",
        )
        self.assertEqual(
            transpile_gml_code("grid[# next_x(), next_y()]++;", indent=""),
            'var _gml_grid_x_0 = GMRuntime.gml_call_named("next_x", [], self, other)\n'
            'var _gml_grid_y_1 = GMRuntime.gml_call_named("next_y", [], self, other)\n'
            "GMRuntime.gml_ds_grid_set(grid, _gml_grid_x_0, _gml_grid_y_1, "
            "GMRuntime.gml_add(GMRuntime.gml_ds_grid_get(grid, _gml_grid_x_0, _gml_grid_y_1), 1))",
        )

    def test_nested_mixed_accessor_mutation_caches_grid_cell_container(self):
        self.assertEqual(
            transpile_gml_code("result = grid[# next_x(), next_y()][? next_key()] += value;", indent=""),
            'var _gml_map_target_0 = GMRuntime.gml_ds_grid_get(grid, '
            'GMRuntime.gml_call_named("next_x", [], self, other), '
            'GMRuntime.gml_call_named("next_y", [], self, other))\n'
            'var _gml_map_key_1 = GMRuntime.gml_call_named("next_key", [], self, other)\n'
            "var _gml_assignment_value_2 = GMRuntime.gml_add("
            "GMRuntime.gml_ds_map_find_value(_gml_map_target_0, _gml_map_key_1), value)\n"
            "GMRuntime.gml_ds_map_set(_gml_map_target_0, _gml_map_key_1, _gml_assignment_value_2)\n"
            "result = _gml_assignment_value_2",
        )

    def test_any_values_pass_through_calls_without_lossy_conversion(self):
        self.assertEqual(
            transpile_gml_expression(
                'callback([1, "x"], {value: undefined})',
                local_names={"callback"},
            ),
            'GMRuntime.gml_call_value(callback, [[1, "x"], '
            'GMRuntime.gml_struct({"value": GMRuntime.gml_undefined()})], self, other, "callback")',
        )
        self.assertEqual(
            transpile_gml_expression(
                'callback(ds_map_find_value(inventory, "food"), variable_struct_get(mystruct, "item"))'
            ),
            'GMRuntime.gml_call_named("callback", [GMRuntime.gml_ds_map_find_value(inventory, "food"), '
            'GMRuntime.gml_variable_struct_get(mystruct, "item")], self, other)',
        )

    def test_transpiles_struct_name_enumeration_functions_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("struct_get_names(mystruct)"),
            "GMRuntime.gml_struct_get_names(mystruct)",
        )
        self.assertEqual(
            transpile_gml_expression("struct_names_count(mystruct)"),
            "GMRuntime.gml_struct_names_count(mystruct)",
        )
        self.assertEqual(
            transpile_gml_expression("struct_foreach(mystruct, callback)"),
            "GMRuntime.gml_struct_foreach(mystruct, callback, self, other)",
        )
        self.assertEqual(
            transpile_gml_expression("struct_foreach(mystruct, method(self, callback))"),
            "GMRuntime.gml_struct_foreach("
            "mystruct, GMRuntime.gml_method(self, callback), self, other)",
        )

    def test_transpiles_static_struct_helpers_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("static_get(counter)"),
            "GMRuntime.gml_static_get(counter)",
        )
        self.assertEqual(
            transpile_gml_expression("static_get(method(player, callback))"),
            "GMRuntime.gml_static_get(GMRuntime.gml_method(player, callback))",
        )
        self.assertEqual(
            transpile_gml_expression("static_set(mystruct, static_get(counter))"),
            "GMRuntime.gml_static_set(mystruct, GMRuntime.gml_static_get(counter))",
        )

    def test_transpiles_constructor_identity_helpers_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("is_instanceof(mystruct, counter)"),
            "GMRuntime.gml_is_instanceof(mystruct, counter)",
        )
        self.assertEqual(
            transpile_gml_expression("is_instanceof(mystruct, method(player, callback))"),
            "GMRuntime.gml_is_instanceof(mystruct, GMRuntime.gml_method(player, callback))",
        )
        self.assertEqual(
            transpile_gml_expression("instanceof(mystruct)"),
            "GMRuntime.gml_instanceof(mystruct)",
        )

    def test_transpiles_new_constructor_invocations(self):
        self.assertEqual(
            transpile_gml_expression("new Point(4, 5)"),
            "GMRuntime.gml_new(Point, [4, 5], self, other)",
        )
        self.assertEqual(
            transpile_gml_expression("new factory.Point(name, )"),
            'GMRuntime.gml_new(GMRuntime.gml_selector_get(factory, "Point"), '
            "[name, GMRuntime.gml_undefined()], self, other)",
        )

    def test_transpiles_constructor_qualified_function_literals(self):
        self.assertEqual(
            transpile_gml_expression(
                "function Point(_x, _y) constructor { x = _x; y = _y; }",
            ),
            "GMRuntime.gml_receiver_constructor(self, "
            "func Point(_gml_constructor_self = null, "
            "_gml_constructor_other = null, _x = null, _y = null):\n"
            "\tif _x == null: _x = GMRuntime.gml_undefined()\n"
            "\tif _y == null: _y = GMRuntime.gml_undefined()\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_constructor_self, "x", _x)\n'
            '\tGMRuntime.gml_variable_instance_set(_gml_constructor_self, "y", _y)\n'
            ")",
        )

    def test_transpiles_function_static_variables(self):
        output = transpile_gml_expression(
            "function counter() { show_debug_message(n); static n = 0; n += 1; return n; }"
        )

        self.assertIn(
            "GMRuntime.gml_static_bind(func counter("
            "_gml_method_self = null, _gml_method_other = null):",
            output,
        )
        self.assertIn('GMRuntime.gml_static_scope("gml_static:counter:', output)
        self.assertIn("GMRuntime.gml_static_initialize(_gml_static_scope_", output)
        self.assertIn('[["n", func(): return 0]]', output)
        self.assertIn(
            "GMRuntime.gml_show_debug_message("
            "GMRuntime.gml_struct_get(_gml_static_scope_",
            output,
        )
        self.assertIn("GMRuntime.gml_struct_set(_gml_static_scope_", output)
        self.assertLess(
            output.index("GMRuntime.gml_static_initialize"),
            output.index("GMRuntime.gml_show_debug_message"),
        )

    def test_transpiles_static_variables_in_extracted_function_body(self):
        output = transpile_gml_code(
            "static total = 10;\n"
            "static callback = function(value = {amount: 1})\n"
            "{\n"
            "    return value.amount;\n"
            "};\n"
            "total += delta;\n"
            "return callback;",
            indent="",
            local_names={"delta"},
            return_depth=1,
            static_scope_prefix="scr_static.scr_static",
        )

        self.assertIn(
            'GMRuntime.gml_static_scope("scr_static.scr_static:<anonymous>:0:',
            output,
        )
        self.assertIn('[["total", func(): return 10], ["callback", func(): return', output)
        self.assertIn(
            "func(_gml_method_self = null, _gml_method_other = null, "
            "value = null):",
            output,
        )
        self.assertIn(
            'value = GMRuntime.gml_struct({"amount": 1})',
            output,
        )
        self.assertIn(
            "GMRuntime.gml_struct_set(_gml_static_scope_",
            output,
        )
        self.assertIn(
            'return GMRuntime.gml_struct_get(_gml_static_scope_',
            output,
        )
        self.assertLess(
            output.index("GMRuntime.gml_static_initialize"),
            output.index("GMRuntime.gml_struct_set"),
        )

    def test_rejects_static_declarations_outside_functions(self):
        with self.assertRaisesRegex(GMLTranspileError, "static declarations"):
            transpile_gml_code("static n = 0;", indent="")

    def test_transpiles_constructor_static_method_variables(self):
        output = transpile_gml_expression(
            "function Point() constructor { static make = function() { return 1; }; return make; }"
        )

        self.assertIn(
            "GMRuntime.gml_receiver_constructor("
            "self, GMRuntime.gml_static_bind(func Point",
            output,
        )
        self.assertIn('"Point"', output)
        self.assertIn(
            '["make", func(): return GMRuntime.gml_receiver_method('
            "GMRuntime.gml_undefined(), func(_gml_method_self = null, "
            "_gml_method_other = null): return 1)]",
            output,
        )
        self.assertIn("return GMRuntime.gml_struct_get(_gml_static_scope_", output)

    def test_transpiles_semicolonless_constructor_static_methods_on_separate_lines(self):
        output = transpile_gml_expression(
            "function Adding() constructor {\n"
            "static operate = function(a, b) { return a + b; }\n"
            "static invert = function(value) { return operate(-value, 0); }\n"
            "}"
        )

        self.assertIn(
            '["operate", func(): return GMRuntime.gml_receiver_method('
            "GMRuntime.gml_undefined(),",
            output,
        )
        self.assertIn(
            '["invert", func(): return GMRuntime.gml_receiver_method('
            "GMRuntime.gml_undefined(),",
            output,
        )
        self.assertIn(
            'GMRuntime.gml_struct_get(_gml_static_scope_',
            output,
        )
        self.assertNotIn('gml_call_named("operate"', output)
        self.assertNotIn("Unexpected token", output)

    def test_member_calls_pass_the_target_as_the_receiver_of_unbound_methods(self):
        self.assertEqual(
            transpile_gml_expression("point.describe(1, 2)"),
            'GMRuntime.gml_call_member(point, "describe", [1, 2], self, other)',
        )
        self.assertEqual(
            transpile_gml_expression("make().go()"),
            "GMRuntime.gml_call_member("
            'GMRuntime.gml_call_named("make", [], self, other), "go", [], self, other)',
        )
        # self.name() calls a method of the running instance itself.
        self.assertEqual(
            transpile_gml_expression("self.go()"),
            "GMRuntime.gml_call_value(self.go, [], self, other)",
        )

    def test_constructor_static_functions_are_unbound(self):
        output = transpile_gml_expression(
            "function Point() constructor { static make = function() { return 1; }; "
            "static pair = (function() { return 2; }); static count = 0; }"
        )

        self.assertIn(
            '["make", func(): return GMRuntime.gml_receiver_method(GMRuntime.gml_undefined(), func(',
            output,
        )
        self.assertIn(
            '["pair", func(): return GMRuntime.gml_receiver_method(GMRuntime.gml_undefined(), func(',
            output,
        )
        self.assertIn('["count", func(): return 0]', output)

    def test_nested_callback_in_constructor_static_switch_keeps_lambda_indentation(self):
        output = transpile_gml_expression(
            "function Adding() constructor {\n"
            "static operate = function(values, kind) {\n"
            "switch (kind) {\n"
            "case 1: {\n"
            "array_foreach(values, function(value, index) { values[index] = value; });\n"
            "break;\n"
            "}\n"
            "}\n"
            "}\n"
            "}"
        )
        lines = output.splitlines()
        callback_line = next(
            line
            for line in lines
            if "array_foreach" in line and "func(_gml_method_self" in line
        )
        callback_body_line = lines[lines.index(callback_line) + 1]

        callback_indent = len(callback_line) - len(callback_line.lstrip("\t"))
        callback_body_indent = len(callback_body_line) - len(
            callback_body_line.lstrip("\t")
        )
        self.assertEqual(callback_body_indent, callback_indent + 1)

    def test_transpiles_constructor_inheritance_before_child_statics(self):
        output = transpile_gml_expression(
            "function Child(x) : Parent(x) constructor { static c = 1; return c; }"
        )

        self.assertIn(
            "GMRuntime.gml_constructor_inherit("
            "_gml_constructor_self, Parent, [x], "
            "_gml_constructor_self, _gml_constructor_other)",
            output,
        )
        self.assertLess(
            output.index("GMRuntime.gml_constructor_inherit"),
            output.index("GMRuntime.gml_static_initialize"),
        )

    def test_transpiles_hashed_struct_helpers_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression('variable_get_hash("x")'),
            'GMRuntime.gml_variable_get_hash("x")',
        )
        self.assertEqual(
            transpile_gml_expression('struct_get_from_hash(point, variable_get_hash("x"))'),
            'GMRuntime.gml_struct_get_from_hash(point, GMRuntime.gml_variable_get_hash("x"))',
        )
        self.assertEqual(
            transpile_gml_expression('struct_set_from_hash(point, variable_get_hash("x"), 10)'),
            'GMRuntime.gml_struct_set_from_hash(point, GMRuntime.gml_variable_get_hash("x"), 10)',
        )
        self.assertEqual(
            transpile_gml_expression('struct_exists_from_hash(point, variable_get_hash("x"))'),
            'GMRuntime.gml_struct_exists_from_hash(point, GMRuntime.gml_variable_get_hash("x"))',
        )
        self.assertEqual(
            transpile_gml_expression('struct_remove_from_hash(point, variable_get_hash("x"))'),
            'GMRuntime.gml_struct_remove_from_hash(point, GMRuntime.gml_variable_get_hash("x"))',
        )

    def test_transpiles_variable_clone_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("variable_clone(mystruct)"),
            "GMRuntime.gml_variable_clone(mystruct)",
        )
        self.assertEqual(
            transpile_gml_expression("variable_clone(items, 0)"),
            "GMRuntime.gml_variable_clone(items, 0)",
        )

    def test_transpiles_array_indexing_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("items[0]"),
            "GMRuntime.gml_array_get(items, 0)",
        )
        self.assertEqual(
            transpile_gml_expression("items[-1]"),
            "GMRuntime.gml_array_get(items, -1)",
        )

    def test_transpiles_builtin_array_variables_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("view_xview"),
            'GMRuntime.gml_builtin_array("view_xview")',
        )
        self.assertEqual(
            transpile_gml_expression("view_xview[0]"),
            'GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_xview"), 0)',
        )
        self.assertEqual(
            transpile_gml_code("view_xview[0] = x;", indent=""),
            'GMRuntime.gml_array_set(GMRuntime.gml_builtin_array("view_xview"), 0, position.x)',
        )
        self.assertEqual(
            transpile_gml_code("var view_xview = [1]; value = view_xview[0];", indent=""),
            "var view_xview = [1]\nvalue = GMRuntime.gml_array_get(view_xview, 0)",
        )

    def test_transpiles_alarm_array_through_instance_runtime(self):
        self.assertEqual(
            transpile_gml_expression("alarm[0]"),
            "GMRuntime.gml_alarm_get(self, 0)",
        )
        self.assertEqual(
            transpile_gml_code("alarm[0] = 30;", indent=""),
            "GMRuntime.gml_alarm_set(self, 0, 30)",
        )
        self.assertEqual(
            transpile_gml_code("alarm[next_alarm()] += 1;", indent=""),
            'var _gml_alarm_index_0 = GMRuntime.gml_call_named("next_alarm", [], self, other)\n'
            "GMRuntime.gml_alarm_set(self, _gml_alarm_index_0, "
            "GMRuntime.gml_add(GMRuntime.gml_alarm_get(self, _gml_alarm_index_0), 1))",
        )
        self.assertEqual(
            transpile_gml_code("var alarm = [1]; value = alarm[0]; alarm[0] = 2;", indent=""),
            "var alarm = [1]\n"
            "value = GMRuntime.gml_array_get(alarm, 0)\n"
            "GMRuntime.gml_array_set(alarm, 0, 2)",
        )

    def test_transpiles_builtin_room_and_global_variables_through_runtime(self):
        cases = (
            ("room", 'GMRuntime.gml_builtin_global("room")'),
            ("room_width", 'GMRuntime.gml_builtin_global("room_width")'),
            ("room_height", 'GMRuntime.gml_builtin_global("room_height")'),
            ("instance_count", 'GMRuntime.gml_builtin_global("instance_count")'),
            ("async_load", 'GMRuntime.gml_builtin_global("async_load")'),
            ("event_data", 'GMRuntime.gml_builtin_global("event_data")'),
            ("argument", 'GMRuntime.gml_builtin_global("argument")'),
            ("argument_count", 'GMRuntime.gml_builtin_global("argument_count")'),
            ("view_xport[1]", 'GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_xport"), 1)'),
            ("view_enabled", 'GMRuntime.gml_builtin_global("view_enabled")'),
            ("view_current", 'GMRuntime.gml_builtin_global("view_current")'),
        )

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_expression(source), expected)
        self.assertEqual(transpile_gml_code("var room = 1; value = room", indent=""), "var room = 1\nvalue = room")

    def test_rejects_writes_to_read_only_builtin_variables(self):
        for source in (
            "bbox_left = 0",
            "sprite_width = 16",
            "sprite_yoffset += 1",
            "image_number += 1",
            "room++",
            "view_current[0] = 1",
            "view_current = 1",
            "delete object_index",
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, "read-only built-in"):
                    transpile_gml_code(source, indent="")

    def test_allows_mutable_builtin_writes_and_local_readonly_name_shadowing(self):
        self.assertEqual(transpile_gml_code("x = 10", indent=""), "position.x = 10")
        self.assertEqual(transpile_gml_code("image_index += 1", indent=""), "image_index = GMRuntime.gml_add(image_index, 1)")
        self.assertEqual(
            transpile_gml_code("view_xview[0] = x", indent=""),
            'GMRuntime.gml_array_set(GMRuntime.gml_builtin_array("view_xview"), 0, position.x)',
        )
        self.assertEqual(transpile_gml_code("var bbox_left = 1; bbox_left += 1", indent=""), "var bbox_left = 1\nbbox_left = GMRuntime.gml_add(bbox_left, 1)")
        self.assertEqual(
            transpile_gml_code("view_enabled = true", indent=""),
            'GMRuntime.gml_struct_set(GMRuntime.gml_global_scope(), "view_enabled", true)',
        )

    def test_instance_target_preserves_direct_names_and_dynamic_fallback(self):
        output = transpile_gml_code(
            "score = missing + 1; draw = score; score = draw;",
            indent="",
            instance_target="self",
            direct_instance_names={"score"},
            dynamic_instance_names={"draw"},
        )

        self.assertEqual(
            output,
            "score = GMRuntime.gml_add(GMRuntime.gml_variable_instance_get(self, \"missing\"), 1)\n"
            "GMRuntime.gml_variable_instance_set(self, \"draw\", score)\n"
            "score = GMRuntime.gml_variable_instance_get(self, \"draw\")",
        )

    def test_with_bodies_use_the_with_instance_for_the_scripts_own_members(self):
        # The calling object's script declares hp, yet inside with GameMaker
        # reads and writes the with instance's hp; locals stay locals.
        output = transpile_gml_code(
            "var bonus = 2; hp = 1; with (all) { hp += bonus; other.seen = hp; with (other) hp = 7; } hp += 1;",
            indent="",
            instance_target="self",
            direct_instance_names={"hp"},
        )

        self.assertEqual(
            output,
            "var bonus = 2\n"
            "hp = 1\n"
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_instance_all(), self, other):\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "hp", '
            'GMRuntime.gml_add(GMRuntime.gml_variable_instance_get(_gml_with_target_0, "hp"), bonus))\n'
            '\tGMRuntime.gml_selector_set(self, "seen", GMRuntime.gml_variable_instance_get(_gml_with_target_0, "hp"))\n'
            "\tfor _gml_with_target_1 in GMRuntime.gml_with_targets(self, _gml_with_target_0, self):\n"
            '\t\tGMRuntime.gml_variable_instance_set(_gml_with_target_1, "hp", 7)\n'
            "hp = GMRuntime.gml_add(hp, 1)",
        )

    def test_functions_use_their_receiver_for_the_scripts_own_members(self):
        # A method reads its receiver's variables and a constructor sets the
        # new struct's, even where the declaring object's script declares a
        # member of the same name.
        output = transpile_gml_code(
            "get_hp = function() { return hp; }; Point = function(px) constructor { hp = px; };",
            indent="",
            instance_target="self",
            direct_instance_names={"hp", "get_hp", "Point"},
        )

        self.assertIn('return GMRuntime.gml_variable_instance_get(_gml_method_self, "hp")', output)
        self.assertIn('\tGMRuntime.gml_variable_instance_set(_gml_constructor_self, "hp", px)', output)
        self.assertTrue(output.startswith("get_hp = GMRuntime.gml_receiver_method(self, "), output)
        self.assertNotIn("\thp = px", output)

    def test_transpiles_multidimensional_array_access(self):
        self.assertEqual(
            transpile_gml_expression("grid[x][y]"),
            "GMRuntime.gml_array_get(GMRuntime.gml_array_get(grid, position.x), position.y)",
        )
        self.assertEqual(
            transpile_gml_expression("[[1], [2, 3]][1][0]"),
            "GMRuntime.gml_array_get(GMRuntime.gml_array_get([[1], [2, 3]], 1), 0)",
        )


class TestGMLStatementTranspiler(unittest.TestCase):
    def test_tokenizes_begin_end_as_block_delimiters(self):
        tokens = tokenize_gml_source("if ready begin score = 1; end")
        values = [token.value for token in tokens]
        kinds = [token.kind for token in tokens]

        self.assertIn("{", values)
        self.assertIn("}", values)
        self.assertNotIn("begin", values)
        self.assertNotIn("end", values)
        self.assertEqual(kinds[values.index("{")], "OP")
        self.assertEqual(kinds[values.index("}")], "OP")

    def test_lowers_begin_end_if_bodies(self):
        self.assertEqual(
            transpile_gml_code(
                "if ready begin score = 1; end else begin score = 0; end",
                indent="",
            ),
            "if GMRuntime.gml_bool(ready):\n\tscore = 1\nelse:\n\tscore = 0",
        )

    def test_lowers_standalone_begin_end_blocks(self):
        self.assertEqual(
            transpile_gml_code("begin score = 1; score += 2; end", indent=""),
            "score = 1\nscore = GMRuntime.gml_add(score, 2)",
        )

    def test_transpiles_function_return_statements(self):
        self.assertEqual(
            transpile_gml_expression("function() { return; }"),
            "GMRuntime.gml_receiver_method(self, func("
            "_gml_method_self = null, _gml_method_other = null): return)",
        )
        self.assertEqual(
            transpile_gml_expression("function() { return score + bonus; }"),
            "GMRuntime.gml_receiver_method(self, func("
            "_gml_method_self = null, _gml_method_other = null): return "
            'GMRuntime.gml_add(GMRuntime.gml_variable_instance_get(_gml_method_self, "score"), '
            'GMRuntime.gml_variable_instance_get(_gml_method_self, "bonus")))',
        )

    def test_transpiles_named_function_declaration_as_a_method_variable(self):
        output = transpile_gml_code(
            "function ev_helper3(_q) { return _q * 2; }\nscore = ev_helper3(3);",
            indent="",
        )

        self.assertTrue(
            output.startswith(
                "ev_helper3 = GMRuntime.gml_receiver_method(self, func ev_helper3("
                "_gml_method_self = null, _gml_method_other = null, _q = null):"
            ),
            output,
        )
        self.assertIn('GMRuntime.gml_call_named("ev_helper3", [3], self, other)', output)

    def test_named_function_declarations_are_available_before_their_statement(self):
        output = transpile_gml_code(
            "score = early(4);\nfunction early(_q) { return _q + 1; }\n",
            indent="",
        )

        self.assertLess(output.index("early = GMRuntime.gml_receiver_method("), output.index('"early", [4]'))

    def test_function_expressions_are_not_declarations(self):
        output = transpile_gml_code(
            "var _f = function named() { return 1; };\nhandler = function other_named() { return 2; };",
            indent="",
        )

        self.assertIn("var _f = GMRuntime.gml_receiver_method(self, func named(", output)
        self.assertNotIn("\nnamed = ", "\n" + output)
        self.assertNotIn("\nother_named = ", "\n" + output)

    def test_named_function_inside_a_function_belongs_to_that_function_receiver(self):
        output = transpile_gml_code(
            "function outer() {\n"
            "    var _first = inner(1);\n"
            "    function inner(_q) { return _q + 1; }\n"
            "    return _first;\n"
            "}\n",
            indent="",
        )

        declaration = output.index('GMRuntime.gml_variable_instance_set(_gml_method_self, "inner", ')
        call = output.index('GMRuntime.gml_call_named("inner", [1], _gml_method_self, _gml_method_other)')
        self.assertLess(declaration, call)

    def test_named_function_declared_in_a_block_stays_in_the_block(self):
        output = transpile_gml_code(
            "if (ready) {\n    function guarded() { return 1; }\n}\nscore = 2;",
            indent="",
        )

        self.assertLess(output.index("if GMRuntime.gml_bool("), output.index("guarded = GMRuntime.gml_receiver_method("))

    def test_rejects_return_outside_functions_and_methods(self):
        for source in ("return;", "return score + bonus;", "if ready begin return score; end"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, "return used outside"):
                    transpile_gml_code(source, indent="")

    def test_transpiles_exit_statements(self):
        self.assertEqual(transpile_gml_code("exit;", indent=""), "return")
        self.assertEqual(
            transpile_gml_code("if done begin exit; end score += 1;", indent=""),
            "if GMRuntime.gml_bool(done):\n\treturn\nscore = GMRuntime.gml_add(score, 1)",
        )

    def test_transpiles_function_exit_as_early_return(self):
        self.assertEqual(
            transpile_gml_expression("function() { if done begin exit; end return score; }"),
            "GMRuntime.gml_receiver_method(self, func("
            "_gml_method_self = null, _gml_method_other = null):\n"
            '\tif GMRuntime.gml_bool(GMRuntime.gml_variable_instance_get(_gml_method_self, "done")):\n'
            "\t\treturn\n"
            '\treturn GMRuntime.gml_variable_instance_get(_gml_method_self, "score")\n'
            ")",
        )

    def test_exit_aborts_later_generated_event_code(self):
        self.assertEqual(
            transpile_gml_code("score = 1; exit; score = 2;", indent=""),
            "score = 1\nreturn\nscore = 2",
        )

    def test_event_inherited_calls_parent_event_and_continues_child_body(self):
        self.assertEqual(
            transpile_gml_code(
                "child_before = true; event_inherited(); child_after = true;",
                indent="",
                inherited_event_call="super._ready()",
            ),
            "child_before = true\nsuper._ready()\nchild_after = true",
        )

    def test_event_inherited_without_parent_event_is_noop(self):
        self.assertEqual(
            transpile_gml_code(
                "if ready begin event_inherited(); end child_after = true;",
                indent="",
            ),
            "if GMRuntime.gml_bool(ready):\n\tpass\nchild_after = true",
        )

    def test_transpiles_throw_statements(self):
        cases = (
            ('throw "bad";', 'GMRuntime.gml_throw("bad")\nreturn'),
            ("throw 404;", "GMRuntime.gml_throw(404)\nreturn"),
            (
                "throw {message: reason, code: 404};",
                'GMRuntime.gml_throw(GMRuntime.gml_struct({"message": reason, "code": 404}))\nreturn',
            ),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_code(source, indent=""), expected)

        self.assertEqual(
            transpile_gml_code('throw "bad";', indent="", return_depth=1),
            'return GMRuntime.gml_throw("bad")',
        )

        with self.assertRaisesRegex(GMLTranspileError, "throw requires an expression"):
            transpile_gml_code("throw;", indent="")

    def test_transpiles_try_catch_blocks(self):
        output = transpile_gml_code(
            'try { throw "bad"; } catch (err) { message = err.message; }',
            indent="",
        )

        self.assertIn("var _gml_try_control_0 = GMRuntime.gml_undefined()", output)
        self.assertIn('_gml_try_control_0 = {"kind": "throw", "value": GMRuntime.gml_throw("bad")}', output)
        self.assertIn('if not GMRuntime.is_undefined(_gml_try_control_0) and _gml_try_control_0["kind"] == "throw":', output)
        self.assertIn('var err = GMRuntime.gml_exception_struct(_gml_try_control_0["value"])', output)
        self.assertIn('message = GMRuntime.gml_selector_get(err, "message")', output)
        self.assertNotIn('return _gml_try_control_0["value"]', output)
        self.assertIn(
            'if not GMRuntime.is_undefined(_gml_try_control_0) and _gml_try_control_0["kind"] == "throw":\n\treturn',
            output,
        )

    def test_methods_with_several_lines_stay_inside_the_catch_body(self):
        # A method is a GDScript lambda: every line of it has to move in with
        # the catch body, or GDScript finds no indented block under it.
        output = transpile_gml_code(
            "try { throw 1; } catch (_e) {\n"
            "    var _u = function() { var _a = 1; return _a; };\n"
            "    x = _u();\n"
            "}\n",
            indent="",
        )

        self.assertIn(
            "\twhile true:\n"
            "\t\t_u = GMRuntime.gml_receiver_method(self, func(_gml_method_self = null, _gml_method_other = null):\n"
            "\t\t\tvar _a = 1\n"
            "\t\t\treturn _a\n"
            "\t\t)\n"
            '\t\tposition.x = GMRuntime.gml_call_value(_u, [], self, other, "_u")\n'
            "\t\tbreak\n",
            output,
        )

    def test_transpiles_discard_catch_identifier_to_valid_gdscript(self):
        output = transpile_gml_code(
            "try { value = real(text); } catch (_) {}",
            indent="",
        )

        self.assertIn(
            'var __ = GMRuntime.gml_exception_struct(_gml_try_control_0["value"])',
            output,
        )
        self.assertNotIn("var _ =", output)

    def test_a_method_in_a_do_until_condition_or_case_label_keeps_its_body_indented(self):
        # The test lines of these statements are built by the statement
        # parser; a multi-line method inside them is indented with the line.
        until_output = transpile_gml_code(
            "do { n++; continue; } until (is_method(function() { var _a = 1; return _a; }));",
            indent="",
        )
        until_check = (
            "\tif GMRuntime.is_method(GMRuntime.gml_receiver_method(self, func(_gml_method_self = null, _gml_method_other = null):\n"
            "\t\tvar _a = 1\n"
            "\t\treturn _a\n"
            "\t)):\n"
            "\t\tbreak"
        )
        # The check ends the loop body and also runs before the continue.
        self.assertEqual(
            until_output,
            "while true:\n"
            "\tn = GMRuntime.gml_add(n, 1)\n"
            f"{until_check}\n"
            "\tcontinue\n"
            f"{until_check}",
        )

        switch_output = transpile_gml_code(
            "switch (a) { case (function() { var _c = 1; return _c; })(): b = 1; break; }",
            indent="",
        )
        self.assertIn(
            "\tif not _gml_switch_matched_1 and GMRuntime.gml_eq(_gml_switch_value_0, "
            "GMRuntime.gml_call_value((GMRuntime.gml_receiver_method(self, "
            "func(_gml_method_self = null, _gml_method_other = null):\n"
            "\t\tvar _c = 1\n"
            "\t\treturn _c\n"
            "\t)), [], self, other)):\n"
            "\t\t_gml_switch_matched_1 = true\n",
            switch_output,
        )

    def test_transpiles_try_finally_blocks(self):
        output = transpile_gml_code("try { score = 1; } finally { cleaned = true; }", indent="")

        self.assertIn("var _gml_try_control_0 = GMRuntime.gml_undefined()", output)
        self.assertIn("while true:\n\tscore = 1\n\tbreak", output)
        self.assertIn("cleaned = true", output)
        self.assertIn('if not GMRuntime.is_undefined(_gml_try_control_0) and _gml_try_control_0["kind"] == "return":', output)
        self.assertNotIn('return _gml_try_control_0["value"]', output)
        self.assertIn(
            'if not GMRuntime.is_undefined(_gml_try_control_0) and _gml_try_control_0["kind"] == "return":\n\treturn',
            output,
        )
        self.assertIn('if not GMRuntime.is_undefined(_gml_try_control_0) and _gml_try_control_0["kind"] == "throw":', output)

    def test_try_dispatch_preserves_return_values_in_value_returning_functions(self):
        output = transpile_gml_code(
            "try { return 42; } finally { cleaned = true; }",
            indent="",
            return_depth=1,
        )

        self.assertIn('_gml_try_control_0 = {"kind": "return", "value": 42}', output)
        self.assertIn('return _gml_try_control_0["value"]', output)

    def test_transpiles_nested_try_catch_propagation(self):
        output = transpile_gml_code(
            'try { try { throw "bad"; } catch (inner) { throw inner; } } '
            "catch (outer) { message = outer.message; }",
            indent="",
        )

        self.assertIn("var _gml_try_control_0 = GMRuntime.gml_undefined()", output)
        self.assertIn("\tvar _gml_try_control_1 = GMRuntime.gml_undefined()", output)
        self.assertIn('\t\t_gml_try_control_1 = {"kind": "throw", "value": GMRuntime.gml_throw("bad")}', output)
        self.assertIn('var inner = GMRuntime.gml_exception_struct(_gml_try_control_1["value"])', output)
        self.assertIn('_gml_try_control_1 = {"kind": "throw", "value": GMRuntime.gml_throw(inner)}', output)
        self.assertIn('_gml_try_control_0 = {"kind": "throw", "value": _gml_try_control_1["value"]}', output)
        self.assertIn('var outer = GMRuntime.gml_exception_struct(_gml_try_control_0["value"])', output)
        self.assertIn('message = GMRuntime.gml_selector_get(outer, "message")', output)

    def test_finally_preserves_abrupt_control_flow_from_try_body(self):
        return_output = transpile_gml_code(
            "function f() { try { return 1; } finally { cleaned = true; } }",
            indent="",
        )
        self.assertIn('_gml_try_control_0 = {"kind": "return", "value": 1}', return_output)
        self.assertIn(
            'GMRuntime.gml_variable_instance_set(_gml_method_self, "cleaned", true)',
            return_output,
        )
        self.assertIn('return _gml_try_control_0["value"]', return_output)

        break_output = transpile_gml_code(
            "while ready { try { break; } finally { cleaned = true; } after = true; }",
            indent="",
        )
        self.assertIn('_gml_try_control_0 = {"kind": "break", "value": GMRuntime.gml_undefined()}', break_output)
        self.assertIn("cleaned = true", break_output)
        self.assertIn('if not GMRuntime.is_undefined(_gml_try_control_0) and _gml_try_control_0["kind"] == "break":\n\t\tbreak', break_output)

        continue_output = transpile_gml_code(
            "while ready { try { continue; } finally { cleaned = true; } after = true; }",
            indent="",
        )
        self.assertIn('_gml_try_control_0 = {"kind": "continue", "value": GMRuntime.gml_undefined()}', continue_output)
        self.assertIn("cleaned = true", continue_output)
        self.assertIn('if not GMRuntime.is_undefined(_gml_try_control_0) and _gml_try_control_0["kind"] == "continue":\n\t\tcontinue', continue_output)

    def test_rejects_control_flow_inside_finally_blocks(self):
        cases = (
            "try { score = 1; } finally { return; }",
            "try { score = 1; } finally { exit; }",
            "while ready { try { score = 1; } finally { break; } }",
            "while ready { try { score = 1; } finally { continue; } }",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, "not allowed inside finally"):
                    transpile_gml_code(source, indent="")

        with self.assertRaisesRegex(GMLTranspileError, "try requires catch or finally"):
            transpile_gml_code("try { score = 1; }", indent="")

        with self.assertRaisesRegex(GMLTranspileError, "catch requires a variable name"):
            transpile_gml_code("try { score = 1; } catch { score = 2; }", indent="")

    def test_transpiles_delete_variable_operator(self):
        self.assertEqual(
            transpile_gml_code("delete mystruct;", indent=""),
            "mystruct = GMRuntime.gml_undefined()",
        )

    def test_transpiles_delete_member_and_accessor_targets(self):
        self.assertEqual(
            transpile_gml_code("delete mystruct.child;", indent=""),
            'GMRuntime.gml_struct_remove(mystruct, "child")',
        )
        self.assertEqual(
            transpile_gml_code('delete mystruct[$ "child"];', indent=""),
            'GMRuntime.gml_struct_remove(mystruct, "child")',
        )
        self.assertEqual(
            transpile_gml_code("delete items[2];", indent=""),
            "GMRuntime.gml_array_delete(items, 2, 1)",
        )
        self.assertEqual(
            transpile_gml_code('delete inventory[? "food"];', indent=""),
            'GMRuntime.gml_ds_map_delete(inventory, "food")',
        )
        self.assertEqual(
            transpile_gml_code("delete queue[| 0];", indent=""),
            "GMRuntime.gml_ds_list_delete(queue, 0)",
        )

    def test_transpiles_with_blocks(self):
        self.assertEqual(
            transpile_gml_code("with (all) begin score += 1; end", indent=""),
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_instance_all(), self, other):\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "score", '
            'GMRuntime.gml_add(GMRuntime.gml_variable_instance_get(_gml_with_target_0, "score"), 1))',
        )
        self.assertEqual(
            transpile_gml_code("with (enemy) score += 1;", indent=""),
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(enemy, self, other):\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "score", '
            'GMRuntime.gml_add(GMRuntime.gml_variable_instance_get(_gml_with_target_0, "score"), 1))',
        )

    def test_with_noone_lowers_to_zero_target_runtime_loop(self):
        self.assertEqual(
            transpile_gml_code("with (noone) score = 1;", indent=""),
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_instance_noone(), self, other):\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "score", 1)',
        )

    def test_with_lowers_single_targets_through_runtime(self):
        cases = (
            (
                "with (self) score = 1;",
                "for _gml_with_target_0 in GMRuntime.gml_with_targets(self, self, other):\n"
                '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "score", 1)',
            ),
            (
                "with (other) score = 1;",
                "for _gml_with_target_0 in GMRuntime.gml_with_targets(other, self, other):\n"
                '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "score", 1)',
            ),
            (
                "with (global) score = 1;",
                "for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_global_scope(), self, other):\n"
                '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "score", 1)',
            ),
            (
                "with ({hp: 10}) score = 1;",
                'for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_struct({"hp": 10}), self, other):\n'
                '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "score", 1)',
            ),
        )

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_code(source, indent=""), expected)

    def test_with_allows_break_and_continue_as_loop_control(self):
        self.assertEqual(
            transpile_gml_code(
                "with (all) begin if skip begin continue; end if done begin break; end score += 1; end",
                indent="",
            ),
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_instance_all(), self, other):\n"
            '\tif GMRuntime.gml_bool(GMRuntime.gml_variable_instance_get(_gml_with_target_0, "skip")):\n'
            "\t\tcontinue\n"
            '\tif GMRuntime.gml_bool(GMRuntime.gml_variable_instance_get(_gml_with_target_0, "done")):\n'
            "\t\tbreak\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "score", '
            'GMRuntime.gml_add(GMRuntime.gml_variable_instance_get(_gml_with_target_0, "score"), 1))',
        )

    def test_with_remaps_self_other_and_unqualified_instance_members(self):
        self.assertEqual(
            transpile_gml_code(
                "with (enemy) begin hp = hp + damage; other.total += hp; self.flag = true; end",
                indent="",
            ),
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(enemy, self, other):\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "hp", '
            'GMRuntime.gml_add(GMRuntime.gml_variable_instance_get(_gml_with_target_0, "hp"), '
            'GMRuntime.gml_variable_instance_get(_gml_with_target_0, "damage")))\n'
            '\tGMRuntime.gml_selector_update(self, "total", '
            'func(_gml_selector_value_1): return GMRuntime.gml_add(_gml_selector_value_1, '
            'GMRuntime.gml_variable_instance_get(_gml_with_target_0, "hp")))\n'
            '\tGMRuntime.gml_selector_set(_gml_with_target_0, "flag", true)',
        )

    def test_with_preserves_enclosing_local_mutation(self):
        self.assertEqual(
            transpile_gml_code(
                "var total = 0; with (enemy) begin total += hp; var seen = total; hp = seen; end",
                indent="",
            ),
            "var seen = GMRuntime.gml_undefined()\n"
            "var total = 0\n"
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(enemy, self, other):\n"
            '\ttotal = GMRuntime.gml_add(total, GMRuntime.gml_variable_instance_get(_gml_with_target_0, "hp"))\n'
            "\tseen = total\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "hp", seen)',
        )

    def test_nested_with_preserves_self_other_and_outer_locals_for_selectors(self):
        self.assertEqual(
            transpile_gml_code(
                "var total = 0; "
                "with (o_parent) begin "
                "with (o_enemy) begin "
                "total += other.hp + self.hp; "
                "other.hp = total; "
                "self.hp = other.hp; "
                "end end",
                indent="",
                asset_names={"o_parent", "o_enemy"},
            ),
            "var total = 0\n"
            'for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_asset_get_index("o_parent"), self, other):\n'
            '\tfor _gml_with_target_1 in GMRuntime.gml_with_targets(GMRuntime.gml_asset_get_index("o_enemy"), _gml_with_target_0, self):\n'
            '\t\ttotal = GMRuntime.gml_add(total, GMRuntime.gml_add(GMRuntime.gml_selector_get(_gml_with_target_0, "hp"), '
            'GMRuntime.gml_selector_get(_gml_with_target_1, "hp")))\n'
            '\t\tGMRuntime.gml_selector_set(_gml_with_target_0, "hp", total)\n'
            '\t\tGMRuntime.gml_selector_set(_gml_with_target_1, "hp", GMRuntime.gml_selector_get(_gml_with_target_0, "hp"))',
        )

    def test_delete_clears_only_named_struct_reference(self):
        self.assertEqual(
            transpile_gml_code("mystruct = make_struct(); alias = mystruct; delete mystruct;", indent=""),
            'mystruct = GMRuntime.gml_call_named("make_struct", [], self, other)\n'
            "alias = mystruct\n"
            "mystruct = GMRuntime.gml_undefined()",
        )

    def test_delete_rejects_non_variable_expressions(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_code("delete make_struct();", indent="")

        with self.assertRaises(GMLTranspileError):
            transpile_gml_code("delete grid[# 0, 0];", indent="")

    def test_transpiles_while_blocks(self):
        self.assertEqual(
            transpile_gml_code("while score > 0 begin score -= 1; end", indent=""),
            "while GMRuntime.gml_gt(score, 0):\n\tscore = GMRuntime.gml_sub(score, 1)",
        )
        self.assertEqual(
            transpile_gml_code("while (count) count--;", indent=""),
            "while GMRuntime.gml_bool(count):\n\tcount = GMRuntime.gml_sub(count, 1)",
        )

    def test_control_flow_accepts_newline_before_braced_body(self):
        source = (
            "if (first)\n{\ncall_a();\n}\n"
            "else if (second)\n{\ncall_b();\n}\n"
            "else\n{\ncall_c();\n}\n"
            "while (running)\n{\ntick();\n}\n"
            "repeat (2)\n{\ntick();\n}\n"
            "for (var i = 0; i < 1; i++)\n{\ntick();\n}\n"
            "do\n{\ntick();\n}\nuntil (done);"
        )

        self.assertEqual(
            transpile_gml_code(source, indent=""),
            "if GMRuntime.gml_bool(first):\n"
            '\tGMRuntime.gml_call_named("call_a", [], self, other)\n'
            "elif GMRuntime.gml_bool(second):\n"
            '\tGMRuntime.gml_call_named("call_b", [], self, other)\n'
            "else:\n"
            '\tGMRuntime.gml_call_named("call_c", [], self, other)\n'
            "while GMRuntime.gml_bool(running):\n"
            '\tGMRuntime.gml_call_named("tick", [], self, other)\n'
            "for _gml_repeat_index_0 in range(GMRuntime.gml_repeat_count(2)):\n"
            '\tGMRuntime.gml_call_named("tick", [], self, other)\n'
            "var i = 0\n"
            "while GMRuntime.gml_lt(i, 1):\n"
            '\tGMRuntime.gml_call_named("tick", [], self, other)\n'
            "\ti = GMRuntime.gml_add(i, 1)\n"
            "while true:\n"
            '\tGMRuntime.gml_call_named("tick", [], self, other)\n'
            "\tif GMRuntime.gml_bool(done):\n"
            "\t\tbreak",
        )

    def test_while_condition_stays_in_loop_header(self):
        self.assertEqual(
            transpile_gml_code(
                "while next_value() begin count += 1; threshold -= count; end",
                indent="",
            ),
            'while GMRuntime.gml_bool(GMRuntime.gml_call_named("next_value", [], self, other)):\n'
            "\tcount = GMRuntime.gml_add(count, 1)\n"
            "\tthreshold = GMRuntime.gml_sub(threshold, count)",
        )

    def test_transpiles_break_and_continue_inside_while(self):
        self.assertEqual(
            transpile_gml_code(
                "while running begin if should_skip begin continue; end if done begin break; end count += 1; end",
                indent="",
            ),
            "while GMRuntime.gml_bool(running):\n"
            "\tif GMRuntime.gml_bool(should_skip):\n"
            "\t\tcontinue\n"
            "\tif GMRuntime.gml_bool(done):\n"
            "\t\tbreak\n"
            "\tcount = GMRuntime.gml_add(count, 1)",
        )

    def test_rejects_break_outside_loop(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_code("break;", indent="")

    def test_rejects_continue_outside_loop(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_code("continue;", indent="")

    def test_transpiles_repeat_blocks(self):
        self.assertEqual(
            transpile_gml_code("repeat (3) begin score += 1; end", indent=""),
            "for _gml_repeat_index_0 in range(GMRuntime.gml_repeat_count(3)):\n"
            "\tscore = GMRuntime.gml_add(score, 1)",
        )
        self.assertEqual(
            transpile_gml_code("repeat (count + 1) score += 1;", indent=""),
            "for _gml_repeat_index_0 in range(GMRuntime.gml_repeat_count(GMRuntime.gml_add(count, 1))):\n"
            "\tscore = GMRuntime.gml_add(score, 1)",
        )

    def test_repeat_count_expression_uses_runtime_rounding_once(self):
        self.assertEqual(
            transpile_gml_code("repeat (next_count()) score += 1;", indent=""),
            'for _gml_repeat_index_0 in range(GMRuntime.gml_repeat_count('
            'GMRuntime.gml_call_named("next_count", [], self, other))):\n'
            "\tscore = GMRuntime.gml_add(score, 1)",
        )

    def test_multiple_repeat_loops_use_distinct_godot_iterators(self):
        self.assertEqual(
            transpile_gml_code(
                "repeat (2) first(); repeat (3) second();",
                indent="",
            ),
            "for _gml_repeat_index_0 in range(GMRuntime.gml_repeat_count(2)):\n"
            '\tGMRuntime.gml_call_named("first", [], self, other)\n'
            "for _gml_repeat_index_1 in range(GMRuntime.gml_repeat_count(3)):\n"
            '\tGMRuntime.gml_call_named("second", [], self, other)',
        )

    def test_transpiles_break_and_continue_inside_repeat(self):
        self.assertEqual(
            transpile_gml_code(
                "repeat (count) begin if should_skip begin continue; end if done begin break; end score += 1; end",
                indent="",
            ),
            "for _gml_repeat_index_0 in range(GMRuntime.gml_repeat_count(count)):\n"
            "\tif GMRuntime.gml_bool(should_skip):\n"
            "\t\tcontinue\n"
            "\tif GMRuntime.gml_bool(done):\n"
            "\t\tbreak\n"
            "\tscore = GMRuntime.gml_add(score, 1)",
        )

    def test_transpiles_do_until_blocks(self):
        self.assertEqual(
            transpile_gml_code("do begin score += 1; end until score >= 3;", indent=""),
            "while true:\n"
            "\tscore = GMRuntime.gml_add(score, 1)\n"
            "\tif GMRuntime.gml_gte(score, 3):\n"
            "\t\tbreak",
        )
        self.assertEqual(
            transpile_gml_code("do score += 1 until score >= 3;", indent=""),
            "while true:\n"
            "\tscore = GMRuntime.gml_add(score, 1)\n"
            "\tif GMRuntime.gml_gte(score, 3):\n"
            "\t\tbreak",
        )

    def test_do_until_checks_condition_after_body(self):
        self.assertEqual(
            transpile_gml_code("do begin ran = true; end until false;", indent=""),
            "while true:\n"
            "\tran = true\n"
            "\tif false:\n"
            "\t\tbreak",
        )

    def test_do_until_continue_checks_condition_first(self):
        self.assertEqual(
            transpile_gml_code(
                "do begin if should_skip begin continue; end score += 1; end until score >= 3;",
                indent="",
            ),
            "while true:\n"
            "\tif GMRuntime.gml_bool(should_skip):\n"
            "\t\tif GMRuntime.gml_gte(score, 3):\n"
            "\t\t\tbreak\n"
            "\t\tcontinue\n"
            "\tscore = GMRuntime.gml_add(score, 1)\n"
            "\tif GMRuntime.gml_gte(score, 3):\n"
            "\t\tbreak",
        )

    def test_transpiles_for_loop_clauses(self):
        self.assertEqual(
            transpile_gml_code("for (i = 0; i < 3; i++) begin score += i; end", indent=""),
            "i = 0\n"
            "while GMRuntime.gml_lt(i, 3):\n"
            "\tscore = GMRuntime.gml_add(score, i)\n"
            "\ti = GMRuntime.gml_add(i, 1)",
        )
        self.assertEqual(
            transpile_gml_code("for (; keep_running; ) tick();", indent=""),
            "while GMRuntime.gml_bool(keep_running):\n"
            '\tGMRuntime.gml_call_named("tick", [], self, other)',
        )
        self.assertEqual(
            transpile_gml_code("for (;;) score += 1;", indent=""),
            "while true:\n"
            "\tscore = GMRuntime.gml_add(score, 1)",
        )

    def test_transpiles_switch_case_and_default_labels(self):
        self.assertEqual(
            transpile_gml_code(
                "switch (state) { case 1: score = 10; break; default: score = 0; }",
                indent="",
            ),
            "var _gml_switch_value_0 = state\n"
            "var _gml_switch_matched_1 = false\n"
            "var _gml_switch_has_case_2 = GMRuntime.gml_eq(_gml_switch_value_0, 1)\n"
            "while true:\n"
            "\tif not _gml_switch_matched_1 and GMRuntime.gml_eq(_gml_switch_value_0, 1):\n"
            "\t\t_gml_switch_matched_1 = true\n"
            "\tif _gml_switch_matched_1:\n"
            "\t\tscore = 10\n"
            "\t\tbreak\n"
            "\tif not _gml_switch_matched_1 and not _gml_switch_has_case_2:\n"
            "\t\t_gml_switch_matched_1 = true\n"
            "\tif _gml_switch_matched_1:\n"
            "\t\tscore = 0\n"
            "\tbreak",
        )

    def test_switch_matches_cases_against_single_evaluated_expression(self):
        self.assertEqual(
            transpile_gml_code(
                "switch (next_state()) { case 1: score = 1; break; case 2: score = 2; break; }",
                indent="",
            ),
            'var _gml_switch_value_0 = GMRuntime.gml_call_named("next_state", [], self, other)\n'
            "var _gml_switch_matched_1 = false\n"
            "var _gml_switch_has_case_2 = GMRuntime.gml_eq(_gml_switch_value_0, 1) or GMRuntime.gml_eq(_gml_switch_value_0, 2)\n"
            "while true:\n"
            "\tif not _gml_switch_matched_1 and GMRuntime.gml_eq(_gml_switch_value_0, 1):\n"
            "\t\t_gml_switch_matched_1 = true\n"
            "\tif _gml_switch_matched_1:\n"
            "\t\tscore = 1\n"
            "\t\tbreak\n"
            "\tif not _gml_switch_matched_1 and GMRuntime.gml_eq(_gml_switch_value_0, 2):\n"
            "\t\t_gml_switch_matched_1 = true\n"
            "\tif _gml_switch_matched_1:\n"
            "\t\tscore = 2\n"
            "\t\tbreak\n"
            "\tbreak",
        )

    def test_switch_preserves_case_fallthrough(self):
        self.assertEqual(
            transpile_gml_code(
                'switch (keyboard_key) { case vk_left: case ord("A"): x -= 4; break; }',
                indent="",
            ),
            'var _gml_switch_value_0 = GMRuntime.gml_builtin_global("keyboard_key")\n'
            "var _gml_switch_matched_1 = false\n"
            'var _gml_switch_has_case_2 = GMRuntime.gml_eq(_gml_switch_value_0, 37) or GMRuntime.gml_eq(_gml_switch_value_0, GMRuntime.gml_ord("A"))\n'
            "while true:\n"
            "\tif not _gml_switch_matched_1 and GMRuntime.gml_eq(_gml_switch_value_0, 37):\n"
            "\t\t_gml_switch_matched_1 = true\n"
            "\tif _gml_switch_matched_1:\n"
            "\t\tpass\n"
            '\tif not _gml_switch_matched_1 and GMRuntime.gml_eq(_gml_switch_value_0, GMRuntime.gml_ord("A")):\n'
            "\t\t_gml_switch_matched_1 = true\n"
            "\tif _gml_switch_matched_1:\n"
            "\t\tposition.x = GMRuntime.gml_sub(position.x, 4)\n"
            "\t\tbreak\n"
            "\tbreak",
        )

    def test_switch_break_exits_switch_not_outer_loop(self):
        output = transpile_gml_code(
            "while running begin switch (state) { case 1: score = 1; break; } ticks += 1; end",
            indent="",
        )

        self.assertIn("while GMRuntime.gml_bool(running):", output)
        self.assertIn("\t\tscore = 1\n\t\t\tbreak", output)
        self.assertIn("\tticks = GMRuntime.gml_add(ticks, 1)", output)

    def test_switch_continue_targets_outer_loop(self):
        output = transpile_gml_code(
            "while running begin switch (state) { case 1: if skip begin continue; end score = 1; break; } ticks += 1; end",
            indent="",
        )

        self.assertIn("var _gml_switch_control_3 = GMRuntime.gml_undefined()", output)
        self.assertIn('_gml_switch_control_3 = {"kind": "continue", "value": GMRuntime.gml_undefined()}', output)
        self.assertIn('if not GMRuntime.is_undefined(_gml_switch_control_3) and _gml_switch_control_3["kind"] == "continue":\n\t\tcontinue', output)
        self.assertIn("\tticks = GMRuntime.gml_add(ticks, 1)", output)

    def test_for_loop_preserves_execution_order(self):
        self.assertEqual(
            transpile_gml_code(
                "for (setup(); should_run(); advance()) begin body(); end",
                indent="",
            ),
            'GMRuntime.gml_call_named("setup", [], self, other)\n'
            'while GMRuntime.gml_bool(GMRuntime.gml_call_named("should_run", [], self, other)):\n'
            '\tGMRuntime.gml_call_named("body", [], self, other)\n'
            '\tGMRuntime.gml_call_named("advance", [], self, other)',
        )

    def test_for_loop_supports_var_declarations_in_header(self):
        self.assertEqual(
            transpile_gml_code("for (var i = 0, total = 0; i < 3; i++) total += i;", indent=""),
            "var i = 0\n"
            "var total = 0\n"
            "while GMRuntime.gml_lt(i, 3):\n"
            "\ttotal = GMRuntime.gml_add(total, i)\n"
            "\ti = GMRuntime.gml_add(i, 1)",
        )

    def test_for_loop_header_may_end_with_a_semicolon(self):
        # The manual's form is for (<assignment>; <expression>; <operation>;).
        for source in (
            "for (var i = 0; i < 3; i++;) total += i;",
            "for (var i = 0; i < 3; i++;\n) total += i;",
        ):
            self.assertEqual(
                transpile_gml_code(source, indent=""),
                transpile_gml_code("for (var i = 0; i < 3; i++) total += i;", indent=""),
            )
        with self.assertRaisesRegex(GMLTranspileError, "Expected for initializer"):
            transpile_gml_code("for (var i = 0; i < 3; i++; i++) total += i;", indent="")

    def test_for_continue_runs_operation_clause(self):
        self.assertEqual(
            transpile_gml_code(
                "for (i = 0; i < 3; i++) begin if skip begin continue; end score += i; end",
                indent="",
            ),
            "i = 0\n"
            "while GMRuntime.gml_lt(i, 3):\n"
            "\tif GMRuntime.gml_bool(skip):\n"
            "\t\ti = GMRuntime.gml_add(i, 1)\n"
            "\t\tcontinue\n"
            "\tscore = GMRuntime.gml_add(score, i)\n"
            "\ti = GMRuntime.gml_add(i, 1)",
        )

    def test_transpiles_var_assignments(self):
        self.assertEqual(
            transpile_gml_code("var x = a + b * c;", indent=""),
            "var x = GMRuntime.gml_add(a, GMRuntime.gml_mul(b, c))",
        )
        self.assertEqual(
            transpile_gml_code("var x := 1;", indent=""),
            "var x = 1",
        )

    def test_transpiles_multiple_var_assignments(self):
        self.assertEqual(
            transpile_gml_code("var x = 1, y = x + 2;", indent=""),
            "var x = 1\nvar y = GMRuntime.gml_add(x, 2)",
        )

    def test_unassigned_local_vars_initialize_to_gml_undefined(self):
        self.assertEqual(
            transpile_gml_code("var _i, _num = 24.5, _str;", indent=""),
            "var _i = GMRuntime.gml_undefined()\n"
            "var _num = 24.5\n"
            "var _str = GMRuntime.gml_undefined()",
        )

    def test_redeclared_local_vars_lower_to_assignments(self):
        self.assertEqual(
            transpile_gml_code(
                "var x = 1; var x = 2; if ready { var x = 3; var x; } if retry { var x = 4; }",
                indent="",
            ),
            "var x = 1\n"
            "x = 2\n"
            "if GMRuntime.gml_bool(ready):\n"
            "\tx = 3\n"
            "\tx = GMRuntime.gml_undefined()\n"
            "if GMRuntime.gml_bool(retry):\n"
            "\tx = 4",
        )

    def test_nested_local_vars_are_hoisted_to_function_scope(self):
        self.assertEqual(
            transpile_gml_code(
                "if ready { var color = c_red; } else { var color = c_blue; } draw_set_color(color);",
                indent="",
            ),
            "var color = GMRuntime.gml_undefined()\n"
            "if GMRuntime.gml_bool(ready):\n"
            "\tcolor = 0x0000ff\n"
            "else:\n"
            "\tcolor = 0xff0000\n"
            "GMRuntime.gml_draw_set_color(color)",
        )

    def test_nested_function_local_vars_do_not_hoist_to_enclosing_scope(self):
        self.assertEqual(
            transpile_gml_code("var fn = function() { var inner = 1; return inner; };", indent=""),
            "var fn = GMRuntime.gml_receiver_method(self, func("
            "_gml_method_self = null, _gml_method_other = null):\n"
            "\tvar inner = 1\n"
            "\treturn inner\n"
            ")",
        )

    def test_unknown_reads_remain_runtime_or_compile_errors(self):
        self.assertEqual(
            transpile_gml_expression("missing_value"),
            "missing_value",
        )
        self.assertEqual(
            transpile_gml_code("var explicit; value = missing_value;", indent=""),
            "var explicit = GMRuntime.gml_undefined()\nvalue = missing_value",
        )

    def test_local_var_lifetime_does_not_leak_between_transpiler_calls(self):
        self.assertEqual(transpile_gml_code("var x = 1;", indent=""), "var x = 1")
        self.assertEqual(
            transpile_gml_code("x += 1;", indent=""),
            "position.x = GMRuntime.gml_add(position.x, 1)",
        )

    def test_transpiles_compound_assignments(self):
        self.assertEqual(
            transpile_gml_code("x += y * 2;", indent=""),
            "position.x = GMRuntime.gml_add(position.x, GMRuntime.gml_mul(position.y, 2))",
        )
        self.assertEqual(
            transpile_gml_code("flags |= mask; flags &= keep; flags ^= toggle;", indent=""),
            "flags = GMRuntime.gml_bit_or(flags, mask)\n"
            "flags = GMRuntime.gml_bit_and(flags, keep)\n"
            "flags = GMRuntime.gml_bit_xor(flags, toggle)",
        )
        self.assertEqual(
            transpile_gml_code("score := 10;", indent=""),
            "score = 10",
        )

    def test_transpiles_chained_assignment_results(self):
        self.assertEqual(
            transpile_gml_code("a = b = c;", indent=""),
            "var _gml_assignment_value_0 = c\n"
            "b = _gml_assignment_value_0\n"
            "a = _gml_assignment_value_0",
        )
        self.assertEqual(
            transpile_gml_code("a = b += 1;", indent=""),
            "var _gml_assignment_value_0 = GMRuntime.gml_add(b, 1)\n"
            "b = _gml_assignment_value_0\n"
            "a = _gml_assignment_value_0",
        )
        self.assertEqual(
            transpile_gml_code("a = b ??= 1;", indent=""),
            "var _gml_assignment_value_0 = b\n"
            "if GMRuntime.gml_is_nullish(_gml_assignment_value_0):\n"
            "\t_gml_assignment_value_0 = 1\n"
            "\tb = _gml_assignment_value_0\n"
            "a = _gml_assignment_value_0",
        )
        self.assertEqual(
            transpile_gml_code("items[next_index()] = b = c;", indent=""),
            'var _gml_array_index_0 = GMRuntime.gml_call_named("next_index", [], self, other)\n'
            "var _gml_assignment_value_1 = c\n"
            "b = _gml_assignment_value_1\n"
            "GMRuntime.gml_array_set(items, _gml_array_index_0, _gml_assignment_value_1)",
        )

    def test_chained_nullish_assignment_keeps_a_multi_line_method_inside_its_block(self):
        self.assertEqual(
            transpile_gml_code("a = b ??= [function() { return 1; }, function() { var c = 2; return c; }];", indent=""),
            "var _gml_assignment_value_0 = b\n"
            "if GMRuntime.gml_is_nullish(_gml_assignment_value_0):\n"
            "\t_gml_assignment_value_0 = [GMRuntime.gml_receiver_method(self, func(_gml_method_self = null, _gml_method_other = null): return 1), "
            "GMRuntime.gml_receiver_method(self, func(_gml_method_self = null, _gml_method_other = null):\n"
            "\t\tvar c = 2\n"
            "\t\treturn c\n"
            "\t)]\n"
            "\tb = _gml_assignment_value_0\n"
            "a = _gml_assignment_value_0",
        )

    def test_rejects_invalid_local_var_names(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_code("var 6fish;", indent="")

        with self.assertRaises(GMLTranspileError):
            transpile_gml_code("var foo bar;", indent="")

        with self.assertRaises(GMLTranspileError):
            transpile_gml_code(f"var {'a' * 65};", indent="")

        with self.assertRaises(GMLTranspileError):
            transpile_gml_code(f"globalvar {'a' * 65};", indent="")

        with self.assertRaises(GMLTranspileError):
            transpile_gml_expression(f"function({'a' * 65}) {{ return 0; }}")

    def test_sanitizes_gdscript_reserved_local_names(self):
        self.assertEqual(
            transpile_gml_code("var match = 1; match += 1;", indent=""),
            "var match_ = 1\nmatch_ = GMRuntime.gml_add(match_, 1)",
        )

    def test_sanitizes_generated_helper_name_collisions(self):
        self.assertEqual(
            transpile_gml_code("var _gml_switch_value_0 = 1; _gml_switch_value_0 += 1;", indent=""),
            "var gml_user_gml_switch_value_0 = 1\n"
            "gml_user_gml_switch_value_0 = GMRuntime.gml_add(gml_user_gml_switch_value_0, 1)",
        )

    def test_rejects_unscoped_asset_name_variable_collisions(self):
        asset_names = {"Script1"}

        for source in ("var Script1 = 1;", "globalvar Script1;", "Script1 = 1;", "Script1++;"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, "collides with an asset name"):
                    transpile_gml_code(source, indent="", asset_names=asset_names)

        self.assertEqual(
            transpile_gml_code("self.Script1 = Script1;", indent="", asset_names=asset_names),
            'self.Script1 = GMRuntime.gml_asset_get_index("Script1")',
        )

    def test_scope_lookup_precedence_and_asset_values_are_explicit(self):
        self.assertEqual(
            transpile_gml_expression("score", local_names={"score"}, global_names={"score"}),
            "score",
        )
        self.assertEqual(
            transpile_gml_expression("score", global_names={"score"}),
            'GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "score")',
        )
        self.assertEqual(
            transpile_gml_expression("spr_player", asset_names={"spr_player"}),
            'GMRuntime.gml_asset_get_index("spr_player")',
        )
        self.assertEqual(
            transpile_gml_expression("spr_player", local_names={"spr_player"}, asset_names={"spr_player"}),
            "spr_player",
        )
        self.assertEqual(
            transpile_gml_expression("scr_add(1)", asset_names={"scr_add"}),
            'GMRuntime.gml_script_call(GMRuntime.gml_asset_get_index("scr_add"), [1], self, other)',
        )
        with self.assertRaisesRegex(GMLTranspileError, "collides with a global and asset name"):
            transpile_gml_expression("shared_name", global_names={"shared_name"}, asset_names={"shared_name"})

    def test_instance_object_selector_arguments_use_asset_registry_ids(self):
        asset_names = {"o_enemy"}

        self.assertEqual(
            transpile_gml_expression("instance_exists(o_enemy)", asset_names=asset_names),
            'GMRuntime.gml_instance_exists(GMRuntime.gml_asset_get_index("o_enemy"))',
        )
        self.assertEqual(
            transpile_gml_expression('instance_create_layer(x, y, "Instances", o_enemy)', asset_names=asset_names),
            'GMRuntime.gml_instance_create_layer(position.x, position.y, "Instances", '
            'GMRuntime.gml_asset_get_index("o_enemy"), self)',
        )
        self.assertEqual(
            transpile_gml_expression("instance_create_depth(0, 0, -1, o_enemy, { hp: 3 })", asset_names=asset_names),
            'GMRuntime.gml_instance_create_depth(0, 0, -1, GMRuntime.gml_asset_get_index("o_enemy"), self, '
            'GMRuntime.gml_struct({"hp": 3}))',
        )
        self.assertEqual(
            transpile_gml_expression("instance_destroy()"),
            "GMRuntime.gml_instance_destroy(self)",
        )
        # instance_change acts on the calling instance.
        self.assertEqual(
            transpile_gml_code("instance_change(o_enemy, true);", indent="", asset_names=asset_names),
            'GMRuntime.gml_instance_change(GMRuntime.gml_asset_get_index("o_enemy"), true, self)',
        )
        self.assertEqual(
            transpile_gml_expression("instance_destroy(o_enemy, false)", asset_names=asset_names),
            'GMRuntime.gml_instance_destroy(GMRuntime.gml_asset_get_index("o_enemy"), false)',
        )
        self.assertEqual(
            transpile_gml_code("with (o_enemy) hp = 0;", indent="", asset_names=asset_names),
            'for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_asset_get_index("o_enemy"), self, other):\n'
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "hp", 0)',
        )

    def _transpile_with_continuations(
        self,
        source: str,
        *,
        enabled: bool = True,
        inherited_event_call: str | None = None,
    ) -> GMLTranspileResult:
        return transpile_gml_code_with_source_map(
            source,
            indent="",
            asset_names={"o_b", "o_c", "s_a"},
            instance_target="self",
            direct_instance_names={"hp", "speed"},
            dynamic_instance_names=set(),
            inherited_event_call=inherited_event_call,
            instance_change_continuations=enabled,
        )

    def test_instance_change_runs_the_rest_of_the_event_on_the_new_object(self):
        # GameMaker changes the instance at the call, so the statements after
        # it act on the new object. The converter cannot swap a node's script
        # while a method of the old script runs, so the rest of the event is
        # compiled as a function that gml_instance_change_then runs after the
        # change, reaching the instance by name only, and the event returns.
        result = self._transpile_with_continuations(
            "var s = sprite_index;\ninstance_change(o_b, false);\nsprite_index = s;\nhp = 3;"
        )
        self.assertEqual(
            result.code,
            "var s = sprite_index\n"
            "var _gml_change_self = self\n"
            "var _gml_change_continue = func():\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_change_self, "sprite_index", s)\n'
            '\tGMRuntime.gml_variable_instance_set(_gml_change_self, "hp", 3)\n'
            'GMRuntime.gml_instance_change_then(GMRuntime.gml_asset_get_index("o_b"), false, '
            "_gml_change_continue, self)\n"
            "return",
        )
        # The call is reported by the number of instance_change names before it,
        # so the analyser does not warn about it.
        self.assertEqual(result.continued_instance_changes, (0,))

        # The last statement has nothing to continue with.
        self.assertEqual(
            self._transpile_with_continuations("instance_change(o_b, true);").code,
            "var _gml_change_continue = func():\n"
            "\tpass\n"
            'GMRuntime.gml_instance_change_then(GMRuntime.gml_asset_get_index("o_b"), true, '
            "_gml_change_continue, self)\n"
            "return",
        )

    def test_instance_change_continuation_is_off_unless_the_event_allows_it(self):
        # (The Destroy event, the user events and the like run inside code of
        # the instance that goes on after them.)
        result = self._transpile_with_continuations("instance_change(o_b, true);\nhp = 1;", enabled=False)
        self.assertEqual(
            result.code,
            'GMRuntime.gml_instance_change(GMRuntime.gml_asset_get_index("o_b"), true, self)\nhp = 1',
        )
        self.assertEqual(result.continued_instance_changes, ())
        self.assertEqual(
            transpile_gml_code("instance_change(o_b, true);\nhp = 1;", indent="", asset_names={"o_b"}),
            'GMRuntime.gml_instance_change(GMRuntime.gml_asset_get_index("o_b"), true, self)\nhp = 1',
        )

    def test_instance_change_continuation_follows_the_branches_it_is_in(self):
        # Each branch that changes the instance carries the statements that come
        # after the branches, since they run on the new object in that branch.
        result = self._transpile_with_continuations(
            "if hp = 1 { instance_change(o_b, 1) } else { instance_change(o_c, 0); hp = 9 }\nx = 3"
        )
        self.assertEqual(
            result.code,
            "if GMRuntime.gml_eq(hp, 1):\n"
            "\tvar _gml_change_self = self\n"
            "\tvar _gml_change_continue = func():\n"
            '\t\tGMRuntime.gml_variable_instance_set(_gml_change_self, "x", 3)\n'
            '\tGMRuntime.gml_instance_change_then(GMRuntime.gml_asset_get_index("o_b"), 1, '
            "_gml_change_continue, self)\n"
            "\treturn\n"
            "else:\n"
            "\tvar _gml_change_self = self\n"
            "\tvar _gml_change_continue = func():\n"
            '\t\tGMRuntime.gml_variable_instance_set(_gml_change_self, "hp", 9)\n'
            '\t\tGMRuntime.gml_variable_instance_set(_gml_change_self, "x", 3)\n'
            '\tGMRuntime.gml_instance_change_then(GMRuntime.gml_asset_get_index("o_c"), 0, '
            "_gml_change_continue, self)\n"
            "\treturn\n"
            "position.x = 3",
        )
        self.assertEqual(result.continued_instance_changes, (0, 1))

        # An unbraced branch and an else-if chain.
        unbraced = self._transpile_with_continuations("if (hp = 1) instance_change(o_b, 1);\nelse hp = 2;\nx = 3")
        self.assertEqual(unbraced.continued_instance_changes, (0,))
        self.assertIn('"x", 3)', unbraced.code.split("else:")[0])
        self.assertIn("else:\n\thp = 2\nposition.x = 3", unbraced.code)
        chain = self._transpile_with_continuations(
            "if (hp) { instance_change(o_b, true) } else if (speed) { instance_change(o_c, true) }\nhp = 2;"
        )
        self.assertEqual(chain.continued_instance_changes, (0, 1))
        self.assertEqual(chain.code.count("gml_instance_change_then("), 2)
        self.assertTrue(chain.code.endswith("\nhp = 2"))

    def test_instance_change_continuation_ends_at_exit_and_nests_later_calls(self):
        result = self._transpile_with_continuations("instance_change(o_b, true); exit; hp = 4")
        self.assertIn("\treturn\n", result.code)
        # Only the first call of a straight run of statements is a site; the
        # call that follows it is made by the continuation on the instance
        # (its own change takes place when the continuation returns).
        several = self._transpile_with_continuations(
            "instance_change(o_b, true);\ninstance_change(o_c, true);\nhp = 1;"
        )
        self.assertEqual(several.continued_instance_changes, (0,))
        self.assertEqual(
            several.code,
            "var _gml_change_self = self\n"
            "var _gml_change_continue = func():\n"
            '\tGMRuntime.gml_instance_change(GMRuntime.gml_asset_get_index("o_c"), true, _gml_change_self)\n'
            '\tGMRuntime.gml_variable_instance_set(_gml_change_self, "hp", 1)\n'
            'GMRuntime.gml_instance_change_then(GMRuntime.gml_asset_get_index("o_b"), true, '
            "_gml_change_continue, self)\n"
            "return",
        )
        # (The count does not depend on where the call is: comments before it
        # do not move it, and calls that stay deferred are counted.)
        counted = self._transpile_with_continuations(
            "/* a\nb */ with (o_c) { instance_change(o_b, true); }\n// c\n  instance_change(o_c, false); hp = 1;"
            "\n\tif hp { instance_change(o_c, false) }"
        )
        self.assertEqual(counted.continued_instance_changes, (1,))

    def test_instance_change_keeps_the_deferred_form_where_the_rest_cannot_run_after_it(self):
        deferred_sources = (
            # Inside a loop, a switch, a try statement or a with statement the
            # rest of the event is not the rest of the enclosing statement.
            "while (hp > 0) { instance_change(o_b, true); hp -= 1; }\nx = 1",
            "repeat (3) { instance_change(o_b, true); }",
            "switch (hp) { case 1: instance_change(o_b, true); break; }\nx = 1",
            "try { instance_change(o_b, true); } catch (e) { }\nx = 1",
            "with (o_c) { instance_change(o_b, true); }\nhp = 1",
            # An argument that changes a variable, or code that goes on to the
            # parent's event, must not run twice or after the swap.
            "instance_change(o_b, ++hp);\nx = 1",
        )
        for source in deferred_sources:
            with self.subTest(source=source):
                result = self._transpile_with_continuations(source)
                self.assertNotIn("gml_instance_change_then", result.code)
                self.assertIn("GMRuntime.gml_instance_change(", result.code)
                self.assertEqual(result.continued_instance_changes, ())

        inherited = self._transpile_with_continuations(
            "instance_change(o_b, true);\nevent_inherited();", inherited_event_call="super._on_step()"
        )
        self.assertEqual(
            inherited.code,
            'GMRuntime.gml_instance_change(GMRuntime.gml_asset_get_index("o_b"), true, self)\nsuper._on_step()',
        )
        # event_inherited before the call is no obstacle.
        before = self._transpile_with_continuations(
            "event_inherited();\ninstance_change(o_b, true);\nx = 1", inherited_event_call="super._on_step()"
        )
        self.assertTrue(before.code.startswith("super._on_step()\nvar _gml_change_self = self\n"))
        self.assertEqual(before.continued_instance_changes, (0,))

    def test_cross_instance_dot_access_uses_selector_helpers(self):
        asset_names = {"o_enemy", "o_parent"}

        self.assertEqual(
            transpile_gml_expression("o_enemy.hp", asset_names=asset_names),
            'GMRuntime.gml_selector_get(GMRuntime.gml_asset_get_index("o_enemy"), "hp")',
        )
        self.assertEqual(
            transpile_gml_expression("(o_parent).hp", asset_names=asset_names),
            'GMRuntime.gml_selector_get(GMRuntime.gml_asset_get_index("o_parent"), "hp")',
        )
        self.assertEqual(
            transpile_gml_expression("enemy_id.hp", local_names={"enemy_id"}),
            'GMRuntime.gml_selector_get(enemy_id, "hp")',
        )
        self.assertEqual(
            transpile_gml_code("o_enemy.hp = 0;", indent="", asset_names=asset_names),
            'GMRuntime.gml_selector_set(GMRuntime.gml_asset_get_index("o_enemy"), "hp", 0)',
        )
        self.assertEqual(
            transpile_gml_code("enemy_id.hp = 10;", indent=""),
            'GMRuntime.gml_selector_set(enemy_id, "hp", 10)',
        )

    def test_collision_queries_pass_self_and_selector_arguments(self):
        asset_names = {"o_wall"}

        self.assertEqual(
            transpile_gml_expression("place_meeting(x, y, o_wall)", asset_names=asset_names),
            'GMRuntime.gml_place_meeting(self, position.x, position.y, GMRuntime.gml_asset_get_index("o_wall"))',
        )
        self.assertEqual(
            transpile_gml_expression("position_meeting(target_x, target_y, all)", asset_names=asset_names),
            "GMRuntime.gml_position_meeting(self, target_x, target_y, GMRuntime.gml_instance_all())",
        )
        self.assertEqual(
            transpile_gml_expression("instance_place(x + 1, y, o_wall)", asset_names=asset_names),
            'GMRuntime.gml_instance_place(self, GMRuntime.gml_add(position.x, 1), position.y, GMRuntime.gml_asset_get_index("o_wall"))',
        )
        self.assertEqual(
            transpile_gml_expression("instance_position(target_x, target_y, o_wall)", asset_names=asset_names),
            'GMRuntime.gml_instance_position(self, target_x, target_y, GMRuntime.gml_asset_get_index("o_wall"))',
        )
        self.assertEqual(
            transpile_gml_expression("collision_point(target_x, target_y, o_wall, true, true)", asset_names=asset_names),
            'GMRuntime.gml_collision_point(self, target_x, target_y, GMRuntime.gml_asset_get_index("o_wall"), true, true)',
        )
        self.assertEqual(
            transpile_gml_expression("collision_rectangle(0, 0, 10, 10, o_wall, false, true)", asset_names=asset_names),
            'GMRuntime.gml_collision_rectangle(self, 0, 0, 10, 10, GMRuntime.gml_asset_get_index("o_wall"), false, true)',
        )
        self.assertEqual(
            transpile_gml_expression("collision_line(0, 0, 10, 10, o_wall)", asset_names=asset_names),
            'GMRuntime.gml_collision_line(self, 0, 0, 10, 10, GMRuntime.gml_asset_get_index("o_wall"))',
        )
        self.assertEqual(
            transpile_gml_expression("collision_circle(4, 5, 8, o_wall, false, false)", asset_names=asset_names),
            'GMRuntime.gml_collision_circle(self, 4, 5, 8, GMRuntime.gml_asset_get_index("o_wall"), false, false)',
        )
        self.assertEqual(
            transpile_gml_expression(
                "collision_point_list(target_x, target_y, o_wall, false, true, hits, true)",
                asset_names=asset_names,
            ),
            'GMRuntime.gml_collision_point_list(self, target_x, target_y, GMRuntime.gml_asset_get_index("o_wall"), false, true, hits, true)',
        )
        self.assertEqual(
            transpile_gml_expression(
                "collision_rectangle_list(0, 0, 10, 10, o_wall, false, true, hits, false)",
                asset_names=asset_names,
            ),
            'GMRuntime.gml_collision_rectangle_list(self, 0, 0, 10, 10, GMRuntime.gml_asset_get_index("o_wall"), false, true, hits, false)',
        )
        self.assertEqual(
            transpile_gml_expression(
                "collision_line_list(0, 0, 10, 10, o_wall, false, true, hits, true)",
                asset_names=asset_names,
            ),
            'GMRuntime.gml_collision_line_list(self, 0, 0, 10, 10, GMRuntime.gml_asset_get_index("o_wall"), false, true, hits, true)',
        )
        self.assertEqual(
            transpile_gml_expression(
                "collision_circle_list(4, 5, 8, o_wall, false, false, hits, true)",
                asset_names=asset_names,
            ),
            'GMRuntime.gml_collision_circle_list(self, 4, 5, 8, GMRuntime.gml_asset_get_index("o_wall"), false, false, hits, true)',
        )

    def test_free_empty_list_and_ellipse_collision_queries_pass_self(self):
        asset_names = {"o_wall"}

        self.assertEqual(
            transpile_gml_expression("place_free(x + 1, y)"),
            "GMRuntime.gml_place_free(self, GMRuntime.gml_add(position.x, 1), position.y)",
        )
        self.assertEqual(
            transpile_gml_expression("place_empty(x, y)"),
            "GMRuntime.gml_place_empty(self, position.x, position.y)",
        )
        self.assertEqual(
            transpile_gml_expression("place_empty(x, y, o_wall)", asset_names=asset_names),
            'GMRuntime.gml_place_empty(self, position.x, position.y, GMRuntime.gml_asset_get_index("o_wall"))',
        )
        self.assertEqual(
            transpile_gml_expression("position_empty(mouse_x, mouse_y)"),
            'GMRuntime.gml_position_empty(self, GMRuntime.gml_builtin_global("mouse_x"), '
            'GMRuntime.gml_builtin_global("mouse_y"))',
        )
        self.assertEqual(
            transpile_gml_expression("distance_to_point(10, 20)"),
            "GMRuntime.gml_distance_to_point(self, 10, 20)",
        )
        self.assertEqual(
            transpile_gml_expression("collision_ellipse(0, 0, 10, 8, o_wall, true, true)", asset_names=asset_names),
            'GMRuntime.gml_collision_ellipse(self, 0, 0, 10, 8, GMRuntime.gml_asset_get_index("o_wall"), true, true)',
        )
        self.assertEqual(
            transpile_gml_expression(
                "collision_ellipse_list(0, 0, 10, 8, o_wall, false, true, hits, true)",
                asset_names=asset_names,
            ),
            'GMRuntime.gml_collision_ellipse_list(self, 0, 0, 10, 8, GMRuntime.gml_asset_get_index("o_wall"), false, true, hits, true)',
        )
        self.assertEqual(
            transpile_gml_expression("instance_place_list(x, y, o_wall, hits, true)", asset_names=asset_names),
            'GMRuntime.gml_instance_place_list(self, position.x, position.y, GMRuntime.gml_asset_get_index("o_wall"), hits, true)',
        )
        self.assertEqual(
            transpile_gml_expression("instance_position_list(4, 5, all, hits, false)"),
            "GMRuntime.gml_instance_position_list(self, 4, 5, GMRuntime.gml_instance_all(), hits, false)",
        )

    def test_builtin_instance_members_use_runtime_lookups(self):
        self.assertEqual(
            transpile_gml_expression("bbox_bottom <= platform.bbox_top"),
            'GMRuntime.gml_lte(GMRuntime.gml_struct_get(self, "bbox_bottom"), '
            'GMRuntime.gml_selector_get(platform, "bbox_top"))',
        )
        self.assertEqual(
            transpile_gml_expression("x + sprite_width - other.sprite_xoffset"),
            'GMRuntime.gml_sub(GMRuntime.gml_add(position.x, GMRuntime.gml_struct_get(self, "sprite_width")), '
            'GMRuntime.gml_selector_get(other, "sprite_xoffset"))',
        )
        self.assertEqual(
            transpile_gml_code("with (all) h = sprite_height + sprite_yoffset;", indent=""),
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_instance_all(), self, other):\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "h", GMRuntime.gml_add('
            'GMRuntime.gml_variable_instance_get(_gml_with_target_0, "sprite_height"), '
            'GMRuntime.gml_variable_instance_get(_gml_with_target_0, "sprite_yoffset")))',
        )
        self.assertEqual(
            transpile_gml_code("with (all) left = bbox_left;", indent=""),
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_instance_all(), self, other):\n"
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "left", '
            'GMRuntime.gml_variable_instance_get(_gml_with_target_0, "bbox_left"))',
        )
        self.assertEqual(
            transpile_gml_code("other.hp -= 1; x = other.x; other.speed = 3;", indent=""),
            'GMRuntime.gml_selector_update(other, "hp", func(_gml_selector_value_0): '
            "return GMRuntime.gml_sub(_gml_selector_value_0, 1))\n"
            'position.x = GMRuntime.gml_selector_get(other, "x")\n'
            'GMRuntime.gml_selector_set(other, "speed", 3)',
        )
        self.assertEqual(
            transpile_gml_code("self.speed = 3; total = self.hp;", indent=""),
            'GMRuntime.gml_selector_set(self, "speed", 3)\n'
            "total = self.hp",
        )

    def test_motion_helpers_pass_self_and_sync_motion_assignments(self):
        self.assertEqual(
            transpile_gml_expression("motion_set(180, 4)"),
            "GMRuntime.gml_motion_set(self, 180, 4)",
        )
        self.assertEqual(
            transpile_gml_expression("motion_add(90, 2)"),
            "GMRuntime.gml_motion_add(self, 90, 2)",
        )
        self.assertEqual(
            transpile_gml_expression("move_towards_point(target_x, target_y, 3)"),
            "GMRuntime.gml_move_towards_point(self, target_x, target_y, 3)",
        )
        self.assertEqual(
            transpile_gml_expression("move_contact_solid(0, 100)"),
            "GMRuntime.gml_move_contact_solid(self, 0, 100)",
        )
        self.assertEqual(
            transpile_gml_expression("move_bounce_all(true)"),
            "GMRuntime.gml_move_bounce_all(self, true)",
        )
        self.assertEqual(
            transpile_gml_expression("place_snapped(16, 16)"),
            "GMRuntime.gml_place_snapped(self, 16, 16)",
        )
        self.assertEqual(
            transpile_gml_expression("move_outside_solid(90, -1)"),
            "GMRuntime.gml_move_outside_solid(self, 90, -1)",
        )
        self.assertEqual(
            transpile_gml_expression("move_outside_all(180, 8)"),
            "GMRuntime.gml_move_outside_all(self, 180, 8)",
        )
        self.assertEqual(
            transpile_gml_expression("move_wrap(true, false, sprite_get_width(spr))"),
            "GMRuntime.gml_move_wrap(self, true, false, GMRuntime.gml_sprite_get_width(spr))",
        )
        self.assertEqual(
            transpile_gml_code("speed = 5; direction = 90; hspeed += 2; vspeed--;", indent=""),
            "GMRuntime.gml_motion_set_speed(self, 5)\n"
            "GMRuntime.gml_motion_set_direction(self, 90)\n"
            "GMRuntime.gml_motion_set_hspeed(self, GMRuntime.gml_add(hspeed, 2))\n"
            "GMRuntime.gml_motion_set_vspeed(self, GMRuntime.gml_sub(vspeed, 1))",
        )
        self.assertEqual(
            transpile_gml_code("with (all) speed = 3;", indent=""),
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_instance_all(), self, other):\n"
            "\tGMRuntime.gml_motion_set_speed(_gml_with_target_0, 3)",
        )

    def test_move_and_collide_and_mp_steps_lower_to_runtime_motion_calls(self):
        asset_names = {"o_wall", "o_block"}
        cases = (
            (
                "hits = move_and_collide(hspd, vspd, o_wall)",
                'hits = GMRuntime.gml_move_and_collide(self, hspd, vspd, GMRuntime.gml_asset_get_index("o_wall"))',
            ),
            (
                "move_and_collide(4, 0, all, 8, 0, 1, 2, 2)",
                "GMRuntime.gml_move_and_collide(self, 4, 0, GMRuntime.gml_instance_all(), 8, 0, 1, 2, 2)",
            ),
            ("mp_linear_step(gx, gy, 4, false)", "GMRuntime.gml_mp_linear_step(self, gx, gy, 4, false)"),
            (
                "mp_linear_step_object(gx, gy, 4, o_block)",
                'GMRuntime.gml_mp_linear_step_object(self, gx, gy, 4, GMRuntime.gml_asset_get_index("o_block"))',
            ),
            ("mp_potential_step(gx, gy, 4, true)", "GMRuntime.gml_mp_potential_step(self, gx, gy, 4, true)"),
            (
                "mp_potential_step_object(gx, gy, 4, all)",
                "GMRuntime.gml_mp_potential_step_object(self, gx, gy, 4, GMRuntime.gml_instance_all())",
            ),
            ("mp_potential_settings(45, 15, 2, false)", "GMRuntime.gml_mp_potential_settings(self, 45, 15, 2, false)"),
            (
                "mp_grid_add_instances(grid, o_wall, false)",
                'GMRuntime.gml_mp_grid_add_instances(grid, GMRuntime.gml_asset_get_index("o_wall"), false)',
            ),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_code(source + ";", indent="", asset_names=asset_names), expected)
        self.assertEqual(
            transpile_gml_code("with (o_block) mp_linear_step(0, 0, 2, true);", indent="", asset_names=asset_names),
            'for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_asset_get_index("o_block"), self, other):\n'
            "\tGMRuntime.gml_mp_linear_step(_gml_with_target_0, 0, 0, 2, true)",
        )

    def test_path_and_mp_grid_helpers_lower_asset_arguments(self):
        asset_names = {"path_patrol"}

        self.assertEqual(
            transpile_gml_expression("path_start(path_patrol, 4, 0, false)", asset_names=asset_names),
            'GMRuntime.gml_path_start(self, GMRuntime.gml_asset_get_index("path_patrol"), 4, 0, false)',
        )
        self.assertEqual(
            transpile_gml_expression("path_end()"),
            "GMRuntime.gml_path_end(self)",
        )
        # The Path End Action constants are GameMaker's 0..3.
        self.assertEqual(
            transpile_gml_expression("path_start(path_patrol, 4, path_action_reverse, false)", asset_names=asset_names),
            'GMRuntime.gml_path_start(self, GMRuntime.gml_asset_get_index("path_patrol"), 4, 3, false)',
        )
        self.assertEqual(
            [
                transpile_gml_expression(name)
                for name in ("path_action_stop", "path_action_restart", "path_action_continue", "path_action_reverse")
            ],
            ["0", "1", "2", "3"],
        )
        self.assertEqual(
            transpile_gml_expression("path_get_length(path_patrol)", asset_names=asset_names),
            'GMRuntime.gml_path_get_length(GMRuntime.gml_asset_get_index("path_patrol"))',
        )
        for name, arguments in (
            ("path_exists", ""),
            ("path_get_name", ""),
            ("path_get_kind", ""),
            ("path_get_closed", ""),
            ("path_get_precision", ""),
            ("path_get_number", ""),
            ("path_get_point_x", ", 1"),
            ("path_get_point_y", ", 1"),
            ("path_get_point_speed", ", 1"),
            ("path_get_x", ", 0.5"),
            ("path_get_y", ", 0.5"),
            ("path_get_speed", ", 0.5"),
            ("path_delete", ""),
            ("path_duplicate", ""),
            ("path_clear_points", ""),
            ("path_reverse", ""),
            ("path_flip", ""),
            ("path_mirror", ""),
            ("path_add_point", ", 10, 20, 100"),
            ("path_insert_point", ", 1, 10, 20, 100"),
            ("path_change_point", ", 1, 10, 20, 100"),
            ("path_delete_point", ", 1"),
            ("path_set_kind", ", 1"),
            ("path_set_closed", ", false"),
            ("path_set_precision", ", 8"),
            ("path_shift", ", 5, -5"),
            ("path_rescale", ", 2, 0.5"),
            ("path_rotate", ", 90"),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    transpile_gml_expression(f"{name}(path_patrol{arguments})", asset_names=asset_names),
                    f'GMRuntime.gml_{name}(GMRuntime.gml_asset_get_index("path_patrol"){arguments})',
                )
        self.assertEqual(transpile_gml_expression("path_add()"), "GMRuntime.gml_path_add()")
        for name in ("path_assign", "path_append"):
            with self.subTest(name=name):
                self.assertEqual(
                    transpile_gml_expression(f"{name}(path_patrol, path_patrol)", asset_names=asset_names),
                    f'GMRuntime.gml_{name}(GMRuntime.gml_asset_get_index("path_patrol"), '
                    'GMRuntime.gml_asset_get_index("path_patrol"))',
                )
        self.assertEqual(
            transpile_gml_expression("mp_grid_create(0, 0, 4, 4, 16, 16)"),
            "GMRuntime.gml_mp_grid_create(0, 0, 4, 4, 16, 16)",
        )
        self.assertEqual(
            transpile_gml_expression(
                "mp_grid_path(grid, path_patrol, 0, 0, 48, 48, false)",
                asset_names=asset_names,
            ),
            'GMRuntime.gml_mp_grid_path(grid, GMRuntime.gml_asset_get_index("path_patrol"), 0, 0, 48, 48, false)',
        )

    def test_basic_draw_helpers_lower_to_runtime_context(self):
        self.assertEqual(
            transpile_gml_code(
                "draw_set_color(c_red); draw_set_alpha(0.5); draw_set_line_width(2); "
                "draw_line(0, 0, 10, 10); draw_rectangle(0, 0, 8, 8, false); "
                "draw_line_width(0, 0, 10, 10, 3); "
                "draw_rectangle_color(0, 0, 8, 8, c_red, c_white, c_blue, c_black, false); "
                "draw_circle_color(4, 4, 2, c_white, c_black, false); "
                "draw_circle(4, 4, 2, true); draw_triangle(0, 0, 4, 0, 0, 4, false); "
                "draw_point(1, 1); draw_clear(c_black); seen = draw_get_alpha();",
                indent="",
            ),
            "GMRuntime.gml_draw_set_color(0x0000ff)\n"
            "GMRuntime.gml_draw_set_alpha(0.5)\n"
            "GMRuntime.gml_draw_set_line_width(2)\n"
            "GMRuntime.gml_draw_line(0, 0, 10, 10)\n"
            "GMRuntime.gml_draw_rectangle(0, 0, 8, 8, false)\n"
            "GMRuntime.gml_draw_line_width(0, 0, 10, 10, 3)\n"
            "GMRuntime.gml_draw_rectangle_color(0, 0, 8, 8, 0x0000ff, 0xffffff, 0xff0000, 0x000000, false)\n"
            "GMRuntime.gml_draw_circle_color(4, 4, 2, 0xffffff, 0x000000, false)\n"
            "GMRuntime.gml_draw_circle(4, 4, 2, true)\n"
            "GMRuntime.gml_draw_triangle(0, 0, 4, 0, 0, 4, false)\n"
            "GMRuntime.gml_draw_point(1, 1)\n"
            "GMRuntime.gml_draw_clear(0x000000)\n"
            "seen = GMRuntime.gml_draw_get_alpha()",
        )

    def test_monophobia_helper_apis_lower_to_runtime(self):
        asset_names = {"o_enemy"}
        self.assertEqual(
            transpile_gml_expression("distance_to_object(o_enemy)", asset_names=asset_names),
            'GMRuntime.gml_distance_to_object(self, GMRuntime.gml_asset_get_index("o_enemy"))',
        )
        self.assertEqual(
            transpile_gml_expression("matrix_build_lookat(0, 0, -10, 0, 0, 0, 0, 1, 0)"),
            "GMRuntime.gml_matrix_build_lookat(0, 0, -10, 0, 0, 0, 0, 1, 0)",
        )
        self.assertEqual(
            transpile_gml_expression("matrix_build_projection_ortho(320, 180, 1, 1000)"),
            "GMRuntime.gml_matrix_build_projection_ortho(320, 180, 1, 1000)",
        )
        self.assertEqual(
            transpile_gml_expression("make_color_rgb(255, 128, 0)"),
            "GMRuntime.gml_make_color_rgb(255, 128, 0)",
        )

    def test_sprite_and_text_draw_helpers_lower_assets_and_state(self):
        asset_names = {"fnt_main", "spr_player", "tiles_world"}

        self.assertEqual(
            transpile_gml_code(
                "draw_self();"
                "draw_sprite(spr_player, image_index, x, y);"
                "draw_sprite_ext(spr_player, 0, x, y, image_xscale, image_yscale, image_angle, image_blend, image_alpha);"
                "draw_sprite_part(spr_player, 0, 1, 2, 8, 9, 10, 11);"
                "draw_sprite_pos(spr_player, 0, 0, 0, 8, 0, 8, 8, 0, 8, 0.75);"
                "draw_sprite_tiled(spr_player, 0, 0, 0);"
                "draw_tile(tiles_world, 3 | tile_flip, 0, 16, 24);"
                "draw_set_font(fnt_main);"
                "draw_set_halign(fa_center);"
                "draw_set_valign(fa_bottom);"
                'draw_text(16, 24, "Score");'
                'draw_text_ext(16, 40, "Wrapped text", -1, 100);'
                'draw_text_transformed(16, 64, "Big", 2, 2, image_angle);'
                "w = string_width(label); h = string_height_ext(label, -1, 120);",
                indent="",
                asset_names=asset_names,
            ),
            "GMRuntime.gml_draw_self(self)\n"
            'GMRuntime.gml_draw_sprite(GMRuntime.gml_asset_get_index("spr_player"), image_index, position.x, position.y)\n'
            'GMRuntime.gml_draw_sprite_ext(GMRuntime.gml_asset_get_index("spr_player"), 0, position.x, position.y, image_xscale, image_yscale, image_angle, image_blend, image_alpha)\n'
            'GMRuntime.gml_draw_sprite_part(GMRuntime.gml_asset_get_index("spr_player"), 0, 1, 2, 8, 9, 10, 11)\n'
            'GMRuntime.gml_draw_sprite_pos(GMRuntime.gml_asset_get_index("spr_player"), 0, 0, 0, 8, 0, 8, 8, 0, 8, 0.75)\n'
            'GMRuntime.gml_draw_sprite_tiled(GMRuntime.gml_asset_get_index("spr_player"), 0, 0, 0)\n'
            'GMRuntime.gml_draw_tile(GMRuntime.gml_asset_get_index("tiles_world"), GMRuntime.gml_bit_or(3, 0x20000000), 0, 16, 24)\n'
            'GMRuntime.gml_draw_set_font(GMRuntime.gml_asset_get_index("fnt_main"))\n'
            "GMRuntime.gml_draw_set_halign(1)\n"
            "GMRuntime.gml_draw_set_valign(2)\n"
            'GMRuntime.gml_draw_text(16, 24, "Score")\n'
            'GMRuntime.gml_draw_text_ext(16, 40, "Wrapped text", -1, 100)\n'
            'GMRuntime.gml_draw_text_transformed(16, 64, "Big", 2, 2, image_angle)\n'
            "w = GMRuntime.gml_string_width(label)\n"
            "h = GMRuntime.gml_string_height_ext(label, -1, 120)",
        )

    def test_surface_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "surf = surface_create(64, 32, surface_rgba8unorm);"
                "exists = surface_exists(surf);"
                "ok = surface_set_target(surf);"
                "draw_clear(c_black);"
                "surface_reset_target();"
                "w = surface_get_width(surf); h = surface_get_height(surf);"
                "draw_surface_ext(surf, 0, 0, 2, 2, 0, c_white, 1);"
                "surface_copy(surf, 1, 2, application_surface);"
                'surface_save(surf, "shot.png");'
                "application_surface_enable(false);"
                "application_surface_draw_enable(false);"
                "app_ok = application_surface_is_enabled();"
                "draw_ok = application_surface_is_draw_enabled();"
                "pos = application_get_position();"
                "surface_free(surf);",
                indent="",
            ),
            "surf = GMRuntime.gml_surface_create(64, 32, 0)\n"
            "exists = GMRuntime.gml_surface_exists(surf)\n"
            "ok = GMRuntime.gml_surface_set_target(surf)\n"
            "GMRuntime.gml_draw_clear(0x000000)\n"
            "GMRuntime.gml_surface_reset_target()\n"
            "w = GMRuntime.gml_surface_get_width(surf)\n"
            "h = GMRuntime.gml_surface_get_height(surf)\n"
            "GMRuntime.gml_draw_surface_ext(surf, 0, 0, 2, 2, 0, 0xffffff, 1)\n"
            "GMRuntime.gml_surface_copy(surf, 1, 2, GMRuntime.gml_builtin_global(\"application_surface\"))\n"
            'GMRuntime.gml_surface_save(surf, "shot.png")\n'
            "GMRuntime.gml_application_surface_enable(false)\n"
            "GMRuntime.gml_application_surface_draw_enable(false)\n"
            "app_ok = GMRuntime.gml_application_surface_is_enabled()\n"
            "draw_ok = GMRuntime.gml_application_surface_is_draw_enabled()\n"
            "pos = GMRuntime.gml_application_get_position()\n"
            "GMRuntime.gml_surface_free(surf)",
        )

    def test_camera_and_display_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "empty_cam = camera_create();"
                "cam = camera_create_view(0, 0, 320, 180, 0, o_player, 16, 16, 4, 4);"
                "view_set_camera(0, cam);"
                "active_before = view_get_camera(0);"
                "camera_apply(cam); active_after = camera_get_active();"
                "camera_set_view_pos(cam, 10, 20);"
                "camera_set_view_size(cam, 640, 360);"
                "camera_set_view_angle(cam, 15);"
                "vx = camera_get_view_x(cam); vy = camera_get_view_y(cam);"
                "vw = camera_get_view_width(cam); vh = camera_get_view_height(cam);"
                "va = camera_get_view_angle(cam);"
                "surface_id = view_get_surface_id(0);"
                "view_set_surface_id(0, surface_id);"
                "view_set_visible(1, true); view_visible_one = view_get_visible(1);"
                "view_set_xport(1, 320); view_set_yport(1, 20);"
                "view_set_wport(1, 640); view_set_hport(1, 360);"
                "vxport = view_get_xport(1); vyport = view_get_yport(1);"
                "vwport = view_get_wport(1); vhport = view_get_hport(1);"
                "display_set_gui_size(800, 450);"
                "gw = display_get_gui_width(); gh = display_get_gui_height();"
                "display_set_gui_maximise(0.5, 0.5, 2, 4);"
                "display_w = display_get_width(); display_h = display_get_height();"
                "dpi_x = display_get_dpi_x(); dpi_y = display_get_dpi_y();"
                "orientation = display_get_orientation(); display_set_orientation(orientation);"
                "frequency = display_get_frequency();"
                "display_reset(0, false);"
                "timing = display_get_timing_method(); display_set_timing_method(tm_sleep);"
                "sleep_margin = display_get_sleep_margin(); display_set_sleep_margin(12);"
                "display_mouse_set(10, 20); display_set_ui_visibility(0);"
                "window_center();"
                "fullscreen = window_get_fullscreen();"
                "ww = window_get_width(); wh = window_get_height();"
                "wx = window_get_x(); wy = window_get_y(); rects = window_get_visible_rects();"
                "wmx = window_mouse_get_x(); wmy = window_mouse_get_y();"
                "window_mouse_set(11, 22);"
                "vmx = window_view_mouse_get_x(1); vmy = window_view_mouse_get_y(1);"
                "avmx = window_views_mouse_get_x(); avmy = window_views_mouse_get_y();"
                "window_set_fullscreen(false);"
                "window_set_position(10, 20); window_set_size(640, 480);"
                "window_set_rectangle(0, 0, 320, 240); window_set_cursor(cr_handpoint);"
                "window_set_min_width(200); window_set_max_width(2000);"
                "window_set_min_height(150); window_set_max_height(1500);"
                "window_minimise(); window_restore();"
                "screen_save('shot.png'); screen_save_part('shot_part.png', 0, 0, 8, 8);"
                "camera_destroy(empty_cam);",
                indent="",
                asset_names={"o_player"},
            ),
            "empty_cam = GMRuntime.gml_camera_create()\n"
            'cam = GMRuntime.gml_camera_create_view(0, 0, 320, 180, 0, GMRuntime.gml_asset_get_index("o_player"), 16, 16, 4, 4)\n'
            "GMRuntime.gml_view_set_camera(0, cam)\n"
            "active_before = GMRuntime.gml_view_get_camera(0)\n"
            "GMRuntime.gml_camera_apply(cam)\n"
            "active_after = GMRuntime.gml_camera_get_active()\n"
            "GMRuntime.gml_camera_set_view_pos(cam, 10, 20)\n"
            "GMRuntime.gml_camera_set_view_size(cam, 640, 360)\n"
            "GMRuntime.gml_camera_set_view_angle(cam, 15)\n"
            "vx = GMRuntime.gml_camera_get_view_x(cam)\n"
            "vy = GMRuntime.gml_camera_get_view_y(cam)\n"
            "vw = GMRuntime.gml_camera_get_view_width(cam)\n"
            "vh = GMRuntime.gml_camera_get_view_height(cam)\n"
            "va = GMRuntime.gml_camera_get_view_angle(cam)\n"
            "surface_id = GMRuntime.gml_view_get_surface_id(0)\n"
            "GMRuntime.gml_view_set_surface_id(0, surface_id)\n"
            "GMRuntime.gml_view_set_visible(1, true)\n"
            "view_visible_one = GMRuntime.gml_view_get_visible(1)\n"
            "GMRuntime.gml_view_set_xport(1, 320)\n"
            "GMRuntime.gml_view_set_yport(1, 20)\n"
            "GMRuntime.gml_view_set_wport(1, 640)\n"
            "GMRuntime.gml_view_set_hport(1, 360)\n"
            "vxport = GMRuntime.gml_view_get_xport(1)\n"
            "vyport = GMRuntime.gml_view_get_yport(1)\n"
            "vwport = GMRuntime.gml_view_get_wport(1)\n"
            "vhport = GMRuntime.gml_view_get_hport(1)\n"
            "GMRuntime.gml_display_set_gui_size(800, 450)\n"
            "gw = GMRuntime.gml_display_get_gui_width()\n"
            "gh = GMRuntime.gml_display_get_gui_height()\n"
            "GMRuntime.gml_display_set_gui_maximise(0.5, 0.5, 2, 4)\n"
            "display_w = GMRuntime.gml_display_get_width()\n"
            "display_h = GMRuntime.gml_display_get_height()\n"
            "dpi_x = GMRuntime.gml_display_get_dpi_x()\n"
            "dpi_y = GMRuntime.gml_display_get_dpi_y()\n"
            "orientation = GMRuntime.gml_display_get_orientation()\n"
            "GMRuntime.gml_display_set_orientation(orientation)\n"
            "frequency = GMRuntime.gml_display_get_frequency()\n"
            "GMRuntime.gml_display_reset(0, false)\n"
            "timing = GMRuntime.gml_display_get_timing_method()\n"
            "GMRuntime.gml_display_set_timing_method(0)\n"
            "sleep_margin = GMRuntime.gml_display_get_sleep_margin()\n"
            "GMRuntime.gml_display_set_sleep_margin(12)\n"
            "GMRuntime.gml_display_mouse_set(10, 20)\n"
            "GMRuntime.gml_display_set_ui_visibility(0)\n"
            "GMRuntime.gml_window_center()\n"
            "fullscreen = GMRuntime.gml_window_get_fullscreen()\n"
            "ww = GMRuntime.gml_window_get_width()\n"
            "wh = GMRuntime.gml_window_get_height()\n"
            "wx = GMRuntime.gml_window_get_x()\n"
            "wy = GMRuntime.gml_window_get_y()\n"
            "rects = GMRuntime.gml_window_get_visible_rects()\n"
            "wmx = GMRuntime.gml_window_mouse_get_x()\n"
            "wmy = GMRuntime.gml_window_mouse_get_y()\n"
            "GMRuntime.gml_window_mouse_set(11, 22)\n"
            "vmx = GMRuntime.gml_window_view_mouse_get_x(1)\n"
            "vmy = GMRuntime.gml_window_view_mouse_get_y(1)\n"
            "avmx = GMRuntime.gml_window_views_mouse_get_x()\n"
            "avmy = GMRuntime.gml_window_views_mouse_get_y()\n"
            "GMRuntime.gml_window_set_fullscreen(false)\n"
            "GMRuntime.gml_window_set_position(10, 20)\n"
            "GMRuntime.gml_window_set_size(640, 480)\n"
            "GMRuntime.gml_window_set_rectangle(0, 0, 320, 240)\n"
            "GMRuntime.gml_window_set_cursor(6)\n"
            "GMRuntime.gml_window_set_min_width(200)\n"
            "GMRuntime.gml_window_set_max_width(2000)\n"
            "GMRuntime.gml_window_set_min_height(150)\n"
            "GMRuntime.gml_window_set_max_height(1500)\n"
            "GMRuntime.gml_window_minimise()\n"
            "GMRuntime.gml_window_restore()\n"
            "GMRuntime.gml_screen_save('shot.png')\n"
            "GMRuntime.gml_screen_save_part('shot_part.png', 0, 0, 8, 8)\n"
            "GMRuntime.gml_camera_destroy(empty_cam)",
        )

    def test_camera_display_unsupported_gif_apis_get_diagnostics(self):
        # An unsupported call fails on its own at run time; the code around it
        # still converts.
        self.assertRegex(
            transpile_gml_code("gif_open(320, 180);", indent=""),
            r'^GMRuntime\.gml_unsupported_call\("gif_open", "[^"]*unsupported[^"]*#493[^"]*GIF[^"]*", \[320, 180\]\)$',
        )
        self.assertRegex(
            transpile_gml_code("gif_add_surface(gif_id, surf, 6);", indent=""),
            r'^GMRuntime\.gml_unsupported_call\("gif_add_surface", "[^"]*unsupported[^"]*#493[^"]*GIF[^"]*", \[gif_id, surf, 6\]\)$',
        )
        self.assertRegex(
            transpile_gml_code("gif_save_buffer(gif_id);", indent=""),
            r'^GMRuntime\.gml_unsupported_call\("gif_save_buffer", "[^"]*unsupported[^"]*#493[^"]*GIF[^"]*", \[gif_id\]\)$',
        )

    def test_transpiles_array_assignments_through_runtime(self):
        self.assertEqual(
            transpile_gml_code("items[index] = score + 1;", indent=""),
            "GMRuntime.gml_array_set(items, index, GMRuntime.gml_add(score, 1))",
        )
        self.assertEqual(
            transpile_gml_code("items[index] += 1;", indent=""),
            "GMRuntime.gml_array_set(items, index, "
            "GMRuntime.gml_add(GMRuntime.gml_array_get(items, index), 1))",
        )
        self.assertEqual(
            transpile_gml_code("items[next_index()] += value;", indent=""),
            'var _gml_array_index_0 = GMRuntime.gml_call_named("next_index", [], self, other)\n'
            "GMRuntime.gml_array_set(items, _gml_array_index_0, "
            "GMRuntime.gml_add(GMRuntime.gml_array_get(items, _gml_array_index_0), value))",
        )
        self.assertEqual(
            transpile_gml_code('global.telephonenumber[3] = "";', indent=""),
            'var _gml_array_target_0 = GMRuntime.gml_selector_get(GMRuntime.gml_global_scope(), "telephonenumber")\n'
            "if GMRuntime.is_undefined(_gml_array_target_0):\n"
            "\t_gml_array_target_0 = []\n"
            'GMRuntime.gml_array_set(_gml_array_target_0, 3, "")\n'
            'GMRuntime.gml_selector_set(GMRuntime.gml_global_scope(), "telephonenumber", _gml_array_target_0)',
        )
        self.assertEqual(
            transpile_gml_code("player.inventory[slot] = item;", indent=""),
            'var _gml_array_target_0 = GMRuntime.gml_selector_get(player, "inventory")\n'
            "if GMRuntime.is_undefined(_gml_array_target_0):\n"
            "\t_gml_array_target_0 = []\n"
            "GMRuntime.gml_array_set(_gml_array_target_0, slot, item)\n"
            'GMRuntime.gml_selector_set(player, "inventory", _gml_array_target_0)',
        )

    def test_transpiles_lts_direct_array_accessors(self):
        self.assertEqual(
            transpile_gml_expression("items[@ index]"),
            "GMRuntime.gml_array_get(items, index)",
        )
        self.assertEqual(
            transpile_gml_code("_dst[@ _i] = _dst_value;", indent=""),
            "GMRuntime.gml_array_set(_dst, _i, _dst_value)",
        )
        self.assertEqual(
            transpile_gml_code(
                "_tokens[@ array_length(_tokens)] = [value];",
                indent="",
            ),
            "GMRuntime.gml_array_set(_tokens, "
            "GMRuntime.gml_array_length(_tokens), [value])",
        )

    def test_transpiles_multidimensional_array_assignments(self):
        self.assertEqual(
            transpile_gml_code("grid[x][y] = value;", indent=""),
            "GMRuntime.gml_array_set(GMRuntime.gml_array_get(grid, position.x), position.y, value)",
        )

    def test_transpiles_struct_member_assignments_through_runtime(self):
        self.assertEqual(
            transpile_gml_code("mystruct.a = 20;", indent=""),
            'GMRuntime.gml_selector_set(mystruct, "a", 20)',
        )
        self.assertEqual(
            transpile_gml_code('mystruct[$ "x"] = score + 1;', indent=""),
            'GMRuntime.gml_struct_set(mystruct, "x", GMRuntime.gml_add(score, 1))',
        )
        self.assertEqual(
            transpile_gml_code("mystruct.a += 1;", indent=""),
            'GMRuntime.gml_selector_update(mystruct, "a", '
            'func(_gml_selector_value_0): return GMRuntime.gml_add(_gml_selector_value_0, 1))',
        )
        self.assertEqual(
            transpile_gml_code("mystruct.a ??= 1;", indent=""),
            'GMRuntime.gml_selector_set_if_nullish(mystruct, "a", func(): return 1)',
        )
        self.assertEqual(
            transpile_gml_code("mystruct.a++;", indent=""),
            'GMRuntime.gml_selector_update(mystruct, "a", '
            'func(_gml_selector_value_0): return GMRuntime.gml_add(_gml_selector_value_0, 1))',
        )
        self.assertEqual(
            transpile_gml_code("get_struct().a += 1;", indent=""),
            'var _gml_selector_target_0 = GMRuntime.gml_call_named("get_struct", [], self, other)\n'
            'GMRuntime.gml_selector_update(_gml_selector_target_0, "a", '
            'func(_gml_selector_value_1): return GMRuntime.gml_add(_gml_selector_value_1, 1))',
        )

    def test_array_assignment_aliases_preserve_reference_mutation(self):
        self.assertEqual(
            transpile_gml_code("items = [1, 2]; alias = items; alias[0] = 9;", indent=""),
            "items = [1, 2]\n"
            "alias = items\n"
            "GMRuntime.gml_array_set(alias, 0, 9)",
        )

    def test_struct_assignment_aliases_preserve_reference_mutation(self):
        self.assertEqual(
            transpile_gml_code("mystruct = {a: 1}; alias = mystruct; alias.a = 2; value = mystruct.a;", indent=""),
            'mystruct = GMRuntime.gml_struct({"a": 1})\n'
            "alias = mystruct\n"
            'GMRuntime.gml_selector_set(alias, "a", 2)\n'
            'value = GMRuntime.gml_selector_get(mystruct, "a")',
        )

    def test_struct_function_arguments_pass_reference_without_clone(self):
        self.assertEqual(
            transpile_gml_code("mystruct = {a: 1}; mutate_struct(mystruct); value = mystruct.a;", indent=""),
            'mystruct = GMRuntime.gml_struct({"a": 1})\n'
            'GMRuntime.gml_call_named("mutate_struct", [mystruct], self, other)\n'
            'value = GMRuntime.gml_selector_get(mystruct, "a")',
        )

    def test_function_argument_reassignment_does_not_mutate_caller_value(self):
        self.assertEqual(
            transpile_gml_code(
                "var try_to_modify_value = function(argument0) { argument0 = 2; }; "
                "value = 1; try_to_modify_value(value); result = value;",
                indent="",
            ),
            "var try_to_modify_value = GMRuntime.gml_receiver_method(self, "
            "func(_gml_method_self = null, _gml_method_other = null, "
            "argument0 = null):\n"
            "\tif argument0 == null: argument0 = GMRuntime.gml_undefined()\n"
            "\targument0 = 2\n"
            ")\n"
            "value = 1\n"
            'GMRuntime.gml_call_value(try_to_modify_value, [value], self, other, "try_to_modify_value")\n'
            "result = value",
        )

    def test_array_function_arguments_pass_reference_without_clone(self):
        self.assertEqual(
            transpile_gml_code(
                "var try_to_modify_array = function(argument0) { array_push(argument0, 2); }; "
                "items = [1]; try_to_modify_array(items); value = items[1];",
                indent="",
            ),
            "var try_to_modify_array = GMRuntime.gml_receiver_method(self, "
            "func(_gml_method_self = null, _gml_method_other = null, "
            "argument0 = null):\n"
            "\tif argument0 == null: argument0 = GMRuntime.gml_undefined()\n"
            "\tGMRuntime.gml_array_push(argument0, [2])\n"
            ")\n"
            "items = [1]\n"
            'GMRuntime.gml_call_value(try_to_modify_array, [items], self, other, "try_to_modify_array")\n'
            "value = GMRuntime.gml_array_get(items, 1)",
        )

    def test_array_assignment_to_undefined_releases_reference(self):
        self.assertEqual(
            transpile_gml_code("items = [1, 2]; items = undefined;", indent=""),
            "items = [1, 2]\nitems = GMRuntime.gml_undefined()",
        )

    def test_transpiles_array_create(self):
        self.assertEqual(
            transpile_gml_code("arr = array_create(5);", indent=""),
            "arr = GMRuntime.gml_array_create(5)",
        )
        self.assertEqual(
            transpile_gml_code("arr = array_create(5, 0);", indent=""),
            "arr = GMRuntime.gml_array_create(5, 0)",
        )

    def test_transpiles_array_length_1d(self):
        self.assertEqual(
            transpile_gml_code("n = array_length_1d(arr);", indent=""),
            "n = GMRuntime.gml_array_length_1d(arr)",
        )

    def test_transpiles_array_length(self):
        self.assertEqual(
            transpile_gml_code("n = array_length(arr);", indent=""),
            "n = GMRuntime.gml_array_length(arr)",
        )

    def test_transpiles_array_resize(self):
        self.assertEqual(
            transpile_gml_code("array_resize(arr, 10);", indent=""),
            "GMRuntime.gml_array_resize(arr, 10)",
        )

    def test_transpiles_array_pop(self):
        self.assertEqual(
            transpile_gml_code("val = array_pop(arr);", indent=""),
            "val = GMRuntime.gml_array_pop(arr)",
        )

    def test_transpiles_array_push_back(self):
        self.assertEqual(
            transpile_gml_code("array_push_back(arr, 42);", indent=""),
            "GMRuntime.gml_array_push_back(arr, 42)",
        )

    def test_transpiles_array_insert(self):
        self.assertEqual(
            transpile_gml_code("array_insert(arr, 0, 42);", indent=""),
            "GMRuntime.gml_array_insert(arr, 0, 42)",
        )

    def test_transpiles_array_delete(self):
        self.assertEqual(
            transpile_gml_code("array_delete(arr, 0, 3);", indent=""),
            "GMRuntime.gml_array_delete(arr, 0, 3)",
        )
        self.assertEqual(
            transpile_gml_code(
                "array_delete(_nameArray, "
                "__SnapToJSONArrayFindIndex(_nameArray, _name), 1);",
                indent="",
            ),
            'GMRuntime.gml_array_delete(_nameArray, '
            'GMRuntime.gml_call_named("__SnapToJSONArrayFindIndex", '
            '[_nameArray, _name], self, other), 1)',
        )
        with self.assertRaisesRegex(
            GMLTranspileError,
            "array_delete.*expects 3.*got 2",
        ):
            transpile_gml_code("array_delete(arr, 0);", indent="")

    def test_transpiles_array_sort(self):
        self.assertEqual(
            transpile_gml_code("array_sort(arr, true);", indent=""),
            "GMRuntime.gml_array_sort(arr, true, self, other)",
        )
        self.assertEqual(
            transpile_gml_code("array_sort(arr, comparator);", indent=""),
            "GMRuntime.gml_array_sort(arr, comparator, self, other)",
        )
        self.assertEqual(
            transpile_gml_code(
                "array_sort(arr, function(current, next) "
                "{ return current - next; });",
                indent="",
            ),
            "GMRuntime.gml_array_sort(arr, GMRuntime.gml_receiver_method(self, "
            "func(_gml_method_self = null, _gml_method_other = null, "
            "current = null, next = null):\n"
            "\tif current == null: current = GMRuntime.gml_undefined()\n"
            "\tif next == null: next = GMRuntime.gml_undefined()\n"
            "\treturn GMRuntime.gml_sub(current, next)\n"
            "), self, other)",
        )
        with self.assertRaisesRegex(
            GMLTranspileError,
            "array_sort.*expects 2.*got 1",
        ):
            transpile_gml_code("array_sort(arr);", indent="")
        with self.assertRaisesRegex(
            GMLTranspileError,
            "array_sort.*expects 2.*got 3",
        ):
            transpile_gml_code("array_sort(arr, true, false);", indent="")

    def test_transpiles_array_shuffle(self):
        self.assertEqual(
            transpile_gml_code("array_shuffle(arr);", indent=""),
            "GMRuntime.gml_array_shuffle(arr)",
        )

    def test_transpiles_array_copy(self):
        self.assertEqual(
            transpile_gml_code(
                "array_copy(dest, 0, src, 0, 5);", indent=""
            ),
            "GMRuntime.gml_array_copy(dest, 0, src, 0, 5)",
        )

    def test_transpiles_array_concat(self):
        self.assertEqual(
            transpile_gml_code("result = array_concat(a, b);", indent=""),
            "result = GMRuntime.gml_array_concat(a, b)",
        )

    def test_transpiles_array_contains(self):
        self.assertEqual(
            transpile_gml_code("found = array_contains(arr, 42);", indent=""),
            "found = GMRuntime.gml_array_contains(arr, 42)",
        )
        self.assertEqual(
            transpile_gml_code("found = array_contains(arr, 42, -1, -3);", indent=""),
            "found = GMRuntime.gml_array_contains(arr, 42, -1, -3)",
        )

    def test_transpiles_array_get_index(self):
        self.assertEqual(
            transpile_gml_code("idx = array_get_index(arr, 42);", indent=""),
            "idx = GMRuntime.gml_array_get_index(arr, 42)",
        )
        self.assertEqual(
            transpile_gml_code("idx = array_get_index(arr, 42, 2, 3);", indent=""),
            "idx = GMRuntime.gml_array_get_index(arr, 42, 2, 3)",
        )

    def test_transpiles_array_find_index_with_a_predicate(self):
        self.assertEqual(
            transpile_gml_code("idx = array_find_index(arr, is_big);", indent=""),
            "idx = GMRuntime.gml_array_find_index(arr, is_big, 0, null, self, other)",
        )
        self.assertEqual(
            transpile_gml_code("idx = array_find_index(arr, is_big, -1, -4);", indent=""),
            "idx = GMRuntime.gml_array_find_index(arr, is_big, -1, -4, self, other)",
        )
        inline = transpile_gml_code(
            "idx = array_find_index(arr, function(_e, _i) { return _e > 1; });",
            indent="",
        )
        self.assertTrue(
            inline.startswith(
                "idx = GMRuntime.gml_array_find_index("
                "arr, GMRuntime.gml_receiver_method(self, "
            )
        )
        self.assertTrue(inline.endswith("), 0, null, self, other)"))

    def test_transpiles_array_foreach(self):
        self.assertEqual(
            transpile_gml_code("array_foreach(arr, callback);", indent=""),
            "GMRuntime.gml_array_foreach(arr, callback, 0, null, self, other)",
        )
        self.assertEqual(
            transpile_gml_code("array_foreach(arr, callback, -2);", indent=""),
            "GMRuntime.gml_array_foreach(arr, callback, -2, null, self, other)",
        )
        self.assertEqual(
            transpile_gml_code("array_foreach(arr, callback, 3, -3);", indent=""),
            "GMRuntime.gml_array_foreach(arr, callback, 3, -3, self, other)",
        )
        inline = transpile_gml_code(
            "array_foreach(arr, function(value, index) { seen[index] = value; });",
            indent="",
        )
        self.assertTrue(
            inline.startswith(
                "GMRuntime.gml_array_foreach("
                "arr, GMRuntime.gml_receiver_method(self, "
            )
        )
        self.assertTrue(inline.endswith("), 0, null, self, other)"))
        with self.assertRaisesRegex(
            GMLTranspileError,
            "array_foreach.*expects 2 to 4.*got 1",
        ):
            transpile_gml_code("array_foreach(arr);", indent="")
        with self.assertRaisesRegex(
            GMLTranspileError,
            "array_foreach.*expects 2 to 4.*got 5",
        ):
            transpile_gml_code(
                "array_foreach(arr, callback, 0, 1, 2);",
                indent="",
            )

    def test_transpiles_array_map(self):
        self.assertEqual(
            transpile_gml_code(
                "result = array_map(arr, double);", indent=""
            ),
            "result = GMRuntime.gml_array_map(arr, double, self, other)",
        )

    def test_transpiles_array_filter(self):
        self.assertEqual(
            transpile_gml_code(
                "result = array_filter(arr, is_odd);", indent=""
            ),
            "result = GMRuntime.gml_array_filter(arr, is_odd, self, other)",
        )

    def test_transpiles_array_reduce(self):
        self.assertEqual(
            transpile_gml_code(
                "result = array_reduce(arr, add, 0);", indent=""
            ),
            "result = GMRuntime.gml_array_reduce(arr, add, 0, self, other)",
        )
        self.assertEqual(
            transpile_gml_code(
                "result = array_reduce(arr, add);", indent=""
            ),
            "result = GMRuntime.gml_array_reduce(arr, add, null, self, other)",
        )

    def test_transpiles_newline_separated_statements(self):
        self.assertEqual(
            transpile_gml_code("superSpeed = 0\nfaster = false;", indent=""),
            "superSpeed = 0\nfaster = false",
        )

    def test_transpiles_divide_assignment_through_runtime(self):
        self.assertEqual(
            transpile_gml_code("x /= 0;", indent=""),
            "position.x = GMRuntime.gml_div(position.x, 0)",
        )

    def test_transpiles_nullish_assignment(self):
        self.assertEqual(
            transpile_gml_code("score ??= 10;", indent=""),
            "if GMRuntime.gml_is_nullish(score):\n\tscore = 10",
        )
        self.assertEqual(
            transpile_gml_code("score ??= count++;", indent=""),
            "if GMRuntime.gml_is_nullish(score):\n"
            "\tvar _gm2gd_mutation_value_0 = count\n"
            "\tcount = GMRuntime.gml_add(_gm2gd_mutation_value_0, 1)\n"
            "\tscore = _gm2gd_mutation_value_0",
        )

    def test_statements_end_where_their_expression_ends(self):
        # GameMaker needs no semicolons and treats line breaks as white space:
        # a statement ends before the first token that cannot continue it
        # (manual: If Else and Conditional Operators).
        cases = {
            "a = 2 trace(a);": 'a = 2\nGMRuntime.gml_call_named("trace", [a], self, other)',
            "instance_destroy(o) exit": "GMRuntime.gml_instance_destroy(o)\nreturn",
            "{onice = false onGround = true}": "onice = false\nonGround = true",
            "var s = 1, t = 2 u = 3": "var s = 1\nvar t = 2\nu = 3",
            "total = a +\n    b;": "total = GMRuntime.gml_add(a, b)",
            "total = a\n    + b;": "total = GMRuntime.gml_add(a, b)",
            "total = ready\n    ? a\n    : b;": "total = a if GMRuntime.gml_bool(ready) else b",
            "count++ total = 1": "count = GMRuntime.gml_add(count, 1)\ntotal = 1",
            'lang = "english" set_language(0);': 'lang = "english"\nGMRuntime.gml_call_named("set_language", [0], self, other)',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_code(source, indent=""), expected)

    def test_conditions_without_parentheses_end_before_their_body(self):
        cases = {
            "if f(v) g()": (
                'if GMRuntime.gml_bool(GMRuntime.gml_call_named("f", [v], self, other)):\n'
                '\tGMRuntime.gml_call_named("g", [], self, other)'
            ),
            "if a == 1\n    b = 1;": "if GMRuntime.gml_eq(a, 1):\n\tb = 1",
            "if test == true variable = false else variable = true;": (
                "if GMRuntime.gml_eq(test, true):\n\tvariable = false\nelse:\n\tvariable = true"
            ),
            "if ready then go = 1 else { go = 2 }": (
                "if GMRuntime.gml_bool(ready):\n\tgo = 1\nelse:\n\tgo = 2"
            ),
            "if (a) ++b;": "if GMRuntime.gml_bool(a):\n\tb = GMRuntime.gml_add(b, 1)",
            "while i < 3 i += 1": "while GMRuntime.gml_lt(i, 3):\n\ti = GMRuntime.gml_add(i, 1)",
            "with o_thing instance_destroy()": (
                "for _gml_with_target_0 in GMRuntime.gml_with_targets(o_thing, self, other):\n"
                "\tGMRuntime.gml_instance_destroy(_gml_with_target_0)"
            ),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_code(source, indent=""), expected)
        self.assertEqual(
            transpile_gml_code("function loc(p) {\n    if !file_exists(p) return false;\n    return true;\n}", indent=""),
            transpile_gml_code("function loc(p) {\n    if (!file_exists(p)) { return false; }\n    return true;\n}", indent=""),
        )

    def test_case_bodies_and_methods_split_statements_without_semicolons(self):
        self.assertEqual(
            transpile_gml_code('switch (k) { case("40"): r = 1 break; default: v = 5 break }', indent=""),
            transpile_gml_code('switch (k) { case("40"): r = 1; break; default: v = 5; break; }', indent=""),
        )
        self.assertEqual(
            transpile_gml_code("fn = function() {\n    a = 1\n    b = 2\n}", indent=""),
            transpile_gml_code("fn = function() {\n    a = 1;\n    b = 2;\n}", indent=""),
        )

    def test_transpiles_increment_decrement_statements(self):
        self.assertEqual(
            transpile_gml_code("count++;", indent=""),
            "count = GMRuntime.gml_add(count, 1)",
        )
        self.assertEqual(
            transpile_gml_code("--count;", indent=""),
            "count = GMRuntime.gml_sub(count, 1)",
        )
        self.assertEqual(
            transpile_gml_code("value = count++; other_value = --count;", indent=""),
            "var _gml_increment_value_0 = count\n"
            "count = GMRuntime.gml_add(count, 1)\n"
            "value = _gml_increment_value_0\n"
            "count = GMRuntime.gml_sub(count, 1)\n"
            "other_value = count",
        )
        with self.assertRaisesRegex(GMLTranspileError, "Increment target must be assignable"):
            transpile_gml_code("1++;", indent="")

    def test_transpiles_mutation_expressions(self):
        self.assertEqual(
            transpile_gml_code("foo(i++);", indent=""),
            "var _gm2gd_mutation_value_0 = i\n"
            "i = GMRuntime.gml_add(_gm2gd_mutation_value_0, 1)\n"
            'GMRuntime.gml_call_named("foo", [_gm2gd_mutation_value_0], self, other)',
        )
        self.assertEqual(
            transpile_gml_code("foo(--i);", indent=""),
            "var _gm2gd_mutation_value_0 = GMRuntime.gml_sub(i, 1)\n"
            "i = _gm2gd_mutation_value_0\n"
            'GMRuntime.gml_call_named("foo", [_gm2gd_mutation_value_0], self, other)',
        )
        self.assertEqual(
            transpile_gml_code("foo(items[i]++);", indent=""),
            "var _gm2gd_mutation_value_0 = GMRuntime.gml_array_get(items, i)\n"
            "GMRuntime.gml_array_set(items, i, GMRuntime.gml_add(_gm2gd_mutation_value_0, 1))\n"
            'GMRuntime.gml_call_named("foo", [_gm2gd_mutation_value_0], self, other)',
        )
        self.assertEqual(
            transpile_gml_code("foo(alarm[i]++);", indent=""),
            "var _gm2gd_mutation_value_0 = GMRuntime.gml_alarm_get(self, i)\n"
            "GMRuntime.gml_alarm_set(self, i, GMRuntime.gml_add(_gm2gd_mutation_value_0, 1))\n"
            'GMRuntime.gml_call_named("foo", [_gm2gd_mutation_value_0], self, other)',
        )
        self.assertEqual(
            transpile_gml_code("foo(items[i++]);", indent=""),
            "var _gm2gd_mutation_value_0 = i\n"
            "i = GMRuntime.gml_add(_gm2gd_mutation_value_0, 1)\n"
            'GMRuntime.gml_call_named("foo", [GMRuntime.gml_array_get(items, _gm2gd_mutation_value_0)], self, other)',
        )
        self.assertEqual(
            transpile_gml_code("foo(get_struct().a++);", indent=""),
            'var _gml_selector_target_0 = GMRuntime.gml_call_named("get_struct", [], self, other)\n'
            "var _gm2gd_mutation_value_1 = GMRuntime.gml_selector_get(_gml_selector_target_0, \"a\")\n"
            "GMRuntime.gml_selector_set(_gml_selector_target_0, \"a\", "
            "GMRuntime.gml_add(_gm2gd_mutation_value_1, 1))\n"
            'GMRuntime.gml_call_named("foo", [_gm2gd_mutation_value_1], self, other)',
        )

        for source in ("foo(1++);", "foo(++1);", "foo((1)++);"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, "Increment expression target must be assignable"):
                    transpile_gml_code(source, indent="")

    def test_transpiles_postincrement_in_simple_array_assignment_index(self):
        self.assertEqual(
            transpile_gml_code(
                "var index = 0; var values = []; values[@ index++] = next_value();",
                indent="",
            ),
            "var index = 0\n"
            "var values = []\n"
            "var _gm2gd_mutation_value_0 = index\n"
            "index = GMRuntime.gml_add(_gm2gd_mutation_value_0, 1)\n"
            "GMRuntime.gml_array_set(values, _gm2gd_mutation_value_0, "
            'GMRuntime.gml_call_named("next_value", [], self, other))',
        )

    def test_assignment_expression_results_cover_member_and_accessor_targets(self):
        self.assertEqual(
            transpile_gml_code("result = mystruct.a += 1;", indent=""),
            "var _gml_assignment_value_0 = GMRuntime.gml_add("
            "GMRuntime.gml_selector_get(mystruct, \"a\"), 1)\n"
            "GMRuntime.gml_selector_set(mystruct, \"a\", _gml_assignment_value_0)\n"
            "result = _gml_assignment_value_0",
        )
        self.assertEqual(
            transpile_gml_code("result = mystruct.a ??= fallback;", indent=""),
            "var _gml_assignment_value_0 = GMRuntime.gml_selector_get(mystruct, \"a\")\n"
            "if GMRuntime.gml_is_nullish(_gml_assignment_value_0):\n"
            "\t_gml_assignment_value_0 = fallback\n"
            "\tGMRuntime.gml_selector_set(mystruct, \"a\", _gml_assignment_value_0)\n"
            "result = _gml_assignment_value_0",
        )
        self.assertEqual(
            transpile_gml_code("result = items[next_index()] += value;", indent=""),
            'var _gml_array_index_0 = GMRuntime.gml_call_named("next_index", [], self, other)\n'
            "var _gml_assignment_value_1 = GMRuntime.gml_add("
            "GMRuntime.gml_array_get(items, _gml_array_index_0), value)\n"
            "GMRuntime.gml_array_set(items, _gml_array_index_0, _gml_assignment_value_1)\n"
            "result = _gml_assignment_value_1",
        )
        self.assertEqual(
            transpile_gml_code("result = list[| index] ??= fallback;", indent=""),
            "var _gml_assignment_value_0 = GMRuntime.gml_ds_list_find_value(list, index)\n"
            "if GMRuntime.gml_is_nullish(_gml_assignment_value_0):\n"
            "\t_gml_assignment_value_0 = fallback\n"
            "\tGMRuntime.gml_ds_list_set(list, index, _gml_assignment_value_0)\n"
            "result = _gml_assignment_value_0",
        )

    def test_transpiles_expression_statements(self):
        self.assertEqual(
            transpile_gml_code("show_debug_message(score ?? 0);", indent=""),
            "GMRuntime.gml_show_debug_message("
            "score if not GMRuntime.gml_is_nullish(score) else 0, [])",
        )

    def test_show_debug_message_supports_lts_variadic_format_arguments(self):
        self.assertEqual(
            transpile_gml_code('show_debug_message("Ready");', indent=""),
            'GMRuntime.gml_show_debug_message("Ready", [])',
        )
        self.assertEqual(
            transpile_gml_code(
                'show_debug_message("Adding: {0}", _message);',
                indent="",
            ),
            'GMRuntime.gml_show_debug_message("Adding: {0}", [_message])',
        )
        self.assertEqual(
            transpile_gml_code(
                'show_debug_message("{0}/{1}", label, value);',
                indent="",
            ),
            'GMRuntime.gml_show_debug_message("{0}/{1}", [label, value])',
        )
        with self.assertRaisesRegex(
            GMLTranspileError,
            "show_debug_message.*at least 1.*got 0",
        ):
            transpile_gml_code("show_debug_message();", indent="")

    def test_local_vars_shadow_instance_position_builtins(self):
        self.assertEqual(
            transpile_gml_code("var x = 1, y = x + 2; x += y;", indent=""),
            "var x = 1\nvar y = GMRuntime.gml_add(x, 2)\nx = GMRuntime.gml_add(x, y)",
        )
        self.assertEqual(
            transpile_gml_code("var x = 1; self.x += x;", indent=""),
            "var x = 1\n"
            'GMRuntime.gml_selector_update(self, "x", func(_gml_selector_value_0): '
            "return GMRuntime.gml_add(_gml_selector_value_0, x))",
        )

    def test_transpiles_if_blocks(self):
        self.assertEqual(
            transpile_gml_code("if score > 0 { score -= 1; } else { score = 0; }", indent=""),
            "if GMRuntime.gml_gt(score, 0):\n\tscore = GMRuntime.gml_sub(score, 1)\nelse:\n\tscore = 0",
        )

    def test_parenthesized_condition_can_continue_after_its_first_group(self):
        self.assertEqual(
            transpile_gml_code(
                'if ((token == "]") || (token == "}")) && (previous == ",") '
                "{ trailing = true; }",
                indent="",
            ),
            'if ((GMRuntime.gml_eq(token, "]")) or (GMRuntime.gml_eq(token, "}"))) '
            'and (GMRuntime.gml_eq(previous, ",")):\n'
            "\ttrailing = true",
        )

    def test_transpiles_if_blocks_with_single_equals_conditions(self):
        self.assertEqual(
            transpile_gml_code("if faster = true { superSpeed = 20 }", indent=""),
            "if GMRuntime.gml_eq(faster, true):\n\tsuperSpeed = 20",
        )

    def test_transpiles_if_conditions_with_gml_numeric_truthiness(self):
        self.assertEqual(
            transpile_gml_code("if score { score = 1; }", indent=""),
            "if GMRuntime.gml_bool(score):\n\tscore = 1",
        )
        self.assertEqual(
            transpile_gml_code("if 0.5 { score = 1; }", indent=""),
            "if GMRuntime.gml_bool(0.5):\n\tscore = 1",
        )
        self.assertEqual(
            transpile_gml_code("if score div 2 { score = 1; }", indent=""),
            "if GMRuntime.gml_bool(GMRuntime.gml_int_div(score, 2)):\n\tscore = 1",
        )
        self.assertEqual(
            transpile_gml_code('if is_handle(handle_parse("ref ds_list 1")) { score = 1; }', indent=""),
            'if GMRuntime.is_handle(GMRuntime.gml_handle_parse("ref ds_list 1")):\n\tscore = 1',
        )

    def test_transpiles_shift_keyboard_check(self):
        self.assertEqual(
            transpile_gml_code("if keyboard_check(vk_shift) { faster = true }", indent=""),
            "if GMRuntime.gml_keyboard_check(16):\n\tfaster = true",
        )

    def test_input_bridge_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "pressed = keyboard_check_pressed(vk_space);"
                "released = keyboard_check_released(vk_escape);"
                "keyboard_key_press(vk_left); keyboard_key_release(vk_left);"
                "keyboard_clear(vk_anykey);"
                "mouse_down = mouse_check_button(mb_left);"
                "mouse_pressed = mouse_check_button_pressed(mb_right);"
                "mouse_released = mouse_check_button_released(mb_middle);"
                "mx = mouse_x; my = mouse_y; gx = device_mouse_x_to_gui(0); gy = device_mouse_y_to_gui(0);"
                "pad = gamepad_is_connected(0);"
                "pad_down = gamepad_button_check(0, gp_face1);"
                "pad_pressed = gamepad_button_check_pressed(0, gp_face2);"
                "pad_released = gamepad_button_check_released(0, gp_face3);"
                "axis = gamepad_axis_value(0, gp_axislh);"
                "gamepad_set_axis_deadzone(0, 0.2); deadzone = gamepad_get_axis_deadzone(0);"
                "gamepad_set_vibration(0, 1, 0.5); gamepad_set_color(0, c_blue);",
                indent="",
            ),
            "pressed = GMRuntime.gml_keyboard_check_pressed(32)\n"
            "released = GMRuntime.gml_keyboard_check_released(27)\n"
            "GMRuntime.gml_keyboard_key_press(37)\n"
            "GMRuntime.gml_keyboard_key_release(37)\n"
            "GMRuntime.gml_keyboard_clear(1)\n"
            "mouse_down = GMRuntime.gml_mouse_check_button(MOUSE_BUTTON_LEFT)\n"
            "mouse_pressed = GMRuntime.gml_mouse_check_button_pressed(MOUSE_BUTTON_RIGHT)\n"
            "mouse_released = GMRuntime.gml_mouse_check_button_released(MOUSE_BUTTON_MIDDLE)\n"
            'mx = GMRuntime.gml_builtin_global("mouse_x")\n'
            'my = GMRuntime.gml_builtin_global("mouse_y")\n'
            "gx = GMRuntime.gml_device_mouse_x_to_gui(0)\n"
            "gy = GMRuntime.gml_device_mouse_y_to_gui(0)\n"
            "pad = GMRuntime.gml_gamepad_is_connected(0)\n"
            "pad_down = GMRuntime.gml_gamepad_button_check(0, JOY_BUTTON_A)\n"
            "pad_pressed = GMRuntime.gml_gamepad_button_check_pressed(0, JOY_BUTTON_B)\n"
            "pad_released = GMRuntime.gml_gamepad_button_check_released(0, JOY_BUTTON_X)\n"
            "axis = GMRuntime.gml_gamepad_axis_value(0, JOY_AXIS_LEFT_X)\n"
            "GMRuntime.gml_gamepad_set_axis_deadzone(0, 0.2)\n"
            "deadzone = GMRuntime.gml_gamepad_get_axis_deadzone(0)\n"
            "GMRuntime.gml_gamepad_set_vibration(0, 1, 0.5)\n"
            "GMRuntime.gml_gamepad_set_color(0, 0xff0000)",
        )

    def test_audio_helpers_lower_sound_assets_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "handle = audio_play_sound(snd_hit, 10, false, 0.5, 0.25, 1.5);"
                "playing = audio_is_playing(snd_hit);"
                "audio_pause_sound(handle); audio_resume_sound(handle);"
                "audio_sound_gain(snd_hit, 0.25, 0);"
                "audio_sound_pitch(handle, 0.75);"
                "sound_loop(snd_hit); sound_stop(snd_hit);"
                "sound_volume(snd_hit, 0.1); sound_global_volume(0.8);",
                indent="",
                asset_names={"snd_hit"},
            ),
            'handle = GMRuntime.gml_audio_play_sound(GMRuntime.gml_asset_get_index("snd_hit"), 10, false, 0.5, 0.25, 1.5)\n'
            'playing = GMRuntime.gml_audio_is_playing(GMRuntime.gml_asset_get_index("snd_hit"))\n'
            "GMRuntime.gml_audio_pause_sound(handle)\n"
            "GMRuntime.gml_audio_resume_sound(handle)\n"
            'GMRuntime.gml_audio_sound_gain(GMRuntime.gml_asset_get_index("snd_hit"), 0.25, 0)\n'
            "GMRuntime.gml_audio_sound_pitch(handle, 0.75)\n"
            'GMRuntime.gml_sound_loop(GMRuntime.gml_asset_get_index("snd_hit"))\n'
            'GMRuntime.gml_sound_stop(GMRuntime.gml_asset_get_index("snd_hit"))\n'
            'GMRuntime.gml_sound_volume(GMRuntime.gml_asset_get_index("snd_hit"), 0.1)\n'
            "GMRuntime.gml_sound_global_volume(0.8)",
        )

    def test_advanced_audio_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "emitter = audio_emitter_create();"
                "audio_emitter_position(emitter, 10, 20, 0);"
                "audio_emitter_gain(emitter, 0.75);"
                "spatial = audio_play_sound_at(snd_hit, 10, 20, 0, 64, 512, 1, false, 5, 0.8);"
                "attached = audio_play_sound_on(emitter, snd_hit, true, 3);"
                "gain = audio_sound_get_gain(attached);"
                "asset = audio_sound_get_asset(attached);"
                "audio_channel_num(8);"
                "queue = audio_create_play_queue(1, 44100, 2);"
                "audio_queue_sound(queue, buffer_id, 0, 128);"
                "audio_free_play_queue(queue);"
                "recorders = audio_get_recorder_count();"
                "audio_start_recording(0);"
                "group = audio_create_sync_group(false);"
                "audio_play_in_sync_group(group, snd_hit);"
                "audio_start_sync_group(group);"
                "audio_destroy_sync_group(group);",
                indent="",
                asset_names={"snd_hit"},
            ),
            "emitter = GMRuntime.gml_audio_emitter_create()\n"
            "GMRuntime.gml_audio_emitter_position(emitter, 10, 20, 0)\n"
            "GMRuntime.gml_audio_emitter_gain(emitter, 0.75)\n"
            'spatial = GMRuntime.gml_audio_play_sound_at(GMRuntime.gml_asset_get_index("snd_hit"), 10, 20, 0, 64, 512, 1, false, 5, 0.8)\n'
            'attached = GMRuntime.gml_audio_play_sound_on(emitter, GMRuntime.gml_asset_get_index("snd_hit"), true, 3)\n'
            "gain = GMRuntime.gml_audio_sound_get_gain(attached)\n"
            "asset = GMRuntime.gml_audio_sound_get_asset(attached)\n"
            "GMRuntime.gml_audio_channel_num(8)\n"
            "queue = GMRuntime.gml_audio_create_play_queue(1, 44100, 2)\n"
            "GMRuntime.gml_audio_queue_sound(queue, buffer_id, 0, 128)\n"
            "GMRuntime.gml_audio_free_play_queue(queue)\n"
            "recorders = GMRuntime.gml_audio_get_recorder_count()\n"
            "GMRuntime.gml_audio_start_recording(0)\n"
            "group = GMRuntime.gml_audio_create_sync_group(false)\n"
            'GMRuntime.gml_audio_play_in_sync_group(group, GMRuntime.gml_asset_get_index("snd_hit"))\n'
            "GMRuntime.gml_audio_start_sync_group(group)\n"
            "GMRuntime.gml_audio_destroy_sync_group(group)",
        )

    def test_master_and_emitter_gain_take_gamemaker_arguments(self):
        # Manual: audio_set_master_gain(listenerIndex, gain),
        # audio_get_master_gain(listenerIndex) and
        # audio_emitter_gain(emitter, gain, [time]).
        self.assertEqual(
            transpile_gml_code(
                "audio_set_master_gain(0, 0.5);"
                "g = audio_get_master_gain(0);"
                "audio_emitter_gain(e, 0.5);"
                "audio_emitter_gain(e, 0, 1000);"
                "audio_master_gain(0.25);",
                indent="",
            ),
            "GMRuntime.gml_audio_set_master_gain(0, 0.5)\n"
            "g = GMRuntime.gml_audio_get_master_gain(0)\n"
            "GMRuntime.gml_audio_emitter_gain(e, 0.5)\n"
            "GMRuntime.gml_audio_emitter_gain(e, 0, 1000)\n"
            "GMRuntime.gml_audio_master_gain(0.25)",
        )
        for source in ("audio_set_master_gain(0.5);", "g = audio_get_master_gain();"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, "argument"):
                    transpile_gml_code(source, indent="")

    def test_audio_group_helpers_lower_to_runtime_and_group_constants(self):
        self.assertEqual(
            transpile_gml_code(
                "loaded = audio_group_is_loaded(audiogroup_music);"
                "audio_group_load(audiogroup_music);"
                "progress = audio_group_load_progress(audiogroup_music);"
                "name = audio_group_name(audiogroup_music);"
                "audio_group_set_gain(audiogroup_music, 0.5, 0);"
                "gain = audio_group_get_gain(audiogroup_music);"
                "audio_group_stop_all(audiogroup_music);"
                "audio_group_unload(audiogroup_music);",
                indent="",
            ),
            'loaded = GMRuntime.gml_audio_group_is_loaded("audiogroup_music")\n'
            'GMRuntime.gml_audio_group_load("audiogroup_music")\n'
            'progress = GMRuntime.gml_audio_group_load_progress("audiogroup_music")\n'
            'name = GMRuntime.gml_audio_group_name("audiogroup_music")\n'
            'GMRuntime.gml_audio_group_set_gain("audiogroup_music", 0.5, 0)\n'
            'gain = GMRuntime.gml_audio_group_get_gain("audiogroup_music")\n'
            'GMRuntime.gml_audio_group_stop_all("audiogroup_music")\n'
            'GMRuntime.gml_audio_group_unload("audiogroup_music")',
        )

    def test_audio_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "audio_play_sound.*expects 3 to 7.*got 2"):
            transpile_gml_code("audio_play_sound(snd_hit, 10);", indent="", asset_names={"snd_hit"})
        with self.assertRaisesRegex(GMLTranspileError, "audio_play_sound_at.*expects 9 to 13.*got 8"):
            transpile_gml_code("audio_play_sound_at(snd_hit, 0, 0, 0, 1, 10, 1, false);", indent="", asset_names={"snd_hit"})
        with self.assertRaisesRegex(GMLTranspileError, "audio_group_set_gain.*expects 2 to 3.*got 4"):
            transpile_gml_code("audio_group_set_gain(audiogroup_music, 1, 0, 0);", indent="")

    def test_room_flow_helpers_lower_room_assets_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "room_goto(r_next);"
                "ok = room_exists(r_next);"
                "name = room_get_name(r_next);"
                "info = room_get_info(r_next);"
                "room_goto_next(); room_goto_previous(); room_restart();"
                "game_set_speed(60, gamespeed_fps); room_speed = 60;"
                "game_restart(); game_end();",
                indent="",
                asset_names={"r_next"},
            ),
            'GMRuntime.gml_room_goto(GMRuntime.gml_asset_get_index("r_next"))\n'
            'ok = GMRuntime.gml_room_exists(GMRuntime.gml_asset_get_index("r_next"))\n'
            'name = GMRuntime.gml_room_get_name(GMRuntime.gml_asset_get_index("r_next"))\n'
            'info = GMRuntime.gml_room_get_info(GMRuntime.gml_asset_get_index("r_next"))\n'
            "GMRuntime.gml_room_goto_next()\n"
            "GMRuntime.gml_room_goto_previous()\n"
            "GMRuntime.gml_room_restart()\n"
            "GMRuntime.gml_game_set_speed(60, 0)\n"
            'GMRuntime.gml_builtin_global_set("room_speed", 60)\n'
            "GMRuntime.gml_game_restart()\n"
            "GMRuntime.gml_game_end()",
        )

    def test_room_speed_reads_and_writes_go_through_the_game_speed(self):
        # room_speed is the game speed (yyBuiltIn.js get_room_speed and
        # set_room_speed), so every write reaches the runtime's setter.
        self.assertEqual(
            transpile_gml_code(
                "room_speed += 5; room_speed++; room_speed ??= 30;"
                "steps = room_speed * 10;"
                "speed_fps = game_get_speed(gamespeed_fps); mpf = game_get_speed(gamespeed_microseconds);",
                indent="",
            ),
            'GMRuntime.gml_builtin_global_set("room_speed", '
            'GMRuntime.gml_add(GMRuntime.gml_builtin_global("room_speed"), 5))\n'
            'GMRuntime.gml_builtin_global_set("room_speed", '
            'GMRuntime.gml_add(GMRuntime.gml_builtin_global("room_speed"), 1))\n'
            'if GMRuntime.gml_is_nullish(GMRuntime.gml_builtin_global("room_speed")):\n'
            '\tGMRuntime.gml_builtin_global_set("room_speed", 30)\n'
            'steps = GMRuntime.gml_mul(GMRuntime.gml_builtin_global("room_speed"), 10)\n'
            "speed_fps = GMRuntime.gml_game_get_speed(0)\n"
            "mpf = GMRuntime.gml_game_get_speed(1)",
        )
        self.assertEqual(
            transpile_gml_code("x = room_speed--;", indent=""),
            'var _gml_increment_value_0 = GMRuntime.gml_builtin_global("room_speed")\n'
            'GMRuntime.gml_builtin_global_set("room_speed", '
            'GMRuntime.gml_sub(GMRuntime.gml_builtin_global("room_speed"), 1))\n'
            "position.x = _gml_increment_value_0",
        )
        self.assertEqual(
            transpile_gml_code("var room_speed = 3; room_speed = 9;", indent=""),
            "var room_speed = 3\nroom_speed = 9",
        )

    def test_layer_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                'layer_id = layer_get_id("Instances");'
                "ok = layer_exists(layer_id);"
                "name = layer_get_name(layer_id);"
                "layers = layer_get_all();"
                "depth = layer_get_depth(layer_id);"
                "lx = layer_get_x(layer_id);"
                "ly = layer_get_y(layer_id);"
                "hs = layer_get_hspeed(layer_id);"
                "vs = layer_get_vspeed(layer_id);"
                "layer_depth(layer_id, 50);"
                "layer_x(layer_id, 8);"
                "layer_y(layer_id, 16);"
                "layer_hspeed(layer_id, 2);"
                "layer_vspeed(layer_id, -1);"
                "front = layer_get_id_at_depth(50);"
                'fx = layer_create(25, "Effects");'
                "layer_add_instance(fx, id);"
                "elements = layer_get_all_elements(layer_id);"
                "layer_element_move(elements[0], fx);"
                "kind = layer_get_element_type(elements[0]);"
                "layer_set_visible(fx, false);"
                "visible = layer_get_visible(fx);"
                "bg = layer_background_get_id(layer_id);"
                "layer_background_alpha(bg, 0.25);"
                "layer_background_blend(bg, 255);"
                "layer_destroy(fx);",
                indent="",
            ),
            'layer_id = GMRuntime.gml_layer_get_id("Instances")\n'
            "ok = GMRuntime.gml_layer_exists(layer_id)\n"
            "name = GMRuntime.gml_layer_get_name(layer_id)\n"
            "layers = GMRuntime.gml_layer_get_all()\n"
            "depth = GMRuntime.gml_layer_get_depth(layer_id)\n"
            "lx = GMRuntime.gml_layer_get_x(layer_id)\n"
            "ly = GMRuntime.gml_layer_get_y(layer_id)\n"
            "hs = GMRuntime.gml_layer_get_hspeed(layer_id)\n"
            "vs = GMRuntime.gml_layer_get_vspeed(layer_id)\n"
            "GMRuntime.gml_layer_depth(layer_id, 50)\n"
            "GMRuntime.gml_layer_x(layer_id, 8)\n"
            "GMRuntime.gml_layer_y(layer_id, 16)\n"
            "GMRuntime.gml_layer_hspeed(layer_id, 2)\n"
            "GMRuntime.gml_layer_vspeed(layer_id, -1)\n"
            "front = GMRuntime.gml_layer_get_id_at_depth(50)\n"
            'fx = GMRuntime.gml_layer_create(25, "Effects")\n'
            "GMRuntime.gml_layer_add_instance(fx, id)\n"
            "elements = GMRuntime.gml_layer_get_all_elements(layer_id)\n"
            "GMRuntime.gml_layer_element_move(GMRuntime.gml_array_get(elements, 0), fx)\n"
            "kind = GMRuntime.gml_layer_get_element_type(GMRuntime.gml_array_get(elements, 0))\n"
            "GMRuntime.gml_layer_set_visible(fx, false)\n"
            "visible = GMRuntime.gml_layer_get_visible(fx)\n"
            "bg = GMRuntime.gml_layer_background_get_id(layer_id)\n"
            "GMRuntime.gml_layer_background_alpha(bg, 0.25)\n"
            "GMRuntime.gml_layer_background_blend(bg, 255)\n"
            "GMRuntime.gml_layer_destroy(fx)",
        )

    def test_layer_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "layer_create.*expects 1 to 2.*got 3"):
            transpile_gml_code('layer_create(1, "A", "B");', indent="")
        with self.assertRaisesRegex(GMLTranspileError, "layer_tilemap_create.*expects 6.*got 5"):
            transpile_gml_code(
                "layer_tilemap_create(layer_id, 0, 0, ts_ground, 2);",
                indent="",
                asset_names={"ts_ground"},
            )

    def test_tilemap_helpers_lower_tileset_assets_and_runtime_calls(self):
        self.assertEqual(
            transpile_gml_code(
                "map_id = layer_tilemap_create(layer_id, 3, 4, ts_ground, 2, 2);"
                "same_id = layer_tilemap_get_id(layer_id);"
                "ok = tilemap_set(map_id, tiledata, 1, 0);"
                "data = tilemap_get(map_id, 1, 0);"
                "width = tilemap_get_width(map_id);"
                "height = tilemap_get_height(map_id);",
                indent="",
                asset_names={"ts_ground"},
            ),
            'map_id = GMRuntime.gml_layer_tilemap_create(layer_id, 3, 4, GMRuntime.gml_asset_get_index("ts_ground"), 2, 2)\n'
            "same_id = GMRuntime.gml_layer_tilemap_get_id(layer_id)\n"
            "ok = GMRuntime.gml_tilemap_set(map_id, tiledata, 1, 0)\n"
            "data = GMRuntime.gml_tilemap_get(map_id, 1, 0)\n"
            "width = GMRuntime.gml_tilemap_get_width(map_id)\n"
            "height = GMRuntime.gml_tilemap_get_height(map_id)",
        )

    def test_sequence_timeline_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "timeline_exists(tl_intro);"
                "timeline_moment_add_script(tl_intro, 2, scr_add);"
                "timeline_step();"
                "seq = sequence_get(seq_intro);"
                "el = layer_sequence_create(layer_id, 1, 2, seq_intro);"
                "inst = layer_sequence_get_instance(el);"
                "layer_sequence_headpos(el, 10);"
                "layer_sequence_speedscale(el, 0.5);"
                "layer_sequence_headdir(el, seqdir_left);"
                "layer_sequence_pause(el);"
                "layer_sequence_play(el);"
                "layer_sequence_step(el, 4);"
                "layer_sequence_destroy(el);",
                indent="",
                asset_names={"tl_intro", "scr_add", "seq_intro"},
            ),
            'GMRuntime.gml_timeline_exists(GMRuntime.gml_asset_get_index("tl_intro"))\n'
            'GMRuntime.gml_timeline_moment_add_script(GMRuntime.gml_asset_get_index("tl_intro"), 2, GMRuntime.gml_asset_get_index("scr_add"))\n'
            "GMRuntime.gml_timeline_step(self)\n"
            'seq = GMRuntime.gml_sequence_get(GMRuntime.gml_asset_get_index("seq_intro"))\n'
            'el = GMRuntime.gml_layer_sequence_create(layer_id, 1, 2, GMRuntime.gml_asset_get_index("seq_intro"))\n'
            "inst = GMRuntime.gml_layer_sequence_get_instance(el)\n"
            "GMRuntime.gml_layer_sequence_headpos(el, 10)\n"
            "GMRuntime.gml_layer_sequence_speedscale(el, 0.5)\n"
            "GMRuntime.gml_layer_sequence_headdir(el, -1)\n"
            "GMRuntime.gml_layer_sequence_pause(el)\n"
            "GMRuntime.gml_layer_sequence_play(el)\n"
            "GMRuntime.gml_layer_sequence_step(el, 4)\n"
            "GMRuntime.gml_layer_sequence_destroy(el)",
        )

    def test_sequence_track_authoring_rejects_with_diagnostic(self):
        self.assertRegex(
            transpile_gml_code("sequence_track_new(seqtracktype_graphic);", indent=""),
            r'^GMRuntime\.gml_unsupported_call\("sequence_track_new", "[^"]*unsupported[^"]*#567[^"]*", \[',
        )

    def test_ds_list_collection_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "list = ds_list_create();"
                "ds_list_add(list, 1, 2, 3);"
                "ds_list_set(list, 0, 10);"
                "val = ds_list_find_value(list, 0);"
                "idx = ds_list_find_index(list, 10);"
                "ds_list_insert(list, 0, -1);"
                "ds_list_replace(list, 1, 99);"
                "ds_list_delete(list, 2);"
                "size = ds_list_size(list);"
                "empty = ds_list_empty(list);"
                "ds_list_shuffle(list);"
                "ds_list_sort(list, true);"
                "ds_list_clear(list);"
                "ds_list_destroy(list);",
                indent="",
            ),
            "list = GMRuntime.gml_ds_list_create()\n"
            "GMRuntime.gml_ds_list_add(list, [1, 2, 3])\n"
            "GMRuntime.gml_ds_list_set(list, 0, 10)\n"
            "val = GMRuntime.gml_ds_list_find_value(list, 0)\n"
            "idx = GMRuntime.gml_ds_list_find_index(list, 10)\n"
            "GMRuntime.gml_ds_list_insert(list, 0, -1)\n"
            "GMRuntime.gml_ds_list_replace(list, 1, 99)\n"
            "GMRuntime.gml_ds_list_delete(list, 2)\n"
            "size = GMRuntime.gml_ds_list_size(list)\n"
            "empty = GMRuntime.gml_ds_list_empty(list)\n"
            "GMRuntime.gml_ds_list_shuffle(list)\n"
            "GMRuntime.gml_ds_list_sort(list, true)\n"
            "GMRuntime.gml_ds_list_clear(list)\n"
            "GMRuntime.gml_ds_list_destroy(list)",
        )

    def test_ds_stack_collection_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "stack = ds_stack_create();"
                "ds_stack_push(stack, 1, 2, 3);"
                "top = ds_stack_top(stack);"
                "pop = ds_stack_pop(stack);"
                "size = ds_stack_size(stack);"
                "empty = ds_stack_empty(stack);"
                "ds_stack_clear(stack);"
                "ds_stack_destroy(stack);",
                indent="",
            ),
            "stack = GMRuntime.gml_ds_stack_create()\n"
            "GMRuntime.gml_ds_stack_push(stack, [1, 2, 3])\n"
            "top = GMRuntime.gml_ds_stack_top(stack)\n"
            "pop = GMRuntime.gml_ds_stack_pop(stack)\n"
            "size = GMRuntime.gml_ds_stack_size(stack)\n"
            "empty = GMRuntime.gml_ds_stack_empty(stack)\n"
            "GMRuntime.gml_ds_stack_clear(stack)\n"
            "GMRuntime.gml_ds_stack_destroy(stack)",
        )

    def test_ds_queue_collection_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                'queue = ds_queue_create();'
                "ds_queue_enqueue(queue, 'a', 'b', 'c');"
                "head = ds_queue_head(queue);"
                "tail = ds_queue_tail(queue);"
                "deq = ds_queue_dequeue(queue);"
                "size = ds_queue_size(queue);"
                "empty = ds_queue_empty(queue);"
                "ds_queue_clear(queue);"
                "ds_queue_destroy(queue);",
                indent="",
            ),
            "queue = GMRuntime.gml_ds_queue_create()\n"
            "GMRuntime.gml_ds_queue_enqueue(queue, ['a', 'b', 'c'])\n"
            "head = GMRuntime.gml_ds_queue_head(queue)\n"
            "tail = GMRuntime.gml_ds_queue_tail(queue)\n"
            "deq = GMRuntime.gml_ds_queue_dequeue(queue)\n"
            "size = GMRuntime.gml_ds_queue_size(queue)\n"
            "empty = GMRuntime.gml_ds_queue_empty(queue)\n"
            "GMRuntime.gml_ds_queue_clear(queue)\n"
            "GMRuntime.gml_ds_queue_destroy(queue)",
        )

    def test_ds_priority_collection_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "prio = ds_priority_create();"
                "ds_priority_add(prio, 'apple', 5);"
                "ds_priority_add(prio, 'banana', 1);"
                "ds_priority_change_priority(prio, 'apple', 3);"
                "max_val = ds_priority_find_max(prio);"
                "min_val = ds_priority_find_min(prio);"
                "p = ds_priority_find_priority(prio, 'apple');"
                "pop_max = ds_priority_delete_max(prio);"
                "pop_min = ds_priority_delete_min(prio);"
                "ds_priority_delete_value(prio, 'apple');"
                "size = ds_priority_size(prio);"
                "empty = ds_priority_empty(prio);"
                "ds_priority_clear(prio);"
                "ds_priority_destroy(prio);",
                indent="",
            ),
            "prio = GMRuntime.gml_ds_priority_create()\n"
            "GMRuntime.gml_ds_priority_add(prio, 'apple', 5)\n"
            "GMRuntime.gml_ds_priority_add(prio, 'banana', 1)\n"
            "GMRuntime.gml_ds_priority_change_priority(prio, 'apple', 3)\n"
            "max_val = GMRuntime.gml_ds_priority_find_max(prio)\n"
            "min_val = GMRuntime.gml_ds_priority_find_min(prio)\n"
            "p = GMRuntime.gml_ds_priority_find_priority(prio, 'apple')\n"
            "pop_max = GMRuntime.gml_ds_priority_delete_max(prio)\n"
            "pop_min = GMRuntime.gml_ds_priority_delete_min(prio)\n"
            "GMRuntime.gml_ds_priority_delete_value(prio, 'apple')\n"
            "size = GMRuntime.gml_ds_priority_size(prio)\n"
            "empty = GMRuntime.gml_ds_priority_empty(prio)\n"
            "GMRuntime.gml_ds_priority_clear(prio)\n"
            "GMRuntime.gml_ds_priority_destroy(prio)",
        )

    def test_math_number_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "a = clamp(abs(-5), 0, 3);"
                "b = lerp(10, 20, 0.25);"
                "c = point_direction(0, 0, 0, -10);"
                "d = lengthdir_y(8, 90);"
                "e = angle_difference(10, 350);"
                "f = dot_product(1, 2, 3, 4);"
                "g = dcos(180);",
                indent="",
            ),
            "a = GMRuntime.gml_clamp(GMRuntime.gml_abs(-5), 0, 3)\n"
            "b = GMRuntime.gml_lerp(10, 20, 0.25)\n"
            "c = GMRuntime.gml_point_direction(0, 0, 0, -10)\n"
            "d = GMRuntime.gml_lengthdir_y(8, 90)\n"
            "e = GMRuntime.gml_angle_difference(10, 350)\n"
            "f = GMRuntime.gml_dot_product(1, 2, 3, 4)\n"
            "g = GMRuntime.gml_dcos(180)",
        )

    def test_random_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "random_set_seed(123);"
                "a = random(10);"
                "b = irandom_range(2, 5);"
                "c = choose('a', 'b', 'c');"
                "d = random_get_seed();",
                indent="",
            ),
            "GMRuntime.gml_random_set_seed(123)\n"
            "a = GMRuntime.gml_random(10)\n"
            "b = GMRuntime.gml_irandom_range(2, 5)\n"
            "c = GMRuntime.gml_choose(['a', 'b', 'c'])\n"
            "d = GMRuntime.gml_random_get_seed()",
        )

    def test_file_ini_json_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "if file_exists('save.txt') { file_delete('save.txt'); }"
                "f = file_text_open_write('save.txt');"
                "file_text_write_string(f, 'ok');"
                "file_text_close(f);"
                "ini_open('settings.ini');"
                "ini_write_real('audio', 'volume', 0.5);"
                "volume = ini_read_real('audio', 'volume', 1);"
                "ini_close();"
                "payload = json_encode({volume: volume});"
                "decoded = json_decode(payload);",
                indent="",
            ),
            "if GMRuntime.gml_file_exists('save.txt'):\n"
            "\tGMRuntime.gml_file_delete('save.txt')\n"
            "f = GMRuntime.gml_file_text_open_write('save.txt')\n"
            "GMRuntime.gml_file_text_write_string(f, 'ok')\n"
            "GMRuntime.gml_file_text_close(f)\n"
            "GMRuntime.gml_ini_open('settings.ini')\n"
            "GMRuntime.gml_ini_write_real('audio', 'volume', 0.5)\n"
            "volume = GMRuntime.gml_ini_read_real('audio', 'volume', 1)\n"
            "GMRuntime.gml_ini_close()\n"
            'payload = GMRuntime.gml_json_encode(GMRuntime.gml_struct({"volume": volume}))\n'
            "decoded = GMRuntime.gml_json_decode(payload)",
        )

    def test_file_path_builtins_lower_to_runtime_globals(self):
        self.assertEqual(
            transpile_gml_expression("working_directory"),
            'GMRuntime.gml_builtin_global("working_directory")',
        )
        self.assertEqual(
            transpile_gml_expression("program_directory"),
            'GMRuntime.gml_builtin_global("program_directory")',
        )
        self.assertEqual(
            transpile_gml_expression("temp_directory"),
            'GMRuntime.gml_builtin_global("temp_directory")',
        )

    def test_file_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "file_text_write_string.*expects 2.*got 1"):
            transpile_gml_code("file_text_write_string(f);", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "ini_read_string.*expects 3.*got 2"):
            transpile_gml_code("ini_read_string('section', 'key');", indent="")

    def test_buffer_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "buf = buffer_create(16, buffer_grow, 4);"
                "buffer_write(buf, buffer_u8, 7);"
                "buffer_write(buf, buffer_s16, -2);"
                "buffer_seek(buf, buffer_seek_start, 0);"
                "a = buffer_read(buf, buffer_u8);"
                "b = buffer_peek(buf, 4, buffer_s16);"
                "buffer_poke(buf, 8, buffer_string, 'ok');"
                "hash = buffer_md5(buf, 0, buffer_get_used_size(buf));"
                "buffer_delete(buf);",
                indent="",
            ),
            "buf = GMRuntime.gml_buffer_create(16, 1, 4)\n"
            "GMRuntime.gml_buffer_write(buf, 1, 7)\n"
            "GMRuntime.gml_buffer_write(buf, 4, -2)\n"
            "GMRuntime.gml_buffer_seek(buf, 0, 0)\n"
            "a = GMRuntime.gml_buffer_read(buf, 1)\n"
            "b = GMRuntime.gml_buffer_peek(buf, 4, 4)\n"
            "GMRuntime.gml_buffer_poke(buf, 8, 10, 'ok')\n"
            "hash = GMRuntime.gml_buffer_md5(buf, 0, GMRuntime.gml_buffer_get_used_size(buf))\n"
            "GMRuntime.gml_buffer_delete(buf)",
        )

    def test_buffer_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "buffer_create.*expects 3.*got 2"):
            transpile_gml_code("buffer_create(16, buffer_grow);", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "buffer_poke.*expects 4.*got 3"):
            transpile_gml_code("buffer_poke(buf, 0, buffer_u8);", indent="")

    def test_async_http_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "a = http_get('https://example.test/data');"
                "b = http_post_string('https://example.test/post', 'x=1');"
                "c = http_request('https://example.test/api', 'PUT', ['X-Test: 1'], 'body');",
                indent="",
            ),
            "a = GMRuntime.gml_http_get('https://example.test/data')\n"
            "b = GMRuntime.gml_http_post_string('https://example.test/post', 'x=1')\n"
            "c = GMRuntime.gml_http_request('https://example.test/api', 'PUT', ['X-Test: 1'], 'body')",
        )

    def test_async_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "http_request.*expects 4.*got 3"):
            transpile_gml_code("http_request('url', 'GET', []);", indent="")

    def test_networking_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "server = network_create_server(network_socket_tcp, 6502, 4);"
                "sock = network_create_socket(network_socket_tcp);"
                "network_connect(sock, '127.0.0.1', 6502);"
                "sent = network_send_raw(sock, buf, buffer_get_used_size(buf));"
                "packet = network_send_packet(sock, buf, 4);"
                "network_destroy(sock);",
                indent="",
            ),
            "server = GMRuntime.gml_network_create_server(0, 6502, 4)\n"
            "sock = GMRuntime.gml_network_create_socket(0)\n"
            "GMRuntime.gml_network_connect(sock, '127.0.0.1', 6502)\n"
            "sent = GMRuntime.gml_network_send_raw(sock, buf, GMRuntime.gml_buffer_get_used_size(buf))\n"
            "packet = GMRuntime.gml_network_send_packet(sock, buf, 4)\n"
            "GMRuntime.gml_network_destroy(sock)",
        )

    def test_networking_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "network_connect.*expects 3.*got 2"):
            transpile_gml_code("network_connect(sock, '127.0.0.1');", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "network_send_udp_raw.*expects 5.*got 4"):
            transpile_gml_code("network_send_udp_raw(sock, '127.0.0.1', 6502, buf);", indent="")

    def test_gpu_texture_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "gpu_set_blendmode(bm_add);"
                "draw_set_blend_mode(bm_subtract);"
                "gpu_set_texfilter(true);"
                "texture_set_repeat(false);"
                "gpu_set_colorwriteenable(true, false, true, true);"
                "gpu_set_alphatestref(128);"
                "tex = sprite_get_texture(spr_player, 0);"
                "uvs = sprite_get_uvs(spr_player, 0);"
                "sw = sprite_get_width(spr_player); sh = sprite_get_height(spr_player);"
                "sprite_set_offset(spr_player, 4, 5); sprite_delete(spr_player);"
                "w = texture_get_width(tex);"
                "tw = texture_get_texel_width(tex);"
                "th = texture_get_texel_height(tex);"
                "ready = texture_is_ready(tex);"
                "texture_prefetch(tex);"
                "texture_flush(tex);"
                "sprite_prefetch(spr_player);"
                "sprite_flush(spr_player);"
                "draw_texture_flush();"
                "draw_flush();"
                "texture_global_scale(2);"
                "texture_debug_messages(true);"
                "texturegroup_set_mode(true, false, spr_player);"
                "texturegroup_load('Characters');"
                "texturegroup_unload('Characters');"
                "texturegroup_status = texturegroup_get_status('Characters');"
                "texturegroup_names = texturegroup_get_names();"
                "texturegroup_sprites = texturegroup_get_sprites('Characters');",
                indent="",
                asset_names={"spr_player"},
            ),
            "GMRuntime.gml_gpu_set_blendmode(1)\n"
            "GMRuntime.gml_draw_set_blend_mode(3)\n"
            "GMRuntime.gml_gpu_set_texfilter(true)\n"
            "GMRuntime.gml_texture_set_repeat(false)\n"
            "GMRuntime.gml_gpu_set_colorwriteenable(true, false, true, true)\n"
            "GMRuntime.gml_gpu_set_alphatestref(128)\n"
            "tex = GMRuntime.gml_sprite_get_texture(GMRuntime.gml_asset_get_index(\"spr_player\"), 0)\n"
            "uvs = GMRuntime.gml_sprite_get_uvs(GMRuntime.gml_asset_get_index(\"spr_player\"), 0)\n"
            "sw = GMRuntime.gml_sprite_get_width(GMRuntime.gml_asset_get_index(\"spr_player\"))\n"
            "sh = GMRuntime.gml_sprite_get_height(GMRuntime.gml_asset_get_index(\"spr_player\"))\n"
            "GMRuntime.gml_sprite_set_offset(GMRuntime.gml_asset_get_index(\"spr_player\"), 4, 5)\n"
            "GMRuntime.gml_sprite_delete(GMRuntime.gml_asset_get_index(\"spr_player\"))\n"
            "w = GMRuntime.gml_texture_get_width(tex)\n"
            "tw = GMRuntime.gml_texture_get_texel_width(tex)\n"
            "th = GMRuntime.gml_texture_get_texel_height(tex)\n"
            "ready = GMRuntime.gml_texture_is_ready(tex)\n"
            "GMRuntime.gml_texture_prefetch(tex)\n"
            "GMRuntime.gml_texture_flush(tex)\n"
            "GMRuntime.gml_sprite_prefetch(GMRuntime.gml_asset_get_index(\"spr_player\"))\n"
            "GMRuntime.gml_sprite_flush(GMRuntime.gml_asset_get_index(\"spr_player\"))\n"
            "GMRuntime.gml_draw_texture_flush()\n"
            "GMRuntime.gml_draw_flush()\n"
            "GMRuntime.gml_texture_global_scale(2)\n"
            "GMRuntime.gml_texture_debug_messages(true)\n"
            "GMRuntime.gml_texturegroup_set_mode(true, false, GMRuntime.gml_asset_get_index(\"spr_player\"))\n"
            "GMRuntime.gml_texturegroup_load('Characters')\n"
            "GMRuntime.gml_texturegroup_unload('Characters')\n"
            "texturegroup_status = GMRuntime.gml_texturegroup_get_status('Characters')\n"
            "texturegroup_names = GMRuntime.gml_texturegroup_get_names()\n"
            "texturegroup_sprites = GMRuntime.gml_texturegroup_get_sprites('Characters')",
        )

    def test_gpu_state_aliases_and_colour_write_array_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "gpu_set_tex_filter(true);"
                "old = gpu_get_tex_filter();"
                "gpu_set_tex_repeat(false);"
                "mask = gpu_get_colourwriteenable();"
                "gpu_set_colourwriteenable(true, true, true, false);"
                "gpu_set_colourwriteenable(mask);",
                indent="",
            ),
            "GMRuntime.gml_gpu_set_texfilter(true)\n"
            "old = GMRuntime.gml_gpu_get_texfilter()\n"
            "GMRuntime.gml_gpu_set_texrepeat(false)\n"
            "mask = GMRuntime.gml_gpu_get_colorwriteenable()\n"
            "GMRuntime.gml_gpu_set_colorwriteenable(true, true, true, false)\n"
            "GMRuntime.gml_gpu_set_colorwriteenable(mask)",
        )

    def test_gpu_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "gpu_set_colorwriteenable.*expects 1 to 4.*got 5"):
            transpile_gml_code("gpu_set_colorwriteenable(true, true, true, true, true);", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "texturegroup_set_mode.*1 to 3.*got 4"):
            transpile_gml_code("texturegroup_set_mode(true, false, spr_player, 0);", indent="", asset_names={"spr_player"})

    def test_video_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "video_open('intro.ogv');"
                "video_set_volume(0.5);"
                "video_enable_loop(true);"
                "video_pause();"
                "video_resume();"
                "video_seek_to(1.25);"
                "frame = video_draw();"
                "looping = video_is_looping();"
                "volume = video_get_volume();"
                "duration = video_get_duration();"
                "position = video_get_position();"
                "status = video_get_status();"
                "format = video_get_format();"
                "video_close();",
                indent="",
            ),
            "GMRuntime.gml_video_open('intro.ogv')\n"
            "GMRuntime.gml_video_set_volume(0.5)\n"
            "GMRuntime.gml_video_enable_loop(true)\n"
            "GMRuntime.gml_video_pause()\n"
            "GMRuntime.gml_video_resume()\n"
            "GMRuntime.gml_video_seek_to(1.25)\n"
            "frame = GMRuntime.gml_video_draw()\n"
            "looping = GMRuntime.gml_video_is_looping()\n"
            "volume = GMRuntime.gml_video_get_volume()\n"
            "duration = GMRuntime.gml_video_get_duration()\n"
            "position = GMRuntime.gml_video_get_position()\n"
            "status = GMRuntime.gml_video_get_status()\n"
            "format = GMRuntime.gml_video_get_format()\n"
            "GMRuntime.gml_video_close()",
        )

    def test_shader_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "shader_set(shd_wave);"
                "u = shader_get_uniform(shd_wave, 'amount');"
                "shader_set_uniform_f(u, 1, 2, 3, 4);"
                "shader_set_uniform_i(u, 1);"
                "shader_set_uniform_matrix(u);"
                "texture_set_stage(u, tex);"
                "shader_reset();",
                indent="",
                asset_names={"shd_wave"},
            ),
            "GMRuntime.gml_shader_set(GMRuntime.gml_asset_get_index(\"shd_wave\"))\n"
            "u = GMRuntime.gml_shader_get_uniform(GMRuntime.gml_asset_get_index(\"shd_wave\"), 'amount')\n"
            "GMRuntime.gml_shader_set_uniform_f(u, 1, 2, 3, 4)\n"
            "GMRuntime.gml_shader_set_uniform_i(u, 1)\n"
            "GMRuntime.gml_shader_set_uniform_matrix(u)\n"
            "GMRuntime.gml_texture_set_stage(u, tex)\n"
            "GMRuntime.gml_shader_reset()",
        )

    def test_shader_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "shader_set_uniform_f.*2 to 5.*got 6"):
            transpile_gml_code("shader_set_uniform_f(u, 1, 2, 3, 4, 5);", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "shader_set_uniform_matrix.*expects 1.*got 0"):
            transpile_gml_code("shader_set_uniform_matrix();", indent="")

    def test_particle_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "ps = part_system_create_layer('Effects', true);"
                "part_system_depth(ps, -1000);"
                "part_system_position(ps, 20, 30);"
                "layer_id = part_system_get_layer(ps);"
                "part_system_layer(ps, 'OtherEffects');"
                "ok = part_system_exists(ps);"
                "pt = part_type_create();"
                "part_type_shape(pt, pt_shape_flare);"
                "part_type_size(pt, 1, 2, 0.1, 0);"
                "part_type_scale(pt, 2, 1);"
                "part_type_life(pt, 30, 60);"
                "part_type_speed(pt, 0.5, 2, 0, 0);"
                "part_type_direction(pt, 0, 359, 0, 10);"
                "part_type_gravity(pt, 0.25, 270);"
                "part_type_orientation(pt, 0, 90, 0, 0, true);"
                "part_type_colour3(pt, c_red, c_white, c_yellow);"
                "part_type_alpha3(pt, 1, 0.5, 0);"
                "part_type_blend(pt, true);"
                "pe = part_emitter_create(ps);"
                "part_emitter_region(ps, pe, -10, 10, -5, 5, ps_shape_ellipse, ps_distr_linear);"
                "part_emitter_relative(ps, pe, false);"
                "part_particles_create(ps, x, y, pt, 3);"
                "part_emitter_burst(ps, pe, pt, 4);"
                "part_emitter_stream(ps, pe, pt, 1);"
                "count = part_particles_count(ps);"
                "part_emitter_destroy(ps, pe);"
                "part_type_destroy(pt);"
                "part_system_destroy(ps);",
                indent="",
            ),
            "ps = GMRuntime.gml_part_system_create_layer('Effects', true)\n"
            "GMRuntime.gml_part_system_depth(ps, -1000)\n"
            "GMRuntime.gml_part_system_position(ps, 20, 30)\n"
            "layer_id = GMRuntime.gml_part_system_get_layer(ps)\n"
            "GMRuntime.gml_part_system_layer(ps, 'OtherEffects')\n"
            "ok = GMRuntime.gml_part_system_exists(ps)\n"
            "pt = GMRuntime.gml_part_type_create()\n"
            "GMRuntime.gml_part_type_shape(pt, \"flare\")\n"
            "GMRuntime.gml_part_type_size(pt, 1, 2, 0.1, 0)\n"
            "GMRuntime.gml_part_type_scale(pt, 2, 1)\n"
            "GMRuntime.gml_part_type_life(pt, 30, 60)\n"
            "GMRuntime.gml_part_type_speed(pt, 0.5, 2, 0, 0)\n"
            "GMRuntime.gml_part_type_direction(pt, 0, 359, 0, 10)\n"
            "GMRuntime.gml_part_type_gravity(pt, 0.25, 270)\n"
            "GMRuntime.gml_part_type_orientation(pt, 0, 90, 0, 0, true)\n"
            "GMRuntime.gml_part_type_colour3(pt, 0x0000ff, 0xffffff, 0x00ffff)\n"
            "GMRuntime.gml_part_type_alpha3(pt, 1, 0.5, 0)\n"
            "GMRuntime.gml_part_type_blend(pt, true)\n"
            "pe = GMRuntime.gml_part_emitter_create(ps)\n"
            "GMRuntime.gml_part_emitter_region(ps, pe, -10, 10, -5, 5, \"ellipse\", \"linear\")\n"
            "GMRuntime.gml_part_emitter_relative(ps, pe, false)\n"
            "GMRuntime.gml_part_particles_create(ps, position.x, position.y, pt, 3)\n"
            "GMRuntime.gml_part_emitter_burst(ps, pe, pt, 4)\n"
            "GMRuntime.gml_part_emitter_stream(ps, pe, pt, 1)\n"
            "count = GMRuntime.gml_part_particles_count(ps)\n"
            "GMRuntime.gml_part_emitter_destroy(ps, pe)\n"
            "GMRuntime.gml_part_type_destroy(pt)\n"
            "GMRuntime.gml_part_system_destroy(ps)",
        )

    def test_particle_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "part_emitter_destroy.*expects 2.*got 1"):
            transpile_gml_code("part_emitter_destroy(pe);", indent="")

    def test_physics_helpers_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "physics_world_create(0.1);"
                "physics_world_gravity(0, 9.8);"
                "fix = physics_fixture_create();"
                "physics_fixture_set_box_shape(fix, 8, 4);"
                "physics_fixture_set_linear_damping(fix, 0.3);"
                "physics_fixture_set_angular_damping(fix, 0.4);"
                "physics_fixture_bind(fix, id);"
                "physics_apply_force(0, 0, 2, 0);"
                "physics_apply_impulse(0, 0, 10, 0);"
                "joint = physics_joint_distance_create(id, other, x, y, x + 10, y, false);"
                "rev = physics_joint_revolute_create(id, other, x, y, -90, 90, true, 10, 2, false, false);"
                "len = physics_joint_get_value(joint, phy_joint_length);"
                "physics_joint_set_value(joint, phy_joint_length, 32);"
                "physics_joint_enable_motor(rev, true);"
                "physics_mass_properties(2, 0, 0, 1);"
                "physics_joint_delete(joint);",
                indent="",
            ),
            "GMRuntime.gml_physics_world_create(0.1)\n"
            "GMRuntime.gml_physics_world_gravity(0, 9.8)\n"
            "fix = GMRuntime.gml_physics_fixture_create()\n"
            "GMRuntime.gml_physics_fixture_set_box_shape(fix, 8, 4)\n"
            "GMRuntime.gml_physics_fixture_set_linear_damping(fix, 0.3)\n"
            "GMRuntime.gml_physics_fixture_set_angular_damping(fix, 0.4)\n"
            "GMRuntime.gml_physics_fixture_bind(fix, id)\n"
            "GMRuntime.gml_physics_apply_force(0, 0, 2, 0, self)\n"
            "GMRuntime.gml_physics_apply_impulse(0, 0, 10, 0, self)\n"
            "joint = GMRuntime.gml_physics_joint_distance_create(id, other, position.x, position.y, GMRuntime.gml_add(position.x, 10), position.y, false)\n"
            "rev = GMRuntime.gml_physics_joint_revolute_create(id, other, position.x, position.y, -90, 90, true, 10, 2, false, false)\n"
            "len = GMRuntime.gml_physics_joint_get_value(joint, \"length\")\n"
            "GMRuntime.gml_physics_joint_set_value(joint, \"length\", 32)\n"
            "GMRuntime.gml_physics_joint_enable_motor(rev, true)\n"
            "GMRuntime.gml_physics_mass_properties(2, 0, 0, 1, self)\n"
            "GMRuntime.gml_physics_joint_delete(joint)",
        )

    def test_physics_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "physics_apply_force.*expects 4.*got 3"):
            transpile_gml_code("physics_apply_force(0, 0, 1);", indent="")

    def test_script_helpers_and_legacy_arguments_lower_to_runtime(self):
        self.assertEqual(
            transpile_gml_code(
                "result = script_execute(scr_add, 1, 2);"
                "ok = script_exists(scr_add);"
                "name = script_get_name(scr_add);"
                "fn = global_function('scr_add');"
                "same = script_get_callable(scr_add) == global_function('scr_add');"
                "legacy = argument0 + argument1 + argument_count;",
                indent="",
                asset_names={"scr_add"},
            ),
            "result = GMRuntime.gml_script_execute(GMRuntime.gml_asset_get_index(\"scr_add\"), [1, 2], self, other)\n"
            "ok = GMRuntime.gml_script_exists(GMRuntime.gml_asset_get_index(\"scr_add\"))\n"
            "name = GMRuntime.gml_script_get_name(GMRuntime.gml_asset_get_index(\"scr_add\"))\n"
            "fn = GMRuntime.gml_global_function('scr_add')\n"
            "same = GMRuntime.gml_eq(GMRuntime.gml_script_get_callable(GMRuntime.gml_asset_get_index(\"scr_add\")), GMRuntime.gml_global_function('scr_add'))\n"
            "legacy = GMRuntime.gml_add(GMRuntime.gml_add(GMRuntime.gml_argument(0), GMRuntime.gml_argument(1)), GMRuntime.gml_builtin_global(\"argument_count\"))",
        )

    def test_flex_panel_helpers_lower_to_runtime_and_enum_structs(self):
        self.assertEqual(
            transpile_gml_code(
                "root = flexpanel_create_node();"
                "child = flexpanel_create_node({name: 'slot'});"
                "flexpanel_node_style_set_width(root, 100, flexpanel_unit.percent);"
                "flexpanel_node_style_set_height(root, 80, flexpanel_unit.point);"
                "flexpanel_node_style_set_flex_direction(root, flexpanel_flex_direction.row);"
                "flexpanel_node_style_set_gap(root, flexpanel_gutter.all_gutters, 4);"
                "flexpanel_node_insert_child(root, child, 0);"
                "flexpanel_calculate_layout(root, 320, 180, flexpanel_direction.LTR);"
                "pos = flexpanel_node_layout_get_position(child, false);",
                indent="",
            ),
            "root = GMRuntime.gml_flexpanel_create_node()\n"
            "child = GMRuntime.gml_flexpanel_create_node(GMRuntime.gml_struct({\"name\": 'slot'}))\n"
            "GMRuntime.gml_flexpanel_node_style_set_width(root, 100, GMRuntime.gml_selector_get(GMRuntime.gml_flexpanel_unit(), \"percent\"))\n"
            "GMRuntime.gml_flexpanel_node_style_set_height(root, 80, GMRuntime.gml_selector_get(GMRuntime.gml_flexpanel_unit(), \"point\"))\n"
            "GMRuntime.gml_flexpanel_node_style_set_flex_direction(root, GMRuntime.gml_selector_get(GMRuntime.gml_flexpanel_flex_direction(), \"row\"))\n"
            "GMRuntime.gml_flexpanel_node_style_set_gap(root, GMRuntime.gml_selector_get(GMRuntime.gml_flexpanel_gutter(), \"all_gutters\"), 4)\n"
            "GMRuntime.gml_flexpanel_node_insert_child(root, child, 0)\n"
            "GMRuntime.gml_flexpanel_calculate_layout(root, 320, 180, GMRuntime.gml_selector_get(GMRuntime.gml_flexpanel_direction(), \"LTR\"))\n"
            "pos = GMRuntime.gml_flexpanel_node_layout_get_position(child, false)",
        )

    def test_script_execute_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "script_execute.*at least 1.*got 0"):
            transpile_gml_code("script_execute();", indent="")

    def test_flex_panel_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "flexpanel_node_style_set_width.*expects 3.*got 2"):
            transpile_gml_code("flexpanel_node_style_set_width(node, 100);", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "flexpanel_calculate_layout.*expects 4.*got 3"):
            transpile_gml_code("flexpanel_calculate_layout(root, 320, 180);", indent="")

    def test_delta_time_and_get_timer_read_the_runtime_clock(self):
        self.assertEqual(
            transpile_gml_expression("delta_time / 1000000"),
            'GMRuntime.gml_div(GMRuntime.gml_builtin_global("delta_time"), 1000000)',
        )
        self.assertEqual(transpile_gml_expression("get_timer()"), "GMRuntime.gml_get_timer()")
        with self.assertRaisesRegex(GMLTranspileError, "delta_time"):
            transpile_gml_code("delta_time = 5;", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "get_timer.*expects 0.*got 1"):
            transpile_gml_code("t = get_timer(1);", indent="")

    def test_time_source_constants_and_functions_use_gamemaker_values(self):
        # yyTime.js: time_source_global 0, time_source_game 1, units seconds
        # 0 and frames 1, expiry nearest 0 and after 1, states 0 to 3.
        self.assertEqual(
            transpile_gml_expression(
                "time_source_create(time_source_game, 1, time_source_units_seconds, f, [], -1, time_source_expire_after)"
            ),
            "GMRuntime.gml_time_source_create(1, 1, 0, f, [], -1, 1)",
        )
        self.assertEqual(
            transpile_gml_expression(
                "call_later(2, time_source_units_frames, f) + time_source_global + time_source_expire_nearest"
            ),
            "GMRuntime.gml_add(GMRuntime.gml_add(GMRuntime.gml_call_later(2, 1, f), 0), 0)",
        )
        self.assertEqual(
            transpile_gml_expression(
                "[time_source_state_initial, time_source_state_active, time_source_state_paused, time_source_state_stopped]"
            ),
            "[0, 1, 2, 3]",
        )
        self.assertEqual(
            transpile_gml_expression("time_source_destroy(ts, true)"),
            "GMRuntime.gml_time_source_destroy(ts, true)",
        )
        self.assertEqual(
            transpile_gml_expression("[time_source_exists(ts), time_source_get_children(time_source_game)]"),
            "[GMRuntime.gml_time_source_exists(ts), GMRuntime.gml_time_source_get_children(1)]",
        )

    def test_os_type_and_browser_constants_are_gamemaker_numbers(self):
        # os_type and os_browser hold numbers in GameMaker. The HTML5 runner's
        # Globals.js gives the desktop, mobile, unknown and browser values.
        cases = {
            "os_unknown": -1,
            "os_windows": 0,
            "os_macosx": 1,
            "os_ios": 3,
            "os_android": 4,
            "os_linux": 6,
            "os_winphone": 7,
            "os_win8native": 9,
            "os_ps4": 14,
            "os_xboxone": 15,
            "os_uwp": 18,
            "os_tvos": 20,
            "os_switch": 21,
            "os_ps5": 22,
            "os_gxgames": 23,
            "os_operagx": 23,
            "os_gdk": 24,
            "os_xboxseriesxs": 24,
            "browser_not_a_browser": -1,
            "browser_unknown": 0,
            "browser_ie": 1,
            "browser_firefox": 2,
            "browser_chrome": 3,
            "browser_safari": 4,
            "browser_safari_mobile": 5,
            "browser_opera": 6,
            "browser_windows_store": 8,
            "browser_tizen": 9,
            "browser_ie_mobile": 10,
            "browser_edge": 11,
        }
        for name, value in cases.items():
            with self.subTest(constant=name):
                self.assertEqual(transpile_gml_expression(name), str(value))

    def test_os_debug_gc_helpers_lower_to_runtime_and_builtins(self):
        self.assertEqual(
            transpile_gml_expression("os_type == os_macosx"),
            'GMRuntime.gml_eq(GMRuntime.gml_builtin_global("os_type"), 1)',
        )
        self.assertEqual(
            transpile_gml_expression("fps_real"),
            'GMRuntime.gml_builtin_global("fps_real")',
        )
        self.assertEqual(
            transpile_gml_expression("current_minute + current_second"),
            'GMRuntime.gml_add(GMRuntime.gml_builtin_global("current_minute"), GMRuntime.gml_builtin_global("current_second"))',
        )
        self.assertEqual(
            transpile_gml_expression("current_year + current_month + current_day"),
            'GMRuntime.gml_add(GMRuntime.gml_add(GMRuntime.gml_builtin_global("current_year"), GMRuntime.gml_builtin_global("current_month")), GMRuntime.gml_builtin_global("current_day"))',
        )
        self.assertEqual(
            transpile_gml_code(
                'info = os_get_info();'
                'show_debug_message_ext("{0}:{1}", [os_get_language(), os_type]);'
                'clipboard_set_text("done");'
                'has_clipboard = clipboard_has_text();'
                'gc_collect();'
                'alive = weak_ref_alive(weak_ref_create({a: 1}));',
                indent="",
            ),
            "info = GMRuntime.gml_os_get_info()\n"
            'GMRuntime.gml_show_debug_message_ext("{0}:{1}", [GMRuntime.gml_os_get_language(), GMRuntime.gml_builtin_global("os_type")])\n'
            'GMRuntime.gml_clipboard_set_text("done")\n'
            "has_clipboard = GMRuntime.gml_clipboard_has_text()\n"
            "GMRuntime.gml_gc_collect()\n"
            'alive = GMRuntime.gml_weak_ref_alive(GMRuntime.gml_weak_ref_create(GMRuntime.gml_struct({"a": 1})))',
        )

    def test_compile_time_and_runner_debug_calls_lower_to_runtime_no_ops(self):
        # The HTML5 runner does nothing for these (Function_Debug.js,
        # Function_Game.js); gml_pragma is compile-time and takes any number
        # of arguments.
        self.assertEqual(
            transpile_gml_code(
                'gml_pragma("global", "init();");'
                'gml_pragma("MarkTagAsUsed", "a", "b", "c");'
                "show_debug_overlay(true);"
                "show_debug_overlay(true, false, 2, 0.5, true, -1);"
                "open = is_debug_overlay_open();"
                "mouse = is_mouse_over_debug_overlay();"
                "keyboard = is_keyboard_used_debug_overlay();"
                'debug_event("DumpMemory", true);'
                "scheduler_resolution_set(2);"
                "resolution = scheduler_resolution_get();"
                "os_powersave_enable(false);"
                "os_lock_orientation(true);",
                indent="",
            ),
            'GMRuntime.gml_pragma(["global", "init();"])\n'
            'GMRuntime.gml_pragma(["MarkTagAsUsed", "a", "b", "c"])\n'
            "GMRuntime.gml_show_debug_overlay(true)\n"
            "GMRuntime.gml_show_debug_overlay(true, false, 2, 0.5, true, -1)\n"
            "open = GMRuntime.gml_is_debug_overlay_open()\n"
            "mouse = GMRuntime.gml_is_mouse_over_debug_overlay()\n"
            "keyboard = GMRuntime.gml_is_keyboard_used_debug_overlay()\n"
            'GMRuntime.gml_debug_event("DumpMemory", true)\n'
            "GMRuntime.gml_scheduler_resolution_set(2)\n"
            "resolution = GMRuntime.gml_scheduler_resolution_get()\n"
            "GMRuntime.gml_os_powersave_enable(false)\n"
            "GMRuntime.gml_os_lock_orientation(true)",
        )

    def test_os_debug_gc_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "environment_get_variable.*expects 1.*got 0"):
            transpile_gml_code("environment_get_variable();", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "weak_ref_any_alive.*expects 1 to 3.*got 4"):
            transpile_gml_code("weak_ref_any_alive(items, 0, 1, true);", indent="")

    def test_platform_service_helpers_lower_to_runtime_and_builtins(self):
        self.assertEqual(
            transpile_gml_expression("steam_is_initialized()"),
            "GMRuntime.gml_steam_is_initialized()",
        )
        self.assertEqual(
            transpile_gml_expression("browser_width + browser_height"),
            'GMRuntime.gml_add(GMRuntime.gml_builtin_global("browser_width"), GMRuntime.gml_builtin_global("browser_height"))',
        )
        self.assertEqual(
            transpile_gml_expression("webgl_enabled"),
            'GMRuntime.gml_builtin_global("webgl_enabled")',
        )
        self.assertEqual(
            transpile_gml_code(
                'browser_input_capture(true);'
                'domain = url_get_domain();'
                'url_open_ext("https://example.com", "_blank");'
                'signed_in = xboxlive_user_is_signed_in();'
                'wallpaper_set_subscriptions(subscriptions);'
                'cloud_id = cloud_synchronise();'
                'steam_set_achievement("ACH_WIN");'
                'iap_activate();'
                'xboxlive_achievements_set_progress(user_id, "Game_Completed", 100);'
                'xboxlive_matchmaking_create();',
                indent="",
            ),
            "GMRuntime.gml_browser_input_capture(true)\n"
            "domain = GMRuntime.gml_url_get_domain()\n"
            'GMRuntime.gml_url_open_ext("https://example.com", "_blank")\n'
            "signed_in = GMRuntime.gml_xboxlive_user_is_signed_in()\n"
            "GMRuntime.gml_wallpaper_set_subscriptions(subscriptions)\n"
            "cloud_id = GMRuntime.gml_cloud_synchronise()\n"
            'GMRuntime.gml_platform_service_call("steam", "steam_set_achievement", ["ACH_WIN"])\n'
            'GMRuntime.gml_platform_service_call("iap", "iap_activate", [])\n'
            'GMRuntime.gml_platform_service_call("xboxlive", "xboxlive_achievements_set_progress", [user_id, "Game_Completed", 100])\n'
            'GMRuntime.gml_platform_service_call("xboxlive", "xboxlive_matchmaking_create", [])',
        )

    def test_admob_extension_calls_lower_to_quiet_runtime_bridge(self):
        self.assertEqual(
            transpile_gml_code(
                "if AdMob_Interstitial_IsLoaded() {"
                "AdMob_Interstitial_Show();"
                "} "
                "AdMob_Banner_Hide();",
                indent="",
            ),
            'if GMRuntime.gml_bool(GMRuntime.gml_admob_extension_call("AdMob_Interstitial_IsLoaded", [])):\n'
            '\tGMRuntime.gml_admob_extension_call("AdMob_Interstitial_Show", [])\n'
            'GMRuntime.gml_admob_extension_call("AdMob_Banner_Hide", [])',
        )

    def test_platform_service_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "url_open.*expects 1.*got 0.*#569"):
            transpile_gml_code("url_open();", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "browser_input_capture.*expects 1.*got 0.*#569"):
            transpile_gml_code("browser_input_capture();", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "steam_set_achievement.*expects 1.*got 0.*#570"):
            transpile_gml_code("steam_set_achievement();", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "xboxlive_achievements_set_progress.*expects 3.*got 2.*#570"):
            transpile_gml_code("xboxlive_achievements_set_progress(user_id, 'Achievement');", indent="")

    def test_os_device_media_unsupported_apis_get_diagnostics(self):
        self.assertRegex(
            transpile_gml_code("device_get_tilt_y();", indent=""),
            r'^GMRuntime\.gml_unsupported_call\("device_get_tilt_y", "[^"]*unsupported[^"]*#569[^"]*sensor[^"]*", \[\]\)$',
        )

    def test_extension_function_mappings_emit_configured_hook_calls(self):
        self.assertEqual(
            transpile_gml_code(
                'ads_show_rewarded("zone_1");'
                'analytics_track("level_start", score + 1);'
                'local_project_call(score);',
                indent="",
                extension_functions={
                    "ads_show_rewarded": "AdSDK",
                    "analytics_track": "AnalyticsSDK",
                },
                extension_function_mappings={
                    "ads_show_rewarded": {
                        "target": "AdBridge.show_rewarded",
                        "min_args": 1,
                        "max_args": 1,
                    },
                    "analytics_track": {
                        "target": "AnalyticsBridge.track",
                        "min_args": 2,
                        "max_args": 2,
                    },
                },
            ),
            'AdBridge.show_rewarded("zone_1")\n'
            'AnalyticsBridge.track("level_start", GMRuntime.gml_add(score, 1))\n'
            'GMRuntime.gml_call_named("local_project_call", [score], self, other)',
        )
        self.assertEqual(
            transpile_gml_expression(
                'analytics_event("start")',
                extension_function_mappings={"analytics_event": "AnalyticsBridge.event"},
            ),
            'AnalyticsBridge.event("start")',
        )

    def test_unmapped_extension_function_reports_actionable_diagnostic(self):
        # Without a mapping the call fails on its own at run time with the
        # actionable message; the rest of the script still converts.
        self.assertRegex(
            transpile_gml_code(
                'ads_show_rewarded("zone_1");\nscore = 1;',
                indent="",
                extension_functions={"ads_show_rewarded": "AdSDK"},
            ),
            r'^GMRuntime\.gml_unsupported_call\("ads_show_rewarded", '
            r'"[^"]*AdSDK[^"]*gm2godot_extension_functions\.json[^"]*", \["zone_1"\]\)\n'
            r"score = 1$",
        )

    def test_extension_mapping_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "ads_show_rewarded.*expects 1.*got 0"):
            transpile_gml_expression(
                "ads_show_rewarded()",
                extension_function_mappings={
                    "ads_show_rewarded": {
                        "target": "AdBridge.show_rewarded",
                        "min_args": 1,
                        "max_args": 1,
                    }
                },
            )

    def test_loads_extension_function_mapping_file(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as mapping_file:
            json.dump(
                {
                    "functions": {
                        "ads_show_rewarded": {
                            "target": "AdBridge.show_rewarded",
                            "min_args": 1,
                            "max_args": 1,
                        }
                    }
                },
                mapping_file,
            )
            mapping_path = mapping_file.name
        try:
            mappings = load_gml_extension_function_mappings(mapping_path)
        finally:
            os.unlink(mapping_path)

        mapping = mappings["ads_show_rewarded"]
        self.assertEqual(mapping.target, "AdBridge.show_rewarded")
        self.assertEqual(mapping.min_args, 1)
        self.assertEqual(mapping.max_args, 1)

    def test_math_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "clamp.*expects 3.*got 2"):
            transpile_gml_code("clamp(1, 2);", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "choose.*at least 1.*got 0"):
            transpile_gml_code("choose();", indent="")

    def test_room_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "room_goto.*expects 1.*got 0"):
            transpile_gml_code("room_goto();", indent="", asset_names={"r_next"})

    def test_transpiles_keyboard_check_and_position_movement(self):
        source = """
        if keyboard_check(vk_left) {
            x -= 10;
        }
        if keyboard_check(vk_right) {
            x += 10;
        }
        if keyboard_check(vk_up) {
            y -= 10;
        }
        if keyboard_check(vk_down) {
            y += 10;
        }
        """

        self.assertEqual(
            transpile_gml_code(source, indent=""),
            "if GMRuntime.gml_keyboard_check(37):\n"
            "\tposition.x = GMRuntime.gml_sub(position.x, 10)\n"
            "if GMRuntime.gml_keyboard_check(39):\n"
            "\tposition.x = GMRuntime.gml_add(position.x, 10)\n"
            "if GMRuntime.gml_keyboard_check(38):\n"
            "\tposition.y = GMRuntime.gml_sub(position.y, 10)\n"
            "if GMRuntime.gml_keyboard_check(40):\n"
            "\tposition.y = GMRuntime.gml_add(position.y, 10)",
        )

    def test_collects_assigned_instance_variables(self):
        instance_variables: set[str] = set()

        self.assertEqual(
            transpile_gml_code(
                "superSpeed = 0\nvar localSpeed = 1; localSpeed += 1; x += localSpeed;",
                indent="",
                instance_variables=instance_variables,
            ),
            "superSpeed = 0\n"
            "var localSpeed = 1\n"
            "localSpeed = GMRuntime.gml_add(localSpeed, 1)\n"
            "position.x = GMRuntime.gml_add(position.x, localSpeed)",
        )
        self.assertEqual(instance_variables, {"superSpeed"})

    def test_collects_indexed_instance_array_assignments(self):
        instance_variables: set[str] = set()

        self.assertEqual(
            transpile_gml_code(
                'strings[48] = "hello"; var local = []; local[0] = "skip";',
                indent="",
                instance_variables=instance_variables,
            ),
            'GMRuntime.gml_array_set(strings, 48, "hello")\n'
            "var local = []\n"
            'GMRuntime.gml_array_set(local, 0, "skip")',
        )
        self.assertEqual(instance_variables, {"strings"})

    def test_sprite_builtins_are_not_collected_instance_variables(self):
        instance_variables: set[str] = set()

        self.assertEqual(
            transpile_gml_code(
                "sprite_index = s_enemy; image_index = 2; image_index += 1; "
                "image_xscale = 2; image_angle += 45; image_alpha = 0.5;",
                indent="",
                instance_variables=instance_variables,
            ),
            "sprite_index = s_enemy\n"
            "image_index = 2\n"
            "image_index = GMRuntime.gml_add(image_index, 1)\n"
            "image_xscale = 2\n"
            "image_angle = GMRuntime.gml_add(image_angle, 45)\n"
            "image_alpha = 0.5",
        )
        self.assertEqual(instance_variables, set())

    def test_mask_index_is_a_builtin_instance_variable(self):
        instance_variables: set[str] = set()

        self.assertEqual(
            transpile_gml_code(
                "mask_index = s_hitbox; if (mask_index == -1) mask_index = sprite_index;",
                indent="",
                asset_names={"s_hitbox"},
                instance_variables=instance_variables,
            ),
            'mask_index = GMRuntime.gml_asset_get_index("s_hitbox")\n'
            "if GMRuntime.gml_eq(mask_index, -1):\n"
            "\tmask_index = sprite_index",
        )
        self.assertEqual(instance_variables, set())
        self.assertEqual(
            transpile_gml_code("other.mask_index = s_hitbox", indent="", asset_names={"s_hitbox"}),
            'GMRuntime.gml_selector_set(other, "mask_index", GMRuntime.gml_asset_get_index("s_hitbox"))',
        )

    def test_sprite_get_name_reads_the_asset_registry(self):
        self.assertEqual(
            transpile_gml_expression("sprite_get_name(sprite_index)"),
            "GMRuntime.gml_sprite_get_name(sprite_index)",
        )

    def test_path_builtins_are_predeclared_instance_state(self):
        instance_variables: set[str] = set()

        self.assertEqual(
            transpile_gml_code(
                "path_index = path_main; path_scale *= 2; path_speed = speed;",
                indent="",
                instance_variables=instance_variables,
            ),
            "path_index = path_main\n"
            "path_scale = GMRuntime.gml_mul(path_scale, 2)\n"
            "path_speed = speed",
        )
        self.assertEqual(
            transpile_gml_code(
                "path_orientation = 90; path_endaction = path_action_reverse; last = path_positionprevious;",
                indent="",
                instance_variables=instance_variables,
            ),
            "path_orientation = 90\n"
            "path_endaction = 3\n"
            "last = path_positionprevious",
        )
        self.assertEqual(instance_variables, {"last"})

    def test_transpiles_current_simple_topdown_step_body(self):
        source = """
        if keyboard_check(vk_shift) {
            faster = true
        } else {
            faster = false
        }

        if faster = true {
            superSpeed = 20
        }

        if keyboard_check(vk_left) {
            x -= superSpeed;
        }
        if keyboard_check(vk_right) {
            x += superSpeed;
        }
        if keyboard_check(vk_up) {
            y -= superSpeed;
        }
        if keyboard_check(vk_down) {
            y += superSpeed;
        }

        superSpeed = 10;
        """

        self.assertEqual(
            transpile_gml_code(source, indent=""),
            "if GMRuntime.gml_keyboard_check(16):\n"
            "\tfaster = true\n"
            "else:\n"
            "\tfaster = false\n"
            "if GMRuntime.gml_eq(faster, true):\n"
            "\tsuperSpeed = 20\n"
            "if GMRuntime.gml_keyboard_check(37):\n"
            "\tposition.x = GMRuntime.gml_sub(position.x, superSpeed)\n"
            "if GMRuntime.gml_keyboard_check(39):\n"
            "\tposition.x = GMRuntime.gml_add(position.x, superSpeed)\n"
            "if GMRuntime.gml_keyboard_check(38):\n"
            "\tposition.y = GMRuntime.gml_sub(position.y, superSpeed)\n"
            "if GMRuntime.gml_keyboard_check(40):\n"
            "\tposition.y = GMRuntime.gml_add(position.y, superSpeed)\n"
            "superSpeed = 10",
        )


if __name__ == "__main__":
    unittest.main()
