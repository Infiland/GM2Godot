# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from PIL import Image

from src.conversion import converter as converter_module
from src.conversion import managed_output_publisher as publisher_module
from src.conversion.conversion_manifest import (
    CONVERSION_MANIFEST_RELATIVE_PATH,
)
from src.conversion.converter import Converter
from src.conversion.godot_validation import (
    find_godot_binary,
    validate_generated_godot_project,
)
from src.conversion.managed_resource_outputs import managed_resource_outputs


class _Setting:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def get(self) -> bool:
        return self.enabled


class TestManagedResourceOutputPolicy(unittest.TestCase):
    def test_defines_each_stale_invalidation_resource_output(self) -> None:
        object_outputs = managed_resource_outputs(
            "objects",
            "res://objects/game/o_stale/o_stale.tscn",
        )
        self.assertEqual(
            object_outputs.required_paths,
            (
                "objects/game/o_stale/o_stale.gd",
                "objects/game/o_stale/o_stale.tscn",
            ),
        )
        self.assertTrue(
            object_outputs.owns(
                "objects/game/o_stale/o_stale.gd.gmlmap.json"
            )
        )

        room_outputs = managed_resource_outputs(
            "rooms",
            "res://rooms/r_stale/r_stale.tscn",
        )
        self.assertEqual(
            room_outputs.required_paths,
            ("rooms/r_stale/r_stale.tscn",),
        )
        self.assertTrue(room_outputs.owns("rooms/r_stale/r_stale.gd"))

        sprite_outputs = managed_resource_outputs(
            "sprites",
            "res://sprites/s_stale/s_stale.tscn",
        )
        self.assertTrue(sprite_outputs.owns("sprites/s_stale/s_stale_2.png"))

        shader_outputs = managed_resource_outputs(
            "shaders",
            "res://shaders/sh_stale.gdshader",
        )
        self.assertEqual(
            shader_outputs.required_paths,
            ("shaders/sh_stale.gdshader",),
        )

        timeline_outputs = managed_resource_outputs(
            "timelines",
            "",
            {
                "moments": [
                    {
                        "actions": [
                            {
                                "kind": "gml",
                                "script_path": (
                                    "res://gm2godot/timelines/tl_stale_3.gd"
                                ),
                            }
                        ]
                    }
                ]
            },
        )
        self.assertEqual(
            timeline_outputs.required_paths,
            ("gm2godot/timelines/tl_stale_3.gd",),
        )

        particle_outputs = managed_resource_outputs(
            "particlesystems",
            "res://particlesystems/ps_stale/ps_stale.tres",
        )
        self.assertEqual(
            particle_outputs.required_paths,
            ("particlesystems/ps_stale/ps_stale.tres",),
        )
        self.assertTrue(
            particle_outputs.owns(
                "particlesystems/ps_stale/ps_stale.tres"
            )
        )


class TestStaleManagedOutputInvalidation(unittest.TestCase):
    OBJECT_NAME = "o_stale"
    ROOM_NAME = "r_stale"
    SPRITE_NAME = "s_stale"
    SHADER_NAME = "sh_stale"
    TIMELINE_NAME = "tl_stale"

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.gm_dir = self.temp_dir / "gm"
        self.godot_dir = self.temp_dir / "godot"
        self.gm_dir.mkdir()
        self.godot_dir.mkdir()
        self._write_text(
            self.godot_dir / "project.godot",
            (
                'config_version=5\n\n[application]\nconfig/name="User Project"\n'
                "\n[display]\nwindow/size/viewport_width=777\n"
            ),
        )
        self.running = threading.Event()
        self.running.set()
        self._write_all_sources()
        baseline = self._convert()
        self.assertEqual(baseline.state, "success")
        self.user_sentinel = self.godot_dir / "user-content" / "keep.txt"
        self.user_sentinel.parent.mkdir()
        self.user_sentinel.write_bytes(b"user-owned\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    @staticmethod
    def _settings(*, objects: bool = True) -> dict[str, _Setting]:
        return {
            "sprites": _Setting(True),
            "shaders": _Setting(True),
            "objects": _Setting(objects),
            "rooms": _Setting(True),
            "asset_registry": _Setting(True),
        }

    def _converter(self) -> Converter:
        return Converter(
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=self.running,
            max_workers=1,
        )

    def _convert(
        self,
        *,
        converter: Converter | None = None,
        objects: bool = True,
    ):
        selected = converter if converter is not None else self._converter()
        return selected.convert(
            str(self.gm_dir),
            "windows",
            str(self.godot_dir),
            self._settings(objects=objects),
        )

    def _write_all_sources(self) -> None:
        self._write_object("object_value = 1;\n")
        self._write_room("room_value = 1;\n")
        self._write_sprite()
        self._write_shader(self._valid_shader_source())
        self._write_timeline("timeline_value = 1;\n")
        self._write_yyp()

    def _write_yyp(self, *, include_object: bool = True) -> None:
        resources = [
            (
                "rooms",
                self.ROOM_NAME,
                "GMRoom",
            ),
            (
                "sprites",
                self.SPRITE_NAME,
                "GMSprite",
            ),
            (
                "shaders",
                self.SHADER_NAME,
                "GMShader",
            ),
            (
                "timelines",
                self.TIMELINE_NAME,
                "GMTimeline",
            ),
        ]
        if include_object:
            resources.insert(0, ("objects", self.OBJECT_NAME, "GMObject"))
        payload = {
            "%Name": "Stale Output Policy",
            "resourceType": "GMProject",
            "resources": [
                {
                    "id": {
                        "name": name,
                        "path": f"{kind}/{name}/{name}.yy",
                    },
                    "resourceType": resource_type,
                }
                for kind, name, resource_type in resources
            ],
            "RoomOrderNodes": [
                {
                    "roomId": {
                        "name": self.ROOM_NAME,
                        "path": (
                            f"rooms/{self.ROOM_NAME}/{self.ROOM_NAME}.yy"
                        ),
                    }
                }
            ],
        }
        self._write_json(self.gm_dir / "StalePolicy.yyp", payload)

    def _write_object(self, source: str) -> None:
        object_dir = self.gm_dir / "objects" / self.OBJECT_NAME
        self._write_json(
            object_dir / f"{self.OBJECT_NAME}.yy",
            {
                "%Name": self.OBJECT_NAME,
                "name": self.OBJECT_NAME,
                "resourceType": "GMObject",
                "eventList": [{"eventType": 0, "eventNum": 0}],
                "parent": {
                    "name": "Objects",
                    "path": "folders/Objects.yy",
                },
            },
        )
        self._write_text(object_dir / "Create_0.gml", source)

    def _write_room(self, source: str) -> None:
        room_dir = self.gm_dir / "rooms" / self.ROOM_NAME
        self._write_json(
            room_dir / f"{self.ROOM_NAME}.yy",
            {
                "%Name": self.ROOM_NAME,
                "name": self.ROOM_NAME,
                "resourceType": "GMRoom",
                "creationCodeFile": "RoomCreationCode.gml",
                "instanceCreationOrder": [],
                "layers": [],
                "physicsSettings": {},
                "roomSettings": {"Width": 320, "Height": 180},
                "viewSettings": {"enableViews": False},
                "views": [],
                "parent": {
                    "name": "Rooms",
                    "path": "folders/Rooms.yy",
                },
            },
        )
        self._write_text(room_dir / "RoomCreationCode.gml", source)

    def _write_sprite(self) -> None:
        frame = "frame-0"
        layer = "layer-0"
        sprite_dir = self.gm_dir / "sprites" / self.SPRITE_NAME
        self._write_json(
            sprite_dir / f"{self.SPRITE_NAME}.yy",
            {
                "%Name": self.SPRITE_NAME,
                "name": self.SPRITE_NAME,
                "resourceType": "GMSprite",
                "frames": [{"name": frame}],
                "layers": [{"name": layer, "visible": True}],
                "width": 2,
                "height": 2,
                "parent": {
                    "name": "Sprites",
                    "path": "folders/Sprites.yy",
                },
            },
        )
        image_path = sprite_dir / "layers" / frame / f"{layer}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (2, 2), "red").save(image_path, "PNG")

    def _write_shader(self, source: str) -> None:
        shader_dir = self.gm_dir / "shaders" / self.SHADER_NAME
        self._write_json(
            shader_dir / f"{self.SHADER_NAME}.yy",
            {
                "%Name": self.SHADER_NAME,
                "name": self.SHADER_NAME,
                "resourceType": "GMShader",
                "parent": {
                    "name": "Shaders",
                    "path": "folders/Shaders.yy",
                },
            },
        )
        self._write_text(shader_dir / f"{self.SHADER_NAME}.fsh", source)

    def _write_timeline(self, source: str) -> None:
        timeline_dir = self.gm_dir / "timelines" / self.TIMELINE_NAME
        self._write_json(
            timeline_dir / f"{self.TIMELINE_NAME}.yy",
            {
                "%Name": self.TIMELINE_NAME,
                "name": self.TIMELINE_NAME,
                "resourceType": "GMTimeline",
                "momentList": [
                    {"moment": 3, "eventFile": "Moment_3.gml"}
                ],
                "parent": {
                    "name": "Timelines",
                    "path": "folders/Timelines.yy",
                },
            },
        )
        self._write_text(timeline_dir / "Moment_3.gml", source)

    @staticmethod
    def _valid_shader_source() -> str:
        return (
            "precision highp float;\n"
            "varying vec2 v_vTexcoord;\n"
            "varying vec4 v_vColour;\n"
            "uniform sampler2D gm_BaseTexture;\n"
            "void main() {\n"
            "    gl_FragColor = texture2D("
            "gm_BaseTexture, v_vTexcoord) * v_vColour;\n"
            "}\n"
        )

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _object_outputs(self) -> tuple[Path, ...]:
        root = self.godot_dir / "objects" / self.OBJECT_NAME
        return (
            root / f"{self.OBJECT_NAME}.tscn",
            root / f"{self.OBJECT_NAME}.gd",
            root / f"{self.OBJECT_NAME}.gd.gmlmap.json",
        )

    def _room_outputs(self) -> tuple[Path, ...]:
        root = self.godot_dir / "rooms" / self.ROOM_NAME
        return (
            root / f"{self.ROOM_NAME}.tscn",
            root / f"{self.ROOM_NAME}.gd",
        )

    def _sprite_outputs(self) -> tuple[Path, ...]:
        root = self.godot_dir / "sprites" / self.SPRITE_NAME
        return (
            root / f"{self.SPRITE_NAME}.tscn",
            root / f"{self.SPRITE_NAME}.png",
        )

    def _shader_output(self) -> Path:
        return self.godot_dir / "shaders" / f"{self.SHADER_NAME}.gdshader"

    def _timeline_output(self) -> Path:
        return (
            self.godot_dir
            / "gm2godot"
            / "timelines"
            / f"{self.TIMELINE_NAME}_3.gd"
        )

    def _manifest(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(
                (
                    self.godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
                ).read_text(encoding="utf-8")
            ),
        )

    def _registry(self) -> str:
        return (
            self.godot_dir / "gm2godot" / "gml_asset_registry.gd"
        ).read_text(encoding="utf-8")

    def _manifest_resource(self, name: str) -> dict[str, object] | None:
        resources = cast(list[object], self._manifest()["resources"])
        for raw_resource in resources:
            if not isinstance(raw_resource, dict):
                continue
            resource = cast(dict[str, object], raw_resource)
            if resource.get("name") == name:
                return resource
        return None

    def _assert_absent_from_inventory(self, paths: tuple[Path, ...]) -> None:
        payload = self._manifest()
        inventory = cast(dict[str, object], payload["generation_inventory"])
        entries = cast(list[object], inventory["entries"])
        inventory_paths: set[str] = set()
        for raw_entry in entries:
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, object], raw_entry)
            relative_path = entry.get("path")
            if isinstance(relative_path, str):
                inventory_paths.add(relative_path)
        for path in paths:
            relative = path.relative_to(self.godot_dir).as_posix()
            self.assertNotIn(relative, inventory_paths)

    def _assert_user_file_preserved(self) -> None:
        self.assertEqual(self.user_sentinel.read_bytes(), b"user-owned\n")

    def test_removed_yyp_object_deletes_all_prior_owned_outputs(self) -> None:
        baseline_outputs = self._object_outputs()
        self.assertTrue(all(path.is_file() for path in baseline_outputs))
        self._write_yyp(include_object=False)
        shutil.rmtree(self.gm_dir / "objects" / self.OBJECT_NAME)

        outcome = self._convert()

        self.assertEqual(outcome.state, "success")
        self.assertTrue(all(not path.exists() for path in baseline_outputs))
        self.assertIsNone(self._manifest_resource(self.OBJECT_NAME))
        self.assertNotIn(f'"name": "{self.OBJECT_NAME}"', self._registry())
        self._assert_absent_from_inventory(baseline_outputs)
        self._assert_user_file_preserved()

    def test_object_transpile_failure_removes_prior_scene_script_and_map(
        self,
    ) -> None:
        self._write_object("if (\n")

        outcome = self._convert()

        outputs = self._object_outputs()
        self.assertEqual(outcome.state, "partial")
        self.assertTrue(all(not path.exists() for path in outputs))
        self.assertIsNone(self._manifest_resource(self.OBJECT_NAME))
        self.assertNotIn(f'"name": "{self.OBJECT_NAME}"', self._registry())
        self._assert_absent_from_inventory(outputs)
        self._assert_user_file_preserved()

    def test_room_transpile_failure_removes_prior_scene_and_script(self) -> None:
        self._write_room("if (\n")
        project_path = self.godot_dir / "project.godot"

        outcome = self._convert()

        outputs = self._room_outputs()
        self.assertEqual(outcome.state, "partial")
        self.assertTrue(all(not path.exists() for path in outputs))
        self.assertIsNone(self._manifest_resource(self.ROOM_NAME))
        self.assertNotIn(f'"name": "{self.ROOM_NAME}"', self._registry())
        project = project_path.read_text(encoding="utf-8")
        self.assertNotIn(
            f'run/main_scene="res://rooms/{self.ROOM_NAME}/'
            f'{self.ROOM_NAME}.tscn"',
            project,
        )
        self.assertIn("window/size/viewport_width=777", project)
        self._assert_absent_from_inventory(outputs)
        self._assert_user_file_preserved()

    def test_sprite_source_loss_removes_prior_scene_and_texture(self) -> None:
        image_path = (
            self.gm_dir
            / "sprites"
            / self.SPRITE_NAME
            / "layers"
            / "frame-0"
            / "layer-0.png"
        )
        image_path.unlink()

        outcome = self._convert()

        outputs = self._sprite_outputs()
        self.assertEqual(outcome.state, "partial")
        self.assertTrue(all(not path.exists() for path in outputs))
        self.assertIsNone(self._manifest_resource(self.SPRITE_NAME))
        self.assertNotIn(f'"name": "{self.SPRITE_NAME}"', self._registry())
        self._assert_absent_from_inventory(outputs)
        self._assert_user_file_preserved()

    def test_shader_source_loss_removes_prior_generated_shader(self) -> None:
        self._write_shader(" \n\t")

        outcome = self._convert()

        output = self._shader_output()
        self.assertEqual(outcome.state, "partial")
        self.assertFalse(output.exists())
        self.assertIsNone(self._manifest_resource(self.SHADER_NAME))
        self.assertNotIn(f'"name": "{self.SHADER_NAME}"', self._registry())
        self._assert_absent_from_inventory((output,))
        self._assert_user_file_preserved()

    def test_timeline_transpile_failure_removes_prior_action_script_reference(
        self,
    ) -> None:
        self._write_timeline("if (\n")

        outcome = self._convert()

        output = self._timeline_output()
        self.assertEqual(outcome.state, "partial")
        self.assertFalse(output.exists())
        registry = self._registry()
        self.assertIn(f'"name": "{self.TIMELINE_NAME}"', registry)
        self.assertNotIn(
            f"res://gm2godot/timelines/{self.TIMELINE_NAME}_3.gd",
            registry,
        )
        timeline = self._manifest_resource(self.TIMELINE_NAME)
        self.assertIsNotNone(timeline)
        assert timeline is not None
        self.assertNotIn(
            f"res://gm2godot/timelines/{self.TIMELINE_NAME}_3.gd",
            json.dumps(timeline),
        )
        self._assert_absent_from_inventory((output,))
        self._assert_user_file_preserved()

    def test_cancellation_before_commit_preserves_prior_stale_resource(
        self,
    ) -> None:
        expected = {
            path: (
                path.read_bytes(),
                stat.S_IMODE(path.stat().st_mode),
            )
            for path in self._object_outputs()
        }
        self._write_yyp(include_object=False)

        def cancel_after_validation(phase: str, _path: str) -> None:
            if phase == "after_staged_validation":
                self.running.clear()

        with patch.object(
            converter_module,
            "_before_conversion_transaction_phase",
            side_effect=cancel_after_validation,
        ):
            outcome = self._convert()

        self.assertEqual(outcome.state, "cancelled")
        for path, (content, mode) in expected.items():
            self.assertEqual(path.read_bytes(), content)
            actual_mode = stat.S_IMODE(path.stat().st_mode)
            if os.name == "nt":
                self.assertEqual(
                    bool(actual_mode & stat.S_IWUSR),
                    bool(mode & stat.S_IWUSR),
                )
            else:
                self.assertEqual(actual_mode, mode)
        self._assert_user_file_preserved()

    def test_publication_failure_rolls_back_stale_resource_deletion(
        self,
    ) -> None:
        expected = {
            path: path.read_bytes()
            for path in self._object_outputs()
        }
        self._write_yyp(include_object=False)
        failed = False

        def fail_after_install(phase: str, _path: str | None) -> None:
            nonlocal failed
            if phase == "public_installed" and not failed:
                failed = True
                raise OSError("injected stale-output publication failure")

        with patch.object(
            publisher_module,
            "_before_managed_output_phase",
            side_effect=fail_after_install,
        ):
            with self.assertRaisesRegex(
                OSError,
                "stale-output publication failure",
            ):
                self._convert()

        self.assertTrue(failed)
        for path, content in expected.items():
            self.assertEqual(path.read_bytes(), content)
        self._assert_user_file_preserved()

    def test_unknown_file_inside_managed_root_fails_closed_and_is_preserved(
        self,
    ) -> None:
        unknown = self.godot_dir / "objects" / "user-owned.keep"
        unknown.write_bytes(b"do not adopt or delete\n")
        expected = {
            path: path.read_bytes()
            for path in self._object_outputs()
        }
        self._write_yyp(include_object=False)

        with self.assertRaisesRegex(
            OSError,
            "unexpected 'objects/user-owned.keep'",
        ):
            self._convert()

        self.assertEqual(unknown.read_bytes(), b"do not adopt or delete\n")
        for path, content in expected.items():
            self.assertEqual(path.read_bytes(), content)
        self._assert_user_file_preserved()

    def test_disabled_converter_carries_prior_output_unchanged(self) -> None:
        expected = {
            path: path.read_bytes()
            for path in self._object_outputs()
        }
        self._write_yyp(include_object=False)

        outcome = self._convert(objects=False)

        self.assertEqual(outcome.state, "success")
        for path, content in expected.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertIsNone(self._manifest_resource(self.OBJECT_NAME))
        self._assert_user_file_preserved()

    @unittest.skipIf(
        find_godot_binary() is None,
        "Godot binary not available",
    )
    def test_combined_partial_rerun_validates_with_exact_godot(self) -> None:
        self._write_object("if (\n")
        self._write_room("if (\n")
        (
            self.gm_dir
            / "sprites"
            / self.SPRITE_NAME
            / "layers"
            / "frame-0"
            / "layer-0.png"
        ).unlink()
        self._write_shader("\n")
        self._write_timeline("if (\n")

        outcome = self._convert()

        self.assertEqual(outcome.state, "partial")
        godot_binary = find_godot_binary()
        assert godot_binary is not None
        version = subprocess.run(
            [godot_binary, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        self.assertEqual(
            version.stdout.strip(),
            "4.7.1.stable.official.a13da4feb",
        )
        report = validate_generated_godot_project(
            str(self.godot_dir),
            godot_binary=godot_binary,
        )
        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.output_issues, (), report.output)
        self._assert_user_file_preserved()


if __name__ == "__main__":
    unittest.main()
