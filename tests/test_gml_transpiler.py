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


if __name__ == "__main__":
    unittest.main()
