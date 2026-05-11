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
    RuntimeValueParityCase("pointer_null", "GMRuntime.gml_pointer_null()"),
    RuntimeValueParityCase("pointer_invalid", "GMRuntime.gml_pointer_invalid()"),
    RuntimeValueParityCase("typeof(undefined)", "GMRuntime.gml_typeof(GMRuntime.gml_undefined())"),
    RuntimeValueParityCase("typeof(pointer_null)", "GMRuntime.gml_typeof(GMRuntime.gml_pointer_null())"),
    RuntimeValueParityCase("string(undefined)", "GMRuntime.gml_string(GMRuntime.gml_undefined())"),
    RuntimeValueParityCase("string(pointer_invalid)", "GMRuntime.gml_string(GMRuntime.gml_pointer_invalid())"),
    RuntimeValueParityCase("bool(undefined)", "GMRuntime.gml_bool(GMRuntime.gml_undefined())"),
    RuntimeValueParityCase("bool(pointer_null)", "GMRuntime.gml_bool(GMRuntime.gml_pointer_null())"),
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
    RuntimeValueParityCase(
        "int64(score) + int64(delta)",
        "GMRuntime.gml_add(GMRuntime.gml_int64(score), GMRuntime.gml_int64(delta))",
    ),
    RuntimeValueParityCase("is_real(score)", "GMRuntime.is_real(score)"),
    RuntimeValueParityCase("is_numeric(score)", "GMRuntime.is_numeric(score)"),
    RuntimeValueParityCase("is_int32(score)", "GMRuntime.is_int32(score)"),
    RuntimeValueParityCase("is_int64(score)", "GMRuntime.is_int64(score)"),
    RuntimeValueParityCase("is_array(items)", "GMRuntime.is_array(items)"),
    RuntimeValueParityCase("is_struct(mystruct)", "GMRuntime.is_struct(mystruct)"),
    RuntimeValueParityCase("is_method(callback)", "GMRuntime.is_method(callback)"),
    RuntimeValueParityCase("is_callable(callback)", "GMRuntime.is_callable(callback)"),
    RuntimeValueParityCase("ptr(0)", "GMRuntime.gml_ptr(0)"),
    RuntimeValueParityCase("is_ptr(ptr(0))", "GMRuntime.is_ptr(GMRuntime.gml_ptr(0))"),
    RuntimeValueParityCase(
        "pointer_null == pointer_null",
        "GMRuntime.gml_eq(GMRuntime.gml_pointer_null(), GMRuntime.gml_pointer_null())",
    ),
    RuntimeValueParityCase(
        "pointer_invalid != pointer_null",
        "GMRuntime.gml_ne(GMRuntime.gml_pointer_invalid(), GMRuntime.gml_pointer_null())",
    ),
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
    RuntimeValueParityCase("{a: 1}", 'GMRuntime.gml_struct({"a": 1})'),
    RuntimeValueParityCase("mystruct.a", 'GMRuntime.gml_struct_get(mystruct, "a")'),
    RuntimeValueParityCase('mystruct[$ "x"]', 'GMRuntime.gml_struct_get(mystruct, "x")'),
    RuntimeValueParityCase('struct_exists(mystruct, "x")', 'GMRuntime.gml_struct_exists(mystruct, "x")'),
    RuntimeValueParityCase('struct_get(mystruct, "x")', 'GMRuntime.gml_struct_get(mystruct, "x")'),
    RuntimeValueParityCase('struct_set(mystruct, "x", 1)', 'GMRuntime.gml_struct_set(mystruct, "x", 1)'),
    RuntimeValueParityCase('struct_remove(mystruct, "x")', 'GMRuntime.gml_struct_remove(mystruct, "x")'),
    RuntimeValueParityCase("struct_get_names(mystruct)", "GMRuntime.gml_struct_get_names(mystruct)"),
    RuntimeValueParityCase("struct_names_count(mystruct)", "GMRuntime.gml_struct_names_count(mystruct)"),
    RuntimeValueParityCase('string({a: 1})', 'GMRuntime.gml_string(GMRuntime.gml_struct({"a": 1}))'),
    RuntimeValueParityCase("variable_clone(mystruct)", "GMRuntime.gml_variable_clone(mystruct)"),
    RuntimeValueParityCase("variable_clone(items, 0)", "GMRuntime.gml_variable_clone(items, 0)"),
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
        "score if not GMRuntime.gml_is_nullish(score) else fallback",
    ),
)


class TestGMLRuntimeScript(unittest.TestCase):
    def test_runtime_defines_shared_value_helpers(self):
        for helper_name in (
            "gml_undefined",
            "gml_pointer_null",
            "gml_pointer_invalid",
            "is_undefined",
            "is_bool",
            "is_string",
            "is_number",
            "is_real",
            "is_numeric",
            "is_int32",
            "is_int64",
            "is_ptr",
            "is_array",
            "is_struct",
            "is_method",
            "is_callable",
            "is_nan_value",
            "is_infinity",
            "gml_eq",
            "gml_ne",
            "gml_div",
            "gml_int_div",
            "gml_real",
            "gml_int64",
            "gml_ptr",
            "gml_repeat_count",
            "gml_sqrt",
            "gml_add",
            "gml_sub",
            "gml_mul",
            "gml_mod",
            "gml_array_get",
            "gml_array_set",
            "gml_struct",
            "gml_struct_exists",
            "gml_struct_get",
            "gml_struct_get_names",
            "gml_struct_names_count",
            "gml_struct_set",
            "gml_struct_remove",
            "gml_variable_clone",
            "gml_bit_and",
            "gml_bit_or",
            "gml_bit_xor",
            "gml_bit_not",
            "gml_shift_left",
            "gml_shift_right",
            "gml_typeof",
            "gml_string",
            "gml_bool",
            "gml_is_nullish",
        ):
            self.assertIn(f"static func {helper_name}", GML_RUNTIME_SCRIPT)

    def test_runtime_uses_distinct_undefined_sentinel(self):
        self.assertIn("class GMLUndefined:", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_undefined = GMLUndefined.new()", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_undefined():\n\treturn _gml_undefined", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_undefined(value):\n\treturn value is GMLUndefined", GML_RUNTIME_SCRIPT)

    def test_runtime_represents_pointer_values(self):
        self.assertIn('const GML_TYPE_POINTER = "ptr"', GML_RUNTIME_SCRIPT)
        self.assertIn("class GMLPointer:", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_pointer_null = GMLPointer.new(0)", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_pointer_invalid = GMLPointer.new(-1, true)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_pointer_null():\n\treturn _gml_pointer_null", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_pointer_invalid():\n\treturn _gml_pointer_invalid", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_ptr(value):\n\treturn value is GMLPointer", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_ptr(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLPointer.new(value)", GML_RUNTIME_SCRIPT)

    def test_runtime_undefined_equality_is_special_cased(self):
        self.assertIn("static func gml_eq(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_undefined(left) or is_undefined(right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return is_undefined(left) and is_undefined(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_ne(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return not gml_eq(left, right)", GML_RUNTIME_SCRIPT)

    def test_runtime_pointer_equality_and_nullish_are_special_cased(self):
        self.assertIn("if is_ptr(left) or is_ptr(right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return is_ptr(left) and is_ptr(right) and left.value == right.value and left.invalid == right.invalid", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_is_nullish(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return is_undefined(value) or (is_ptr(value) and value.value == 0)", GML_RUNTIME_SCRIPT)

    def test_runtime_rejects_pointer_numeric_operations(self):
        self.assertIn('return gml_error("GML pointer arithmetic is not supported")', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML pointer numeric conversion is not supported")', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML pointer bitwise conversion is not supported")', GML_RUNTIME_SCRIPT)

    def test_runtime_undefined_truthiness_and_conversions(self):
        self.assertIn(
            "static func gml_typeof(value):\n\tif is_undefined(value):\n\t\treturn GML_TYPE_UNDEFINED",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn(
            "static func gml_string(value):\n\tif is_undefined(value):\n\t\treturn GML_TYPE_UNDEFINED",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn(
            "static func gml_bool(value):\n\tif is_undefined(value):\n\t\treturn false",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if is_ptr(value):\n\t\treturn not value.invalid and value.value != 0", GML_RUNTIME_SCRIPT)

    def test_runtime_helpers_keep_variant_backed_parameters(self):
        self.assertIn("static func gml_typeof(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_bool(value):", GML_RUNTIME_SCRIPT)
        self.assertNotIn("static func gml_typeof(value:", GML_RUNTIME_SCRIPT)
        self.assertNotIn("static func gml_bool(value:", GML_RUNTIME_SCRIPT)

    def test_runtime_primitive_type_predicates_cover_gml_value_categories(self):
        self.assertIn("static func is_array(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return typeof(value) == TYPE_ARRAY", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_struct(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return typeof(value) == TYPE_DICTIONARY or typeof(value) == TYPE_OBJECT", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_method(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return typeof(value) == TYPE_CALLABLE", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_callable(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return is_method(value)", GML_RUNTIME_SCRIPT)

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

    def test_runtime_array_reads_check_bounds_before_access(self):
        self.assertIn("if typeof(array_value) != TYPE_ARRAY:", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML array access requires an array")', GML_RUNTIME_SCRIPT)
        self.assertIn("if resolved_index >= array_value.size():", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML array index out of bounds")', GML_RUNTIME_SCRIPT)

    def test_runtime_array_set_mutates_reference_without_copying(self):
        self.assertIn("array_value[resolved_index] = value", GML_RUNTIME_SCRIPT)
        self.assertIn("return value", GML_RUNTIME_SCRIPT)
        self.assertNotIn("array_value.duplicate", GML_RUNTIME_SCRIPT)

    def test_runtime_array_deletion_uses_undefined_without_registries(self):
        self.assertIn("static func gml_undefined():\n\treturn _gml_undefined", GML_RUNTIME_SCRIPT)
        self.assertNotIn("array_registry", GML_RUNTIME_SCRIPT)

    def test_runtime_array_copy_on_write_flag_emits_diagnostic(self):
        self.assertIn("const GML_ARRAY_COPY_ON_WRITE_ENABLED = false", GML_RUNTIME_SCRIPT)
        self.assertIn(
            'const GML_ARRAY_COPY_ON_WRITE_DIAGNOSTIC = "Legacy GML array copy-on-write mode is not supported by GM2Godot"',
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if GML_ARRAY_COPY_ON_WRITE_ENABLED:", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_error(GML_ARRAY_COPY_ON_WRITE_DIAGNOSTIC)", GML_RUNTIME_SCRIPT)

    def test_runtime_struct_helper_keeps_dictionary_reference(self):
        self.assertIn("static func gml_struct(fields = {}):", GML_RUNTIME_SCRIPT)
        self.assertIn("if typeof(fields) != TYPE_DICTIONARY:", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML struct literal requires a dictionary")', GML_RUNTIME_SCRIPT)
        self.assertIn("return fields", GML_RUNTIME_SCRIPT)
        self.assertNotIn("fields.duplicate", GML_RUNTIME_SCRIPT)

    def test_runtime_struct_access_helpers_preserve_gml_missing_member_behavior(self):
        self.assertIn("static func gml_struct_get(struct_value, member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_exists(struct_value, member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_set(struct_value, member_name, value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_remove(struct_value, member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("if typeof(struct_value) == TYPE_DICTIONARY:", GML_RUNTIME_SCRIPT)
        self.assertIn("if struct_value.has(key):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_undefined()", GML_RUNTIME_SCRIPT)
        self.assertIn("struct_value[key] = value", GML_RUNTIME_SCRIPT)
        self.assertIn("struct_value.erase(key)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _object_has_property(object_value, property_name):", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML struct access requires a struct")', GML_RUNTIME_SCRIPT)

    def test_runtime_struct_name_helpers_return_visible_member_names(self):
        self.assertIn("static func gml_struct_get_names(struct_value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_names_count(struct_value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return struct_value.keys()", GML_RUNTIME_SCRIPT)
        self.assertIn("return struct_value.size()", GML_RUNTIME_SCRIPT)
        self.assertIn("return -1", GML_RUNTIME_SCRIPT)

    def test_runtime_struct_string_output_uses_to_string_convention(self):
        self.assertIn("static func gml_string(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if typeof(value) == TYPE_DICTIONARY:", GML_RUNTIME_SCRIPT)
        self.assertIn('if value.has("toString") and typeof(value["toString"]) == TYPE_CALLABLE:', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_string(value["toString"].call())', GML_RUNTIME_SCRIPT)
        self.assertIn("return str(value)", GML_RUNTIME_SCRIPT)

    def test_runtime_variable_clone_preserves_documented_depth_behavior(self):
        self.assertIn("static func gml_variable_clone(value, depth = 128):", GML_RUNTIME_SCRIPT)
        self.assertIn("return _gml_clone_value(value, max(0, int(_to_real(depth))))", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_clone_value(value, depth):", GML_RUNTIME_SCRIPT)
        self.assertIn("if value_type == TYPE_ARRAY:", GML_RUNTIME_SCRIPT)
        self.assertIn("if value_type == TYPE_DICTIONARY:", GML_RUNTIME_SCRIPT)
        self.assertIn("clone.append(_gml_clone_value(element, depth - 1) if depth > 0 else element)", GML_RUNTIME_SCRIPT)
        self.assertIn("clone[key] = _gml_clone_value(value[key], depth - 1) if depth > 0 else value[key]", GML_RUNTIME_SCRIPT)
        self.assertIn("return value", GML_RUNTIME_SCRIPT)

    def test_runtime_represents_explicit_int64_values(self):
        self.assertIn("const GML_TYPE_INT64", GML_RUNTIME_SCRIPT)
        self.assertIn("class GMLInt64", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_int64(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return value is GMLInt64", GML_RUNTIME_SCRIPT)
        self.assertIn("return GML_TYPE_INT64", GML_RUNTIME_SCRIPT)

    def test_runtime_preserves_int64_arithmetic_results(self):
        self.assertIn("static func _returns_int64_arithmetic_result(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(_to_int64_value(left) + _to_int64_value(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(_to_int64_value(left) - _to_int64_value(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(_to_int64_value(left) * _to_int64_value(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(_to_int64_value(left) % _to_int64_value(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("(is_int64(left) and (is_int64(right) or is_int32(right)))", GML_RUNTIME_SCRIPT)
        self.assertIn("or (is_int64(right) and is_int32(left))", GML_RUNTIME_SCRIPT)

    def test_runtime_checks_int32_range_over_godot_ints(self):
        self.assertIn("static func is_int32(value):", GML_RUNTIME_SCRIPT)
        self.assertIn(
            "return typeof(value) == TYPE_INT and int(value) >= -2147483648 and int(value) <= 2147483647",
            GML_RUNTIME_SCRIPT,
        )

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
