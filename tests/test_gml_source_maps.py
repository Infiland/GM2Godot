from __future__ import annotations

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_transpiler import (
    GMLTranspileError,
    analyze_gml_source_identifiers,
    transpile_gml_code,
    transpile_gml_code_with_source_map,
)


class TestGMLSourceMaps(unittest.TestCase):
    def test_source_map_tracks_comments_macros_multiline_and_nested_blocks(self) -> None:
        source = "\n".join(
            [
                "// keep this gameplay note",
                "#macro STEP 2",
                "if (score",
                "    > 10) {",
                "    total = score + STEP;",
                "}",
            ]
        )

        result = transpile_gml_code_with_source_map(
            source,
            source_path="objects/o_player/Step_0.gml",
            event="_process",
            preserve_source_comments=True,
        )

        self.assertIn("# GML line 1: keep this gameplay note", result.code)
        self.assertTrue(result.source_map.entries)
        self.assertEqual(result.source_map.source_path, "objects/o_player/Step_0.gml")
        self.assertEqual(result.source_map.event, "_process")
        source_lines = {entry.source_line for entry in result.source_map.entries}
        self.assertIn(3, source_lines)
        self.assertIn(5, source_lines)
        self.assertTrue(any("if " in entry.generated_text for entry in result.source_map.entries))

    def test_malformed_syntax_reports_source_span(self) -> None:
        with self.assertRaises(GMLTranspileError) as raised:
            transpile_gml_code("if (score > 10 {\n    score = 1;")

        self.assertIsNotNone(raised.exception.line)
        self.assertIsNotNone(raised.exception.column)
        self.assertIn("line", str(raised.exception))
        self.assertIn("column", str(raised.exception))

    def test_reserved_name_and_case_collision_diagnostics_have_locations(self) -> None:
        diagnostics = analyze_gml_source_identifiers(
            "\n".join(
                [
                    "var class = 1;",
                    "score = 1;",
                    "Score = 2;",
                ]
            )
        )

        reserved = [diagnostic for diagnostic in diagnostics if diagnostic.code == "GM2GD-GML-RESERVED-NAME"]
        case_collisions = [diagnostic for diagnostic in diagnostics if diagnostic.code == "GM2GD-GML-CASE-COLLISION"]

        self.assertEqual(len(reserved), 1)
        self.assertEqual(reserved[0].line, 1)
        self.assertEqual(reserved[0].suggested_name, "class_")
        self.assertGreaterEqual(len(case_collisions), 2)
        self.assertTrue(all(diagnostic.line in (2, 3) for diagnostic in case_collisions))


if __name__ == "__main__":
    unittest.main()
