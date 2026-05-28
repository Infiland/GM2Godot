from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import cast

from src import cli
from src.conversion.architecture_policy import ARCHITECTURE_POLICY_RELATIVE_PATH
from src.conversion.conversion_manifest import (
    CONVERSION_MANIFEST_RELATIVE_PATH,
    build_conversion_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "golden" / "basic_scripts"


class TestConversionManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def test_convert_emits_deterministic_manifest_with_source_and_path_metadata(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        (godot_dir / "project.godot").write_text(
            '[application]\nconfig/name="Manifest Fixture"\n',
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
                "--max-warnings",
                "0",
            ]
        )

        self.assertEqual(exit_code, 0)
        manifest_path = godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        resources = cast(list[dict[str, object]], manifest["resources"])
        generated_files = cast(list[dict[str, object]], manifest["generated_files"])

        self.assertEqual(manifest["target_platform"], "windows")
        self.assertEqual(manifest["enabled_converters"], ["scripts"])
        self.assertEqual(
            cast(dict[str, object], manifest["architecture_policies"])["target_platform"],
            "windows",
        )
        self.assertTrue((godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH).is_file())
        self.assertTrue(
            any(
                resource["name"] == "scr_add"
                and resource["source_path"] == "scripts/scr_add/scr_add.yy"
                and resource["godot_path"] == "res://scripts/game/scr_add.gd"
                for resource in resources
            )
        )
        self.assertTrue(
            any(
                generated["path"] == "scripts/game/scr_add.gd.gmlmap.json"
                and generated["kind"] == "source_map"
                for generated in generated_files
            )
        )
        self.assertTrue(
            any(
                generated["path"] == ARCHITECTURE_POLICY_RELATIVE_PATH.replace("\\", "/")
                and generated["kind"] == "report"
                for generated in generated_files
            )
        )
        self.assertEqual(manifest["path_diagnostics"], [])

    def test_manifest_reports_collision_safe_generated_paths(self) -> None:
        gm_dir = self.temp_dir / "gm"
        godot_dir = self.temp_dir / "godot"
        gm_dir.mkdir()
        godot_dir.mkdir()
        (gm_dir / "CollisionTest.yyp").write_text(
            json.dumps(
                {
                    "resources": [
                        {"id": {"name": "Scr Spawn", "path": "scripts/Scr Spawn/Scr Spawn.yy"}},
                        {"id": {"name": "scr_spawn", "path": "scripts/scr_spawn/scr_spawn.yy"}},
                    ],
                    "RoomOrderNodes": [],
                    "resourceType": "GMProject",
                }
            ),
            encoding="utf-8",
        )
        for script_name in ("Scr Spawn", "scr_spawn"):
            script_dir = gm_dir / "scripts" / script_name
            script_dir.mkdir(parents=True)
            (script_dir / f"{script_name}.yy").write_text(
                json.dumps(
                    {
                        "%Name": script_name,
                        "name": script_name,
                        "parent": {"name": "Scripts", "path": "folders/Scripts.yy"},
                        "resourceType": "GMScript",
                    }
                ),
                encoding="utf-8",
            )

        manifest = build_conversion_manifest(
            str(gm_dir),
            str(godot_dir),
            target_platform="windows",
            enabled_converters=["scripts"],
        )
        resources = cast(list[dict[str, object]], manifest["resources"])

        self.assertEqual(
            {
                str(resource["name"]): str(resource["godot_path"])
                for resource in resources
            },
            {
                "Scr Spawn": "res://scripts/scr_spawn.gd",
                "scr_spawn": "res://scripts/scr_spawn_2.gd",
            },
        )
        self.assertTrue(
            any(
                diagnostic["code"] == "GM2GD-PATH-COLLISION-RENAMED"
                for diagnostic in cast(list[dict[str, object]], manifest["path_diagnostics"])
            )
        )


if __name__ == "__main__":
    unittest.main()
