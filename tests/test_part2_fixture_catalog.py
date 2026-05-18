from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from typing import TypedDict, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.conversion.gml_transpiler import category_issue_numbers, get_gml_api_entry


FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "part2"
CATALOG_PATH = FIXTURE_ROOT / "fixtures.json"
REQUIRED_BUCKETS = {
    "movement_collisions",
    "multi_room_transitions",
    "draw_text_surface",
    "audio_playback",
    "ds_collections_save_files",
    "async_http",
    "camera_view",
}


class UnsupportedAPIRef(TypedDict):
    api: str
    issue: int
    note: str


class Part2Fixture(TypedDict):
    id: str
    bucket: str
    title: str
    issue_numbers: list[int]
    manifest_entries: list[str]
    game_maker_source_path: str
    game_maker_expectation: str
    expected_godot_assertions: list[str]
    godot_assertion_paths: list[str]
    unsupported_api_issue_refs: list[UnsupportedAPIRef]


class Part2FixtureCatalog(TypedDict):
    issue: int
    required_buckets: list[str]
    unsupported_api_policy: str
    fixtures: list[Part2Fixture]


def _load_catalog() -> Part2FixtureCatalog:
    with CATALOG_PATH.open(encoding="utf-8") as file:
        return cast(Part2FixtureCatalog, json.load(file))


class TestPart2FixtureCatalog(unittest.TestCase):
    def test_catalog_covers_required_p0_buckets(self) -> None:
        catalog = _load_catalog()

        self.assertEqual(catalog["issue"], 518)
        self.assertEqual(set(catalog["required_buckets"]), REQUIRED_BUCKETS)
        self.assertEqual({fixture["bucket"] for fixture in catalog["fixtures"]}, REQUIRED_BUCKETS)

    def test_fixture_sources_manifest_links_and_assertion_paths_exist(self) -> None:
        known_issue_numbers = set(category_issue_numbers().values())

        for fixture in _load_catalog()["fixtures"]:
            with self.subTest(fixture=fixture["id"]):
                self.assertTrue(fixture["title"])
                self.assertTrue(fixture["game_maker_expectation"])
                self.assertGreaterEqual(len(fixture["expected_godot_assertions"]), 1)
                self.assertGreaterEqual(len(fixture["godot_assertion_paths"]), 1)
                self.assertTrue(set(fixture["issue_numbers"]).issubset(known_issue_numbers))

                source_path = FIXTURE_ROOT / fixture["game_maker_source_path"]
                self.assertTrue(source_path.is_file(), source_path)
                source = source_path.read_text(encoding="utf-8")
                self.assertIn("Fixture:", source)

                for api_name in fixture["manifest_entries"]:
                    entry = get_gml_api_entry(api_name)
                    self.assertIsNotNone(entry, api_name)
                    assert entry is not None
                    self.assertIn(entry.issue_number, fixture["issue_numbers"])

                for assertion_path in fixture["godot_assertion_paths"]:
                    self._assert_test_path_exists(assertion_path)

    def test_unsupported_api_refs_are_manifest_linked(self) -> None:
        catalog = _load_catalog()

        self.assertIn("manifest API name and issue number", catalog["unsupported_api_policy"])
        for fixture in catalog["fixtures"]:
            for unsupported_ref in fixture["unsupported_api_issue_refs"]:
                with self.subTest(fixture=fixture["id"], api=unsupported_ref["api"]):
                    entry = get_gml_api_entry(unsupported_ref["api"])
                    self.assertIsNotNone(entry)
                    assert entry is not None
                    self.assertEqual(entry.issue_number, unsupported_ref["issue"])
                    self.assertIn(entry.status, {"partial", "planned", "unsupported", "out_of_scope"})

    def test_manifest_exposes_full_game_fixture_entries(self) -> None:
        expected_fixture_entries = {
            "compatibility_fixture_suite",
            "part2_fixture_top_down_movement_collision",
            "part2_fixture_multi_room_transition",
            "part2_fixture_draw_text_surface",
            "part2_fixture_audio_playback",
            "part2_fixture_ds_collections_save_files",
            "part2_fixture_async_http_bridge",
            "part2_fixture_camera_view_behavior",
        }

        for api_name in expected_fixture_entries:
            with self.subTest(api=api_name):
                entry = get_gml_api_entry(api_name)
                self.assertIsNotNone(entry, api_name)
                assert entry is not None
                self.assertEqual(entry.category, "Full-Game Fixtures")
                self.assertEqual(entry.issue_number, 518)
                self.assertEqual(entry.status, "implemented")
                self.assertEqual(entry.smoke_coverage, "yes")

    def _assert_test_path_exists(self, assertion_path: str) -> None:
        module_path, separator, target = assertion_path.partition("::")
        self.assertEqual(separator, "::", assertion_path)
        class_name, method_separator, method_name = target.partition(".")
        self.assertEqual(method_separator, ".", assertion_path)

        test_path = PROJECT_ROOT / module_path
        self.assertTrue(test_path.is_file(), test_path)
        source = test_path.read_text(encoding="utf-8")
        self.assertRegex(source, rf"(?m)^class\s+{re.escape(class_name)}\b")
        self.assertRegex(source, rf"(?m)^\s+def\s+{re.escape(method_name)}\b")


if __name__ == "__main__":
    unittest.main()
