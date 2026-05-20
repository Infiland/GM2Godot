import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_transpiler import (
    category_issue_numbers,
    generate_gml_manual_scope_report,
    get_gml_manual_scope_entry,
    iter_gml_manual_scope_entries,
    render_gml_manual_scope_markdown,
    validate_gml_manual_scope_against_manifest,
)


class TestGMLManualScope(unittest.TestCase):
    def test_manual_scope_entries_have_required_metadata(self):
        entries = tuple(iter_gml_manual_scope_entries())

        self.assertGreaterEqual(len(entries), 30)
        for entry in entries:
            with self.subTest(entry=entry.key):
                self.assertTrue(entry.key)
                self.assertTrue(entry.title)
                self.assertTrue(entry.section)
                self.assertTrue(entry.owner_area)
                self.assertTrue(entry.docs_url.startswith("https://manual.gamemaker.io/monthly/en/"))
                self.assertTrue(entry.manifest_categories)
                self.assertGreaterEqual(entry.issue_number, 575)

    def test_manual_scope_cross_checks_against_api_manifest(self):
        self.assertEqual(validate_gml_manual_scope_against_manifest(), ())

        manifest_categories = set(category_issue_numbers())
        covered_categories: set[str] = set()
        for entry in iter_gml_manual_scope_entries():
            covered_categories.update(entry.manifest_categories)

        self.assertEqual(manifest_categories - covered_categories, set())

    def test_manual_scope_report_counts_entries_by_section(self):
        entries = tuple(iter_gml_manual_scope_entries())
        report = generate_gml_manual_scope_report()

        self.assertGreater(len(report), 5)
        self.assertEqual(sum(row.total for row in report), len(entries))
        self.assertIn("GML Code Overview", {row.section for row in report})
        self.assertIn("GML Reference: Drawing", {row.section for row in report})

        for row in report:
            with self.subTest(section=row.section):
                self.assertEqual(
                    row.total,
                    row.implemented
                    + row.partial
                    + row.planned
                    + row.unsupported
                    + row.out_of_scope,
                )

    def test_manual_scope_exposes_specific_milestone_entries(self):
        mutation = get_gml_manual_scope_entry("overview_expressions_operators")
        drawing = get_gml_manual_scope_entry("reference_drawing")
        platform = get_gml_manual_scope_entry("reference_platform_os_debug_gc")

        self.assertIsNotNone(mutation)
        self.assertIsNotNone(drawing)
        self.assertIsNotNone(platform)
        assert mutation is not None
        assert drawing is not None
        assert platform is not None

        self.assertEqual(mutation.issue_number, 580)
        self.assertEqual(drawing.issue_number, 602)
        self.assertEqual(platform.issue_number, 606)
        self.assertIn("Foundation", mutation.manifest_categories)
        self.assertIn("Drawing Surfaces", drawing.manifest_categories)
        self.assertIn("Platform Services", platform.manifest_categories)

    def test_manual_scope_markdown_groups_by_section_and_status(self):
        markdown = render_gml_manual_scope_markdown()

        self.assertIn("# GML Manual Scope Coverage", markdown)
        self.assertIn("| Manual category | Implemented | Partial | Planned | Unsupported | Out of scope | Total |", markdown)
        self.assertIn("### GML Reference: Drawing", markdown)
        self.assertIn("`compatibility_report`", markdown)
        self.assertIn("#602", markdown)


if __name__ == "__main__":
    unittest.main()
