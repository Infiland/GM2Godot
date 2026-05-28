from __future__ import annotations

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestDocumentationHealth(unittest.TestCase):
    def test_readme_describes_transpiler_runtime_reports_and_limits(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        required_phrases = (
            "GML-to-GDScript transpiler",
            "Generated Runtime",
            "Diagnostics and Reports",
            "compatibility reports",
            "A perfect 1:1 conversion tool",
            "--fail-on-unsupported",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)

    def test_contributing_documents_extension_points(self) -> None:
        contributing = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

        required_headings = (
            "### Conversion Architecture",
            "### GML API Support",
            "### Runtime Segments",
            "### Resource Converters",
            "### Event Mappings",
            "### Fixtures",
        )
        for heading in required_headings:
            with self.subTest(heading=heading):
                self.assertIn(heading, contributing)

    def test_runtime_docs_cover_ownership_event_order_and_state(self) -> None:
        segment_readme = (PROJECT_ROOT / "src" / "conversion" / "gml_runtime_parts" / "README.md").read_text(
            encoding="utf-8"
        )
        managers_doc = (PROJECT_ROOT / "src" / "conversion" / "runtime_managers.md").read_text(encoding="utf-8")

        self.assertIn("## Ownership", segment_readme)
        self.assertIn("runtime_api_index()", segment_readme)
        self.assertIn("## Runtime State", segment_readme)
        self.assertIn("## Event Order And Deviations", managers_doc)
        self.assertIn("## State, Globals, And Persistence", managers_doc)

    def test_required_issue_templates_exist(self) -> None:
        template_dir = PROJECT_ROOT / ".github" / "ISSUE_TEMPLATE"
        expected_templates = {
            "unsupported_gml_api.yml": ("Unsupported GML API", "Minimal GameMaker source"),
            "invalid_generated_gdscript.yml": ("Invalid Generated GDScript", "Godot error"),
            "resource_conversion_mismatch.yml": ("Resource Conversion Mismatch", "Resource kind"),
            "fixture_contribution.yml": ("Fixture Contribution", "Fixture checklist"),
        }

        for filename, phrases in expected_templates.items():
            with self.subTest(template=filename):
                content = (template_dir / filename).read_text(encoding="utf-8")
                for phrase in phrases:
                    self.assertIn(phrase, content)

    def test_code_health_workflow_runs_ruff(self) -> None:
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "code-health.yml").read_text(encoding="utf-8")
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("ruff check .", workflow)
        self.assertIn("[tool.ruff.lint]", pyproject)
        self.assertIn('"F82"', pyproject)


if __name__ == "__main__":
    unittest.main()

