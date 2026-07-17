from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, cast

from src.conversion.converter import CONVERSION_CATEGORIES, Converter
from src.conversion.diagnostics import DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
from src.conversion.godot_validation import (
    GodotValidationReport,
    generated_godot_importable_asset_paths,
    validate_generated_godot_project,
    write_godot_validation_report,
)
from src.gui.setting_value import SettingValue


REQUIRE_FIXTURES_ENV = "GM2GODOT_REQUIRE_LTS_FIXTURES"
OUTPUT_ROOT_ENV = "LTS_FIXTURE_OUTPUT_ROOT"
SNAP_PROJECT_ENV = "SNAP_PROJECT_PATH"
ADDING_PROJECT_ENV = "ADDING_PROJECT_PATH"

HISTORICAL_SNAP_SCRIPT_BLOCKERS = frozenset(
    {
        "SnapBufferReadGML",
        "SnapBufferReadYAML",
        "SnapBufferReadTilemapNew",
        "TestGlobalConstructor",
    }
)
# All four historical blockers convert on 0.7.0. Keeping the active set empty
# makes any regression fail rather than silently restoring an old exception.
ACTIVE_SNAP_SCRIPT_BLOCKERS: frozenset[str] = frozenset()
SNAP_CASE_COLLISION_MESSAGE = (
    "GML identifiers differ only by case in a Godot/GDScript output context: "
    "INDENT, indent"
)
EXPECTED_SNAP_WARNINGS = (
    (
        "warning",
        "GM2GD-GML-CASE-COLLISION",
        "SnapBufferReadYAML",
        "script",
        19,
        5,
        SNAP_CASE_COLLISION_MESSAGE,
    ),
    (
        "warning",
        "GM2GD-GML-CASE-COLLISION",
        "SnapBufferReadYAML",
        "script",
        315,
        5,
        SNAP_CASE_COLLISION_MESSAGE,
    ),
)
EXPECTED_ADDING_OPERATIONS = (
    "Equals (=)",
    "Inequal (≠)",
    "Approximately Equal (≈)",
    "Strict Inequality (>)",
    "Strict Inequality (<)",
    "Inequality (≥)",
    "Inequality (≤)",
    "Plus (+)",
    "Minus (-)",
    "Plus - Minus (±)",
    "Minus - Plus (±)",
    "Multiply (*)",
    "Times (×)",
    "Division (÷)",
    "Fraction (/)",
    "Modulo (%)",
    "Power (^)",
    "Square Root (√)",
    "Percent (%)",
    "Per-Mille (‰)",
)
GODOT_LOADABLE_EXTENSIONS = frozenset({".gd", ".gdshader", ".tscn", ".tres"})


@dataclass(frozen=True)
class FixtureSpec:
    name: str
    project_env: str
    project_filename: str
    expected_ide_version: str
    expected_script_count: int
    expected_resource_type_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class FixtureResult:
    spec: FixtureSpec
    source_path: Path
    godot_path: Path
    source_script_names: frozenset[str]
    manifest: dict[str, Any]
    diagnostics: dict[str, Any]
    primary_script_entries: tuple[dict[str, Any], ...]
    validation: GodotValidationReport
    logs: tuple[str, ...]

    def summary(self) -> dict[str, object]:
        diagnostic_summary = cast(dict[str, Any], self.diagnostics["summary"])
        source_project = cast(dict[str, Any], self.manifest["source_project"])
        return {
            "fixture": self.spec.name,
            "ide_version": source_project["ide_version"],
            "source_script_count": len(self.source_script_names),
            "generated_script_count": len(self.primary_script_entries),
            "conversion_warning_count": diagnostic_summary["warning"],
            "conversion_error_count": diagnostic_summary["error"],
            "godot_status": self.validation.status,
            "godot_resource_count": len(self.validation.resource_paths),
            "godot_import_returncode": self.validation.import_returncode,
            "godot_validation_returncode": self.validation.returncode,
            "godot_boot_returncode": self.validation.boot_returncode,
            "godot_output_issue_count": len(self.validation.output_issues),
        }


FIXTURE_SPECS = (
    FixtureSpec(
        name="snap",
        project_env=SNAP_PROJECT_ENV,
        project_filename="snap.yyp",
        expected_ide_version="2026.0.0.15",
        expected_script_count=76,
        expected_resource_type_counts=(
            ("included_file", 1),
            ("object", 19),
            ("room", 1),
            ("script", 123),
            ("sprite", 1),
        ),
    ),
    FixtureSpec(
        name="adding",
        project_env=ADDING_PROJECT_ENV,
        project_filename="Adding.yyp",
        expected_ide_version="2026.0.0.16",
        expected_script_count=4,
        expected_resource_type_counts=(
            ("object", 1),
            ("room", 1),
            ("script", 4),
        ),
    ),
)


def _resolve_fixture_path(spec: FixtureSpec) -> Path | None:
    raw_path = os.environ.get(spec.project_env)
    if raw_path:
        path = Path(raw_path).resolve()
        if path.is_dir() and (path / spec.project_filename).is_file():
            return path
    if os.environ.get(REQUIRE_FIXTURES_ENV) == "1":
        raise RuntimeError(
            f"{spec.project_env} must name a directory containing "
            f"{spec.project_filename} when {REQUIRE_FIXTURES_ENV}=1."
        )
    return None


RESOLVED_FIXTURES = {
    spec.name: resolved_path
    for spec in FIXTURE_SPECS
    if (resolved_path := _resolve_fixture_path(spec)) is not None
}


def _load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _primary_script_entries(manifest: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    resources = cast(list[dict[str, Any]], manifest["resources"])
    entries: list[dict[str, Any]] = []
    for entry in resources:
        metadata = cast(dict[str, Any], entry.get("metadata", {}))
        if entry.get("type") == "script" and not metadata.get("script_function", False):
            entries.append(entry)
    return tuple(sorted(entries, key=lambda entry: str(entry["name"])))


def _convert_fixture(
    spec: FixtureSpec,
    source_path: Path,
    output_root: Path,
) -> FixtureResult:
    godot_path = output_root / spec.name
    godot_path.mkdir(parents=True, exist_ok=False)
    (godot_path / "project.godot").write_text(
        '[application]\nconfig/name="GM2Godot LTS 2026 CI Probe"\n',
        encoding="utf-8",
    )

    all_keys = (
        CONVERSION_CATEGORIES["assets"]
        + CONVERSION_CATEGORIES["project"]
        + CONVERSION_CATEGORIES["wip"]
    )
    settings = {key: SettingValue(True) for key in all_keys}
    logs: list[str] = []
    conversion_running = threading.Event()
    conversion_running.set()

    def log_message(message: object) -> None:
        logs.append(str(message))

    def ignore_progress(_value: object) -> None:
        return None

    def ignore_status(_message: object) -> None:
        return None

    converter = cast(Any, Converter)(
        log_callback=log_message,
        progress_callback=ignore_progress,
        status_callback=ignore_status,
        conversion_running=conversion_running,
        compact_logging=True,
    )
    converter.convert(str(source_path), "windows", str(godot_path), settings)

    manifest = _load_json(godot_path / "gm2godot" / "conversion_manifest.json")
    diagnostics = _load_json(godot_path / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
    validation = validate_generated_godot_project(
        str(godot_path),
        timeout=180,
        load_resources=True,
        boot_frames=2,
    )
    write_godot_validation_report(str(godot_path), validation)
    source_script_names = frozenset(
        path.stem for path in (source_path / "scripts").rglob("*.gml")
    )
    return FixtureResult(
        spec=spec,
        source_path=source_path,
        godot_path=godot_path,
        source_script_names=source_script_names,
        manifest=manifest,
        diagnostics=diagnostics,
        primary_script_entries=_primary_script_entries(manifest),
        validation=validation,
        logs=tuple(logs),
    )


class TestLTS2026Policy(unittest.TestCase):
    def test_snap_blocker_allowlist_can_only_shrink(self) -> None:
        self.assertLessEqual(
            ACTIVE_SNAP_SCRIPT_BLOCKERS,
            HISTORICAL_SNAP_SCRIPT_BLOCKERS,
        )
        self.assertEqual(ACTIVE_SNAP_SCRIPT_BLOCKERS, frozenset())


@unittest.skipUnless(
    len(RESOLVED_FIXTURES) == len(FIXTURE_SPECS),
    "SNAP_PROJECT_PATH and ADDING_PROJECT_PATH are not both available.",
)
class TestLTS2026Conversion(unittest.TestCase):
    results: ClassVar[dict[str, FixtureResult]]
    output_root: ClassVar[Path]
    temporary_output: ClassVar[tempfile.TemporaryDirectory[str] | None]

    @classmethod
    def setUpClass(cls) -> None:
        configured_output_root = os.environ.get(OUTPUT_ROOT_ENV)
        if configured_output_root:
            cls.temporary_output = None
            cls.output_root = Path(configured_output_root).resolve()
            cls.output_root.mkdir(parents=True, exist_ok=True)
        else:
            cls.temporary_output = tempfile.TemporaryDirectory(
                prefix="gm2godot_lts_2026_"
            )
            cls.output_root = Path(cls.temporary_output.name)

        cls.results = {}
        try:
            for spec in FIXTURE_SPECS:
                source_path = RESOLVED_FIXTURES[spec.name]
                cls.results[spec.name] = _convert_fixture(
                    spec,
                    source_path,
                    cls.output_root,
                )
        finally:
            summary_path = cls.output_root / "lts_fixture_report.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "fixtures": [
                            cls.results[name].summary()
                            for name in sorted(cls.results)
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.temporary_output is not None:
            cls.temporary_output.cleanup()

    def _assert_common_fixture_contract(self, result: FixtureResult) -> None:
        spec = result.spec
        source_project = cast(dict[str, Any], result.manifest["source_project"])
        resources = cast(list[dict[str, Any]], result.manifest["resources"])
        self.assertEqual(source_project["ide_version"], spec.expected_ide_version)
        self.assertEqual(len(result.source_script_names), spec.expected_script_count)
        self.assertEqual(len(result.primary_script_entries), spec.expected_script_count)
        self.assertEqual(
            {str(entry["name"]) for entry in result.primary_script_entries},
            set(result.source_script_names),
        )

        generated_paths = [
            str(entry["godot_path"])
            for entry in result.primary_script_entries
        ]
        self.assertEqual(len(generated_paths), len(set(generated_paths)))
        resource_type_counts = Counter(str(entry["type"]) for entry in resources)
        self.assertEqual(
            dict(resource_type_counts),
            dict(spec.expected_resource_type_counts),
        )
        validation_paths = set(result.validation.resource_paths)
        for resource in resources:
            generated_path = str(resource["godot_path"])
            with self.subTest(
                fixture=spec.name,
                resource=resource["name"],
                generated_path=generated_path,
            ):
                self.assertTrue(generated_path.startswith("res://"))
                relative_path = generated_path.removeprefix("res://")
                self.assertTrue((result.godot_path / relative_path).is_file())
                if Path(relative_path).suffix.lower() in GODOT_LOADABLE_EXTENSIONS:
                    self.assertIn(generated_path, validation_paths)

        diagnostic_summary = cast(dict[str, Any], result.diagnostics["summary"])
        self.assertEqual(diagnostic_summary["error"], 0)
        self.assertNotIn("Traceback", "\n".join(result.logs))

        validation = result.validation
        self.assertEqual(validation.status, "passed", validation.message + "\n" + validation.output)
        importable_assets = generated_godot_importable_asset_paths(str(result.godot_path))
        if importable_assets:
            self.assertEqual(validation.import_returncode, 0, validation.import_output)
        else:
            self.assertIsNone(validation.import_returncode, validation.import_output)
        self.assertEqual(validation.returncode, 0, validation.output)
        self.assertEqual(validation.boot_returncode, 0, validation.boot_output)
        self.assertEqual(validation.boot_frames, 2)
        self.assertEqual(validation.output_issues, (), validation.output)

    def test_adding_converts_all_scripts_without_diagnostics(self) -> None:
        result = self.results["adding"]
        self._assert_common_fixture_contract(result)
        diagnostic_summary = cast(dict[str, Any], result.diagnostics["summary"])

        self.assertEqual(diagnostic_summary["warning"], 0)
        operation_names = [
            line.partition("Adding: Performed ")[2].partition(" on ")[0]
            for line in result.validation.boot_output.splitlines()
            if "Adding: Performed " in line
        ]
        self.assertCountEqual(
            operation_names,
            EXPECTED_ADDING_OPERATIONS,
            result.validation.boot_output,
        )

    def test_snap_converts_all_scripts_with_only_known_case_collisions(self) -> None:
        result = self.results["snap"]
        self._assert_common_fixture_contract(result)
        diagnostics = cast(list[dict[str, Any]], result.diagnostics["diagnostics"])
        warnings = [
            diagnostic
            for diagnostic in diagnostics
            if diagnostic.get("severity") == "warning"
        ]
        warning_tuples = tuple(
            (
                diagnostic.get("severity"),
                diagnostic.get("code"),
                diagnostic.get("resource"),
                diagnostic.get("resource_type"),
                diagnostic.get("line"),
                diagnostic.get("column"),
                diagnostic.get("message"),
            )
            for diagnostic in warnings
        )
        observed_blockers = frozenset(
            str(diagnostic["resource"])
            for diagnostic in diagnostics
            if diagnostic.get("code") == "GM2GD-GML-TRANSPILE"
            and diagnostic.get("resource_type") == "script"
            and diagnostic.get("resource")
        )

        self.assertEqual(observed_blockers, ACTIVE_SNAP_SCRIPT_BLOCKERS)
        self.assertCountEqual(warning_tuples, EXPECTED_SNAP_WARNINGS)


if __name__ == "__main__":
    unittest.main()
