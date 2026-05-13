# pyright: reportPrivateUsage=false
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_transpiler import (
    GMLTranspileError,
    category_issue_numbers,
    diagnostic_for_unimplemented_gml_api,
    generate_gml_api_compatibility_report,
    get_gml_api_entry,
    godot_docs_root,
    is_known_gml_api,
    iter_gml_api_entries,
    transpile_gml_expression,
)


class TestGMLAPIManifest(unittest.TestCase):
    def test_report_lists_every_part_2_category_bucket_with_counts(self):
        report = generate_gml_api_compatibility_report()
        issue_numbers = category_issue_numbers()

        self.assertEqual({row.category for row in report}, set(issue_numbers))
        self.assertEqual({row.issue_number for row in report}, set(issue_numbers.values()))

        for row in report:
            with self.subTest(category=row.category):
                self.assertGreater(row.total, 0)
                self.assertEqual(
                    row.total,
                    row.implemented
                    + row.partial
                    + row.planned
                    + row.unsupported
                    + row.out_of_scope,
                )

    def test_manifest_entries_have_owner_issue_module_and_docs(self):
        entries = tuple(iter_gml_api_entries())
        issue_numbers = set(category_issue_numbers().values())

        self.assertGreater(len(entries), 50)
        for entry in entries:
            with self.subTest(api=entry.name):
                self.assertIn(entry.issue_number, issue_numbers)
                self.assertTrue(entry.owner_module)
                self.assertTrue(entry.docs_url.startswith("https://manual.gamemaker.io/monthly/en/"))

    def test_manifest_exposes_implemented_and_planned_apis(self):
        array_push = get_gml_api_entry("array_push")
        draw_sprite = get_gml_api_entry("draw_sprite")

        self.assertIsNotNone(array_push)
        self.assertIsNotNone(draw_sprite)
        assert array_push is not None
        assert draw_sprite is not None

        self.assertEqual(array_push.status, "implemented")
        self.assertEqual(array_push.issue_number, 502)
        self.assertEqual(draw_sprite.status, "planned")
        self.assertEqual(draw_sprite.issue_number, 491)
        self.assertTrue(is_known_gml_api("draw_sprite"))
        self.assertFalse(is_known_gml_api("project_local_function"))
        self.assertEqual(godot_docs_root(), "https://docs.godotengine.org/en/stable")

    def test_known_unimplemented_gml_builtin_gets_diagnostic(self):
        diagnostic = diagnostic_for_unimplemented_gml_api("draw_sprite")

        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        self.assertIn("draw_sprite", diagnostic)
        self.assertIn("#491", diagnostic)

    def test_transpiler_rejects_known_unimplemented_gml_builtin_calls(self):
        with self.assertRaisesRegex(GMLTranspileError, "draw_sprite.*#491"):
            transpile_gml_expression("draw_sprite(spr_player, 0, x, y)")

    def test_unknown_project_local_function_calls_still_pass_through(self):
        self.assertEqual(
            transpile_gml_expression("project_local_function(score + 1)"),
            "project_local_function(GMRuntime.gml_add(score, 1))",
        )


if __name__ == "__main__":
    unittest.main()
