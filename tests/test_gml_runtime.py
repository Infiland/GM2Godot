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
    RuntimeValueParityCase(
        "is_undefined(undefined)",
        "GMRuntime.is_undefined(GMRuntime.gml_undefined())",
    ),
    RuntimeValueParityCase("is_nan(NaN)", "GMRuntime.is_nan_value(NAN)"),
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
            "is_number",
            "is_nan_value",
            "is_infinity",
            "gml_eq",
            "gml_ne",
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
