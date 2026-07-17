from __future__ import annotations

from pathlib import Path
import unittest

from src.version import get_version


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestVersion(unittest.TestCase):
    def test_release_version_is_0_7_0(self) -> None:
        self.assertEqual(get_version(), "0.7.0")

    def test_release_docs_reference_0_7_0(self) -> None:
        changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## 0.7.0 - 2026-07-17", changelog)
        self.assertIn("Current source version: `0.7.0`.", readme)
        self.assertIn("GameMaker LTS 2026", changelog)
        self.assertIn("## 0.6.1 - 2026-05-28", changelog)
        self.assertIn("converter inventory discovery", changelog)
        self.assertIn("## 0.6.0 - 2026-05-28", changelog)
        self.assertIn("Milestone audit", changelog)


if __name__ == "__main__":
    unittest.main()
