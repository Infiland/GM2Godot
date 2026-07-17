from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import TextIO, cast
from unittest.mock import patch

from src import cli
from src.conversion.architecture_policy import ARCHITECTURE_POLICY_RELATIVE_PATH
from src.conversion.conversion_manifest import (
    CONVERSION_MANIFEST_RELATIVE_PATH,
    build_conversion_manifest,
    capture_conversion_output_snapshot,
    write_conversion_manifest,
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
            cast(dict[str, object], manifest["source_project"])["ide_version"],
            "",
        )
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
            output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
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

    def test_manifest_records_source_project_ide_version(self) -> None:
        gm_dir = self.temp_dir / "gm"
        godot_dir = self.temp_dir / "godot"
        gm_dir.mkdir()
        godot_dir.mkdir()
        (gm_dir / "Versioned.yyp").write_text(
            json.dumps(
                {
                    "%Name": "Versioned",
                    "resourceType": "GMProject",
                    "resourceVersion": "1.7",
                    "MetaData": {"IDEVersion": "2026.0.1.123"},
                    "resources": [],
                }
            ),
            encoding="utf-8",
        )

        manifest = build_conversion_manifest(
            str(gm_dir),
            str(godot_dir),
            target_platform="windows",
            enabled_converters=[],
            output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
        )

        source_project = cast(dict[str, object], manifest["source_project"])
        self.assertEqual(source_project["name"], "Versioned")
        self.assertEqual(source_project["ide_version"], "2026.0.1.123")

    def test_generated_files_include_emitted_binary_files_but_not_preexisting_files(self) -> None:
        gm_dir = self.temp_dir / "gm"
        godot_dir = self.temp_dir / "godot"
        datafiles_dir = gm_dir / "datafiles"
        datafiles_dir.mkdir(parents=True)
        godot_dir.mkdir()
        (gm_dir / "BinaryOutputs.yyp").write_text(
            json.dumps(
                {
                    "%Name": "BinaryOutputs",
                    "resourceType": "GMProject",
                    "resources": [],
                }
            ),
            encoding="utf-8",
        )
        emitted_files = {
            "art.png": b"\x89PNG\r\n\x1a\nconverted-image",
            "tone.wav": b"RIFF\x10\x00\x00\x00WAVEconverted-audio",
            "ui.ttf": b"\x00\x01\x00\x00converted-font",
        }
        for filename, content in emitted_files.items():
            (datafiles_dir / filename).write_bytes(content)

        (godot_dir / "project.godot").write_text(
            '[application]\nconfig/name="Existing Project"\n',
            encoding="utf-8",
        )
        (godot_dir / "unrelated.png").write_bytes(b"pre-existing image")
        (godot_dir / "custom.gd").write_text("extends Node\n", encoding="utf-8")

        exit_code = cli.main(
            [
                "convert",
                "--gm-project",
                str(gm_dir),
                "--godot-project",
                str(godot_dir),
                "--target-platform",
                "windows",
                "--only",
                "included_files",
                "--max-warnings",
                "0",
            ]
        )

        self.assertEqual(exit_code, 0)
        manifest = json.loads(
            (godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        generated_files = cast(list[dict[str, object]], manifest["generated_files"])
        generated_by_path = {
            str(entry["path"]): entry
            for entry in generated_files
        }
        expected_kinds = {
            "art.png": "image",
            "tone.wav": "audio",
            "ui.ttf": "font",
        }
        for filename, kind in expected_kinds.items():
            relative_path = f"included_files/{filename}"
            self.assertEqual(generated_by_path[relative_path]["kind"], kind)
            expected_hash = "sha256:" + hashlib.sha256(emitted_files[filename]).hexdigest()
            self.assertEqual(generated_by_path[relative_path]["sha256"], expected_hash)

        self.assertNotIn("unrelated.png", generated_by_path)
        self.assertNotIn("custom.gd", generated_by_path)
        self.assertNotIn("project.godot", generated_by_path)

    def test_manifest_is_published_from_fsynced_same_directory_staged_file(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        snapshot = capture_conversion_output_snapshot(str(godot_dir))
        real_replace = os.replace
        real_fsync = os.fsync

        with (
            patch(
                "src.conversion.conversion_manifest.os.replace",
                wraps=real_replace,
            ) as replace,
            patch(
                "src.conversion.conversion_manifest.os.fsync",
                wraps=real_fsync,
            ) as fsync,
        ):
            manifest_path = write_conversion_manifest(
                str(FIXTURE_ROOT),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=[],
                output_snapshot=snapshot,
            )

        replace.assert_called_once()
        fsync.assert_called_once()
        staged_path, destination_path = replace.call_args.args
        self.assertEqual(Path(staged_path).parent, Path(manifest_path).parent)
        self.assertEqual(Path(destination_path), Path(manifest_path))
        self.assertEqual(self._staged_manifest_files(godot_dir), [])
        self.assertTrue(Path(manifest_path).is_file())

    def test_serialization_failure_preserves_existing_manifest_and_cleans_stage(self) -> None:
        godot_dir, manifest_path, original = self._existing_manifest()
        snapshot = capture_conversion_output_snapshot(str(godot_dir))

        with (
            patch(
                "src.conversion.conversion_manifest.json.dump",
                side_effect=TypeError("injected serialization failure"),
            ),
            self.assertRaisesRegex(TypeError, "injected serialization failure"),
        ):
            write_conversion_manifest(
                str(FIXTURE_ROOT),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=[],
                output_snapshot=snapshot,
            )

        self.assertEqual(manifest_path.read_bytes(), original)
        self.assertEqual(self._staged_manifest_files(godot_dir), [])

    def test_staged_write_failure_preserves_existing_manifest_and_cleans_stage(self) -> None:
        godot_dir, manifest_path, original = self._existing_manifest()
        snapshot = capture_conversion_output_snapshot(str(godot_dir))

        def fail_after_partial_write(
            _payload: object,
            manifest_file: TextIO,
            **_kwargs: object,
        ) -> None:
            manifest_file.write('{"partial":')
            raise OSError("injected staged write failure")

        with (
            patch(
                "src.conversion.conversion_manifest.json.dump",
                side_effect=fail_after_partial_write,
            ),
            self.assertRaisesRegex(OSError, "injected staged write failure"),
        ):
            write_conversion_manifest(
                str(FIXTURE_ROOT),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=[],
                output_snapshot=snapshot,
            )

        self.assertEqual(manifest_path.read_bytes(), original)
        self.assertEqual(self._staged_manifest_files(godot_dir), [])

    def test_replace_failure_preserves_existing_manifest_and_cleans_stage(self) -> None:
        godot_dir, manifest_path, original = self._existing_manifest()
        snapshot = capture_conversion_output_snapshot(str(godot_dir))

        with (
            patch(
                "src.conversion.conversion_manifest.os.replace",
                side_effect=OSError("injected replace failure"),
            ),
            self.assertRaisesRegex(OSError, "injected replace failure"),
        ):
            write_conversion_manifest(
                str(FIXTURE_ROOT),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=[],
                output_snapshot=snapshot,
            )

        self.assertEqual(manifest_path.read_bytes(), original)
        self.assertEqual(self._staged_manifest_files(godot_dir), [])

    def _existing_manifest(self) -> tuple[Path, Path, bytes]:
        godot_dir = self.temp_dir / "godot"
        manifest_path = godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        manifest_path.parent.mkdir(parents=True)
        original = b'{"format_version": 1, "generated_files": []}\n'
        manifest_path.write_bytes(original)
        return godot_dir, manifest_path, original

    @staticmethod
    def _staged_manifest_files(godot_dir: Path) -> list[Path]:
        manifest_path = godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        return list(manifest_path.parent.glob(f".{manifest_path.name}.*.tmp"))


if __name__ == "__main__":
    unittest.main()
