# pyright: reportPrivateUsage=false
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_transpiler import (
    GMLTranspileError,
    _ExpressionParser,
    _NumberLiteral,
    _StringLiteral,
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
            "INF == NAN",
        )
        self.assertEqual(
            transpile_gml_expression("infinity == undefined"),
            "INF == GMRuntime.gml_undefined()",
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
        self.assertEqual(transpile_gml_expression("is_real(score)"), "GMRuntime.is_real(score)")
        self.assertEqual(
            transpile_gml_expression("is_numeric(int64(score))"),
            "GMRuntime.is_numeric(GMRuntime.gml_int64(score))",
        )
        self.assertEqual(
            transpile_gml_expression("is_int64(int64(score))"),
            "GMRuntime.is_int64(GMRuntime.gml_int64(score))",
        )

    def test_transpiles_string_value_helpers(self):
        self.assertEqual(transpile_gml_expression('string("abc")'), 'GMRuntime.gml_string("abc")')
        self.assertEqual(transpile_gml_expression('typeof("abc")'), 'GMRuntime.gml_typeof("abc")')
        self.assertEqual(transpile_gml_expression('is_string("abc")'), 'GMRuntime.is_string("abc")')

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
            "value if not GMRuntime.is_undefined(value) else fallback",
        )

    def test_transpiles_ternary_operator(self):
        self.assertEqual(
            transpile_gml_expression("alive ? speed : 0"),
            "speed if GMRuntime.gml_bool(alive) else 0",
        )

    def test_transpiles_calls_indexes_and_members(self):
        self.assertEqual(
            transpile_gml_expression("choose(items[index + 1], other.value)"),
            "choose(items[GMRuntime.gml_add(index, 1)], other.value)",
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

    def test_transpiles_var_assignments(self):
        self.assertEqual(
            transpile_gml_code("var x = a + b * c;", indent=""),
            "var x = GMRuntime.gml_add(a, GMRuntime.gml_mul(b, c))",
        )

    def test_transpiles_multiple_var_assignments(self):
        self.assertEqual(
            transpile_gml_code("var x = 1, y = x + 2;", indent=""),
            "var x = 1\nvar y = GMRuntime.gml_add(x, 2)",
        )

    def test_transpiles_compound_assignments(self):
        self.assertEqual(
            transpile_gml_code("x += y * 2;", indent=""),
            "position.x = GMRuntime.gml_add(position.x, GMRuntime.gml_mul(position.y, 2))",
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
            "if GMRuntime.is_undefined(score):\n\tscore = 10",
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
            "show_debug_message(score if not GMRuntime.is_undefined(score) else 0)",
        )

    def test_local_vars_shadow_instance_position_builtins(self):
        self.assertEqual(
            transpile_gml_code("var x = 1, y = x + 2; x += y;", indent=""),
            "var x = 1\nvar y = GMRuntime.gml_add(x, 2)\nx = GMRuntime.gml_add(x, y)",
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
