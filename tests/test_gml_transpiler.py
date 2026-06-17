# pyright: reportPrivateUsage=false
import json
import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_transpiler import (
    _ArrayLiteral,
    _BUILTIN_VARIABLE_REGISTRY,
    GMLTranspileError,
    _ExpressionParser,
    _NumberLiteral,
    _StringLiteral,
    _StructLiteral,
    _expression_tokens,
    _tokenize,
    load_gml_extension_function_mappings,
    preprocess_gml_source,
    transpile_gml_code,
    transpile_gml_expression,
)


class TestGMLExpressionTranspiler(unittest.TestCase):
    def test_builtin_variable_registry_captures_scope_defaults_and_mutability(self):
        self.assertEqual(_BUILTIN_VARIABLE_REGISTRY["x"].scope, "instance")
        self.assertEqual(_BUILTIN_VARIABLE_REGISTRY["x"].default, "0")
        self.assertTrue(_BUILTIN_VARIABLE_REGISTRY["x"].mutable)
        self.assertFalse(_BUILTIN_VARIABLE_REGISTRY["x"].is_array)
        self.assertEqual(_BUILTIN_VARIABLE_REGISTRY["x"].subsystem, "transform")
        self.assertEqual(_BUILTIN_VARIABLE_REGISTRY["room"].scope, "global")
        self.assertEqual(_BUILTIN_VARIABLE_REGISTRY["room"].default, "undefined")
        self.assertFalse(_BUILTIN_VARIABLE_REGISTRY["room"].mutable)
        self.assertEqual(_BUILTIN_VARIABLE_REGISTRY["view_xview"].scope, "global")
        self.assertTrue(_BUILTIN_VARIABLE_REGISTRY["view_xview"].mutable)
        self.assertTrue(_BUILTIN_VARIABLE_REGISTRY["view_xview"].is_array)
        self.assertEqual(_BUILTIN_VARIABLE_REGISTRY["view_xview"].subsystem, "view")
        self.assertEqual(_BUILTIN_VARIABLE_REGISTRY["argument"].default, "[]")
        self.assertEqual(_BUILTIN_VARIABLE_REGISTRY["async_load"].subsystem, "async_event")

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
        integer_literal = _ExpressionParser(_expression_tokens("42")).parse()
        decimal_literal = _ExpressionParser(_expression_tokens("3.5")).parse()

        self.assertIsInstance(integer_literal, _NumberLiteral)
        self.assertIsInstance(decimal_literal, _NumberLiteral)
        assert isinstance(integer_literal, _NumberLiteral)
        assert isinstance(decimal_literal, _NumberLiteral)
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

    def test_preserves_string_literal_metadata(self):
        literal = _ExpressionParser(_expression_tokens('"hello"')).parse()

        self.assertIsInstance(literal, _StringLiteral)
        assert isinstance(literal, _StringLiteral)
        self.assertEqual(literal.value, '"hello"')

    def test_rejects_unterminated_string_literals(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_expression('"unterminated')

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
        self.assertEqual(
            transpile_gml_expression('string_join(arr, ",")'),
            'GMRuntime.gml_string_join(arr, ",")',
        )

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
        self.assertEqual(transpile_gml_expression("method_call(callback)"), "GMRuntime.gml_method_call(callback)")
        self.assertEqual(
            transpile_gml_expression("method_call(callback, [1, 2, 3], 1, 2)"),
            "GMRuntime.gml_method_call(callback, [1, 2, 3], 1, 2)",
        )
        self.assertEqual(
            transpile_gml_expression("method_call(callback, [1, 2, 3], -1, -2)"),
            "GMRuntime.gml_method_call(callback, [1, 2, 3], -1, -2)",
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
            'colour = GMRuntime.gml_selector_get(RAINBOW, "GREEN")',
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
            'GMRuntime.gml_array_set(items, GMRuntime.gml_selector_get(RAINBOW, "GREEN"), 2)',
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
            "project_choose(GMRuntime.gml_array_get(items, GMRuntime.gml_add(index, 1)), other.value)",
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
        literal = _ExpressionParser(_expression_tokens("[1, [2]]")).parse()

        self.assertIsInstance(literal, _ArrayLiteral)
        assert isinstance(literal, _ArrayLiteral)
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

    def test_preserves_struct_literal_metadata(self):
        literal = _ExpressionParser(_expression_tokens("{a: 1, child: {b: 2}, shorthand}")).parse()

        self.assertIsInstance(literal, _StructLiteral)
        assert isinstance(literal, _StructLiteral)
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
            'GMRuntime.gml_struct({"apply": func(a = null, b = null): '
            "if a == null: a = GMRuntime.gml_undefined(); "
            "if b == null: b = GMRuntime.gml_undefined(); "
            "return GMRuntime.gml_add(a, b)})",
        )
        self.assertEqual(
            transpile_gml_expression('string({toString: function() { return "ok"; }})'),
            'GMRuntime.gml_string(GMRuntime.gml_struct({"toString": func(): return "ok"}))',
        )

    def test_function_literals_preserve_optional_defaults(self):
        self.assertEqual(
            transpile_gml_expression("function(a, b = 90) { return b; }"),
            "GMRuntime.gml_method(self, func(a = null, b = null): "
            "if a == null: a = GMRuntime.gml_undefined(); "
            "if b == null or GMRuntime.is_undefined(b): b = 90; "
            "return b)",
        )
        self.assertEqual(
            transpile_gml_expression("function(a, b = a + 1) { return b; }"),
            "GMRuntime.gml_method(self, func(a = null, b = null): "
            "if a == null: a = GMRuntime.gml_undefined(); "
            "if b == null or GMRuntime.is_undefined(b): b = GMRuntime.gml_add(a, 1); "
            "return b)",
        )
        self.assertEqual(
            transpile_gml_expression("[function() { return 1; }]"),
            "[GMRuntime.gml_method(self, func(): return 1)]",
        )

    def test_omitted_call_arguments_emit_gml_undefined(self):
        self.assertEqual(
            transpile_gml_expression("move(4,)"),
            "move(4, GMRuntime.gml_undefined())",
        )
        self.assertEqual(
            transpile_gml_expression("my_func(0,,,1)"),
            "my_func(0, GMRuntime.gml_undefined(), GMRuntime.gml_undefined(), 1)",
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
        self.assertEqual(transpile_gml_expression("other.value"), "other.value")

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
            "var _gml_grid_x_0 = next_x()\n"
            "var _gml_grid_y_1 = next_y()\n"
            "GMRuntime.gml_ds_grid_set(grid, _gml_grid_x_0, _gml_grid_y_1, "
            "GMRuntime.gml_add(GMRuntime.gml_ds_grid_get(grid, _gml_grid_x_0, _gml_grid_y_1), value))",
        )
        self.assertEqual(
            transpile_gml_code("grid[# next_x(), next_y()]++;", indent=""),
            "var _gml_grid_x_0 = next_x()\n"
            "var _gml_grid_y_1 = next_y()\n"
            "GMRuntime.gml_ds_grid_set(grid, _gml_grid_x_0, _gml_grid_y_1, "
            "GMRuntime.gml_add(GMRuntime.gml_ds_grid_get(grid, _gml_grid_x_0, _gml_grid_y_1), 1))",
        )

    def test_nested_mixed_accessor_mutation_caches_grid_cell_container(self):
        self.assertEqual(
            transpile_gml_code("result = grid[# next_x(), next_y()][? next_key()] += value;", indent=""),
            "var _gml_map_target_0 = GMRuntime.gml_ds_grid_get(grid, next_x(), next_y())\n"
            "var _gml_map_key_1 = next_key()\n"
            "var _gml_assignment_value_2 = GMRuntime.gml_add("
            "GMRuntime.gml_ds_map_find_value(_gml_map_target_0, _gml_map_key_1), value)\n"
            "GMRuntime.gml_ds_map_set(_gml_map_target_0, _gml_map_key_1, _gml_assignment_value_2)\n"
            "result = _gml_assignment_value_2",
        )

    def test_any_values_pass_through_calls_without_lossy_conversion(self):
        self.assertEqual(
            transpile_gml_expression('callback([1, "x"], {value: undefined})'),
            'callback([1, "x"], GMRuntime.gml_struct({"value": GMRuntime.gml_undefined()}))',
        )
        self.assertEqual(
            transpile_gml_expression(
                'callback(ds_map_find_value(inventory, "food"), variable_struct_get(mystruct, "item"))'
            ),
            'callback(GMRuntime.gml_ds_map_find_value(inventory, "food"), '
            'GMRuntime.gml_variable_struct_get(mystruct, "item"))',
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
            "GMRuntime.gml_struct_foreach(mystruct, callback)",
        )
        self.assertEqual(
            transpile_gml_expression("struct_foreach(mystruct, method(self, callback))"),
            "GMRuntime.gml_struct_foreach(mystruct, GMRuntime.gml_method(self, callback))",
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
            "GMRuntime.gml_new(Point, [4, 5])",
        )
        self.assertEqual(
            transpile_gml_expression("new factory.Point(name, )"),
            'GMRuntime.gml_new(GMRuntime.gml_selector_get(factory, "Point"), '
            "[name, GMRuntime.gml_undefined()])",
        )

    def test_transpiles_constructor_qualified_function_literals(self):
        self.assertEqual(
            transpile_gml_expression(
                "function Point(_x, _y) constructor { x = _x; y = _y; }",
            ),
            "GMRuntime.gml_constructor(self, "
            "func Point(_gml_constructor_self = null, _x = null, _y = null): "
            "if _x == null: _x = GMRuntime.gml_undefined(); "
            "if _y == null: _y = GMRuntime.gml_undefined(); "
            'GMRuntime.gml_variable_instance_set(_gml_constructor_self, "x", _x); '
            'GMRuntime.gml_variable_instance_set(_gml_constructor_self, "y", _y))',
        )

    def test_transpiles_function_static_variables(self):
        output = transpile_gml_expression(
            "function counter() { show_debug_message(n); static n = 0; n += 1; return n; }"
        )

        self.assertIn("GMRuntime.gml_static_bind(func counter():", output)
        self.assertIn('GMRuntime.gml_static_scope("gml_static:counter:', output)
        self.assertIn("GMRuntime.gml_static_initialize(_gml_static_scope_", output)
        self.assertIn('[["n", func(): return 0]]', output)
        self.assertIn(
            "print(GMRuntime.gml_struct_get(_gml_static_scope_",
            output,
        )
        self.assertIn("GMRuntime.gml_struct_set(_gml_static_scope_", output)
        self.assertLess(
            output.index("GMRuntime.gml_static_initialize"),
            output.index("print"),
        )

    def test_rejects_static_declarations_outside_functions(self):
        with self.assertRaisesRegex(GMLTranspileError, "static declarations"):
            transpile_gml_code("static n = 0;", indent="")

    def test_transpiles_constructor_static_method_variables(self):
        output = transpile_gml_expression(
            "function Point() constructor { static make = function() { return 1; }; return make; }"
        )

        self.assertIn("GMRuntime.gml_constructor(self, GMRuntime.gml_static_bind(func Point", output)
        self.assertIn('"Point"', output)
        self.assertIn(
            '["make", func(): return GMRuntime.gml_method(_gml_constructor_self, func(): return 1)]',
            output,
        )
        self.assertIn("return GMRuntime.gml_struct_get(_gml_static_scope_", output)

    def test_transpiles_constructor_inheritance_before_child_statics(self):
        output = transpile_gml_expression(
            "function Child(x) : Parent(x) constructor { static c = 1; return c; }"
        )

        self.assertIn("GMRuntime.gml_constructor_inherit(_gml_constructor_self, Parent, [x])", output)
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
            "var _gml_alarm_index_0 = next_alarm()\n"
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
        )

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_expression(source), expected)
        self.assertEqual(transpile_gml_code("var room = 1; value = room", indent=""), "var room = 1\nvalue = room")

    def test_rejects_writes_to_read_only_builtin_variables(self):
        for source in (
            "bbox_left = 0",
            "image_number += 1",
            "room++",
            "view_current[0] = 1",
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
        tokens = _tokenize("if ready begin score = 1; end")
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
            "GMRuntime.gml_method(self, func(): return)",
        )
        self.assertEqual(
            transpile_gml_expression("function() { return score + bonus; }"),
            "GMRuntime.gml_method(self, func(): return GMRuntime.gml_add(score, bonus))",
        )

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
            "GMRuntime.gml_method(self, func(): "
            "if GMRuntime.gml_bool(done):; \treturn; return score)",
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
            ('throw "bad";', 'return GMRuntime.gml_throw("bad")'),
            ("throw 404;", "return GMRuntime.gml_throw(404)"),
            (
                "throw {message: reason, code: 404};",
                'return GMRuntime.gml_throw(GMRuntime.gml_struct({"message": reason, "code": 404}))',
            ),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transpile_gml_code(source, indent=""), expected)

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
        self.assertIn('return _gml_try_control_0["value"]', output)

    def test_transpiles_try_finally_blocks(self):
        output = transpile_gml_code("try { score = 1; } finally { cleaned = true; }", indent="")

        self.assertIn("var _gml_try_control_0 = GMRuntime.gml_undefined()", output)
        self.assertIn("while true:\n\tscore = 1\n\tbreak", output)
        self.assertIn("cleaned = true", output)
        self.assertIn('if not GMRuntime.is_undefined(_gml_try_control_0) and _gml_try_control_0["kind"] == "return":', output)
        self.assertIn('return _gml_try_control_0["value"]', output)
        self.assertIn('if not GMRuntime.is_undefined(_gml_try_control_0) and _gml_try_control_0["kind"] == "throw":', output)

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
        self.assertIn("cleaned = true", return_output)
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
            "GMRuntime.gml_array_delete(items, 2)",
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
            "var total = 0\n"
            "for _gml_with_target_0 in GMRuntime.gml_with_targets(enemy, self, other):\n"
            '\ttotal = GMRuntime.gml_add(total, GMRuntime.gml_variable_instance_get(_gml_with_target_0, "hp"))\n'
            "\tvar seen = total\n"
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
            "mystruct = make_struct()\n"
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

    def test_while_condition_stays_in_loop_header(self):
        self.assertEqual(
            transpile_gml_code(
                "while next_value() begin count += 1; threshold -= count; end",
                indent="",
            ),
            "while GMRuntime.gml_bool(next_value()):\n"
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
            "for _gml_repeat_index in range(GMRuntime.gml_repeat_count(3)):\n"
            "\tscore = GMRuntime.gml_add(score, 1)",
        )
        self.assertEqual(
            transpile_gml_code("repeat (count + 1) score += 1;", indent=""),
            "for _gml_repeat_index in range(GMRuntime.gml_repeat_count(GMRuntime.gml_add(count, 1))):\n"
            "\tscore = GMRuntime.gml_add(score, 1)",
        )

    def test_repeat_count_expression_uses_runtime_rounding_once(self):
        self.assertEqual(
            transpile_gml_code("repeat (next_count()) score += 1;", indent=""),
            "for _gml_repeat_index in range(GMRuntime.gml_repeat_count(next_count())):\n"
            "\tscore = GMRuntime.gml_add(score, 1)",
        )

    def test_transpiles_break_and_continue_inside_repeat(self):
        self.assertEqual(
            transpile_gml_code(
                "repeat (count) begin if should_skip begin continue; end if done begin break; end score += 1; end",
                indent="",
            ),
            "for _gml_repeat_index in range(GMRuntime.gml_repeat_count(count)):\n"
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
            "\ttick()",
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
            "var _gml_switch_value_0 = next_state()\n"
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
            'var _gml_switch_has_case_2 = GMRuntime.gml_eq(_gml_switch_value_0, KEY_LEFT) or GMRuntime.gml_eq(_gml_switch_value_0, GMRuntime.gml_ord("A"))\n'
            "while true:\n"
            "\tif not _gml_switch_matched_1 and GMRuntime.gml_eq(_gml_switch_value_0, KEY_LEFT):\n"
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
            "setup()\n"
            "while GMRuntime.gml_bool(should_run()):\n"
            "\tbody()\n"
            "\tadvance()",
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
            "\tvar x = 3\n"
            "\tx = GMRuntime.gml_undefined()\n"
            "if GMRuntime.gml_bool(retry):\n"
            "\tvar x = 4",
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
            "var _gml_array_index_0 = next_index()\n"
            "var _gml_assignment_value_1 = c\n"
            "b = _gml_assignment_value_1\n"
            "GMRuntime.gml_array_set(items, _gml_array_index_0, _gml_assignment_value_1)",
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
            transpile_gml_expression("instance_destroy()"),
            "GMRuntime.gml_instance_destroy(self)",
        )
        self.assertEqual(
            transpile_gml_code("with (o_enemy) hp = 0;", indent="", asset_names=asset_names),
            'for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_asset_get_index("o_enemy"), self, other):\n'
            '\tGMRuntime.gml_variable_instance_set(_gml_with_target_0, "hp", 0)',
        )

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
        self.assertEqual(
            transpile_gml_expression("path_get_length(path_patrol)", asset_names=asset_names),
            'GMRuntime.gml_path_get_length(GMRuntime.gml_asset_get_index("path_patrol"))',
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
                "window_set_rectangle(0, 0, 320, 240);"
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
        with self.assertRaisesRegex(GMLTranspileError, "gif_open.*unsupported.*#493.*GIF"):
            transpile_gml_code("gif_open(320, 180);", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "gif_add_surface.*unsupported.*#493.*GIF"):
            transpile_gml_code("gif_add_surface(gif_id, surf, 6);", indent="")
        with self.assertRaisesRegex(GMLTranspileError, "gif_save_buffer.*unsupported.*#493.*GIF"):
            transpile_gml_code("gif_save_buffer(gif_id);", indent="")

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
            "var _gml_array_index_0 = next_index()\n"
            "GMRuntime.gml_array_set(items, _gml_array_index_0, "
            "GMRuntime.gml_add(GMRuntime.gml_array_get(items, _gml_array_index_0), value))",
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
            'var _gml_selector_target_0 = get_struct()\n'
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
            "mutate_struct(mystruct)\n"
            'value = GMRuntime.gml_selector_get(mystruct, "a")',
        )

    def test_function_argument_reassignment_does_not_mutate_caller_value(self):
        self.assertEqual(
            transpile_gml_code(
                "var try_to_modify_value = function(argument0) { argument0 = 2; }; "
                "value = 1; try_to_modify_value(value); result = value;",
                indent="",
            ),
            "var try_to_modify_value = GMRuntime.gml_method(self, func(argument0 = null): "
            "if argument0 == null: argument0 = GMRuntime.gml_undefined(); argument0 = 2)\n"
            "value = 1\n"
            "try_to_modify_value(value)\n"
            "result = value",
        )

    def test_array_function_arguments_pass_reference_without_clone(self):
        self.assertEqual(
            transpile_gml_code(
                "var try_to_modify_array = function(argument0) { array_push(argument0, 2); }; "
                "items = [1]; try_to_modify_array(items); value = items[1];",
                indent="",
            ),
            "var try_to_modify_array = GMRuntime.gml_method(self, func(argument0 = null): "
            "if argument0 == null: argument0 = GMRuntime.gml_undefined(); "
            "GMRuntime.gml_array_push(argument0, [2]))\n"
            "items = [1]\n"
            "try_to_modify_array(items)\n"
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
            transpile_gml_code("array_delete(arr, 0);", indent=""),
            "GMRuntime.gml_array_delete(arr, 0)",
        )

    def test_transpiles_array_sort(self):
        self.assertEqual(
            transpile_gml_code("array_sort(arr);", indent=""),
            "GMRuntime.gml_array_sort(arr)",
        )

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

    def test_transpiles_array_find_index(self):
        self.assertEqual(
            transpile_gml_code("idx = array_find_index(arr, 42);", indent=""),
            "idx = GMRuntime.gml_array_find_index(arr, 42)",
        )

    def test_transpiles_array_map(self):
        self.assertEqual(
            transpile_gml_code(
                "result = array_map(arr, double);", indent=""
            ),
            "result = GMRuntime.gml_array_map(arr, double)",
        )

    def test_transpiles_array_filter(self):
        self.assertEqual(
            transpile_gml_code(
                "result = array_filter(arr, is_odd);", indent=""
            ),
            "result = GMRuntime.gml_array_filter(arr, is_odd)",
        )

    def test_transpiles_array_reduce(self):
        self.assertEqual(
            transpile_gml_code(
                "result = array_reduce(arr, add, 0);", indent=""
            ),
            "result = GMRuntime.gml_array_reduce(arr, add, 0)",
        )
        self.assertEqual(
            transpile_gml_code(
                "result = array_reduce(arr, add);", indent=""
            ),
            "result = GMRuntime.gml_array_reduce(arr, add)",
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
            "foo(_gm2gd_mutation_value_0)",
        )
        self.assertEqual(
            transpile_gml_code("foo(--i);", indent=""),
            "var _gm2gd_mutation_value_0 = GMRuntime.gml_sub(i, 1)\n"
            "i = _gm2gd_mutation_value_0\n"
            "foo(_gm2gd_mutation_value_0)",
        )
        self.assertEqual(
            transpile_gml_code("foo(items[i]++);", indent=""),
            "var _gm2gd_mutation_value_0 = GMRuntime.gml_array_get(items, i)\n"
            "GMRuntime.gml_array_set(items, i, GMRuntime.gml_add(_gm2gd_mutation_value_0, 1))\n"
            "foo(_gm2gd_mutation_value_0)",
        )
        self.assertEqual(
            transpile_gml_code("foo(alarm[i]++);", indent=""),
            "var _gm2gd_mutation_value_0 = GMRuntime.gml_alarm_get(self, i)\n"
            "GMRuntime.gml_alarm_set(self, i, GMRuntime.gml_add(_gm2gd_mutation_value_0, 1))\n"
            "foo(_gm2gd_mutation_value_0)",
        )
        self.assertEqual(
            transpile_gml_code("foo(items[i++]);", indent=""),
            "var _gm2gd_mutation_value_0 = i\n"
            "i = GMRuntime.gml_add(_gm2gd_mutation_value_0, 1)\n"
            "foo(GMRuntime.gml_array_get(items, _gm2gd_mutation_value_0))",
        )
        self.assertEqual(
            transpile_gml_code("foo(get_struct().a++);", indent=""),
            "var _gml_selector_target_0 = get_struct()\n"
            "var _gm2gd_mutation_value_1 = GMRuntime.gml_selector_get(_gml_selector_target_0, \"a\")\n"
            "GMRuntime.gml_selector_set(_gml_selector_target_0, \"a\", "
            "GMRuntime.gml_add(_gm2gd_mutation_value_1, 1))\n"
            "foo(_gm2gd_mutation_value_1)",
        )

        for source in ("foo(1++);", "foo(++1);", "foo((1)++);"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(GMLTranspileError, "Increment expression target must be assignable"):
                    transpile_gml_code(source, indent="")

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
            "var _gml_array_index_0 = next_index()\n"
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
            "print(score if not GMRuntime.gml_is_nullish(score) else 0)",
        )

    def test_local_vars_shadow_instance_position_builtins(self):
        self.assertEqual(
            transpile_gml_code("var x = 1, y = x + 2; x += y;", indent=""),
            "var x = 1\nvar y = GMRuntime.gml_add(x, 2)\nx = GMRuntime.gml_add(x, y)",
        )
        self.assertEqual(
            transpile_gml_code("var x = 1; self.x += x;", indent=""),
            "var x = 1\nself.x = GMRuntime.gml_add(self.x, x)",
        )

    def test_transpiles_if_blocks(self):
        self.assertEqual(
            transpile_gml_code("if score > 0 { score -= 1; } else { score = 0; }", indent=""),
            "if GMRuntime.gml_gt(score, 0):\n\tscore = GMRuntime.gml_sub(score, 1)\nelse:\n\tscore = 0",
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
            "if GMRuntime.gml_keyboard_check(KEY_SHIFT):\n\tfaster = true",
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
                "gamepad_set_vibration(0, 1, 0.5);",
                indent="",
            ),
            "pressed = GMRuntime.gml_keyboard_check_pressed(KEY_SPACE)\n"
            "released = GMRuntime.gml_keyboard_check_released(KEY_ESCAPE)\n"
            "GMRuntime.gml_keyboard_key_press(KEY_LEFT)\n"
            "GMRuntime.gml_keyboard_key_release(KEY_LEFT)\n"
            "GMRuntime.gml_keyboard_clear(0)\n"
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
            "GMRuntime.gml_gamepad_set_vibration(0, 1, 0.5)",
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
                "room_goto_next(); room_goto_previous(); room_restart(); game_restart(); game_end();",
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
            "GMRuntime.gml_game_restart()\n"
            "GMRuntime.gml_game_end()",
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
        with self.assertRaisesRegex(GMLTranspileError, "sequence_track_new.*unsupported.*#567"):
            transpile_gml_code("sequence_track_new(seqtracktype_graphic);", indent="")

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
            "GMRuntime.gml_draw_set_blend_mode(2)\n"
            "GMRuntime.gml_gpu_set_texfilter(true)\n"
            "GMRuntime.gml_texture_set_repeat(false)\n"
            "GMRuntime.gml_gpu_set_colorwriteenable(true, false, true, true)\n"
            "GMRuntime.gml_gpu_set_alphatestref(128)\n"
            "tex = GMRuntime.gml_sprite_get_texture(GMRuntime.gml_asset_get_index(\"spr_player\"), 0)\n"
            "uvs = GMRuntime.gml_sprite_get_uvs(GMRuntime.gml_asset_get_index(\"spr_player\"), 0)\n"
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

    def test_gpu_helper_arity_errors_are_deterministic(self):
        with self.assertRaisesRegex(GMLTranspileError, "gpu_set_colorwriteenable.*expects 4.*got 3"):
            transpile_gml_code("gpu_set_colorwriteenable(true, true, true);", indent="")
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

    def test_os_debug_gc_helpers_lower_to_runtime_and_builtins(self):
        self.assertEqual(
            transpile_gml_expression("os_type == os_macosx"),
            'GMRuntime.gml_eq(GMRuntime.gml_builtin_global("os_type"), "macosx")',
        )
        self.assertEqual(
            transpile_gml_expression("fps_real"),
            'GMRuntime.gml_builtin_global("fps_real")',
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
        with self.assertRaisesRegex(GMLTranspileError, "device_get_tilt_y.*unsupported.*#569.*sensor"):
            transpile_gml_code("device_get_tilt_y();", indent="")

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
            "local_project_call(score)",
        )
        self.assertEqual(
            transpile_gml_expression(
                'analytics_event("start")',
                extension_function_mappings={"analytics_event": "AnalyticsBridge.event"},
            ),
            'AnalyticsBridge.event("start")',
        )

    def test_unmapped_extension_function_reports_actionable_diagnostic(self):
        with self.assertRaisesRegex(
            GMLTranspileError,
            "ads_show_rewarded.*AdSDK.*gm2godot_extension_functions.json",
        ):
            transpile_gml_expression(
                'ads_show_rewarded("zone_1")',
                extension_functions={"ads_show_rewarded": "AdSDK"},
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
            "if GMRuntime.gml_keyboard_check(KEY_LEFT):\n"
            "\tposition.x = GMRuntime.gml_sub(position.x, 10)\n"
            "if GMRuntime.gml_keyboard_check(KEY_RIGHT):\n"
            "\tposition.x = GMRuntime.gml_add(position.x, 10)\n"
            "if GMRuntime.gml_keyboard_check(KEY_UP):\n"
            "\tposition.y = GMRuntime.gml_sub(position.y, 10)\n"
            "if GMRuntime.gml_keyboard_check(KEY_DOWN):\n"
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
        self.assertEqual(instance_variables, set())

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
            "if GMRuntime.gml_keyboard_check(KEY_SHIFT):\n"
            "\tfaster = true\n"
            "else:\n"
            "\tfaster = false\n"
            "if GMRuntime.gml_eq(faster, true):\n"
            "\tsuperSpeed = 20\n"
            "if GMRuntime.gml_keyboard_check(KEY_LEFT):\n"
            "\tposition.x = GMRuntime.gml_sub(position.x, superSpeed)\n"
            "if GMRuntime.gml_keyboard_check(KEY_RIGHT):\n"
            "\tposition.x = GMRuntime.gml_add(position.x, superSpeed)\n"
            "if GMRuntime.gml_keyboard_check(KEY_UP):\n"
            "\tposition.y = GMRuntime.gml_sub(position.y, superSpeed)\n"
            "if GMRuntime.gml_keyboard_check(KEY_DOWN):\n"
            "\tposition.y = GMRuntime.gml_add(position.y, superSpeed)\n"
            "superSpeed = 10",
        )


if __name__ == "__main__":
    unittest.main()
