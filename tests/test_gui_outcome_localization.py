from __future__ import annotations

import json
from pathlib import Path
import re
import unittest
from typing import cast


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATHS = (
    PROJECT_ROOT / "Languages" / "eng.json",
    PROJECT_ROOT / "Languages" / "de.json",
    PROJECT_ROOT / "Languages" / "template" / "template.json",
)
OUTCOME_PLACEHOLDERS: dict[str, set[str]] = {
    "Console_ConversionFailedState": set(),
    "Console_ConversionPartial": set(),
    "Console_ConversionResourceCounts": {
        "requested",
        "executed",
        "completed",
        "skipped",
        "failed",
    },
    "Console_ConversionDiagnostics": {"report_path"},
}
PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class GuiOutcomeLocalizationTests(unittest.TestCase):
    def test_terminal_outcome_keys_have_matching_placeholders(self) -> None:
        for catalog_path in CATALOG_PATHS:
            with self.subTest(catalog=catalog_path.relative_to(PROJECT_ROOT)):
                with catalog_path.open(encoding="utf-8") as catalog_file:
                    catalog = cast(dict[str, object], json.load(catalog_file))

                for key, expected_placeholders in OUTCOME_PLACEHOLDERS.items():
                    value = catalog.get(key)
                    self.assertIsInstance(value, str, key)
                    self.assertTrue(value, key)
                    self.assertEqual(
                        set(PLACEHOLDER_PATTERN.findall(cast(str, value))),
                        expected_placeholders,
                        key,
                    )

    def test_english_and_german_catalog_keys_remain_aligned(self) -> None:
        catalogs: list[dict[str, object]] = []
        for catalog_path in CATALOG_PATHS[:2]:
            with catalog_path.open(encoding="utf-8") as catalog_file:
                catalogs.append(cast(dict[str, object], json.load(catalog_file)))

        self.assertEqual(set(catalogs[0]), set(catalogs[1]))


if __name__ == "__main__":
    unittest.main()
