from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import cli


FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "golden" / "basic_scripts"
SNAPSHOT_PATH = FIXTURE_ROOT / "expected_snapshot.json"


class TestGoldenConversion(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def test_basic_scripts_conversion_matches_golden_snapshot(self) -> None:
        godot_dir = self.temp_dir / "godot"
        report_dir = self.temp_dir / "reports"
        godot_dir.mkdir()
        (godot_dir / "project.godot").write_text(
            '[application]\nconfig/name="Golden Fixture"\n',
            encoding="utf-8",
        )

        exit_code = cli.main(
            [
                "convert",
                "--gm-project",
                str(FIXTURE_ROOT),
                "--godot-project",
                str(godot_dir),
                "--target-platform",
                "windows",
                "--only",
                "scripts",
                "--report-dir",
                str(report_dir),
                "--max-warnings",
                "0",
                "--max-errors",
                "0",
                "--max-unsupported",
                "0",
            ]
        )

        self.assertEqual(exit_code, 0)
        actual = _snapshot_output(godot_dir, FIXTURE_ROOT)
        expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(actual, expected)


def _snapshot_output(godot_dir: Path, gm_project_dir: Path) -> dict[str, object]:
    text_files = [
        "project.godot",
        "gm2godot/gml_script_registry.gd",
        "scripts/game/scr_add.gd",
        "scripts/game/scr_stats.gd",
    ]
    json_files = [
        "gm2godot/conversion_diagnostics.json",
        "scripts/game/scr_add.gd.gmlmap.json",
        "scripts/game/scr_stats.gd.gmlmap.json",
    ]
    hash_files = [
        "gm2godot/gml_runtime.gd",
        *(
            _relative_path(path, godot_dir)
            for path in sorted((godot_dir / "gm2godot" / "managers").glob("*.gd"))
        ),
    ]

    return {
        "fixture": "basic_scripts",
        "files": {
            path: _normalize_text((godot_dir / path).read_text(encoding="utf-8"), godot_dir, gm_project_dir)
            for path in text_files
        },
        "json_files": {
            path: _normalize_json(
                json.loads((godot_dir / path).read_text(encoding="utf-8")),
                godot_dir,
                gm_project_dir,
            )
            for path in json_files
        },
        "hashes": {
            path: "sha256:" + hashlib.sha256((godot_dir / path).read_bytes()).hexdigest()
            for path in hash_files
        },
    }


def _normalize_json(value: object, godot_dir: Path, gm_project_dir: Path) -> object:
    if isinstance(value, dict):
        typed_dict = cast(dict[object, object], value)
        return {
            str(key): _normalize_json(child, godot_dir, gm_project_dir)
            for key, child in sorted(typed_dict.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [
            _normalize_json(child, godot_dir, gm_project_dir)
            for child in cast(list[object], value)
        ]
    if isinstance(value, str):
        return _normalize_text(value, godot_dir, gm_project_dir)
    return value


def _normalize_text(value: str, godot_dir: Path, gm_project_dir: Path) -> str:
    normalized = value.replace(str(godot_dir), "<GODOT_PROJECT>")
    normalized = normalized.replace(str(gm_project_dir), "<GM_PROJECT>")
    return normalized.replace(os.sep, "/")


def _relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


if __name__ == "__main__":
    unittest.main()
