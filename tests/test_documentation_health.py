from __future__ import annotations

from pathlib import Path
import re
import unittest

from src.version import get_version


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIKI_SOURCE_DIR = PROJECT_ROOT / "docs" / "wiki"
WORKFLOW_DIR = PROJECT_ROOT / ".github" / "workflows"
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
WORKFLOW_USES_PATTERN = re.compile(
    r"^\s*(?:-\s*)?(?P<key_quote>['\"]?)uses(?P=key_quote)\s*:"
    r"\s*(?P<value>.*?)\s*$"
)
YAML_BLOCK_SCALAR_PATTERN = re.compile(
    r"^(?P<indent> *)(?:-\s*)?[^#\n]+:\s*[>|][1-9+-]*"
    r"\s*(?:#.*)?$"
)
FLOW_STYLE_USES_PATTERN = re.compile(
    r"\{[^{}]*?(?:['\"]uses['\"]|uses)\s*:"
    r"\s*(?P<value>[^,}]+)"
)
PINNED_EXTERNAL_ACTION_PATTERN = re.compile(
    r"^(?P<quote>['\"]?)"
    r"(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    r"(?:/[A-Za-z0-9_.-]+)*)"
    r"@(?P<sha>[0-9a-fA-F]{40})(?P=quote)"
    r"\s+#\s*"
    r"(?P<version>v(?P<major>0|[1-9]\d*)"
    r"\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)"
    r"\s*$"
)
APPROVED_NODE24_ACTION_MAJORS = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/cache": 5,
    "actions/upload-artifact": 6,
    "actions/download-artifact": 8,
    "softprops/action-gh-release": 3,
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

    def test_dependabot_updates_only_github_actions_weekly(self) -> None:
        dependabot = (
            PROJECT_ROOT / ".github" / "dependabot.yml"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            dependabot,
            'version: 2\n'
            'updates:\n'
            '  - package-ecosystem: "github-actions"\n'
            '    directory: "/"\n'
            '    schedule:\n'
            '      interval: "weekly"\n',
        )

    def test_external_workflow_actions_are_immutable_and_node24_native(
        self,
    ) -> None:
        workflows = sorted(
            [
                *WORKFLOW_DIR.glob("*.yml"),
                *WORKFLOW_DIR.glob("*.yaml"),
            ]
        )
        self.assertTrue(workflows)

        pins: dict[str, tuple[str, str, str]] = {}
        external_count = 0

        for workflow in workflows:
            lines = workflow.read_text(encoding="utf-8").splitlines()
            block_scalar_indent: int | None = None
            for line_number, line in enumerate(lines, start=1):
                stripped_line = line.strip()
                indentation = len(line) - len(line.lstrip(" "))
                if block_scalar_indent is not None:
                    if (
                        not stripped_line
                        or stripped_line.startswith("#")
                        or indentation > block_scalar_indent
                    ):
                        continue
                    block_scalar_indent = None

                location = (
                    f"{workflow.relative_to(PROJECT_ROOT)}:{line_number}"
                )
                uses_match = WORKFLOW_USES_PATTERN.match(line)
                if uses_match is None:
                    block_scalar_match = YAML_BLOCK_SCALAR_PATTERN.match(line)
                    if block_scalar_match is not None:
                        block_scalar_indent = len(
                            block_scalar_match.group("indent")
                        )
                        continue

                    flow_uses_match = FLOW_STYLE_USES_PATTERN.search(line)
                    if flow_uses_match is None:
                        continue

                    flow_value = flow_uses_match.group("value").strip()
                    unquoted_flow_value = (
                        flow_value[1:]
                        if flow_value[:1] in {'"', "'"}
                        else flow_value
                    )
                    if unquoted_flow_value.startswith(("./", "docker://")):
                        continue

                    external_count += 1
                    with self.subTest(location=location):
                        self.fail(
                            f"{location}: external uses must be on its own "
                            "line so its immutable pin can be verified"
                        )
                    continue

                raw_value = uses_match.group("value").strip()
                unquoted_value = (
                    raw_value[1:]
                    if raw_value[:1] in {'"', "'"}
                    else raw_value
                )
                if unquoted_value.startswith(("./", "docker://")):
                    continue

                external_count += 1
                pin_match = PINNED_EXTERNAL_ACTION_PATTERN.fullmatch(raw_value)

                with self.subTest(location=location):
                    self.assertIsNotNone(
                        pin_match,
                        f"{location}: external uses must be "
                        "<action>@<40-character SHA> # vMAJOR.MINOR.PATCH",
                    )
                if pin_match is None:
                    continue

                action = pin_match.group("action")
                sha = pin_match.group("sha").lower()
                version = pin_match.group("version")
                repository = "/".join(action.split("/")[:2]).casefold()
                approved_major = APPROVED_NODE24_ACTION_MAJORS.get(repository)

                with self.subTest(location=location, action=action):
                    self.assertIsNotNone(
                        approved_major,
                        f"{location}: review this action's runtime and add "
                        "its smallest Node-24-native major to "
                        "APPROVED_NODE24_ACTION_MAJORS",
                    )
                if approved_major is None:
                    continue

                with self.subTest(location=location, action=action):
                    self.assertEqual(
                        int(pin_match.group("major")),
                        approved_major,
                        f"{location}: use the approved smallest "
                        f"Node-24-native major v{approved_major}",
                    )

                action_key = action.casefold()
                observed_pin = (sha, version)
                previous_pin = pins.get(action_key)
                if previous_pin is None:
                    pins[action_key] = (sha, version, location)
                    continue

                with self.subTest(location=location, action=action):
                    self.assertEqual(
                        observed_pin,
                        previous_pin[:2],
                        f"{location}: {action} differs from "
                        f"{previous_pin[2]}",
                    )

        self.assertGreater(external_count, 0)


if __name__ == "__main__":
    unittest.main()
