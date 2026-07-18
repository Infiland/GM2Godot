from __future__ import annotations

from pathlib import Path
import re
import unittest

from src.version import get_version


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIKI_SOURCE_DIR = PROJECT_ROOT / "docs" / "wiki"
WIKI_PAGES = {
    "Home.md",
    "Installation.md",
    "Quick-Start-Conversion.md",
    "Compatibility-and-Limitations.md",
    "Diagnostics-and-Troubleshooting.md",
    "Generated-Project-and-Runtime.md",
    "Contributing-and-Testing.md",
    "Maintainer-Release-and-Wiki.md",
}


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

    def test_reviewable_wiki_source_is_complete_and_versioned(self) -> None:
        self.assertEqual(
            {path.name for path in WIKI_SOURCE_DIR.glob("*.md")},
            WIKI_PAGES | {"_Sidebar.md"},
        )

        current_version = get_version()
        applies_to_pattern = re.compile(
            rf"^> \*\*Applies to:\*\* GM2Godot {re.escape(current_version)} · "
            r"GameMaker LTS 2026 · Godot 4\.7\.1\s*$",
            re.MULTILINE,
        )
        reviewed_pattern = re.compile(
            r"^> \*\*Last reviewed:\*\* \d{4}-\d{2}-\d{2}\s*$",
            re.MULTILINE,
        )

        for filename in sorted(WIKI_PAGES):
            with self.subTest(page=filename):
                content = (WIKI_SOURCE_DIR / filename).read_text(encoding="utf-8")
                self.assertRegex(content, applies_to_pattern)
                self.assertRegex(content, reviewed_pattern)
                self.assertEqual(
                    set(re.findall(r"\bGM2Godot (\d+\.\d+\.\d+)\b", content)),
                    {current_version},
                )

    def test_wiki_sidebar_and_local_page_links_resolve(self) -> None:
        sidebar = (WIKI_SOURCE_DIR / "_Sidebar.md").read_text(encoding="utf-8")
        for filename in sorted(WIKI_PAGES):
            with self.subTest(sidebar_page=filename):
                self.assertIn(f"]({filename.removesuffix('.md')})", sidebar)

        markdown_link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        for source in sorted(WIKI_SOURCE_DIR.glob("*.md")):
            content = source.read_text(encoding="utf-8")
            for target in markdown_link_pattern.findall(content):
                target_without_fragment = target.split("#", 1)[0]
                if (
                    not target_without_fragment
                    or "://" in target_without_fragment
                    or target_without_fragment.startswith("mailto:")
                ):
                    continue
                target_filename = (
                    target_without_fragment
                    if target_without_fragment.endswith(".md")
                    else f"{target_without_fragment}.md"
                )
                with self.subTest(source=source.name, target=target):
                    self.assertIn(target_filename, WIKI_PAGES | {"_Sidebar.md"})
                    self.assertTrue((WIKI_SOURCE_DIR / target_filename).is_file())

    def test_user_documentation_links_and_guidance_are_current(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        contributing = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(
            encoding="utf-8"
        )
        maintenance = (PROJECT_ROOT / "docs" / "WIKI_MAINTENANCE.md").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "[Documentation](https://github.com/Infiland/GM2Godot/wiki) ·",
            readme,
        )
        self.assertIn("missing, empty, or an existing valid Godot project", readme)
        self.assertIn("Languages/template/template.json", contributing)
        self.assertNotIn("Languages/template.json", contributing)
        self.assertNotIn("modern_widgets.py", contributing)
        self.assertNotIn("Add community links", readme + contributing)
        self.assertNotIn("Add link if available", readme + contributing)
        self.assertIn("docs/wiki/", maintenance)
        self.assertIn("merged main-repository SHA", maintenance)
        self.assertIn("must not auto-close", maintenance)

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
