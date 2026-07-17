# pyright: reportPrivateUsage=false
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from typing import cast

from PIL import Image

from src.conversion.conversion_manifest import CONVERSION_MANIFEST_RELATIVE_PATH
from src.conversion.conversion_plan import CONVERSION_STEPS
from src.conversion.diagnostics import DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
from src.conversion.fonts import _find_system_font
from src.conversion.godot_validation import (
    generated_godot_importable_asset_paths,
    validate_generated_godot_project,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_MATRIX_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "part2" / "projects" / "resource_matrix"
)

REPRESENTATIVE_OUTPUTS = (
    "addons/gm2godot_extensions/ext_analytics/ext_analytics_extension.gd",
    "default_bus_layout.tres",
    "gm2godot/gml_asset_registry.gd",
    "gm2godot/gml_runtime.gd",
    "included_files/config/defaults.json",
    "objects/o_physics_box/o_physics_box.tscn",
    "paths/path_patrol/path_patrol.tscn",
    "rooms/r_child/r_child.tscn",
    "rooms/r_parent/r_parent.tscn",
    "scripts/scr_macros.gd",
    "shaders/shd_matrix.gdshader",
    "sounds/audio_group_map.json",
    "sounds/snd_click/snd_click.wav",
    "sprites/spr_checker/spr_checker.png",
    "sprites/spr_checker/spr_checker.tscn",
    "tilesets/ts_ground/ts_ground.png",
    "tilesets/ts_ground/ts_ground.tres",
)


def _tree_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot[relative_path] = "directory"
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot[relative_path] = f"file:sha256:{digest}"
    return snapshot


def _read_json_object(path: Path) -> dict[str, object]:
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise AssertionError(f"Expected a JSON object in {path}")
    return cast(dict[str, object], parsed)


def _materialize_core_binary_assets(project_path: Path) -> None:
    """Add valid sprite and sound payloads to the text-only matrix fixture copy."""
    frame_id = "11111111-2222-3333-4444-555555555555"
    layer_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    sprite_yy_path = project_path / "sprites" / "spr_checker" / "spr_checker.yy"
    sprite_data = _read_json_object(sprite_yy_path)
    sprite_data["frames"] = [
        {
            "$GMSpriteFrame": "v1",
            "%Name": frame_id,
            "name": frame_id,
            "resourceType": "GMSpriteFrame",
            "resourceVersion": "2.0",
        }
    ]
    sprite_data["layers"] = [
        {
            "$GMImageLayer": "",
            "%Name": layer_id,
            "name": layer_id,
            "displayName": "checker",
            "opacity": 100.0,
            "visible": True,
            "resourceType": "GMImageLayer",
            "resourceVersion": "2.0",
        }
    ]
    sprite_yy_path.write_text(
        json.dumps(sprite_data, indent=2) + "\n",
        encoding="utf-8",
    )
    sprite_image_path = (
        project_path
        / "sprites"
        / "spr_checker"
        / "layers"
        / frame_id
        / f"{layer_id}.png"
    )
    sprite_image_path.parent.mkdir(parents=True)
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 255))
    for tile_y in range(2):
        for tile_x in range(2):
            color = (255, 255, 255, 255) if (tile_x + tile_y) % 2 == 0 else (25, 80, 180, 255)
            for y in range(tile_y * 16, (tile_y + 1) * 16):
                for x in range(tile_x * 16, (tile_x + 1) * 16):
                    image.putpixel((x, y), color)
    image.save(sprite_image_path, "PNG")

    sound_path = project_path / "sounds" / "snd_click" / "snd_click.wav"
    with wave.open(os.fspath(sound_path), "wb") as sound_file:
        sound_file.setnchannels(1)
        sound_file.setsampwidth(1)
        sound_file.setframerate(8_000)
        sound_file.writeframes(bytes([128, 180, 220, 180, 128, 76, 36, 76]) * 20)


class ResourceMatrixEndToEndTests(unittest.TestCase):
    def test_cli_converts_full_fixture_and_exact_godot_loads_outputs(self) -> None:
        fixture_snapshot = _tree_snapshot(RESOURCE_MATRIX_PATH)
        self.addCleanup(
            lambda: self.assertEqual(
                _tree_snapshot(RESOURCE_MATRIX_PATH),
                fixture_snapshot,
                "ResourceMatrix source fixture was mutated",
            )
        )
        system_font_path = _find_system_font("Arial")

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            source_project = temporary_root / "game-maker-source"
            shutil.copytree(RESOURCE_MATRIX_PATH, source_project)
            _materialize_core_binary_assets(source_project)
            destination = temporary_root / "godot-output"
            conversion = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "convert",
                    "--gm-project",
                    os.fspath(source_project),
                    "--godot-project",
                    os.fspath(destination),
                    "--platform",
                    "linux",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            conversion_output = conversion.stdout + conversion.stderr
            self.assertEqual(conversion.returncode, 0, conversion_output)
            self.assertEqual(_tree_snapshot(RESOURCE_MATRIX_PATH), fixture_snapshot)

            manifest = _read_json_object(
                destination / CONVERSION_MANIFEST_RELATIVE_PATH
            )
            diagnostics = _read_json_object(
                destination / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
            )
            self._assert_manifest(manifest)
            self._assert_diagnostics(diagnostics)
            font_output = self._assert_representative_outputs(
                destination,
                system_font_path,
                source_project,
            )

            generated_files = cast(
                list[dict[str, object]],
                manifest["generated_files"],
            )
            generated_paths = {
                str(entry.get("path", "")) for entry in generated_files
            }
            self.assertTrue(
                set(REPRESENTATIVE_OUTPUTS).issubset(generated_paths),
                sorted(set(REPRESENTATIVE_OUTPUTS) - generated_paths),
            )
            diagnostics_relative_path = DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH.replace(
                os.sep,
                "/",
            )
            diagnostics_manifest_entry = next(
                entry
                for entry in generated_files
                if entry.get("path") == diagnostics_relative_path
            )
            final_diagnostics_hash = "sha256:" + hashlib.sha256(
                (destination / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH).read_bytes()
            ).hexdigest()
            self.assertEqual(
                diagnostics_manifest_entry.get("sha256"),
                final_diagnostics_hash,
            )
            resources = cast(list[dict[str, object]], manifest["resources"])
            resources_by_name = {
                str(resource.get("name", "")): resource for resource in resources
            }
            for resource_name in ("spr_checker", "snd_click", "ts_ground"):
                with self.subTest(resource=resource_name):
                    resource_path = str(
                        resources_by_name[resource_name].get("godot_path", "")
                    )
                    self.assertTrue(resource_path.startswith("res://"), resource_path)
                    self.assertTrue(
                        (destination / resource_path.removeprefix("res://")).is_file(),
                        resource_path,
                    )
            font_resource = next(
                resource for resource in resources if resource.get("name") == "fnt_ui"
            )
            self.assertEqual(font_resource.get("godot_path"), f"res://{font_output}")

            godot_binary = os.environ.get("GODOT_BIN")
            if not godot_binary:
                return

            self._assert_exact_godot_validation(destination, godot_binary)

    def _assert_manifest(self, manifest: dict[str, object]) -> None:
        self.assertEqual(manifest["format_version"], 1)
        self.assertEqual(manifest["target_platform"], "linux")
        self.assertEqual(
            set(cast(list[str], manifest["enabled_converters"])),
            {step.key for step in CONVERSION_STEPS},
        )
        self.assertEqual(manifest["path_diagnostics"], [])

        source_project = cast(dict[str, object], manifest["source_project"])
        self.assertEqual(source_project["name"], "ResourceMatrix")
        self.assertEqual(source_project["yyp_path"], "ResourceMatrix.yyp")

        resources = cast(list[dict[str, object]], manifest["resources"])
        resource_names = {str(resource.get("name", "")) for resource in resources}
        self.assertTrue(
            {
                "ext_analytics",
                "fnt_ui",
                "o_physics_box",
                "path_patrol",
                "r_child",
                "r_parent",
                "scr_macros",
                "seq_intro",
                "shd_matrix",
                "snd_click",
                "spr_checker",
                "tl_intro",
                "ts_ground",
            }.issubset(resource_names)
        )

    def _assert_diagnostics(self, diagnostics: dict[str, object]) -> None:
        summary = cast(dict[str, int], diagnostics["summary"])
        entries = cast(list[dict[str, object]], diagnostics["diagnostics"])
        self.assertEqual(summary["error"], 0)
        self.assertGreater(summary["warning"], 0)
        self.assertEqual(summary["total"], len(entries))

        diagnostic_codes = {str(entry.get("code", "")) for entry in entries}
        self.assertIn("GM2GD-CLI-TARGET-PLATFORM", diagnostic_codes)
        self.assertIn("GM2GD-RESOURCE-UNSUPPORTED", diagnostic_codes)
        self.assertEqual(
            sum(
                entry.get("code") == "GM2GD-CLI-TARGET-PLATFORM"
                for entry in entries
            ),
            1,
        )
        platform_diagnostic = next(
            entry
            for entry in entries
            if entry.get("code") == "GM2GD-CLI-TARGET-PLATFORM"
        )
        self.assertEqual(platform_diagnostic.get("severity"), "info")
        self.assertEqual(platform_diagnostic.get("resource"), "linux")

    def _assert_representative_outputs(
        self,
        destination: Path,
        system_font_path: str | None,
        source_project: Path,
    ) -> str:
        for relative_path in REPRESENTATIVE_OUTPUTS:
            self.assertTrue(
                (destination / relative_path).is_file(),
                relative_path,
            )

        project_content = (destination / "project.godot").read_text(
            encoding="utf-8"
        )
        self.assertIn('config/name="ResourceMatrix"', project_content)
        self.assertIn('config/features=PackedStringArray("4.7")', project_content)
        self.assertIn(
            'run/main_scene="res://rooms/r_child/r_child.tscn"',
            project_content,
        )

        included_source = source_project / "datafiles" / "config" / "defaults.json"
        included_output = destination / "included_files" / "config" / "defaults.json"
        self.assertEqual(included_output.read_bytes(), included_source.read_bytes())
        macro_script = (destination / "scripts" / "scr_macros.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("func _gm_script_call():", macro_script)
        self.assertIn("\treturn 4", macro_script)
        self.assertIn(
            "metadata/gamemaker_physics_world = true",
            (destination / "rooms" / "r_child" / "r_child.tscn").read_text(
                encoding="utf-8"
            ),
        )
        self.assertIn(
            '"name": "r_child"',
            (destination / "gm2godot" / "gml_asset_registry.gd").read_text(
                encoding="utf-8"
            ),
        )

        fallback_path = destination / "fonts" / "ui" / "fnt_ui.tres"
        if system_font_path is None:
            fallback_content = fallback_path.read_text(encoding="utf-8")
            self.assertIn('type="SystemFont"', fallback_content)
            self.assertIn('PackedStringArray("Arial")', fallback_content)
            return fallback_path.relative_to(destination).as_posix()

        source_font = Path(system_font_path)
        copied_font = destination / "fonts" / "ui" / f"fnt_ui{source_font.suffix}"
        self.assertFalse(fallback_path.exists())
        self.assertEqual(copied_font.read_bytes(), source_font.read_bytes())
        return copied_font.relative_to(destination).as_posix()

    def _assert_exact_godot_validation(
        self,
        destination: Path,
        godot_binary: str,
    ) -> None:
        self.assertTrue(os.path.isfile(godot_binary), godot_binary)
        version = subprocess.run(
            [godot_binary, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        version_output = (version.stdout + version.stderr).strip()
        self.assertEqual(version.returncode, 0, version_output)
        self.assertRegex(version_output, r"^4\.7\.1\.stable\.")

        resource_report = validate_generated_godot_project(
            os.fspath(destination),
            godot_binary=godot_binary,
            timeout=120,
            load_resources=True,
        )
        self.assertEqual(
            resource_report.status,
            "passed",
            resource_report.message + "\n" + resource_report.output,
        )
        importable_assets = generated_godot_importable_asset_paths(
            os.fspath(destination)
        )
        if importable_assets:
            self.assertEqual(
                resource_report.import_returncode,
                0,
                resource_report.output,
            )
        else:
            self.assertIsNone(
                resource_report.import_returncode,
                resource_report.output,
            )
        self.assertEqual(resource_report.returncode, 0, resource_report.output)
        self.assertGreaterEqual(len(resource_report.resource_paths), 20)
        self.assertEqual(resource_report.output_issues, (), resource_report.output)

        # The matrix deliberately enables two unsupported room behaviors. Boot
        # the generated main scene and assert those warnings precisely rather
        # than hiding them or pretending this compatibility fixture is clean.
        boot_report = validate_generated_godot_project(
            os.fspath(destination),
            godot_binary=godot_binary,
            timeout=120,
            load_resources=False,
            boot_frames=2,
        )
        self.assertEqual(boot_report.status, "failed", boot_report.output)
        self.assertEqual(boot_report.boot_returncode, 0, boot_report.output)
        self.assertEqual(
            [issue.severity for issue in boot_report.output_issues],
            ["warning", "warning"],
            boot_report.output,
        )
        warning_lines = [issue.line for issue in boot_report.output_issues]
        self.assertTrue(
            any("multiple active GameMaker views" in line for line in warning_lines),
            warning_lines,
        )
        self.assertTrue(
            any("does not preserve full persistent room state" in line for line in warning_lines),
            warning_lines,
        )


if __name__ == "__main__":
    unittest.main()
