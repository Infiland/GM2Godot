from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import TypedDict, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.conversion.conversion_manifest import CONVERSION_MANIFEST_RELATIVE_PATH
from src.conversion.architecture_policy import ARCHITECTURE_POLICY_RELATIVE_PATH
from src.conversion.converter import Converter
from src.conversion.diagnostics import DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH


FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "part2"
CORPUS_PATH = FIXTURE_ROOT / "corpus.json"
REQUIRED_RESOURCE_AREAS = {
    "shaders",
    "materials",
    "paths",
    "timelines",
    "sequences",
    "particles",
    "physics",
    "tilemaps",
    "views_layer_inheritance",
    "extensions",
    "macros_configs",
    "included_files",
    "fonts",
    "texture_groups",
    "audio_groups",
    "options",
}
REQUIRED_TRACE_IDS = {
    "event_order",
    "alarms",
    "input",
    "collision",
    "draw_order",
    "async",
    "rooms_persistence_lifecycle",
    "physics",
    "data_structures",
}


class CorpusResourceArea(TypedDict):
    area: str
    resource_type: str
    game_maker_resource_path: str
    source_path: str
    assertion_paths: list[str]


class CorpusTraceSpec(TypedDict):
    id: str
    expected_trace: list[str]
    assertion_paths: list[str]


class CorpusVisualSpec(TypedDict):
    id: str
    feature: str
    pixel_check: bool
    assertion_paths: list[str]


class CorpusMalformedFixture(TypedDict):
    id: str
    project_path: str
    expected_diagnostic_code: str
    expected_log_fragment: str
    continued_outputs: list[str]


class CorpusCoverageBudget(TypedDict):
    required_resource_area_count: int
    minimum_golden_trace_count: int
    minimum_visual_regression_count: int
    minimum_malformed_fixture_count: int


class Part2Corpus(TypedDict):
    issue: int
    resource_matrix_project: str
    required_resource_areas: list[CorpusResourceArea]
    golden_trace_specs: list[CorpusTraceSpec]
    visual_regression_specs: list[CorpusVisualSpec]
    malformed_fixture_projects: list[CorpusMalformedFixture]
    coverage_budget: CorpusCoverageBudget


class _Setting:
    def __init__(self, value: bool) -> None:
        self._value = value

    def get(self) -> bool:
        return self._value


def _load_corpus() -> Part2Corpus:
    with CORPUS_PATH.open(encoding="utf-8") as file:
        return cast(Part2Corpus, json.load(file))


class TestPart2FixtureCorpus(unittest.TestCase):
    def test_resource_matrix_covers_required_milestone_areas(self) -> None:
        corpus = _load_corpus()
        areas = corpus["required_resource_areas"]
        budget = corpus["coverage_budget"]

        self.assertEqual(corpus["issue"], 610)
        self.assertEqual({entry["area"] for entry in areas}, REQUIRED_RESOURCE_AREAS)
        self.assertGreaterEqual(len(areas), budget["required_resource_area_count"])
        self.assertTrue((FIXTURE_ROOT / corpus["resource_matrix_project"]).is_file())

        for entry in areas:
            with self.subTest(area=entry["area"]):
                resource_path = FIXTURE_ROOT / entry["game_maker_resource_path"]
                source_path = FIXTURE_ROOT / entry["source_path"]
                self.assertTrue(resource_path.is_file(), resource_path)
                self.assertTrue(source_path.is_file(), source_path)
                self.assertIn("Fixture:", source_path.read_text(encoding="utf-8"))
                self.assertGreaterEqual(len(entry["assertion_paths"]), 1)
                for assertion_path in entry["assertion_paths"]:
                    self._assert_test_path_exists(assertion_path)

                if resource_path.suffix == ".yy":
                    data = json.loads(resource_path.read_text(encoding="utf-8"))
                    self.assertEqual(data["resourceType"], entry["resource_type"])

    def test_resource_matrix_yyp_links_committed_resources(self) -> None:
        corpus = _load_corpus()
        yyp_path = FIXTURE_ROOT / corpus["resource_matrix_project"]
        yyp_data = cast(dict[str, object], json.loads(yyp_path.read_text(encoding="utf-8")))
        resources = cast(list[object], yyp_data["resources"])
        yyp_resource_paths: set[str] = set()
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            typed_resource = cast(dict[object, object], resource)
            resource_id = typed_resource.get("id")
            if not isinstance(resource_id, dict):
                continue
            typed_resource_id = cast(dict[object, object], resource_id)
            path = typed_resource_id.get("path")
            if isinstance(path, str):
                yyp_resource_paths.add(path)

        self.assertIn("AudioGroups", yyp_data)
        self.assertIn("TextureGroups", yyp_data)
        for entry in corpus["required_resource_areas"]:
            resource_path = entry["game_maker_resource_path"].removeprefix("projects/resource_matrix/")
            if resource_path.endswith(".yy") and not resource_path.startswith(("options/", "audiogroups/", "texturegroups/", "materials/")):
                self.assertIn(resource_path, yyp_resource_paths)

    def test_golden_trace_specs_have_executable_assertion_paths(self) -> None:
        corpus = _load_corpus()
        traces = corpus["golden_trace_specs"]
        budget = corpus["coverage_budget"]

        self.assertEqual({trace["id"] for trace in traces}, REQUIRED_TRACE_IDS)
        self.assertGreaterEqual(len(traces), budget["minimum_golden_trace_count"])
        for trace in traces:
            with self.subTest(trace=trace["id"]):
                self.assertGreaterEqual(len(trace["expected_trace"]), 1)
                for assertion_path in trace["assertion_paths"]:
                    self._assert_test_path_exists(assertion_path)

    def test_visual_regression_specs_reference_pixel_or_render_assertions(self) -> None:
        corpus = _load_corpus()
        visuals = corpus["visual_regression_specs"]
        budget = corpus["coverage_budget"]

        self.assertGreaterEqual(len(visuals), budget["minimum_visual_regression_count"])
        self.assertTrue(any(spec["pixel_check"] for spec in visuals))
        for spec in visuals:
            with self.subTest(visual=spec["id"]):
                self.assertTrue(spec["feature"])
                for assertion_path in spec["assertion_paths"]:
                    test_path = self._assert_test_path_exists(assertion_path)
                    source = test_path.read_text(encoding="utf-8")
                    if spec["pixel_check"]:
                        self.assertRegex(source, r"get_pixel|Color\(")

    def test_malformed_fixtures_record_diagnostics_and_continue_outputs(self) -> None:
        corpus = _load_corpus()
        self.assertGreaterEqual(
            len(corpus["malformed_fixture_projects"]),
            corpus["coverage_budget"]["minimum_malformed_fixture_count"],
        )

        for malformed in corpus["malformed_fixture_projects"]:
            with self.subTest(fixture=malformed["id"]):
                gm_project = FIXTURE_ROOT / malformed["project_path"]
                gm_dir = gm_project.parent
                godot_dir = Path(tempfile.mkdtemp())
                logs: list[str] = []
                statuses: list[str] = []
                conversion_running = threading.Event()
                conversion_running.set()
                try:
                    (godot_dir / "project.godot").write_text(
                        '[application]\nconfig/name="Malformed Fixture"\n',
                        encoding="utf-8",
                    )
                    converter = Converter(
                        log_callback=lambda message: logs.append(str(message)),
                        progress_callback=lambda _value: None,
                        status_callback=lambda message: statuses.append(str(message)),
                        conversion_running=conversion_running,
                        max_workers=1,
                    )
                    converter.convert(
                        str(gm_dir),
                        "windows",
                        str(godot_dir),
                        {"asset_registry": _Setting(True)},
                    )

                    for relative_path in malformed["continued_outputs"]:
                        self.assertTrue((godot_dir / relative_path).is_file(), relative_path)
                    diagnostics = json.loads(
                        (godot_dir / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH).read_text(encoding="utf-8")
                    )
                    codes = [diagnostic["code"] for diagnostic in diagnostics["diagnostics"]]
                    self.assertIn(malformed["expected_diagnostic_code"], codes)
                    self.assertTrue((godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH).is_file())
                    self.assertTrue((godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH).is_file())
                    self.assertTrue(
                        any(malformed["expected_log_fragment"] in log for log in logs),
                        logs,
                    )
                finally:
                    shutil.rmtree(godot_dir)

    def _assert_test_path_exists(self, assertion_path: str) -> Path:
        module_path, separator, target = assertion_path.partition("::")
        self.assertEqual(separator, "::", assertion_path)
        class_name, method_separator, method_name = target.partition(".")
        self.assertEqual(method_separator, ".", assertion_path)

        test_path = PROJECT_ROOT / module_path
        self.assertTrue(test_path.is_file(), test_path)
        source = test_path.read_text(encoding="utf-8")
        self.assertRegex(source, rf"(?m)^class\s+{re.escape(class_name)}\b")
        self.assertRegex(source, rf"(?m)^\s+def\s+{re.escape(method_name)}\b")
        return test_path


if __name__ == "__main__":
    unittest.main()
