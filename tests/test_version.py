from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.version import get_version

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestVersion(unittest.TestCase):
    def test_release_version_is_0_7_75(self) -> None:
        self.assertEqual(get_version(), "0.7.75")

    def test_release_surfaces_match_source_version(self) -> None:
        version_source = (PROJECT_ROOT / "src" / "version.py").read_text(
            encoding="utf-8"
        )
        changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        issue_template = (
            PROJECT_ROOT / ".github" / "ISSUE_TEMPLATE" / "unsupported_gml_api.yml"
        ).read_text(encoding="utf-8")

        current_version = get_version()
        source_assignment = f'VERSION = "{current_version}"'
        self.assertTrue(version_source.startswith(source_assignment + "\n"))
        self.assertEqual(version_source.count(source_assignment), 1)

        changelog_heading_pattern = (
            rf"## {re.escape(current_version)} - \d{{4}}-\d{{2}}-\d{{2}}"
        )
        self.assertRegex(
            changelog,
            rf"\A# Changelog\n\n{changelog_heading_pattern}\n",
        )
        self.assertEqual(
            len(
                re.findall(
                    rf"(?m)^{changelog_heading_pattern}$",
                    changelog,
                )
            ),
            1,
        )
        current_source_line = f"Current source version: `{current_version}`."
        self.assertRegex(
            readme,
            rf"(?m)^## Releases\n\n{re.escape(current_source_line)}$",
        )
        self.assertEqual(
            readme.count(current_source_line),
            1,
        )
        release_label = (
            f"GM2Godot {current_version}, GameMaker LTS 2026, Godot 4.7.2"
        )
        _, versions_separator, versions_section = issue_template.partition(
            "  - type: input\n    id: versions\n"
        )
        self.assertTrue(versions_separator, "Versions issue-form input is missing")
        versions_section = versions_section.partition("\n  - type: ")[0]
        self.assertRegex(
            versions_section,
            rf'(?m)^      placeholder: "{re.escape(release_label)}, Windows"$',
        )
        self.assertEqual(versions_section.count(release_label), 1)

        wiki_banner = (
            f"> **Applies to:** GM2Godot {current_version} · "
            "GameMaker LTS 2026 · Godot 4.7.2"
        )
        expected_wiki_pages = {
            "Compatibility-and-Limitations.md": "# Compatibility and Limitations",
            "Contributing-and-Testing.md": "# Contributing and Testing",
            "Diagnostics-and-Troubleshooting.md": "# Diagnostics and Troubleshooting",
            "Generated-Project-and-Runtime.md": "# Generated Project and Runtime",
            "Home.md": "# GM2Godot Documentation",
            "Installation.md": "# Installation",
            "Maintainer-Release-and-Wiki.md": "# Release and Wiki Maintenance",
            "Quick-Start-Conversion.md": "# Quick Start Conversion",
        }
        wiki_directory = PROJECT_ROOT / "docs" / "wiki"
        observed_wiki_pages = {
            path.name
            for path in wiki_directory.glob("*.md")
            if not path.name.startswith("_")
        }
        self.assertEqual(observed_wiki_pages, set(expected_wiki_pages))
        for page_name, title in expected_wiki_pages.items():
            with self.subTest(wiki_page=page_name):
                content = (wiki_directory / page_name).read_text(encoding="utf-8")
                self.assertTrue(
                    content.startswith(f"{title}\n\n{wiki_banner}\n"),
                    f"{page_name} must place its release banner directly below its title",
                )
                self.assertEqual(
                    content.count(wiki_banner),
                    1,
                )
        self.assertIn(
            "GM2Godot targets GameMaker LTS 2026 source projects and "
            "Godot 4.7.2 output.",
            readme,
        )
        self.assertIn("## 0.7.57 - 2026-09-02", changelog)
        self.assertIn("`pip==26.2.1` and `pip-tools==7.6.1`", changelog)
        self.assertIn("## 0.7.5 - 2026-07-18", changelog)
        self.assertIn("## 0.7.4 - 2026-07-18", changelog)
        self.assertIn("## 0.7.1 - 2026-07-17", changelog)
        self.assertIn("immutable GameMaker LTS 2026 SNAP and Adding fixtures", changelog)
        self.assertIn("## 0.7.0 - 2026-07-17", changelog)
        self.assertIn("GameMaker LTS 2026", changelog)
        self.assertIn("## 0.6.1 - 2026-05-28", changelog)
        self.assertIn("converter inventory discovery", changelog)
        self.assertIn("## 0.6.0 - 2026-05-28", changelog)
        self.assertIn("Milestone audit", changelog)


if __name__ == "__main__":
    unittest.main()
