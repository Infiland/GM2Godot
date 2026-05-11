import os
import sys
import tempfile
import unittest
from dataclasses import dataclass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_runtime import GML_RUNTIME_RELATIVE_PATH, GML_RUNTIME_SCRIPT, write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_expression


@dataclass(frozen=True)
class RuntimeValueParityCase:
    gml_expression: str
    gdscript_expression: str


RUNTIME_VALUE_PARITY_CASES = (
    RuntimeValueParityCase("undefined", "GMRuntime.gml_undefined()"),
    RuntimeValueParityCase("typeof(undefined)", "GMRuntime.gml_typeof(GMRuntime.gml_undefined())"),
    RuntimeValueParityCase("string(undefined)", "GMRuntime.gml_string(GMRuntime.gml_undefined())"),
    RuntimeValueParityCase("bool(undefined)", "GMRuntime.gml_bool(GMRuntime.gml_undefined())"),
    RuntimeValueParityCase("bool(0.5)", "GMRuntime.gml_bool(0.5)"),
    RuntimeValueParityCase("bool(0.50001)", "GMRuntime.gml_bool(0.50001)"),
    RuntimeValueParityCase("is_bool(true)", "GMRuntime.is_bool(true)"),
    RuntimeValueParityCase('string("abc")', 'GMRuntime.gml_string("abc")'),
    RuntimeValueParityCase('typeof("abc")', 'GMRuntime.gml_typeof("abc")'),
    RuntimeValueParityCase('is_string("abc")', 'GMRuntime.is_string("abc")'),
    RuntimeValueParityCase("real(score)", "GMRuntime.gml_real(score)"),
    RuntimeValueParityCase("int64(score)", "GMRuntime.gml_int64(score)"),
    RuntimeValueParityCase("typeof(int64(score))", "GMRuntime.gml_typeof(GMRuntime.gml_int64(score))"),
    RuntimeValueParityCase("string(int64(score))", "GMRuntime.gml_string(GMRuntime.gml_int64(score))"),
    RuntimeValueParityCase("bool(int64(score))", "GMRuntime.gml_bool(GMRuntime.gml_int64(score))"),
    RuntimeValueParityCase("is_real(score)", "GMRuntime.is_real(score)"),
    RuntimeValueParityCase("is_numeric(score)", "GMRuntime.is_numeric(score)"),
    RuntimeValueParityCase("is_int64(score)", "GMRuntime.is_int64(score)"),
    RuntimeValueParityCase(
        "is_undefined(undefined)",
        "GMRuntime.is_undefined(GMRuntime.gml_undefined())",
    ),
    RuntimeValueParityCase("nan", "NAN"),
    RuntimeValueParityCase("real(NaN)", "GMRuntime.gml_real(NAN)"),
    RuntimeValueParityCase("typeof(NaN)", "GMRuntime.gml_typeof(NAN)"),
    RuntimeValueParityCase("is_nan(NaN)", "GMRuntime.is_nan_value(NAN)"),
    RuntimeValueParityCase("0.5", "0.5"),
    RuntimeValueParityCase("100_000_000", "100000000"),
    RuntimeValueParityCase("3_141.59", "3141.59"),
    RuntimeValueParityCase("1.5 / 2", "GMRuntime.gml_div(1.5, 2)"),
    RuntimeValueParityCase("5 / 2", "GMRuntime.gml_div(5, 2)"),
    RuntimeValueParityCase("0 / 0", "GMRuntime.gml_div(0, 0)"),
    RuntimeValueParityCase("sqrt(-1)", "GMRuntime.gml_sqrt(-1)"),
    RuntimeValueParityCase("5 div 2", "GMRuntime.gml_int_div(5, 2)"),
    RuntimeValueParityCase("0xDEAD_BEEF", "0xDEADBEEF"),
    RuntimeValueParityCase("$2c8e", "0x2c8e"),
    RuntimeValueParityCase("#dd8e2c", "0x2c8edd"),
    RuntimeValueParityCase("#0000ff", "0xff0000"),
    RuntimeValueParityCase("#ff0000", "0x0000ff"),
    RuntimeValueParityCase("typeof(#dd8e2c)", "GMRuntime.gml_typeof(0x2c8edd)"),
    RuntimeValueParityCase("real($2c8e)", "GMRuntime.gml_real(0x2c8e)"),
    RuntimeValueParityCase("0b01101000_01101001", "0b0110100001101001"),
    RuntimeValueParityCase("0b0010 | 0b0100", "GMRuntime.gml_bit_or(0b0010, 0b0100)"),
    RuntimeValueParityCase("[1, score + 1]", "[1, GMRuntime.gml_add(score, 1)]"),
    RuntimeValueParityCase("items[-1]", "GMRuntime.gml_array_get(items, -1)"),
    RuntimeValueParityCase("a + b", "GMRuntime.gml_add(a, b)"),
    RuntimeValueParityCase('"a" + "b"', 'GMRuntime.gml_add("a", "b")'),
    RuntimeValueParityCase('1 + "px"', 'GMRuntime.gml_add(1, "px")'),
    RuntimeValueParityCase('true + "!"', 'GMRuntime.gml_add(true, "!")'),
    RuntimeValueParityCase("a - b", "GMRuntime.gml_sub(a, b)"),
    RuntimeValueParityCase("a * b", "GMRuntime.gml_mul(a, b)"),
    RuntimeValueParityCase("a mod b", "GMRuntime.gml_mod(a, b)"),
    RuntimeValueParityCase("!0.5", "not GMRuntime.gml_bool(0.5)"),
    RuntimeValueParityCase(
        "0.25 || 1",
        "GMRuntime.gml_bool(0.25) or GMRuntime.gml_bool(1)",
    ),
    RuntimeValueParityCase(
        "score ?? fallback",
        "score if not GMRuntime.is_undefined(score) else fallback",
    ),
)


class TestGMLRuntimeScript(unittest.TestCase):
    def test_runtime_defines_shared_value_helpers(self):
        for helper_name in (
            "gml_undefined",
            "is_undefined",
            "is_bool",
            "is_string",
            "is_number",
            "is_real",
            "is_numeric",
            "is_int64",
            "is_nan_value",
            "is_infinity",
            "gml_eq",
            "gml_ne",
            "gml_div",
            "gml_int_div",
            "gml_real",
            "gml_int64",
            "gml_repeat_count",
            "gml_sqrt",
            "gml_add",
            "gml_sub",
            "gml_mul",
            "gml_mod",
            "gml_array_get",
            "gml_array_set",
            "gml_bit_and",
            "gml_bit_or",
            "gml_bit_xor",
            "gml_bit_not",
            "gml_shift_left",
            "gml_shift_right",
            "gml_typeof",
            "gml_string",
            "gml_bool",
        ):
            self.assertIn(f"static func {helper_name}", GML_RUNTIME_SCRIPT)

    def test_runtime_helpers_keep_variant_backed_parameters(self):
        self.assertIn("static func gml_typeof(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_bool(value):", GML_RUNTIME_SCRIPT)
        self.assertNotIn("static func gml_typeof(value:", GML_RUNTIME_SCRIPT)
        self.assertNotIn("static func gml_bool(value:", GML_RUNTIME_SCRIPT)

    def test_runtime_preserves_real_operations_as_float_helpers(self):
        self.assertIn("return NAN", GML_RUNTIME_SCRIPT)
        self.assertIn("return INF if left_value > 0.0 else -INF", GML_RUNTIME_SCRIPT)
        self.assertIn("return left_value / right_value", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_sqrt(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return sqrt(real_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("return _to_real(left) + _to_real(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("return fmod(_to_real(left), _to_real(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("return float(value)", GML_RUNTIME_SCRIPT)

    def test_runtime_repeat_count_preserves_gml_rounding(self):
        self.assertIn("static func gml_repeat_count(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return max(0, int(round(_to_real(value))))", GML_RUNTIME_SCRIPT)

    def test_runtime_array_helpers_reject_negative_indices(self):
        self.assertIn("static func gml_array_get(array_value, index):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_array_set(array_value, index, value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _to_array_index(value):", GML_RUNTIME_SCRIPT)
        self.assertIn('gml_error("Negative GML array index")', GML_RUNTIME_SCRIPT)

    def test_runtime_represents_explicit_int64_values(self):
        self.assertIn("const GML_TYPE_INT64", GML_RUNTIME_SCRIPT)
        self.assertIn("class GMLInt64", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_int64(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return value is GMLInt64", GML_RUNTIME_SCRIPT)
        self.assertIn("return GML_TYPE_INT64", GML_RUNTIME_SCRIPT)

    def test_runtime_bitwise_helpers_return_int64_values(self):
        self.assertIn("static func gml_bit_or(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(_to_int64_value(left) | _to_int64_value(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(~_to_int64_value(value))", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _to_int64_value(value):", GML_RUNTIME_SCRIPT)

    def test_runtime_handles_string_conversion_and_concat_deliberately(self):
        self.assertIn("static func is_string(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return value_type == TYPE_STRING or value_type == TYPE_STRING_NAME", GML_RUNTIME_SCRIPT)
        self.assertIn("return str(left) + str(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_string(left) + str(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("Invalid GML string concatenation", GML_RUNTIME_SCRIPT)
        self.assertIn('return "true" if value else "false"', GML_RUNTIME_SCRIPT)

    def test_runtime_centralizes_error_reporting(self):
        self.assertIn("static func gml_error(message):", GML_RUNTIME_SCRIPT)
        self.assertIn("push_error", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_undefined()", GML_RUNTIME_SCRIPT)

    def test_write_gml_runtime_writes_support_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_path = write_gml_runtime(tmpdir)

            self.assertEqual(runtime_path, os.path.join(tmpdir, GML_RUNTIME_RELATIVE_PATH))
            with open(runtime_path, encoding="utf-8") as runtime_file:
                self.assertEqual(runtime_file.read(), GML_RUNTIME_SCRIPT)


class TestGMLRuntimeParityFixtures(unittest.TestCase):
    def test_runtime_value_expression_fixtures(self):
        for parity_case in RUNTIME_VALUE_PARITY_CASES:
            with self.subTest(gml_expression=parity_case.gml_expression):
                self.assertEqual(
                    transpile_gml_expression(parity_case.gml_expression),
                    parity_case.gdscript_expression,
                )


if __name__ == "__main__":
    unittest.main()
