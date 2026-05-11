# pyright: reportPrivateUsage=false
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_transpiler import (
    _ArrayLiteral,
    GMLTranspileError,
    _ExpressionParser,
    _NumberLiteral,
    _StringLiteral,
    _StructLiteral,
    _expression_tokens,
    _tokenize,
    transpile_gml_code,
    transpile_gml_expression,
)


class TestGMLExpressionTranspiler(unittest.TestCase):
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

    def test_transpiles_nan_as_numeric_runtime_value(self):
        self.assertEqual(transpile_gml_expression("nan"), "NAN")
        self.assertEqual(
            transpile_gml_expression("NaN + 1"),
            "GMRuntime.gml_add(NAN, 1)",
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

    def test_nan_equality_uses_runtime_type_table(self):
        self.assertEqual(
            transpile_gml_expression("NaN == NaN"),
            "GMRuntime.gml_eq(NAN, NAN)",
        )
        self.assertEqual(
            transpile_gml_expression("NaN != NaN"),
            "GMRuntime.gml_ne(NAN, NAN)",
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
            "faster == true",
        )

    def test_transpiles_infinity_variable_functions(self):
        self.assertEqual(
            transpile_gml_expression("is_infinity(infinity)"),
            "GMRuntime.is_infinity(INF)",
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

    def test_transpiles_boolean_value_helpers(self):
        self.assertEqual(transpile_gml_expression("true"), "true")
        self.assertEqual(transpile_gml_expression("false"), "false")
        self.assertEqual(
            transpile_gml_expression("bool(0.5)"),
            "GMRuntime.gml_bool(0.5)",
        )
        self.assertEqual(
            transpile_gml_expression("is_bool(true)"),
            "GMRuntime.is_bool(true)",
        )

    def test_transpiles_real_number_conversion_helpers(self):
        self.assertEqual(transpile_gml_expression("real(score)"), "GMRuntime.gml_real(score)")
        self.assertEqual(transpile_gml_expression("int64(score)"), "GMRuntime.gml_int64(score)")
        self.assertEqual(transpile_gml_expression('int64("42")'), 'GMRuntime.gml_int64("42")')
        self.assertEqual(
            transpile_gml_expression("int64(pointer_null)"),
            "GMRuntime.gml_int64(GMRuntime.gml_pointer_null())",
        )
        self.assertEqual(transpile_gml_expression("is_real(score)"), "GMRuntime.is_real(score)")
        self.assertEqual(transpile_gml_expression("is_int32(score)"), "GMRuntime.is_int32(score)")
        self.assertEqual(
            transpile_gml_expression("is_numeric(int64(score))"),
            "GMRuntime.is_numeric(GMRuntime.gml_int64(score))",
        )
        self.assertEqual(
            transpile_gml_expression("is_int64(int64(score))"),
            "GMRuntime.is_int64(GMRuntime.gml_int64(score))",
        )
        self.assertEqual(
            transpile_gml_expression("int64(score) + int64(delta)"),
            "GMRuntime.gml_add(GMRuntime.gml_int64(score), GMRuntime.gml_int64(delta))",
        )

    def test_transpiles_string_value_helpers(self):
        self.assertEqual(transpile_gml_expression('string("abc")'), 'GMRuntime.gml_string("abc")')
        self.assertEqual(transpile_gml_expression('typeof("abc")'), 'GMRuntime.gml_typeof("abc")')
        self.assertEqual(transpile_gml_expression('is_string("abc")'), 'GMRuntime.is_string("abc")')

    def test_transpiles_primitive_type_predicates(self):
        self.assertEqual(transpile_gml_expression("is_array(items)"), "GMRuntime.is_array(items)")
        self.assertEqual(transpile_gml_expression("is_struct(mystruct)"), "GMRuntime.is_struct(mystruct)")
        self.assertEqual(transpile_gml_expression("is_method(callback)"), "GMRuntime.is_method(callback)")
        self.assertEqual(transpile_gml_expression("is_callable(callback)"), "GMRuntime.is_callable(callback)")

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
            transpile_gml_expression("choose(items[index + 1], other.value)"),
            "choose(GMRuntime.gml_array_get(items, GMRuntime.gml_add(index, 1)), other.value)",
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
            'GMRuntime.gml_struct({"apply": func(a, b): return GMRuntime.gml_add(a, b)})',
        )
        self.assertEqual(
            transpile_gml_expression('string({toString: function() { return "ok"; }})'),
            'GMRuntime.gml_string(GMRuntime.gml_struct({"toString": func(): return "ok"}))',
        )

    def test_rejects_invalid_struct_field_names(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_expression("{6fish: value}")

    def test_transpiles_struct_member_access_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("mystruct.a"),
            'GMRuntime.gml_struct_get(mystruct, "a")',
        )
        self.assertEqual(
            transpile_gml_expression("{a: 1}.a"),
            'GMRuntime.gml_struct_get(GMRuntime.gml_struct({"a": 1}), "a")',
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

    def test_transpiles_struct_name_enumeration_functions_through_runtime(self):
        self.assertEqual(
            transpile_gml_expression("struct_get_names(mystruct)"),
            "GMRuntime.gml_struct_get_names(mystruct)",
        )
        self.assertEqual(
            transpile_gml_expression("struct_names_count(mystruct)"),
            "GMRuntime.gml_struct_names_count(mystruct)",
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

    def test_transpiles_return_statements(self):
        self.assertEqual(transpile_gml_code("return;", indent=""), "return")
        self.assertEqual(
            transpile_gml_code("return score + bonus;", indent=""),
            "return GMRuntime.gml_add(score, bonus)",
        )
        self.assertEqual(
            transpile_gml_code("if ready begin return (score + 1); end", indent=""),
            "if GMRuntime.gml_bool(ready):\n\treturn (GMRuntime.gml_add(score, 1))",
        )

    def test_transpiles_exit_statements(self):
        self.assertEqual(transpile_gml_code("exit;", indent=""), "return")
        self.assertEqual(
            transpile_gml_code("if done begin exit; end score += 1;", indent=""),
            "if GMRuntime.gml_bool(done):\n\treturn\nscore = GMRuntime.gml_add(score, 1)",
        )

    def test_exit_aborts_later_generated_event_code(self):
        self.assertEqual(
            transpile_gml_code("score = 1; exit; score = 2;", indent=""),
            "score = 1\nreturn\nscore = 2",
        )

    def test_transpiles_delete_variable_operator(self):
        self.assertEqual(
            transpile_gml_code("delete mystruct;", indent=""),
            "mystruct = GMRuntime.gml_undefined()",
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
            transpile_gml_code("delete mystruct.child;", indent="")

    def test_transpiles_while_blocks(self):
        self.assertEqual(
            transpile_gml_code("while score > 0 begin score -= 1; end", indent=""),
            "while score > 0:\n\tscore = GMRuntime.gml_sub(score, 1)",
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
            "\tif score >= 3:\n"
            "\t\tbreak",
        )
        self.assertEqual(
            transpile_gml_code("do score += 1 until score >= 3;", indent=""),
            "while true:\n"
            "\tscore = GMRuntime.gml_add(score, 1)\n"
            "\tif score >= 3:\n"
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
            "\t\tif score >= 3:\n"
            "\t\t\tbreak\n"
            "\t\tcontinue\n"
            "\tscore = GMRuntime.gml_add(score, 1)\n"
            "\tif score >= 3:\n"
            "\t\tbreak",
        )

    def test_transpiles_for_loop_clauses(self):
        self.assertEqual(
            transpile_gml_code("for (i = 0; i < 3; i++) begin score += i; end", indent=""),
            "i = 0\n"
            "while i < 3:\n"
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
            "var _gml_switch_value_0 = keyboard_key\n"
            "var _gml_switch_matched_1 = false\n"
            'var _gml_switch_has_case_2 = GMRuntime.gml_eq(_gml_switch_value_0, vk_left) or GMRuntime.gml_eq(_gml_switch_value_0, ord("A"))\n'
            "while true:\n"
            "\tif not _gml_switch_matched_1 and GMRuntime.gml_eq(_gml_switch_value_0, vk_left):\n"
            "\t\t_gml_switch_matched_1 = true\n"
            "\tif _gml_switch_matched_1:\n"
            "\t\tpass\n"
            '\tif not _gml_switch_matched_1 and GMRuntime.gml_eq(_gml_switch_value_0, ord("A")):\n'
            "\t\t_gml_switch_matched_1 = true\n"
            "\tif _gml_switch_matched_1:\n"
            "\t\tposition.x = GMRuntime.gml_sub(position.x, 4)\n"
            "\t\tbreak\n"
            "\tbreak",
        )

    def test_switch_break_exits_switch_not_outer_loop(self):
        self.assertEqual(
            transpile_gml_code(
                "while running begin switch (state) { case 1: score = 1; break; } ticks += 1; end",
                indent="",
            ),
            "while GMRuntime.gml_bool(running):\n"
            "\tvar _gml_switch_value_0 = state\n"
            "\tvar _gml_switch_matched_1 = false\n"
            "\tvar _gml_switch_has_case_2 = GMRuntime.gml_eq(_gml_switch_value_0, 1)\n"
            "\twhile true:\n"
            "\t\tif not _gml_switch_matched_1 and GMRuntime.gml_eq(_gml_switch_value_0, 1):\n"
            "\t\t\t_gml_switch_matched_1 = true\n"
            "\t\tif _gml_switch_matched_1:\n"
            "\t\t\tscore = 1\n"
            "\t\t\tbreak\n"
            "\t\tbreak\n"
            "\tticks = GMRuntime.gml_add(ticks, 1)",
        )

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
            "while i < 3:\n"
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
            "while i < 3:\n"
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
            transpile_gml_code("score := 10;", indent=""),
            "score = 10",
        )

    def test_rejects_chained_assignments(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_code("a = b = c;", indent="")

    def test_rejects_invalid_local_var_names(self):
        with self.assertRaises(GMLTranspileError):
            transpile_gml_code("var 6fish;", indent="")

        with self.assertRaises(GMLTranspileError):
            transpile_gml_code("var foo bar;", indent="")

        with self.assertRaises(GMLTranspileError):
            transpile_gml_code(f"var {'a' * 65};", indent="")

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

    def test_transpiles_multidimensional_array_assignments(self):
        self.assertEqual(
            transpile_gml_code("grid[x][y] = value;", indent=""),
            "GMRuntime.gml_array_set(GMRuntime.gml_array_get(grid, position.x), position.y, value)",
        )

    def test_transpiles_struct_member_assignments_through_runtime(self):
        self.assertEqual(
            transpile_gml_code("mystruct.a = 20;", indent=""),
            'GMRuntime.gml_struct_set(mystruct, "a", 20)',
        )
        self.assertEqual(
            transpile_gml_code('mystruct[$ "x"] = score + 1;', indent=""),
            'GMRuntime.gml_struct_set(mystruct, "x", GMRuntime.gml_add(score, 1))',
        )
        self.assertEqual(
            transpile_gml_code("mystruct.a += 1;", indent=""),
            'GMRuntime.gml_struct_set(mystruct, "a", '
            'GMRuntime.gml_add(GMRuntime.gml_struct_get(mystruct, "a"), 1))',
        )
        self.assertEqual(
            transpile_gml_code("mystruct.a ??= 1;", indent=""),
            'if GMRuntime.gml_is_nullish(GMRuntime.gml_struct_get(mystruct, "a")):\n'
            '\tGMRuntime.gml_struct_set(mystruct, "a", 1)',
        )
        self.assertEqual(
            transpile_gml_code("mystruct.a++;", indent=""),
            'GMRuntime.gml_struct_set(mystruct, "a", '
            'GMRuntime.gml_add(GMRuntime.gml_struct_get(mystruct, "a"), 1))',
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
            'GMRuntime.gml_struct_set(alias, "a", 2)\n'
            'value = GMRuntime.gml_struct_get(mystruct, "a")',
        )

    def test_struct_function_arguments_pass_reference_without_clone(self):
        self.assertEqual(
            transpile_gml_code("mystruct = {a: 1}; mutate_struct(mystruct); value = mystruct.a;", indent=""),
            'mystruct = GMRuntime.gml_struct({"a": 1})\n'
            "mutate_struct(mystruct)\n"
            'value = GMRuntime.gml_struct_get(mystruct, "a")',
        )

    def test_array_assignment_to_undefined_releases_reference(self):
        self.assertEqual(
            transpile_gml_code("items = [1, 2]; items = undefined;", indent=""),
            "items = [1, 2]\nitems = GMRuntime.gml_undefined()",
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

    def test_transpiles_increment_decrement_statements(self):
        self.assertEqual(
            transpile_gml_code("count++;", indent=""),
            "count = GMRuntime.gml_add(count, 1)",
        )
        self.assertEqual(
            transpile_gml_code("--count;", indent=""),
            "count = GMRuntime.gml_sub(count, 1)",
        )

    def test_transpiles_expression_statements(self):
        self.assertEqual(
            transpile_gml_code("show_debug_message(score ?? 0);", indent=""),
            "show_debug_message(score if not GMRuntime.gml_is_nullish(score) else 0)",
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
            "if score > 0:\n\tscore = GMRuntime.gml_sub(score, 1)\nelse:\n\tscore = 0",
        )

    def test_transpiles_if_blocks_with_single_equals_conditions(self):
        self.assertEqual(
            transpile_gml_code("if faster = true { superSpeed = 20 }", indent=""),
            "if faster == true:\n\tsuperSpeed = 20",
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

    def test_transpiles_shift_keyboard_check(self):
        self.assertEqual(
            transpile_gml_code("if keyboard_check(vk_shift) { faster = true }", indent=""),
            "if Input.is_key_pressed(KEY_SHIFT):\n\tfaster = true",
        )

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
            "if Input.is_action_pressed(\"ui_left\"):\n"
            "\tposition.x = GMRuntime.gml_sub(position.x, 10)\n"
            "if Input.is_action_pressed(\"ui_right\"):\n"
            "\tposition.x = GMRuntime.gml_add(position.x, 10)\n"
            "if Input.is_action_pressed(\"ui_up\"):\n"
            "\tposition.y = GMRuntime.gml_sub(position.y, 10)\n"
            "if Input.is_action_pressed(\"ui_down\"):\n"
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
                "sprite_index = s_enemy; image_index = 2; image_index += 1;",
                indent="",
                instance_variables=instance_variables,
            ),
            "sprite_index = s_enemy\n"
            "image_index = 2\n"
            "image_index = GMRuntime.gml_add(image_index, 1)",
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
            "if Input.is_key_pressed(KEY_SHIFT):\n"
            "\tfaster = true\n"
            "else:\n"
            "\tfaster = false\n"
            "if faster == true:\n"
            "\tsuperSpeed = 20\n"
            "if Input.is_action_pressed(\"ui_left\"):\n"
            "\tposition.x = GMRuntime.gml_sub(position.x, superSpeed)\n"
            "if Input.is_action_pressed(\"ui_right\"):\n"
            "\tposition.x = GMRuntime.gml_add(position.x, superSpeed)\n"
            "if Input.is_action_pressed(\"ui_up\"):\n"
            "\tposition.y = GMRuntime.gml_sub(position.y, superSpeed)\n"
            "if Input.is_action_pressed(\"ui_down\"):\n"
            "\tposition.y = GMRuntime.gml_add(position.y, superSpeed)\n"
            "superSpeed = 10",
        )


if __name__ == "__main__":
    unittest.main()
