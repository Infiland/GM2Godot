from __future__ import annotations

from pathlib import Path
import re
import unittest

from src.version import get_version


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestVersion(unittest.TestCase):
    def test_release_version_is_0_7_39(self) -> None:
        self.assertEqual(get_version(), "0.7.39")

    def test_release_surfaces_match_source_version(self) -> None:
        changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        issue_template = (
            PROJECT_ROOT / ".github" / "ISSUE_TEMPLATE" / "unsupported_gml_api.yml"
        ).read_text(encoding="utf-8")

        current_version = get_version()
        self.assertRegex(
            changelog,
            rf"(?m)^## {re.escape(current_version)} - \d{{4}}-\d{{2}}-\d{{2}}$",
        )
        self.assertIn(f"Current source version: `{current_version}`.", readme)
        self.assertIn(
            f"GM2Godot {current_version}, GameMaker LTS 2026, Godot 4.7.1",
            issue_template,
        )
        self.assertIn(
            "GM2Godot targets GameMaker LTS 2026 source projects and "
            "Godot 4.7.1 output.",
            readme,
        )
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
