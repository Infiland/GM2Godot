import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_transpiler import transpile_gml_code, transpile_gml_expression


class TestGMLExpressionTranspiler(unittest.TestCase):
    def test_preserves_arithmetic_precedence(self):
        self.assertEqual(transpile_gml_expression("a + b * c"), "a + b * c")
        self.assertEqual(transpile_gml_expression("(a + b) * c"), "(a + b) * c")

    def test_transpiles_logical_operators(self):
        self.assertEqual(
            transpile_gml_expression("a && !b || c"),
            "a and not b or c",
        )
        self.assertEqual(
            transpile_gml_expression("a and not b or c"),
            "a and not b or c",
        )

    def test_transpiles_div_and_mod(self):
        self.assertEqual(transpile_gml_expression("score div 10"), "int(score / 10)")
        self.assertEqual(transpile_gml_expression("score mod 3"), "score % 3")

    def test_transpiles_runtime_safe_real_division(self):
        self.assertEqual(
            transpile_gml_expression("1 / 0"),
            "GMRuntime.gml_div(1, 0)",
        )
        self.assertEqual(
            transpile_gml_expression("a / b + c"),
            "GMRuntime.gml_div(a, b) + c",
        )

    def test_transpiles_infinity_and_nan_constants(self):
        self.assertEqual(transpile_gml_expression("infinity"), "INF")
        self.assertEqual(transpile_gml_expression("NaN"), "NAN")

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
            "INF == null",
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

    def test_transpiles_bitwise_operators(self):
        self.assertEqual(
            transpile_gml_expression("flags & mask | 4"),
            "flags & mask | 4",
        )
        self.assertEqual(transpile_gml_expression("value << 2"), "value << 2")

    def test_transpiles_nullish_operator(self):
        self.assertEqual(
            transpile_gml_expression("value ?? fallback"),
            "value if value != null else fallback",
        )

    def test_transpiles_ternary_operator(self):
        self.assertEqual(
            transpile_gml_expression("alive ? speed : 0"),
            "speed if alive else 0",
        )

    def test_transpiles_calls_indexes_and_members(self):
        self.assertEqual(
            transpile_gml_expression("choose(items[index + 1], other.value)"),
            "choose(items[index + 1], other.value)",
        )


class TestGMLStatementTranspiler(unittest.TestCase):
    def test_transpiles_var_assignments(self):
        self.assertEqual(
            transpile_gml_code("var x = a + b * c;", indent=""),
            "var x = a + b * c",
        )

    def test_transpiles_multiple_var_assignments(self):
        self.assertEqual(
            transpile_gml_code("var x = 1, y = x + 2;", indent=""),
            "var x = 1\nvar y = x + 2",
        )

    def test_transpiles_compound_assignments(self):
        self.assertEqual(
            transpile_gml_code("x += y * 2;", indent=""),
            "position.x += position.y * 2",
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
            "if score == null:\n\tscore = 10",
        )

    def test_transpiles_increment_decrement_statements(self):
        self.assertEqual(transpile_gml_code("count++;", indent=""), "count += 1")
        self.assertEqual(transpile_gml_code("--count;", indent=""), "count -= 1")

    def test_transpiles_expression_statements(self):
        self.assertEqual(
            transpile_gml_code("show_debug_message(score ?? 0);", indent=""),
            "show_debug_message(score if score != null else 0)",
        )

    def test_local_vars_shadow_instance_position_builtins(self):
        self.assertEqual(
            transpile_gml_code("var x = 1, y = x + 2; x += y;", indent=""),
            "var x = 1\nvar y = x + 2\nx += y",
        )

    def test_transpiles_if_blocks(self):
        self.assertEqual(
            transpile_gml_code("if score > 0 { score -= 1; } else { score = 0; }", indent=""),
            "if score > 0:\n\tscore -= 1\nelse:\n\tscore = 0",
        )

    def test_transpiles_if_blocks_with_single_equals_conditions(self):
        self.assertEqual(
            transpile_gml_code("if faster = true { superSpeed = 20 }", indent=""),
            "if faster == true:\n\tsuperSpeed = 20",
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
            "\tposition.x -= 10\n"
            "if Input.is_action_pressed(\"ui_right\"):\n"
            "\tposition.x += 10\n"
            "if Input.is_action_pressed(\"ui_up\"):\n"
            "\tposition.y -= 10\n"
            "if Input.is_action_pressed(\"ui_down\"):\n"
            "\tposition.y += 10",
        )

    def test_collects_assigned_instance_variables(self):
        instance_variables: set[str] = set()

        self.assertEqual(
            transpile_gml_code(
                "superSpeed = 0\nvar localSpeed = 1; localSpeed += 1; x += localSpeed;",
                indent="",
                instance_variables=instance_variables,
            ),
            "superSpeed = 0\nvar localSpeed = 1\nlocalSpeed += 1\nposition.x += localSpeed",
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
            "sprite_index = s_enemy\nimage_index = 2\nimage_index += 1",
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
            "\tposition.x -= superSpeed\n"
            "if Input.is_action_pressed(\"ui_right\"):\n"
            "\tposition.x += superSpeed\n"
            "if Input.is_action_pressed(\"ui_up\"):\n"
            "\tposition.y -= superSpeed\n"
            "if Input.is_action_pressed(\"ui_down\"):\n"
            "\tposition.y += superSpeed\n"
            "superSpeed = 10",
        )


if __name__ == "__main__":
    unittest.main()
